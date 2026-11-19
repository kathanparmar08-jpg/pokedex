"""
Pokédex Flask Application (All National Dex Pokémon, Gen I–IX)
Routes:
  - GET /                    : Home page with 3D-flip Pokémon card grid, filters & pagination
  - GET /pokemon/<int:id>    : Full Pokémon detail page
  - GET /api/pokemon         : Paginated JSON list supporting search, type, generation,
                               rarity, egg_group, color, habitat, min_stat, sort, page, limit
  - GET /api/pokemon/<id>    : Full JSON payload for a single Pokémon
"""

from __future__ import annotations

import math
from decimal import Decimal
from typing import Any

from flask import Flask, abort, jsonify, render_template, request

from config import Config, TYPE_COLORS, VERSION_METADATA, get_db_connection

app = Flask(__name__)
app.config.from_object(Config)

# Special display names for punctuated/hyphenated Pokémon slugs across Gen I–IX
SPECIAL_NAMES: dict[str, str] = {
    "nidoran-f": "Nidoran ♀",
    "nidoran-m": "Nidoran ♂",
    "farfetchd": "Farfetch'd",
    "sirfetchd": "Sirfetch'd",
    "mr-mime": "Mr. Mime",
    "mime-jr": "Mime Jr.",
    "mr-rime": "Mr. Rime",
    "ho-oh": "Ho-Oh",
    "porygon2": "Porygon2",
    "porygon-z": "Porygon-Z",
    "type-null": "Type: Null",
    "jangmo-o": "Jangmo-o",
    "hakamo-o": "Hakamo-o",
    "kommo-o": "Kommo-o",
    "wo-chien": "Wo-Chien",
    "chien-pao": "Chien-Pao",
    "ting-lu": "Ting-Lu",
    "chi-yu": "Chi-Yu",
    "flabebe": "Flabébé",
}

# Ordered Generation metadata with region names
GENERATION_ORDER: list[tuple[str, str]] = [
    ("generation-i", "Gen I — Kanto"),
    ("generation-ii", "Gen II — Johto"),
    ("generation-iii", "Gen III — Hoenn"),
    ("generation-iv", "Gen IV — Sinnoh"),
    ("generation-v", "Gen V — Unova"),
    ("generation-vi", "Gen VI — Kalos"),
    ("generation-vii", "Gen VII — Alola"),
    ("generation-viii", "Gen VIII — Galar"),
    ("generation-ix", "Gen IX — Paldea"),
]
GENERATION_LABELS: dict[str, str] = dict(GENERATION_ORDER)


# -----------------------------------------------------------------------------
# Formatting & Domain Helpers
# -----------------------------------------------------------------------------
def format_display_name(slug: str | None) -> str:
    """Convert PokéAPI slugs into user-friendly display names."""
    if not slug:
        return ""
    if slug in SPECIAL_NAMES:
        return SPECIAL_NAMES[slug]
    return slug.replace("-", " ").title()


def format_generation(slug: str | None) -> str:
    """Format 'generation-ii' -> 'Gen II — Johto'."""
    if not slug:
        return "Unknown"
    if slug in GENERATION_LABELS:
        return GENERATION_LABELS[slug]
    parts = slug.split("-")
    if len(parts) == 2 and parts[0] == "generation":
        return f"Generation {parts[1].upper()}"
    return slug.replace("-", " ").title()


def format_dex_id(poke_id: int) -> str:
    """Format #001..#999 as 3 digits and #1000+ as 4 digits."""
    return f"#{poke_id:04d}" if poke_id >= 1000 else f"#{poke_id:03d}"


def compute_gender_info(gender_rate: int) -> dict[str, Any]:
    """Convert PokéAPI gender_rate (-1 or 0..8 eighths female) into percentages."""
    if gender_rate is None or gender_rate < 0:
        return {"genderless": True, "male_pct": 0.0, "female_pct": 0.0}
    female_pct = round((gender_rate / 8.0) * 100.0, 1)
    male_pct = round(100.0 - female_pct, 1)
    return {"genderless": False, "male_pct": male_pct, "female_pct": female_pct}


def format_multiplier(mult: float) -> str:
    """Format effectiveness multiplier cleanly (e.g., 4x, 2x, ½x, ¼x, 0x)."""
    if mult == 0:
        return "0×"
    if mult == 0.25:
        return "¼×"
    if mult == 0.5:
        return "½×"
    if mult == int(mult):
        return f"{int(mult)}×"
    return f"{mult:g}×"


def to_float(value: Decimal | float | int | None) -> float:
    return float(value) if value is not None else 0.0


app.jinja_env.filters["display_name"] = format_display_name
app.jinja_env.filters["format_gen"] = format_generation


# -----------------------------------------------------------------------------
# Database Query Helpers
# -----------------------------------------------------------------------------
def get_filter_options() -> dict[str, Any]:
    """Fetch all dynamic dropdown/chip filter options from MySQL."""
    with get_db_connection() as conn:
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT id, name, color_hex FROM types ORDER BY name ASC")
        types = cursor.fetchall()

        cursor.execute("SELECT DISTINCT generation FROM pokemon WHERE generation IS NOT NULL")
        db_gens = {r["generation"] for r in cursor.fetchall()}
        generations = [
            {"value": slug, "label": label}
            for slug, label in GENERATION_ORDER
            if slug in db_gens or not db_gens
        ]

        cursor.execute("SELECT DISTINCT habitat FROM pokemon WHERE habitat IS NOT NULL ORDER BY habitat ASC")
        habitats = [
            {"value": r["habitat"], "label": format_display_name(r["habitat"])}
            for r in cursor.fetchall()
        ]

        cursor.execute("SELECT DISTINCT color FROM pokemon WHERE color IS NOT NULL ORDER BY color ASC")
        colors = [
            {"value": r["color"], "label": format_display_name(r["color"])}
            for r in cursor.fetchall()
        ]

        cursor.execute("SELECT name FROM egg_groups ORDER BY name ASC")
        egg_groups = [
            {"value": r["name"], "label": format_display_name(r["name"])}
            for r in cursor.fetchall()
        ]

        cursor.close()

    return {
        "types": types,
        "generations": generations,
        "habitats": habitats,
        "colors": colors,
        "egg_groups": egg_groups,
    }


def fetch_types_for_pokemon_ids(cursor, pokemon_ids: list[int]) -> dict[int, list[dict[str, Any]]]:
    """Batch-load types for a list of Pokémon IDs to avoid N+1 queries."""
    if not pokemon_ids:
        return {}
    placeholders = ", ".join(["%s"] * len(pokemon_ids))
    cursor.execute(
        f"""
        SELECT pt.pokemon_id, t.id, t.name, t.color_hex, pt.slot
        FROM pokemon_types pt
        JOIN types t ON t.id = pt.type_id
        WHERE pt.pokemon_id IN ({placeholders})
        ORDER BY pt.pokemon_id ASC, pt.slot ASC
        """,
        tuple(pokemon_ids),
    )
    mapping: dict[int, list[dict[str, Any]]] = {pid: [] for pid in pokemon_ids}
    for row in cursor.fetchall():
        mapping[row["pokemon_id"]].append(
            {
                "id": row["id"],
                "name": row["name"],
                "display_name": row["name"].title(),
                "color": row["color_hex"],
                "slot": row["slot"],
            }
        )
    return mapping


def query_pokemon_list(
    search: str = "",
    type_filter: str = "",
    generation: str = "",
    rarity: str = "",
    habitat: str = "",
    color: str = "",
    egg_group: str = "",
    min_stat: int = 0,
    sort: str = "id_asc",
    page: int = 1,
    limit: int = Config.DEFAULT_PAGE_LIMIT,
) -> dict[str, Any]:
    """
    Query a filtered, sorted, strictly paginated (20/page default) list of Pokémon
    for both the home page and the GET /api/pokemon JSON endpoint.
    """
    page = max(1, page)
    limit = max(1, min(limit, Config.MAX_PAGE_LIMIT))

    where_clauses: list[str] = []
    params: list[Any] = []
    joins: list[str] = []

    clean_search = search.strip().lower()
    if clean_search:
        numeric_candidate = clean_search.lstrip("#")
        if numeric_candidate.isdigit():
            where_clauses.append("(p.id = %s OR p.name LIKE %s)")
            params.extend([int(numeric_candidate), f"%{clean_search}%"])
        else:
            where_clauses.append("p.name LIKE %s")
            params.append(f"%{clean_search.replace(' ', '-')}%")

    clean_type = type_filter.strip().lower()
    if clean_type and clean_type != "all":
        joins.append(
            "JOIN pokemon_types pt_filter ON pt_filter.pokemon_id = p.id "
            "JOIN types t_filter ON t_filter.id = pt_filter.type_id"
        )
        where_clauses.append("t_filter.name = %s")
        params.append(clean_type)

    clean_gen = generation.strip().lower()
    if clean_gen and clean_gen != "all":
        where_clauses.append("p.generation = %s")
        params.append(clean_gen)

    clean_rarity = rarity.strip().lower()
    if clean_rarity == "legendary":
        where_clauses.append("p.is_legendary = 1")
    elif clean_rarity == "mythical":
        where_clauses.append("p.is_mythical = 1")
    elif clean_rarity == "special":
        where_clauses.append("(p.is_legendary = 1 OR p.is_mythical = 1)")
    elif clean_rarity == "standard":
        where_clauses.append("(p.is_legendary = 0 AND p.is_mythical = 0)")

    clean_habitat = habitat.strip().lower()
    if clean_habitat and clean_habitat != "all":
        where_clauses.append("p.habitat = %s")
        params.append(clean_habitat)

    clean_color = color.strip().lower()
    if clean_color and clean_color != "all":
        where_clauses.append("p.color = %s")
        params.append(clean_color)

    clean_egg = egg_group.strip().lower()
    if clean_egg and clean_egg != "all":
        joins.append(
            "JOIN pokemon_egg_groups peg_filter ON peg_filter.pokemon_id = p.id "
            "JOIN egg_groups eg_filter ON eg_filter.id = peg_filter.egg_group_id"
        )
        where_clauses.append("eg_filter.name = %s")
        params.append(clean_egg)

    if min_stat and min_stat > 0:
        where_clauses.append("p.stat_total >= %s")
        params.append(min_stat)

    join_sql = (" " + " ".join(joins)) if joins else ""
    where_sql = f" WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    sort_map = {
        "id_asc": "p.id ASC",
        "id_desc": "p.id DESC",
        "name_asc": "p.name ASC",
        "name_desc": "p.name DESC",
        "total_desc": "p.stat_total DESC, p.id ASC",
        "total_asc": "p.stat_total ASC, p.id ASC",
        "hp_desc": "p.hp DESC, p.id ASC",
        "attack_desc": "p.attack DESC, p.id ASC",
        "speed_desc": "p.speed DESC, p.id ASC",
        "weight_desc": "p.weight DESC, p.id ASC",
        "height_desc": "p.height DESC, p.id ASC",
    }
    order_sql = sort_map.get(sort, "p.id ASC")

    with get_db_connection() as conn:
        cursor = conn.cursor(dictionary=True)

        # Total matching records
        cursor.execute(
            f"SELECT COUNT(DISTINCT p.id) AS total FROM pokemon p{join_sql}{where_sql}",
            tuple(params),
        )
        total = cursor.fetchone()["total"]
        total_pages = max(1, math.ceil(total / limit)) if total > 0 else 1

        # Clamp requested page within valid bounds
        page = min(page, total_pages)
        offset = (page - 1) * limit

        # Fetch strictly `limit` (20) rows for the requested page
        cursor.execute(
            f"""
            SELECT DISTINCT
                p.id, p.name, p.height, p.weight,
                p.hp, p.attack, p.defense, p.sp_attack, p.sp_defense, p.speed, p.stat_total,
                p.artwork_url, p.flavor_text, p.genus, p.generation, p.is_legendary, p.is_mythical
            FROM pokemon p
            {join_sql}
            {where_sql}
            ORDER BY {order_sql}
            LIMIT %s OFFSET %s
            """,
            tuple(params + [limit, offset]),
        )
        rows = cursor.fetchall()

        poke_ids = [r["id"] for r in rows]
        types_map = fetch_types_for_pokemon_ids(cursor, poke_ids)
        cursor.close()

    items: list[dict[str, Any]] = []
    for r in rows:
        poke_types = types_map.get(r["id"], [])
        primary_type = poke_types[0] if poke_types else {"name": "normal", "color": TYPE_COLORS["normal"]}
        items.append(
            {
                "id": r["id"],
                "formatted_id": format_dex_id(r["id"]),
                "name": r["name"],
                "display_name": format_display_name(r["name"]),
                "height": to_float(r["height"]),
                "weight": to_float(r["weight"]),
                "stats": {
                    "hp": r["hp"],
                    "attack": r["attack"],
                    "defense": r["defense"],
                    "sp_attack": r["sp_attack"],
                    "sp_defense": r["sp_defense"],
                    "speed": r["speed"],
                    "total": r["stat_total"],
                },
                "artwork_url": r["artwork_url"],
                "flavor_text": r["flavor_text"],
                "genus": r["genus"],
                "generation": format_generation(r["generation"]),
                "is_legendary": bool(r["is_legendary"]),
                "is_mythical": bool(r["is_mythical"]),
                "types": poke_types,
                "primary_type": primary_type["name"],
                "primary_color": primary_type["color"],
            }
        )

    start_index = (offset + 1) if total > 0 else 0
    end_index = min(offset + len(items), total) if total > 0 else 0

    return {
        "items": items,
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": total_pages,
        "has_prev": page > 1,
        "has_next": page < total_pages,
        "start_index": start_index,
        "end_index": end_index,
    }


def compute_type_matchups(cursor, type_ids: list[int]) -> dict[str, list[dict[str, Any]]]:
    """Calculate combined defensive weaknesses, resistances, and immunities."""
    cursor.execute("SELECT id, name, color_hex FROM types ORDER BY name ASC")
    all_types = cursor.fetchall()

    multipliers: dict[int, float] = {t["id"]: 1.0 for t in all_types}

    if type_ids:
        placeholders = ", ".join(["%s"] * len(type_ids))
        cursor.execute(
            f"""
            SELECT attacking_type_id, defending_type_id, multiplier
            FROM type_effectiveness
            WHERE defending_type_id IN ({placeholders})
            """,
            tuple(type_ids),
        )
        for row in cursor.fetchall():
            atk_id = row["attacking_type_id"]
            if atk_id in multipliers:
                multipliers[atk_id] *= float(row["multiplier"])

    weaknesses: list[dict[str, Any]] = []
    resistances: list[dict[str, Any]] = []
    immunities: list[dict[str, Any]] = []

    for t in all_types:
        mult = round(multipliers[t["id"]], 2)
        entry = {
            "name": t["name"],
            "display_name": t["name"].title(),
            "color": t["color_hex"],
            "multiplier": mult,
            "label": format_multiplier(mult),
        }
        if mult == 0.0:
            immunities.append(entry)
        elif mult > 1.0:
            weaknesses.append(entry)
        elif mult < 1.0:
            resistances.append(entry)

    weaknesses.sort(key=lambda x: (-x["multiplier"], x["name"]))
    resistances.sort(key=lambda x: (x["multiplier"], x["name"]))

    return {
        "weaknesses": weaknesses,
        "resistances": resistances,
        "immunities": immunities,
    }


def build_evolution_chain(cursor, chain_id: int | None) -> dict[str, Any]:
    """Build a structured evolution graph supporting both linear and branching chains."""
    if not chain_id:
        return {"has_evolutions": False, "links": []}

    cursor.execute(
        """
        SELECT
            e.stage, e.trigger_name, e.min_level, e.item_name, e.condition_text,
            p_from.id AS from_id, p_from.name AS from_name, p_from.artwork_url AS from_artwork,
            p_to.id AS to_id, p_to.name AS to_name, p_to.artwork_url AS to_artwork
        FROM evolutions e
        JOIN pokemon p_from ON p_from.id = e.from_pokemon_id
        JOIN pokemon p_to   ON p_to.id   = e.to_pokemon_id
        WHERE e.chain_id = %s
        ORDER BY e.stage ASC, p_from.id ASC, p_to.id ASC
        """,
        (chain_id,),
    )
    rows = cursor.fetchall()

    if not rows:
        return {"has_evolutions": False, "links": []}

    links = []
    for r in rows:
        links.append(
            {
                "stage": r["stage"],
                "condition": r["condition_text"],
                "trigger": r["trigger_name"],
                "min_level": r["min_level"],
                "item": format_display_name(r["item_name"]) if r["item_name"] else None,
                "source": {
                    "id": r["from_id"],
                    "formatted_id": format_dex_id(r["from_id"]),
                    "name": r["from_name"],
                    "display_name": format_display_name(r["from_name"]),
                    "artwork_url": r["from_artwork"],
                },
                "target": {
                    "id": r["to_id"],
                    "formatted_id": format_dex_id(r["to_id"]),
                    "name": r["to_name"],
                    "display_name": format_display_name(r["to_name"]),
                    "artwork_url": r["to_artwork"],
                },
            }
        )

    from_ids = [link["source"]["id"] for link in links]
    is_linear = len(from_ids) == len(set(from_ids))

    linear_steps: list[dict[str, Any]] = []
    if is_linear:
        by_from = {link["source"]["id"]: link for link in links}
        to_set = {link["target"]["id"] for link in links}
        roots = [fid for fid in from_ids if fid not in to_set]
        if roots:
            curr_id = roots[0]
            first_link = by_from[curr_id]
            linear_steps.append({"pokemon": first_link["source"], "condition": None})
            visited = {curr_id}
            while curr_id in by_from:
                link = by_from[curr_id]
                next_node = link["target"]
                if next_node["id"] in visited:
                    break
                linear_steps.append({"pokemon": next_node, "condition": link["condition"]})
                visited.add(next_node["id"])
                curr_id = next_node["id"]
        else:
            is_linear = False

    return {
        "has_evolutions": True,
        "is_linear": is_linear,
        "linear_steps": linear_steps,
        "links": links,
    }


def get_pokemon_detail(pokemon_id: int) -> dict[str, Any] | None:
    """Fetch complete details for a single Pokémon by ID."""
    with get_db_connection() as conn:
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT * FROM pokemon WHERE id = %s", (pokemon_id,))
        row = cursor.fetchone()
        if not row:
            cursor.close()
            return None

        types_list = fetch_types_for_pokemon_ids(cursor, [pokemon_id]).get(pokemon_id, [])
        type_ids = [t["id"] for t in types_list]
        primary_type = types_list[0] if types_list else {"name": "normal", "color": TYPE_COLORS["normal"]}

        cursor.execute(
            """
            SELECT a.name, pa.is_hidden, pa.slot
            FROM pokemon_abilities pa
            JOIN abilities a ON a.id = pa.ability_id
            WHERE pa.pokemon_id = %s
            ORDER BY pa.slot ASC
            """,
            (pokemon_id,),
        )
        abilities = [
            {
                "name": a["name"],
                "display_name": format_display_name(a["name"]),
                "is_hidden": bool(a["is_hidden"]),
            }
            for a in cursor.fetchall()
        ]

        cursor.execute(
            """
            SELECT eg.name
            FROM pokemon_egg_groups peg
            JOIN egg_groups eg ON eg.id = peg.egg_group_id
            WHERE peg.pokemon_id = %s
            ORDER BY eg.name ASC
            """,
            (pokemon_id,),
        )
        egg_groups = [format_display_name(eg["name"]) for eg in cursor.fetchall()]

        cursor.execute(
            """
            SELECT m.name, m.type_name, m.damage_class, m.power, m.accuracy, m.pp, pm.level_learned_at
            FROM pokemon_moves pm
            JOIN moves m ON m.id = pm.move_id
            WHERE pm.pokemon_id = %s
            ORDER BY pm.level_learned_at ASC, m.name ASC
            """,
            (pokemon_id,),
        )
        moves = []
        for m in cursor.fetchall():
            m_type = m["type_name"] or "normal"
            moves.append(
                {
                    "name": m["name"],
                    "display_name": format_display_name(m["name"]),
                    "level": m["level_learned_at"],
                    "type": m_type,
                    "type_color": TYPE_COLORS.get(m_type, "#A8A77A"),
                    "damage_class": (m["damage_class"] or "status").title(),
                    "power": m["power"],
                    "accuracy": m["accuracy"],
                    "pp": m["pp"],
                }
            )

        matchups = compute_type_matchups(cursor, type_ids)
        evolution_chain = build_evolution_chain(cursor, row["evolution_chain_id"])

        cursor.execute(
            "SELECT id, name, artwork_url FROM pokemon WHERE id < %s ORDER BY id DESC LIMIT 1",
            (pokemon_id,),
        )
        prev_row = cursor.fetchone()
        prev_pokemon = (
            {
                "id": prev_row["id"],
                "formatted_id": format_dex_id(prev_row["id"]),
                "display_name": format_display_name(prev_row["name"]),
                "artwork_url": prev_row["artwork_url"],
            }
            if prev_row
            else None
        )

        cursor.execute(
            "SELECT id, name, artwork_url FROM pokemon WHERE id > %s ORDER BY id ASC LIMIT 1",
            (pokemon_id,),
        )
        next_row = cursor.fetchone()
        next_pokemon = (
            {
                "id": next_row["id"],
                "formatted_id": format_dex_id(next_row["id"]),
                "display_name": format_display_name(next_row["name"]),
                "artwork_url": next_row["artwork_url"],
            }
            if next_row
            else None
        )

        # Historical Pokédex Lore entries across all game versions
        cursor.execute(
            """
            SELECT version_name, game_era, flavor_text
            FROM pokemon_lore
            WHERE pokemon_id = %s
            ORDER BY id ASC
            """,
            (pokemon_id,),
        )
        lore_archive = []
        lore_by_era: dict[str, list[dict[str, Any]]] = {}
        for l_row in cursor.fetchall():
            v_slug = l_row["version_name"]
            meta = VERSION_METADATA.get(v_slug, {
                "name": format_display_name(v_slug),
                "color": "#64748B",
                "era": l_row["game_era"] or "Core Series",
            })
            entry = {
                "version": v_slug,
                "version_name": meta["name"],
                "color": meta["color"],
                "era": meta["era"],
                "flavor_text": l_row["flavor_text"],
            }
            lore_archive.append(entry)
            era_key = meta["era"]
            if era_key not in lore_by_era:
                lore_by_era[era_key] = []
            lore_by_era[era_key].append(entry)

        cursor.close()

    stats_list = [
        {"key": "hp", "label": "HP", "value": row["hp"]},
        {"key": "attack", "label": "Attack", "value": row["attack"]},
        {"key": "defense", "label": "Defense", "value": row["defense"]},
        {"key": "sp_attack", "label": "Sp. Atk", "value": row["sp_attack"]},
        {"key": "sp_defense", "label": "Sp. Def", "value": row["sp_defense"]},
        {"key": "speed", "label": "Speed", "value": row["speed"]},
    ]

    capture_rate = row["capture_rate"] or 0
    capture_pct = round((capture_rate / 255.0) * 100.0, 1)

    return {
        "id": row["id"],
        "formatted_id": format_dex_id(row["id"]),
        "name": row["name"],
        "display_name": format_display_name(row["name"]),
        "height": to_float(row["height"]),
        "weight": to_float(row["weight"]),
        "base_experience": row["base_experience"],
        "stats": {
            "hp": row["hp"],
            "attack": row["attack"],
            "defense": row["defense"],
            "sp_attack": row["sp_attack"],
            "sp_defense": row["sp_defense"],
            "speed": row["speed"],
            "total": row["stat_total"],
        },
        "stats_list": stats_list,
        "artwork_url": row["artwork_url"],
        "flavor_text": row["flavor_text"],
        "genus": row["genus"] or "Pokémon",
        "habitat": format_display_name(row["habitat"]) if row["habitat"] else "Unknown",
        "color": format_display_name(row["color"]) if row["color"] else "Unknown",
        "generation": format_generation(row["generation"]),
        "growth_rate": format_display_name(row["growth_rate"]) if row["growth_rate"] else "Unknown",
        "gender": compute_gender_info(row["gender_rate"]),
        "capture_rate": capture_rate,
        "capture_pct": capture_pct,
        "base_happiness": row["base_happiness"],
        "is_legendary": bool(row["is_legendary"]),
        "is_mythical": bool(row["is_mythical"]),
        "types": types_list,
        "primary_type": primary_type["name"],
        "primary_color": primary_type["color"],
        "abilities": abilities,
        "egg_groups": egg_groups,
        "moves": moves,
        "matchups": matchups,
        "evolution_chain": evolution_chain,
        "lore_archive": lore_archive,
        "lore_by_era": lore_by_era,
        "total_lore_entries": len(lore_archive),
        "prev_pokemon": prev_pokemon,
        "next_pokemon": next_pokemon,
    }


# -----------------------------------------------------------------------------
# Web Routes
# -----------------------------------------------------------------------------
@app.route("/")
def index():
    """Render the home page with the 3D flip card grid, advanced filters & pagination."""
    filter_options = get_filter_options()
    initial_data = query_pokemon_list(page=1, limit=Config.DEFAULT_PAGE_LIMIT)
    return render_template(
        "index.html",
        filter_options=filter_options,
        initial_data=initial_data,
        type_colors=TYPE_COLORS,
    )


@app.route("/pokemon/<int:pokemon_id>")
def pokemon_detail(pokemon_id: int):
    """Render the comprehensive detail page for a single Pokémon."""
    pokemon = get_pokemon_detail(pokemon_id)
    if pokemon is None:
        abort(404)
    return render_template("detail.html", pokemon=pokemon, type_colors=TYPE_COLORS)


# -----------------------------------------------------------------------------
# JSON API Routes
# -----------------------------------------------------------------------------
@app.route("/api/pokemon")
def api_pokemon_list():
    """
    Paginated JSON list endpoint (default 20 per page).
    Supported query params:
      - search     : substring match on name or numeric ID
      - type       : Pokémon type name (e.g. 'fire')
      - generation : generation slug (e.g. 'generation-i')
      - rarity     : standard | legendary | mythical | special
      - habitat    : habitat slug (e.g. 'forest')
      - color      : color name (e.g. 'red')
      - egg_group  : egg group slug (e.g. 'dragon')
      - min_stat   : minimum base stat total (integer, e.g. 500)
      - sort       : id_asc | id_desc | name_asc | name_desc | total_desc | total_asc |
                     hp_desc | attack_desc | speed_desc | weight_desc | height_desc
      - page       : 1-based page number (default 1)
      - limit      : items per page (default 20, max 100)
    """
    result = query_pokemon_list(
        search=request.args.get("search", "", type=str),
        type_filter=request.args.get("type", "", type=str),
        generation=request.args.get("generation", "", type=str),
        rarity=request.args.get("rarity", "", type=str),
        habitat=request.args.get("habitat", "", type=str),
        color=request.args.get("color", "", type=str),
        egg_group=request.args.get("egg_group", "", type=str),
        min_stat=request.args.get("min_stat", 0, type=int) or 0,
        sort=request.args.get("sort", "id_asc", type=str),
        page=request.args.get("page", 1, type=int) or 1,
        limit=request.args.get("limit", Config.DEFAULT_PAGE_LIMIT, type=int) or Config.DEFAULT_PAGE_LIMIT,
    )
    return jsonify(result)


@app.route("/api/pokemon/<int:pokemon_id>")
def api_pokemon_detail(pokemon_id: int):
    """Return full JSON details for a single Pokémon."""
    pokemon = get_pokemon_detail(pokemon_id)
    if pokemon is None:
        return jsonify({"error": "Pokémon not found", "id": pokemon_id}), 404
    return jsonify(pokemon)


# -----------------------------------------------------------------------------
# Error Handlers
# -----------------------------------------------------------------------------
@app.errorhandler(404)
def handle_404(_error):
    if request.path.startswith("/api/"):
        return jsonify({"error": "Resource not found"}), 404
    return render_template("404.html", type_colors=TYPE_COLORS), 404


@app.errorhandler(500)
def handle_500(_error):
    if request.path.startswith("/api/"):
        return jsonify({"error": "Internal server error"}), 500
    return render_template("404.html", error_code=500, error_title="Something went wrong", type_colors=TYPE_COLORS), 500


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=Config.DEBUG)
