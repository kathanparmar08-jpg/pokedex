"""
Enrich Pokémon Lore across all 1,025 Pokémon (IDs 1..1025).

What it does:
1. Fetches all English Pokédex entries from PokéAPI /pokemon-species/{id}.
2. Cleans text: removes form feeds, soft hyphens, normalizes ALL-CAPS 'POKéMON' with 'Pokémon',
   and cleans all-caps species names.
3. Groups and deduplicates entries by game version.
4. Uses smart word-overlap diversity selection to synthesize an expanded, multi-sentence
   comprehensive lore story (combining 2-3 distinct, complementary entries) and updates `pokemon.flavor_text`.
5. Stores every unique game-version Pokédex entry in the `pokemon_lore` table with its game era.
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

from config import Config, get_db_connection

POKEAPI_BASE = "https://pokeapi.co/api/v2"
BATCH_SIZE = 25

_thread_local = threading.local()

VERSION_ERAS: dict[str, tuple[str, str]] = {
    # version_slug: (Era Display Label, Badge Color Hex)
    "red": ("Gen I (Kanto)", "#DC2626"),
    "blue": ("Gen I (Kanto)", "#2563EB"),
    "yellow": ("Gen I (Kanto)", "#EAB308"),
    "gold": ("Gen II (Johto)", "#D97706"),
    "silver": ("Gen II (Johto)", "#64748B"),
    "crystal": ("Gen II (Johto)", "#06B6D4"),
    "ruby": ("Gen III (Hoenn)", "#DC2626"),
    "sapphire": ("Gen III (Hoenn)", "#2563EB"),
    "emerald": ("Gen III (Hoenn)", "#059669"),
    "firered": ("Gen III (Kanto)", "#EA580C"),
    "leafgreen": ("Gen III (Kanto)", "#16A34A"),
    "colosseum": ("Gen III (Orre)", "#7C3AED"),
    "xd": ("Gen III (Orre)", "#4F46E5"),
    "diamond": ("Gen IV (Sinnoh)", "#0284C7"),
    "pearl": ("Gen IV (Sinnoh)", "#EC4899"),
    "platinum": ("Gen IV (Sinnoh)", "#64748B"),
    "heartgold": ("Gen IV (Johto)", "#D97706"),
    "soulsilver": ("Gen IV (Johto)", "#94A3B8"),
    "black": ("Gen V (Unova)", "#1E293B"),
    "white": ("Gen V (Unova)", "#64748B"),
    "black-2": ("Gen V (Unova)", "#0F172A"),
    "white-2": ("Gen V (Unova)", "#475569"),
    "x": ("Gen VI (Kalos)", "#2563EB"),
    "y": ("Gen VI (Kalos)", "#DC2626"),
    "omega-ruby": ("Gen VI (Hoenn)", "#B91C1C"),
    "alpha-sapphire": ("Gen VI (Hoenn)", "#1D4ED8"),
    "sun": ("Gen VII (Alola)", "#EA580C"),
    "moon": ("Gen VII (Alola)", "#6366F1"),
    "ultra-sun": ("Gen VII (Alola)", "#C2410C"),
    "ultra-moon": ("Gen VII (Alola)", "#4338CA"),
    "lets-go-pikachu": ("Gen VII (Kanto)", "#EAB308"),
    "lets-go-eevee": ("Gen VII (Kanto)", "#B45309"),
    "sword": ("Gen VIII (Galar)", "#0284C7"),
    "shield": ("Gen VIII (Galar)", "#E11D48"),
    "brilliant-diamond": ("Gen VIII (Sinnoh)", "#0284C7"),
    "shining-pearl": ("Gen VIII (Sinnoh)", "#EC4899"),
    "legends-arceus": ("Gen VIII (Hisui)", "#D97706"),
    "scarlet": ("Gen IX (Paldea)", "#DC2626"),
    "violet": ("Gen IX (Paldea)", "#7C3AED"),
}


def get_thread_session() -> requests.Session:
    session = getattr(_thread_local, "session", None)
    if session is None:
        session = requests.Session()
        session.headers.update({"User-Agent": "PokedexLoreEnricher/2.0 (+https://pokeapi.co)"})
        _thread_local.session = session
    return session


def clean_lore_text(raw_text: str, pokemon_name: str = "") -> str:
    """Clean control characters, soft hyphens, and normalize old all-caps typography."""
    if not raw_text:
        return ""
    text = re.sub(r"[\f\n\r\t]+", " ", raw_text)
    text = text.replace("\u00ad ", "").replace("\u00ad", "")
    text = re.sub(r"\bPOK[eé]MON\b", "Pokémon", text, flags=re.IGNORECASE)

    # Clean up all-caps species words (e.g. 'BULBASAUR' -> 'Bulbasaur', 'CHARIZARD' -> 'Charizard')
    if pokemon_name:
        upper_name = pokemon_name.upper().replace("-", " ")
        title_name = pokemon_name.replace("-", " ").title()
        text = re.sub(r"\b" + re.escape(upper_name) + r"\b", title_name, text)

    text = re.sub(r"\s{2,}", " ", text).strip()
    return text


def word_overlap(s1: str, s2: str) -> float:
    """Compute Jaccard similarity of words with len >= 3."""
    w1 = set(re.findall(r"[a-z]{3,}", s1.lower()))
    w2 = set(re.findall(r"[a-z]{3,}", s2.lower()))
    if not w1 or not w2:
        return 0.0
    return len(w1 & w2) / max(len(w1), len(w2))


def select_diverse_entries(entries: list[dict[str, str]], max_count: int = 3) -> list[str]:
    """Select up to `max_count` unique lore snippets that do not duplicate identical facts."""
    selected: list[str] = []
    for e in entries:
        txt = e["text"]
        if any(word_overlap(txt, prev) > 0.40 for prev in selected):
            continue
        selected.append(txt)
        if len(selected) >= max_count:
            break
    if not selected and entries:
        selected.append(entries[0]["text"])
    return selected


def fetch_species_lore(poke_id: int) -> tuple[int, str, list[dict[str, str]]]:
    """Fetch species JSON and return cleaned English flavor text entries."""
    session = get_thread_session()
    url = f"{POKEAPI_BASE}/pokemon-species/{poke_id}"
    resp = session.get(url, timeout=12)
    resp.raise_for_status()
    data = resp.json()
    name = data.get("name", "")

    raw_entries = data.get("flavor_text_entries", [])
    en_entries = [e for e in raw_entries if e.get("language", {}).get("name") == "en"]

    cleaned_entries: list[dict[str, str]] = []
    seen_texts: set[str] = set()

    for e in en_entries:
        v_name = (e.get("version") or {}).get("name", "unknown")
        raw_text = e.get("flavor_text", "")
        cleaned = clean_lore_text(raw_text, name)
        if not cleaned:
            continue

        normalized_key = re.sub(r"[^a-z0-9]", "", cleaned.lower())
        is_duplicate = normalized_key in seen_texts
        seen_texts.add(normalized_key)

        era_info = VERSION_ERAS.get(v_name, ("Core Series", "#64748B"))

        cleaned_entries.append({
            "version": v_name,
            "version_name": v_name.replace("-", " ").title(),
            "era": era_info[0],
            "text": cleaned,
            "is_duplicate": is_duplicate,
        })

    return poke_id, name, cleaned_entries


def main() -> None:
    parser = argparse.ArgumentParser(description="Enrich Pokémon lore from PokéAPI.")
    parser.add_argument("--start", type=int, default=1, help="Start Pokémon ID (default: 1)")
    parser.add_argument("--end", type=int, default=1025, help="End Pokémon ID (default: 1025)")
    parser.add_argument("--workers", type=int, default=12, help="HTTP worker threads (default: 12)")
    args = parser.parse_args()

    started_at = time.time()
    total_pokemon = args.end - args.start + 1
    print(f"\n=== Enriching Lore for Pokémon #{args.start}..#{args.end} ({total_pokemon} total, {args.workers} workers) ===")

    poke_ids = list(range(args.start, args.end + 1))
    processed_count = 0
    total_lore_rows = 0

    with get_db_connection() as conn:
        cursor = conn.cursor()

        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            for b_start in range(0, len(poke_ids), BATCH_SIZE):
                batch = poke_ids[b_start : b_start + BATCH_SIZE]
                future_map = {executor.submit(fetch_species_lore, pid): pid for pid in batch}

                for fut in as_completed(future_map):
                    pid = future_map[fut]
                    try:
                        _, name, entries = fut.result()
                        if not entries:
                            continue

                        # 1. Synthesize diverse, multi-sentence expanded lore narrative
                        diverse_snippets = select_diverse_entries(entries, max_count=3)
                        expanded_lore = " ".join(diverse_snippets)

                        # Update primary lore in pokemon table
                        cursor.execute(
                            "UPDATE pokemon SET flavor_text = %s WHERE id = %s",
                            (expanded_lore, pid),
                        )

                        # 2. Insert all unique game-version lore entries into pokemon_lore
                        for e in entries:
                            cursor.execute(
                                """
                                INSERT INTO pokemon_lore (pokemon_id, version_name, game_era, flavor_text)
                                VALUES (%s, %s, %s, %s)
                                ON DUPLICATE KEY UPDATE
                                    game_era = VALUES(game_era),
                                    flavor_text = VALUES(flavor_text)
                                """,
                                (pid, e["version"], e["era"], e["text"]),
                            )
                            total_lore_rows += 1

                        conn.commit()
                        processed_count += 1
                        if processed_count % 100 == 0 or processed_count == total_pokemon:
                            print(f"  Enriched {processed_count}/{total_pokemon} Pokémon ({total_lore_rows} version logs stored)")

                    except (requests.RequestException, MySQLError, Exception) as exc:
                        conn.rollback()
                        print(f"  ERROR on Pokémon #{pid}: {exc}", file=sys.stderr)

        cursor.close()

    elapsed = time.time() - started_at
    print(f"\nDone! Enriched {processed_count} Pokémon with {total_lore_rows} historical lore entries in {elapsed:.1f}s.")


if __name__ == "__main__":
    main()
