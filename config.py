"""
Application configuration, Pokémon type palette, and MySQL connection pooling.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

from dotenv import load_dotenv
from mysql.connector import pooling
from mysql.connector.connection import MySQLConnection

# Load environment variables from .env (located in the project root)
load_dotenv()


# Official-style color palette for all 18 Pokémon types
TYPE_COLORS: dict[str, str] = {
    "normal": "#A8A77A",
    "fire": "#EE8130",
    "water": "#6390F0",
    "electric": "#F7D02C",
    "grass": "#7AC74C",
    "ice": "#96D9D6",
    "fighting": "#C22E28",
    "poison": "#A33EA1",
    "ground": "#E2BF65",
    "flying": "#A98FF3",
    "psychic": "#F95587",
    "bug": "#A6B91A",
    "rock": "#B6A136",
    "ghost": "#735797",
    "dragon": "#6F35FC",
    "dark": "#705746",
    "steel": "#B7B7CE",
    "fairy": "#D685AD",
}

# Cartridge badges, era groupings and colors for all Pokémon games
VERSION_METADATA: dict[str, dict[str, str]] = {
    "red": {"name": "Red", "color": "#DC2626", "era": "Gen I (Kanto)"},
    "blue": {"name": "Blue", "color": "#2563EB", "era": "Gen I (Kanto)"},
    "yellow": {"name": "Yellow", "color": "#EAB308", "era": "Gen I (Kanto)"},
    "gold": {"name": "Gold", "color": "#D97706", "era": "Gen II (Johto)"},
    "silver": {"name": "Silver", "color": "#64748B", "era": "Gen II (Johto)"},
    "crystal": {"name": "Crystal", "color": "#06B6D4", "era": "Gen II (Johto)"},
    "ruby": {"name": "Ruby", "color": "#DC2626", "era": "Gen III (Hoenn)"},
    "sapphire": {"name": "Sapphire", "color": "#2563EB", "era": "Gen III (Hoenn)"},
    "emerald": {"name": "Emerald", "color": "#059669", "era": "Gen III (Hoenn)"},
    "firered": {"name": "FireRed", "color": "#EA580C", "era": "Gen III (Kanto)"},
    "leafgreen": {"name": "LeafGreen", "color": "#16A34A", "era": "Gen III (Kanto)"},
    "colosseum": {"name": "Colosseum", "color": "#7C3AED", "era": "Gen III (Orre)"},
    "xd": {"name": "XD: Gale of Darkness", "color": "#4F46E5", "era": "Gen III (Orre)"},
    "diamond": {"name": "Diamond", "color": "#0284C7", "era": "Gen IV (Sinnoh)"},
    "pearl": {"name": "Pearl", "color": "#EC4899", "era": "Gen IV (Sinnoh)"},
    "platinum": {"name": "Platinum", "color": "#64748B", "era": "Gen IV (Sinnoh)"},
    "heartgold": {"name": "HeartGold", "color": "#D97706", "era": "Gen IV (Johto)"},
    "soulsilver": {"name": "SoulSilver", "color": "#94A3B8", "era": "Gen IV (Johto)"},
    "black": {"name": "Black", "color": "#1E293B", "era": "Gen V (Unova)"},
    "white": {"name": "White", "color": "#64748B", "era": "Gen V (Unova)"},
    "black-2": {"name": "Black 2", "color": "#0F172A", "era": "Gen V (Unova)"},
    "white-2": {"name": "White 2", "color": "#475569", "era": "Gen V (Unova)"},
    "x": {"name": "X", "color": "#2563EB", "era": "Gen VI (Kalos)"},
    "y": {"name": "Y", "color": "#DC2626", "era": "Gen VI (Kalos)"},
    "omega-ruby": {"name": "Omega Ruby", "color": "#B91C1C", "era": "Gen VI (Hoenn)"},
    "alpha-sapphire": {"name": "Alpha Sapphire", "color": "#1D4ED8", "era": "Gen VI (Hoenn)"},
    "sun": {"name": "Sun", "color": "#EA580C", "era": "Gen VII (Alola)"},
    "moon": {"name": "Moon", "color": "#6366F1", "era": "Gen VII (Alola)"},
    "ultra-sun": {"name": "Ultra Sun", "color": "#C2410C", "era": "Gen VII (Alola)"},
    "ultra-moon": {"name": "Ultra Moon", "color": "#4338CA", "era": "Gen VII (Alola)"},
    "lets-go-pikachu": {"name": "Let's Go, Pikachu!", "color": "#EAB308", "era": "Gen VII (Kanto)"},
    "lets-go-eevee": {"name": "Let's Go, Eevee!", "color": "#B45309", "era": "Gen VII (Kanto)"},
    "sword": {"name": "Sword", "color": "#0284C7", "era": "Gen VIII (Galar)"},
    "shield": {"name": "Shield", "color": "#E11D48", "era": "Gen VIII (Galar)"},
    "brilliant-diamond": {"name": "Brilliant Diamond", "color": "#0284C7", "era": "Gen VIII (Sinnoh)"},
    "shining-pearl": {"name": "Shining Pearl", "color": "#EC4899", "era": "Gen VIII (Sinnoh)"},
    "legends-arceus": {"name": "Legends: Arceus", "color": "#D97706", "era": "Gen VIII (Hisui)"},
    "scarlet": {"name": "Scarlet", "color": "#DC2626", "era": "Gen IX (Paldea)"},
    "violet": {"name": "Violet", "color": "#7C3AED", "era": "Gen IX (Paldea)"},
}


class Config:
    """Centralized configuration read from environment variables."""

    SECRET_KEY: str = os.getenv("SECRET_KEY", "dev-pokedex-secret-key")
    DEBUG: bool = os.getenv("FLASK_DEBUG", "0") == "1"

    DB_HOST: str = os.getenv("DB_HOST", "127.0.0.1")
    DB_PORT: int = int(os.getenv("DB_PORT", "3306"))
    DB_USER: str = os.getenv("DB_USER", "root")
    DB_PASSWORD: str = os.getenv("DB_PASSWORD", "")
    DB_NAME: str = os.getenv("DB_NAME", "pokedex_db")
    DB_POOL_SIZE: int = int(os.getenv("DB_POOL_SIZE", "10"))
    DB_SSL: bool = os.getenv("DB_SSL", "0").lower() in ("1", "true", "yes")

    DEFAULT_PAGE_LIMIT: int = 20
    MAX_PAGE_LIMIT: int = 100
    MAX_POKEMON_ID: int = 1025


_db_pool: pooling.MySQLConnectionPool | None = None


def get_db_pool() -> pooling.MySQLConnectionPool:
    """Lazily initialize and return the MySQL connection pool."""
    global _db_pool
    if _db_pool is None:
        pool_kwargs = {
            "pool_name": "pokedex_pool",
            "pool_size": Config.DB_POOL_SIZE,
            "pool_reset_session": True,
            "host": Config.DB_HOST,
            "port": Config.DB_PORT,
            "user": Config.DB_USER,
            "password": Config.DB_PASSWORD,
            "database": Config.DB_NAME,
            "charset": "utf8mb4",
            "collation": "utf8mb4_unicode_ci",
            "autocommit": False,
        }
        if Config.DB_SSL:
            pool_kwargs["ssl_disabled"] = False
        _db_pool = pooling.MySQLConnectionPool(**pool_kwargs)
    return _db_pool


@contextmanager
def get_db_connection() -> Iterator[MySQLConnection]:
    """
    Context manager that borrows a connection from the pool and ensures it is
    always returned to the pool when the block exits.
    """
    conn = get_db_pool().get_connection()
    try:
        yield conn
    finally:
        conn.close()
