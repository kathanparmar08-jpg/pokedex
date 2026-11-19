# Pokédex Web Application (National Dex #001–#1025, Gen I–IX)

A full-stack Pokédex built with **Python Flask**, **MySQL**, **Bootstrap 5**, **Tailwind CSS**, **AOS**, and **PokéAPI**. Features smooth 3D lift-and-flip Pokémon cards, live search, multi-faceted filtering (Type, Generation, Rarity, Egg Group, Color, Habitat, Min Base Stat Total), sorting, strict 20-per-page numbered pagination, dark mode, animated base stat bars, type effectiveness calculations, visual evolution chains, and level-up moves tables.

## Project Structure

```
pokedex/
├── app.py                # Flask web routes & JSON API endpoints
├── config.py             # Environment config, type colors & MySQL connection pooling
├── seed.py               # Concurrent, resumable PokéAPI data importer (IDs 1–1025)
├── schema.sql            # Normalized MySQL 8+ schema with FKs & indexes
├── requirements.txt      # Python dependencies
├── .env.example          # Environment variable template
├── templates/
│   ├── base.html         # Layout, Bootstrap 5 navbar, modal, Tailwind CDN config
│   ├── index.html        # Home page with 3D-flip card grid, filters & pagination
│   ├── detail.html       # Full Pokémon profile, stats, matchups, evolutions & moves
│   └── 404.html          # Custom 404 / error page
└── static/
    ├── css/style.css     # 3D flip card CSS, filters, pagination & detail page styles
    └── js/main.js        # Live search, filters, 20/page pagination, touch flip & dark mode
```

## Setup Instructions

### 1. Create the MySQL Database & Tables
```powershell
Get-Content schema.sql | mysql -u root -p
```

### 2. Configure `.env`
```powershell
Copy-Item .env.example .env
```
Update `DB_HOST`, `DB_USER`, `DB_PASSWORD`, and `DB_NAME` inside `.env`.

### 3. Install Dependencies
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 4. Seed All Pokémon from PokéAPI
```powershell
python seed.py
```

### 5. Run the Flask App
```powershell
python app.py
```
Open **http://127.0.0.1:5000** in your browser.

## API Endpoints

| Endpoint | Description |
| --- | --- |
| `GET /` | Home page with 3D-flip Pokémon cards, filters & 20/page pagination |
| `GET /pokemon/<id>` | Full Pokémon detail page |
| `GET /api/pokemon` | Filtered, sorted, paginated JSON (`search`, `type`, `generation`, `rarity`, `egg_group`, `color`, `habitat`, `min_stat`, `sort`, `page`, `limit`) |
| `GET /api/pokemon/<id>` | Complete JSON details for a single Pokémon |
