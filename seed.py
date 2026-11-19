"""
Idempotent & resumable PokéAPI importer for ALL National Dex Pokémon (IDs 1..1025).

Usage:
    python seed.py
    python seed.py --start 1 --end 1025 --workers 8

What it does:
  Phase 1: Fetches all 18 Pokémon types and their damage relations from /type/{name}.
  Phase 2: Fetches /pokemon/{id} and /pokemon-species/{id} in concurrent batches
           (writes sequentially to MySQL for thread safety), skipping Pokémon
           already stored in MySQL so interrupted runs resume cleanly.
  Phase 3: Fetches each unique /evolution-chain/{chain_id} referenced by seeded
           Pokémon and stores linear & branching evolution edges with conditions.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import re
import sys
import threading
import time
from typing import Any

import requests
from mysql.connector import Error as MySQLError

from config import Config, TYPE_COLORS, VERSION_METADATA, get_db_connection

POKEAPI_BASE = "https://pokeapi.co/api/v2"
MAX_RETRIES = 4
REQUEST_TIMEOUT = 15
TOP_LEVEL_UP_MOVES = 15
BATCH_SIZE = 25

_thread_local = threading.local()


def get_thread_session() -> requests.Session:
    """Return a per-thread requests.Session for safe connection pooling across workers."""
    session = getattr(_thread_local, "session", None)
    if session is None:
        session = requests.Session()
        session.headers.update({"User-Agent": "PokedexFlaskApp/2.0 (+https://pokeapi.co)"})
        _thread_local.session = session
    return session


def fetch_json(
    url: str,
    delay: float = 0.02,
    retries: int = MAX_RETRIES,
) -> dict[str, Any]:
    """Fetch JSON from PokéAPI with polite delay and exponential-backoff retries."""
    session = get_thread_session()
    last_error: Exception | None = None

    for attempt in range(1, retries + 1):
        try:
            if delay > 0:
                time.sleep(delay)
            response = session.get(url, timeout=REQUEST_TIMEOUT)
            if response.status_code == 429 or response.status_code >= 500:
                raise requests.HTTPError(
                    f"Transient HTTP {response.status_code} for {url}",
                    response=response,
                )
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            wait = min(2.0 ** attempt, 16.0)
            print(
                f"  [retry {attempt}/{retries}] Failed fetching {url}: {exc}. "
                f"Waiting {wait:.1f}s...",
                file=sys.stderr,
            )
            time.sleep(wait)

    raise RuntimeError(f"Exhausted retries fetching {url}: {last_error}")


def extract_id_from_url(url: str | None) -> int | None:
    """Extract the trailing integer ID from a PokéAPI resource URL."""
    if not url:
        return None
    match = re.search(r"/(\d+)/?$", url)
    return int(match.group(1)) if match else None


def format_slug(slug: str | None) -> str:
    """Convert PokéAPI kebab-case slugs into readable Title Case text."""
    if not slug:
        return ""
    return slug.replace("-", " ").title()


def clean_flavor_text(entries: list[dict[str, Any]], pokemon_name: str = "") -> tuple[str, list[dict[str, str]]]:
    """Clean and synthesize a diverse, multi-sentence expanded lore story plus version logs."""
    english_entries = [
        e for e in entries if e.get("language", {}).get("name") == "en"
    ]
    if not english_entries:
        return "No Pokédex description available.", []

    def clean_text(raw: str) -> str:
        text = re.sub(r"[\f\n\r\t]+", " ", raw)
        text = text.replace("\u00ad ", "").replace("\u00ad", "")
        text = re.sub(r"\bPOK[eé]MON\b", "Pokémon", text, flags=re.IGNORECASE)
        if pokemon_name:
            upper_name = pokemon_name.upper().replace("-", " ")
            title_name = pokemon_name.replace("-", " ").title()
            text = re.sub(r"\b" + re.escape(upper_name) + r"\b", title_name, text)
        return re.sub(r"\s{2,}", " ", text).strip()

    def word_overlap(s1: str, s2: str) -> float:
        w1 = set(re.findall(r"[a-z]{3,}", s1.lower()))
        w2 = set(re.findall(r"[a-z]{3,}", s2.lower()))
        return len(w1 & w2) / max(len(w1), len(w2)) if w1 and w2 else 0.0

    cleaned_list: list[dict[str, str]] = []
    seen: set[str] = set()

    for e in english_entries:
        v_name = (e.get("version") or {}).get("name", "unknown")
        txt = clean_text(e.get("flavor_text", ""))
        if not txt:
            continue
        norm = re.sub(r"[^a-z0-9]", "", txt.lower())
        if norm not in seen:
            seen.add(norm)
            meta = VERSION_METADATA.get(v_name, {"era": "Core Series"})
            cleaned_list.append({
                "version": v_name,
                "era": meta.get("era", "Core Series"),
                "text": txt,
            })

    # Pick up to 3 diverse snippets
    diverse: list[str] = []
    for item in cleaned_list:
        if any(word_overlap(item["text"], prev) > 0.40 for prev in diverse):
            continue
        diverse.append(item["text"])
        if len(diverse) >= 3:
            break

    expanded = " ".join(diverse) if diverse else (cleaned_list[0]["text"] if cleaned_list else "No Pokédex description available.")
    return expanded, cleaned_list


def extract_genus(genera: list[dict[str, Any]]) -> str:
    """Extract the English genus (e.g., 'Mouse Pokémon')."""
    for entry in genera:
        if entry.get("language", {}).get("name") == "en":
            return entry.get("genus", "").strip()
    return "Pokémon"


def extract_top_level_up_moves(
    moves_payload: list[dict[str, Any]],
    limit: int = TOP_LEVEL_UP_MOVES,
) -> list[tuple[str, int]]:
    """Extract up to `limit` level-up moves sorted by level learned ascending."""
    level_up_map: dict[str, int] = {}

    for entry in moves_payload:
        move_name = entry.get("move", {}).get("name")
        if not move_name:
            continue

        level_up_levels = [
            detail.get("level_learned_at", 0)
            for detail in entry.get("version_group_details", [])
            if detail.get("move_learn_method", {}).get("name") == "level-up"
        ]
        if not level_up_levels:
            continue

        learned_level = level_up_levels[-1]
        if move_name not in level_up_map or learned_level < level_up_map[move_name]:
            level_up_map[move_name] = learned_level

    sorted_moves = sorted(level_up_map.items(), key=lambda item: (item[1], item[0]))
    return sorted_moves[:limit]


def build_evolution_condition(
    details: list[dict[str, Any]],
) -> tuple[str | None, int | None, str | None, str]:
    """Parse PokéAPI evolution_details into structured fields and a concise readable label."""
    if not details:
        return None, None, None, "Special"

    d = details[0]
    trigger = d.get("trigger", {}).get("name")
    min_level = d.get("min_level")
    item_name = (d.get("item") or {}).get("name")
    held_item = (d.get("held_item") or {}).get("name")
    min_happiness = d.get("min_happiness")
    min_beauty = d.get("min_beauty")
    min_affection = d.get("min_affection")
    time_of_day = d.get("time_of_day") or ""
    known_move = (d.get("known_move") or {}).get("name")
    known_move_type = (d.get("known_move_type") or {}).get("name")
    location = (d.get("location") or {}).get("name")
    rel_stats = d.get("relative_physical_stats")
    needs_rain = d.get("needs_overworld_rain")
    turn_upside_down = d.get("turn_upside_down")
    gender = d.get("gender")

    parts: list[str] = []

    if trigger == "use-item" and item_name:
        parts.append(format_slug(item_name))
    elif trigger == "trade":
        if held_item:
            parts.append(f"Trade holding {format_slug(held_item)}")
        else:
            parts.append("Trade")
    else:
        if min_level is not None:
            parts.append(f"Lv. {min_level}")
        if min_happiness is not None:
            parts.append("High Friendship")
        if min_affection is not None:
            parts.append("High Affection")
        if min_beauty is not None:
            parts.append("High Beauty")
        if item_name:
            parts.append(format_slug(item_name))
        if held_item:
            parts.append(f"Hold {format_slug(held_item)}")
        if known_move:
            parts.append(f"Knows {format_slug(known_move)}")
        if known_move_type:
            parts.append(f"Knows {format_slug(known_move_type)} move")
        if location:
            parts.append(f"At {format_slug(location)}")
        if needs_rain:
            parts.append("In Rain")
        if turn_upside_down:
            parts.append("Upside Down")

    if time_of_day:
        parts.append(f"({time_of_day.title()})")
    if gender == 1:
        parts.append("(Female)")
    elif gender == 2:
        parts.append("(Male)")
    if rel_stats == 1:
        parts.append("(Atk > Def)")
    elif rel_stats == -1:
        parts.append("(Def > Atk)")
    elif rel_stats == 0:
        parts.append("(Atk = Def)")

    condition_text = " ".join(parts).strip() or format_slug(trigger) or "Level up"
    return trigger, min_level, item_name or held_item, condition_text


# -----------------------------------------------------------------------------
# Phase 1: Seed Types & Type Effectiveness
# -----------------------------------------------------------------------------
def seed_types_and_relations(delay: float) -> dict[str, int]:
    """Populate `types` and `type_effectiveness` from PokéAPI /type/{name}."""
    print("\n=== Phase 1: Seeding Pokémon Types & Damage Relations ===")
    type_name_to_id: dict[str, int] = {}

    with get_db_connection() as conn:
        cursor = conn.cursor()

        for type_name, color_hex in TYPE_COLORS.items():
            cursor.execute(
                """
                INSERT INTO types (name, color_hex)
                VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE color_hex = VALUES(color_hex)
                """,
                (type_name, color_hex),
            )
        conn.commit()

        cursor.execute("SELECT id, name FROM types")
        for type_id, type_name in cursor.fetchall():
            type_name_to_id[type_name] = type_id

        cursor.execute("SELECT COUNT(*) FROM type_effectiveness")
        existing_relations = cursor.fetchone()[0]
        if existing_relations > 0:
            print(f"Type effectiveness already seeded ({existing_relations} rows). Skipping.")
            cursor.close()
            return type_name_to_id

        for idx, (type_name, defending_id) in enumerate(type_name_to_id.items(), start=1):
            data = fetch_json(f"{POKEAPI_BASE}/type/{type_name}", delay=delay)
            relations = data.get("damage_relations", {})
            for key, multiplier in (
                ("double_damage_from", 2.00),
                ("half_damage_from", 0.50),
                ("no_damage_from", 0.00),
            ):
                for attacker in relations.get(key, []):
                    attacking_id = type_name_to_id.get(attacker.get("name"))
                    if attacking_id is not None:
                        cursor.execute(
                            """
                            INSERT INTO type_effectiveness (attacking_type_id, defending_type_id, multiplier)
                            VALUES (%s, %s, %s)
                            ON DUPLICATE KEY UPDATE multiplier = VALUES(multiplier)
                            """,
                            (attacking_id, defending_id, multiplier),
                        )
            conn.commit()
            print(f"  Synced type {idx}/{len(type_name_to_id)}: {type_name.title()}")

        cursor.close()

    return type_name_to_id


# -----------------------------------------------------------------------------
# Phase 2: Seed Pokémon in Concurrent Batches
# -----------------------------------------------------------------------------
def fetch_pokemon_bundle(poke_id: int, delay: float) -> tuple[int, dict[str, Any], dict[str, Any]]:
    """Fetch both /pokemon/{id} and /pokemon-species/{id} for a single Pokémon."""
    poke_data = fetch_json(f"{POKEAPI_BASE}/pokemon/{poke_id}", delay=delay)
    species_data = fetch_json(f"{POKEAPI_BASE}/pokemon-species/{poke_id}", delay=delay)
    return poke_id, poke_data, species_data


def fetch_move_meta(move_name: str, delay: float) -> tuple[str, dict[str, Any]]:
    """Fetch metadata for a single move."""
    data = fetch_json(f"{POKEAPI_BASE}/move/{move_name}", delay=delay)
    return move_name, {
        "type_name": (data.get("type") or {}).get("name"),
        "damage_class": (data.get("damage_class") or {}).get("name"),
        "power": data.get("power"),
        "accuracy": data.get("accuracy"),
        "pp": data.get("pp"),
    }


def get_or_create_ability(cursor, ability_cache: dict[str, int], name: str) -> int:
    if name in ability_cache:
        return ability_cache[name]
    cursor.execute("INSERT IGNORE INTO abilities (name) VALUES (%s)", (name,))
    cursor.execute("SELECT id FROM abilities WHERE name = %s", (name,))
    ability_id = cursor.fetchone()[0]
    ability_cache[name] = ability_id
    return ability_id


def get_or_create_egg_group(cursor, egg_cache: dict[str, int], name: str) -> int:
    if name in egg_cache:
        return egg_cache[name]
    cursor.execute("INSERT IGNORE INTO egg_groups (name) VALUES (%s)", (name,))
    cursor.execute("SELECT id FROM egg_groups WHERE name = %s", (name,))
    egg_group_id = cursor.fetchone()[0]
    egg_cache[name] = egg_group_id
    return egg_group_id


def seed_pokemon_range(
    type_name_to_id: dict[str, int],
    start_id: int,
    end_id: int,
    delay: float,
    workers: int,
) -> int:
    """
    Fetch and store Pokémon `start_id`..`end_id` using concurrent HTTP fetches
    and sequential MySQL transactions. Returns count of newly inserted Pokémon.
    """
    print(f"\n=== Phase 2: Seeding Pokémon #{start_id} to #{end_id} (workers={workers}) ===")

    ability_cache: dict[str, int] = {}
    egg_cache: dict[str, int] = {}
    move_cache: dict[str, int] = {}
    newly_saved = 0

    with get_db_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT id FROM pokemon WHERE id BETWEEN %s AND %s", (start_id, end_id))
        existing_ids = {row[0] for row in cursor.fetchall()}

        cursor.execute("SELECT name, id FROM abilities")
        ability_cache.update(cursor.fetchall())
        cursor.execute("SELECT name, id FROM egg_groups")
        egg_cache.update(cursor.fetchall())
        cursor.execute("SELECT name, id FROM moves")
        move_cache.update(cursor.fetchall())

        missing_ids = [pid for pid in range(start_id, end_id + 1) if pid not in existing_ids]
        skipped_count = (end_id - start_id + 1) - len(missing_ids)
        if skipped_count:
            print(f"Skipping {skipped_count} already-imported Pokémon. {len(missing_ids)} remaining.")

        if not missing_ids:
            cursor.close()
            return 0

        with ThreadPoolExecutor(max_workers=workers) as executor:
            for batch_start in range(0, len(missing_ids), BATCH_SIZE):
                batch_ids = missing_ids[batch_start : batch_start + BATCH_SIZE]

                # 1. Fetch pokemon + species payloads concurrently for this batch
                bundles: dict[int, tuple[dict[str, Any], dict[str, Any]]] = {}
                future_map = {
                    executor.submit(fetch_pokemon_bundle, pid, delay): pid for pid in batch_ids
                }
                for fut in as_completed(future_map):
                    pid = future_map[fut]
                    try:
                        _, poke_data, species_data = fut.result()
                        bundles[pid] = (poke_data, species_data)
                    except Exception as exc:
                        print(f"ERROR fetching Pokémon #{pid}: {exc}", file=sys.stderr)

                # 2. Collect all unseen level-up moves in this batch and fetch them concurrently
                batch_moves_by_pid: dict[int, list[tuple[str, int]]] = {}
                unseen_moves: set[str] = set()
                for pid, (poke_data, _) in bundles.items():
                    top_moves = extract_top_level_up_moves(
                        poke_data.get("moves", []), limit=TOP_LEVEL_UP_MOVES
                    )
                    batch_moves_by_pid[pid] = top_moves
                    for move_name, _ in top_moves:
                        if move_name not in move_cache:
                            unseen_moves.add(move_name)

                if unseen_moves:
                    move_futures = {
                        executor.submit(fetch_move_meta, mname, delay): mname
                        for mname in unseen_moves
                    }
                    for fut in as_completed(move_futures):
                        mname = move_futures[fut]
                        try:
                            _, meta = fut.result()
                            cursor.execute(
                                """
                                INSERT INTO moves (name, type_name, damage_class, power, accuracy, pp)
                                VALUES (%s, %s, %s, %s, %s, %s)
                                ON DUPLICATE KEY UPDATE
                                    type_name = VALUES(type_name),
                                    damage_class = VALUES(damage_class),
                                    power = VALUES(power),
                                    accuracy = VALUES(accuracy),
                                    pp = VALUES(pp)
                                """,
                                (
                                    mname,
                                    meta["type_name"],
                                    meta["damage_class"],
                                    meta["power"],
                                    meta["accuracy"],
                                    meta["pp"],
                                ),
                            )
                            cursor.execute("SELECT id FROM moves WHERE name = %s", (mname,))
                            move_cache[mname] = cursor.fetchone()[0]
                        except Exception as exc:
                            print(f"  WARN fetching move '{mname}': {exc}", file=sys.stderr)
                    conn.commit()

                # 3. Insert each Pokémon in ID order on the main thread
                for pid in batch_ids:
                    if pid not in bundles:
                        continue
                    poke_data, species_data = bundles[pid]
                    try:
                        name = poke_data["name"]
                        height_m = round(poke_data.get("height", 0) / 10.0, 2)
                        weight_kg = round(poke_data.get("weight", 0) / 10.0, 2)
                        base_experience = poke_data.get("base_experience")

                        stat_map = {
                            s["stat"]["name"]: s["base_stat"]
                            for s in poke_data.get("stats", [])
                        }
                        hp = stat_map.get("hp", 0)
                        attack = stat_map.get("attack", 0)
                        defense = stat_map.get("defense", 0)
                        sp_attack = stat_map.get("special-attack", 0)
                        sp_defense = stat_map.get("special-defense", 0)
                        speed = stat_map.get("speed", 0)
                        stat_total = hp + attack + defense + sp_attack + sp_defense + speed

                        sprites = poke_data.get("sprites", {})
                        artwork_url = (
                            sprites.get("other", {})
                            .get("official-artwork", {})
                            .get("front_default")
                            or sprites.get("front_default")
                            or ""
                        )

                        flavor_text, version_logs = clean_flavor_text(
                            species_data.get("flavor_text_entries", []), name
                        )
                        genus = extract_genus(species_data.get("genera", []))
                        habitat = (species_data.get("habitat") or {}).get("name")
                        color = (species_data.get("color") or {}).get("name")
                        generation = (species_data.get("generation") or {}).get("name")
                        gender_rate = species_data.get("gender_rate", -1)
                        capture_rate = species_data.get("capture_rate")
                        base_happiness = species_data.get("base_happiness")
                        growth_rate = (species_data.get("growth_rate") or {}).get("name")
                        is_legendary = bool(species_data.get("is_legendary", False))
                        is_mythical = bool(species_data.get("is_mythical", False))
                        evolution_chain_id = extract_id_from_url(
                            (species_data.get("evolution_chain") or {}).get("url")
                        )

                        cursor.execute(
                            """
                            INSERT INTO pokemon (
                                id, name, height, weight, base_experience,
                                hp, attack, defense, sp_attack, sp_defense, speed, stat_total,
                                artwork_url, flavor_text, genus, habitat, color, generation,
                                gender_rate, capture_rate, base_happiness, growth_rate,
                                is_legendary, is_mythical, evolution_chain_id
                            ) VALUES (
                                %s, %s, %s, %s, %s,
                                %s, %s, %s, %s, %s, %s, %s,
                                %s, %s, %s, %s, %s, %s,
                                %s, %s, %s, %s,
                                %s, %s, %s
                            )
                            """,
                            (
                                pid, name, height_m, weight_kg, base_experience,
                                hp, attack, defense, sp_attack, sp_defense, speed, stat_total,
                                artwork_url, flavor_text, genus, habitat, color, generation,
                                gender_rate, capture_rate, base_happiness, growth_rate,
                                is_legendary, is_mythical, evolution_chain_id,
                            ),
                        )

                        for log in version_logs:
                            cursor.execute(
                                """
                                INSERT INTO pokemon_lore (pokemon_id, version_name, game_era, flavor_text)
                                VALUES (%s, %s, %s, %s)
                                ON DUPLICATE KEY UPDATE
                                    game_era = VALUES(game_era),
                                    flavor_text = VALUES(flavor_text)
                                """,
                                (pid, log["version"], log["era"], log["text"]),
                            )

                        for type_entry in poke_data.get("types", []):
                            t_id = type_name_to_id.get(type_entry["type"]["name"])
                            if t_id is not None:
                                cursor.execute(
                                    """
                                    INSERT IGNORE INTO pokemon_types (pokemon_id, type_id, slot)
                                    VALUES (%s, %s, %s)
                                    """,
                                    (pid, t_id, type_entry["slot"]),
                                )

                        for ab_entry in poke_data.get("abilities", []):
                            ab_id = get_or_create_ability(
                                cursor, ability_cache, ab_entry["ability"]["name"]
                            )
                            cursor.execute(
                                """
                                INSERT IGNORE INTO pokemon_abilities (pokemon_id, ability_id, is_hidden, slot)
                                VALUES (%s, %s, %s, %s)
                                """,
                                (pid, ab_id, bool(ab_entry.get("is_hidden", False)), ab_entry.get("slot", 1)),
                            )

                        for eg_entry in species_data.get("egg_groups", []):
                            eg_name = eg_entry.get("name")
                            if eg_name:
                                eg_id = get_or_create_egg_group(cursor, egg_cache, eg_name)
                                cursor.execute(
                                    """
                                    INSERT IGNORE INTO pokemon_egg_groups (pokemon_id, egg_group_id)
                                    VALUES (%s, %s)
                                    """,
                                    (pid, eg_id),
                                )

                        for move_name, level_learned in batch_moves_by_pid.get(pid, []):
                            move_id = move_cache.get(move_name)
                            if move_id is not None:
                                cursor.execute(
                                    """
                                    INSERT IGNORE INTO pokemon_moves (pokemon_id, move_id, level_learned_at, learn_method)
                                    VALUES (%s, %s, %s, 'level-up')
                                    """,
                                    (pid, move_id, level_learned),
                                )

                        conn.commit()
                        newly_saved += 1
                        print(f"Saved {pid}/{end_id}: {format_slug(name)}")
                    except (MySQLError, KeyError) as exc:
                        conn.rollback()
                        print(f"ERROR saving Pokémon #{pid}: {exc}", file=sys.stderr)

        cursor.close()

    return newly_saved


# -----------------------------------------------------------------------------
# Phase 3: Seed Evolution Chains (Concurrent Fetch)
# -----------------------------------------------------------------------------
def collect_evolution_edges(
    node: dict[str, Any],
    chain_id: int,
    valid_ids: set[int],
    stage: int = 1,
) -> list[tuple[int, int, int, int, str | None, int | None, str | None, str]]:
    """Recursively traverse an evolution chain tree and collect valid directed edges."""
    edges = []
    from_id = extract_id_from_url((node.get("species") or {}).get("url"))

    for child in node.get("evolves_to", []):
        to_id = extract_id_from_url((child.get("species") or {}).get("url"))
        trigger, min_level, item_name, condition_text = build_evolution_condition(
            child.get("evolution_details", [])
        )

        if from_id in valid_ids and to_id in valid_ids:
            edges.append(
                (chain_id, from_id, to_id, stage, trigger, min_level, item_name, condition_text)
            )
            edges.extend(collect_evolution_edges(child, chain_id, valid_ids, stage=stage + 1))
        else:
            edges.extend(collect_evolution_edges(child, chain_id, valid_ids, stage=stage))

    return edges


def seed_evolution_chains(delay: float, workers: int, refresh_all: bool = False) -> None:
    """Fetch and store evolution chains for all seeded Pokémon."""
    print("\n=== Phase 3: Seeding Evolution Chains ===")

    with get_db_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT id FROM pokemon")
        valid_ids = {row[0] for row in cursor.fetchall()}

        cursor.execute(
            "SELECT DISTINCT evolution_chain_id FROM pokemon WHERE evolution_chain_id IS NOT NULL ORDER BY evolution_chain_id"
        )
        all_chain_ids = [row[0] for row in cursor.fetchall()]

        if refresh_all:
            target_chains = all_chain_ids
        else:
            cursor.execute("SELECT DISTINCT chain_id FROM evolutions")
            existing_chains = {row[0] for row in cursor.fetchall()}
            target_chains = [cid for cid in all_chain_ids if cid not in existing_chains]

        total_chains = len(target_chains)
        print(f"Syncing {total_chains} evolution chains (workers={workers})...")

        if total_chains == 0:
            cursor.close()
            return

        def fetch_chain(cid: int) -> tuple[int, dict[str, Any]]:
            return cid, fetch_json(f"{POKEAPI_BASE}/evolution-chain/{cid}", delay=delay)

        saved_links = 0
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_map = {executor.submit(fetch_chain, cid): cid for cid in target_chains}
            for idx, fut in enumerate(as_completed(future_map), start=1):
                cid = future_map[fut]
                try:
                    _, chain_data = fut.result()
                    root = chain_data.get("chain")
                    if not root:
                        continue
                    edges = collect_evolution_edges(root, cid, valid_ids, stage=1)
                    for edge in edges:
                        cursor.execute(
                            """
                            INSERT INTO evolutions (
                                chain_id, from_pokemon_id, to_pokemon_id, stage,
                                trigger_name, min_level, item_name, condition_text
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                            ON DUPLICATE KEY UPDATE
                                stage = VALUES(stage),
                                trigger_name = VALUES(trigger_name),
                                min_level = VALUES(min_level),
                                item_name = VALUES(item_name),
                                condition_text = VALUES(condition_text)
                            """,
                            edge,
                        )
                    conn.commit()
                    saved_links += len(edges)
                    if idx % 50 == 0 or idx == total_chains:
                        print(f"  Processed {idx}/{total_chains} chains ({saved_links} total links)")
                except (RuntimeError, MySQLError) as exc:
                    conn.rollback()
                    print(f"  ERROR on evolution chain #{cid}: {exc}", file=sys.stderr)

        cursor.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed MySQL Pokédex database from PokéAPI.")
    parser.add_argument("--start", type=int, default=1, help="First Pokémon ID (default: 1)")
    parser.add_argument(
        "--end",
        type=int,
        default=Config.MAX_POKEMON_ID,
        help=f"Last Pokémon ID (default: {Config.MAX_POKEMON_ID} = all National Dex Pokémon)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.02,
        help="Small polite delay in seconds per HTTP request (default: 0.02)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=8,
        help="Concurrent HTTP worker threads (default: 8)",
    )
    parser.add_argument(
        "--refresh-evolutions",
        action="store_true",
        help="Re-sync all evolution chains (auto-enabled when new Pokémon are added)",
    )
    args = parser.parse_args()

    started_at = time.time()
    type_map = seed_types_and_relations(delay=args.delay)
    newly_saved = seed_pokemon_range(
        type_map,
        start_id=args.start,
        end_id=args.end,
        delay=args.delay,
        workers=args.workers,
    )
    # Refresh all chains if new Pokémon were added so cross-gen evolutions (e.g. Eevee -> Sylveon) link up
    seed_evolution_chains(
        delay=args.delay,
        workers=args.workers,
        refresh_all=(args.refresh_evolutions or newly_saved > 0),
    )

    elapsed = time.time() - started_at
    print(f"\nDone! Pokédex seeding finished in {elapsed:.1f}s ({newly_saved} new Pokémon saved).")


if __name__ == "__main__":
    main()
