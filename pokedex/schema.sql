-- =============================================================================
-- Pokédex Database Schema (MySQL 8.0+)
-- Normalized relational schema for the first 200 Pokémon from PokéAPI
-- =============================================================================

CREATE DATABASE IF NOT EXISTS pokedex_db
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE pokedex_db;

-- -----------------------------------------------------------------------------
-- 1. Types (e.g. fire, water, grass, electric)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS types (
    id          INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    name        VARCHAR(30) NOT NULL,
    color_hex   VARCHAR(7)  NOT NULL DEFAULT '#A8A77A',
    UNIQUE KEY uq_types_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- 2. Type Damage Relations (derived from PokéAPI /type/{name})
--    multiplier: 2.00 (super effective), 0.50 (not very effective), 0.00 (immune)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS type_effectiveness (
    attacking_type_id INT UNSIGNED  NOT NULL,
    defending_type_id INT UNSIGNED  NOT NULL,
    multiplier        DECIMAL(3, 2) NOT NULL,
    PRIMARY KEY (attacking_type_id, defending_type_id),
    INDEX idx_te_defending (defending_type_id),
    CONSTRAINT fk_te_attacking
        FOREIGN KEY (attacking_type_id) REFERENCES types(id)
        ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_te_defending
        FOREIGN KEY (defending_type_id) REFERENCES types(id)
        ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- 3. Core Pokémon Table (IDs 1..200)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pokemon (
    id                 INT UNSIGNED      PRIMARY KEY,
    name               VARCHAR(100)      NOT NULL,
    height             DECIMAL(6, 2)     NOT NULL COMMENT 'Height in meters',
    weight             DECIMAL(6, 2)     NOT NULL COMMENT 'Weight in kilograms',
    base_experience    SMALLINT UNSIGNED DEFAULT NULL,
    hp                 SMALLINT UNSIGNED NOT NULL,
    attack             SMALLINT UNSIGNED NOT NULL,
    defense            SMALLINT UNSIGNED NOT NULL,
    sp_attack          SMALLINT UNSIGNED NOT NULL,
    sp_defense         SMALLINT UNSIGNED NOT NULL,
    speed              SMALLINT UNSIGNED NOT NULL,
    stat_total         SMALLINT UNSIGNED NOT NULL,
    artwork_url        VARCHAR(500)      NOT NULL,
    flavor_text        TEXT              NOT NULL,
    genus              VARCHAR(100)      DEFAULT NULL,
    habitat            VARCHAR(50)       DEFAULT NULL,
    color              VARCHAR(50)       DEFAULT NULL,
    generation         VARCHAR(50)       DEFAULT NULL,
    gender_rate        TINYINT           NOT NULL DEFAULT -1 COMMENT '-1 = genderless, 0..8 = eighths female',
    capture_rate       SMALLINT UNSIGNED DEFAULT NULL,
    base_happiness     SMALLINT UNSIGNED DEFAULT NULL,
    growth_rate        VARCHAR(50)       DEFAULT NULL,
    is_legendary       BOOLEAN           NOT NULL DEFAULT FALSE,
    is_mythical        BOOLEAN           NOT NULL DEFAULT FALSE,
    evolution_chain_id INT UNSIGNED      DEFAULT NULL,
    created_at         TIMESTAMP         NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE KEY uq_pokemon_name (name),
    INDEX idx_pokemon_evolution_chain (evolution_chain_id),
    INDEX idx_pokemon_stat_total (stat_total),
    INDEX idx_pokemon_generation (generation),
    INDEX idx_pokemon_flags (is_legendary, is_mythical)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- 4. Pokémon <-> Types (1 to 2 types per Pokémon; slot 1 = primary type)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pokemon_types (
    pokemon_id INT UNSIGNED     NOT NULL,
    type_id    INT UNSIGNED     NOT NULL,
    slot       TINYINT UNSIGNED NOT NULL COMMENT '1 = primary, 2 = secondary',
    PRIMARY KEY (pokemon_id, slot),
    UNIQUE KEY uq_pokemon_type_pair (pokemon_id, type_id),
    INDEX idx_pt_type_id (type_id),
    CONSTRAINT fk_pt_pokemon
        FOREIGN KEY (pokemon_id) REFERENCES pokemon(id)
        ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_pt_type
        FOREIGN KEY (type_id) REFERENCES types(id)
        ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- 5. Abilities & Pokémon <-> Abilities
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS abilities (
    id   INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    UNIQUE KEY uq_abilities_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS pokemon_abilities (
    pokemon_id INT UNSIGNED     NOT NULL,
    ability_id INT UNSIGNED     NOT NULL,
    is_hidden  BOOLEAN          NOT NULL DEFAULT FALSE,
    slot       TINYINT UNSIGNED NOT NULL DEFAULT 1,
    PRIMARY KEY (pokemon_id, ability_id),
    INDEX idx_pa_ability_id (ability_id),
    CONSTRAINT fk_pa_pokemon
        FOREIGN KEY (pokemon_id) REFERENCES pokemon(id)
        ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_pa_ability
        FOREIGN KEY (ability_id) REFERENCES abilities(id)
        ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- 6. Egg Groups & Pokémon <-> Egg Groups
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS egg_groups (
    id   INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(50) NOT NULL,
    UNIQUE KEY uq_egg_groups_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS pokemon_egg_groups (
    pokemon_id   INT UNSIGNED NOT NULL,
    egg_group_id INT UNSIGNED NOT NULL,
    PRIMARY KEY (pokemon_id, egg_group_id),
    INDEX idx_peg_egg_group_id (egg_group_id),
    CONSTRAINT fk_peg_pokemon
        FOREIGN KEY (pokemon_id) REFERENCES pokemon(id)
        ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_peg_egg_group
        FOREIGN KEY (egg_group_id) REFERENCES egg_groups(id)
        ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- 7. Moves & Pokémon <-> Moves (top level-up moves per Pokémon)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS moves (
    id           INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    name         VARCHAR(100)      NOT NULL,
    type_name    VARCHAR(30)       DEFAULT NULL,
    damage_class VARCHAR(30)       DEFAULT NULL COMMENT 'physical, special, or status',
    power        SMALLINT UNSIGNED DEFAULT NULL,
    accuracy     SMALLINT UNSIGNED DEFAULT NULL,
    pp           SMALLINT UNSIGNED DEFAULT NULL,
    UNIQUE KEY uq_moves_name (name),
    INDEX idx_moves_type (type_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS pokemon_moves (
    pokemon_id       INT UNSIGNED      NOT NULL,
    move_id          INT UNSIGNED      NOT NULL,
    level_learned_at SMALLINT UNSIGNED NOT NULL DEFAULT 0,
    learn_method     VARCHAR(30)       NOT NULL DEFAULT 'level-up',
    PRIMARY KEY (pokemon_id, move_id, learn_method),
    INDEX idx_pm_pokemon_level (pokemon_id, level_learned_at),
    CONSTRAINT fk_pm_pokemon
        FOREIGN KEY (pokemon_id) REFERENCES pokemon(id)
        ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_pm_move
        FOREIGN KEY (move_id) REFERENCES moves(id)
        ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- 8. Evolution Chains (directed edges supporting linear & branching chains)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS evolutions (
    id              INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    chain_id        INT UNSIGNED      NOT NULL,
    from_pokemon_id INT UNSIGNED      NOT NULL,
    to_pokemon_id   INT UNSIGNED      NOT NULL,
    stage           TINYINT UNSIGNED  NOT NULL DEFAULT 1 COMMENT '1 = base -> stage 1, 2 = stage 1 -> stage 2',
    trigger_name    VARCHAR(50)       DEFAULT NULL,
    min_level       SMALLINT UNSIGNED DEFAULT NULL,
    item_name       VARCHAR(100)      DEFAULT NULL,
    condition_text  VARCHAR(255)      NOT NULL DEFAULT 'Level up',
    UNIQUE KEY uq_evolution_edge (chain_id, from_pokemon_id, to_pokemon_id),
    INDEX idx_evolutions_chain (chain_id),
    INDEX idx_evolutions_from (from_pokemon_id),
    INDEX idx_evolutions_to (to_pokemon_id),
    CONSTRAINT fk_evo_from_pokemon
        FOREIGN KEY (from_pokemon_id) REFERENCES pokemon(id)
        ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_evo_to_pokemon
        FOREIGN KEY (to_pokemon_id) REFERENCES pokemon(id)
        ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- 9. Historical Pokédex Lore Entries across Game Versions
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pokemon_lore (
    id           INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    pokemon_id   INT UNSIGNED NOT NULL,
    version_name VARCHAR(50)  NOT NULL,
    game_era     VARCHAR(50)  DEFAULT NULL,
    flavor_text  TEXT         NOT NULL,
    UNIQUE KEY uq_poke_version (pokemon_id, version_name),
    INDEX idx_pl_pokemon (pokemon_id),
    CONSTRAINT fk_pl_pokemon
        FOREIGN KEY (pokemon_id) REFERENCES pokemon(id)
        ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
