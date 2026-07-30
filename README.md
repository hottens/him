# Home Inventory Manager

A minimal, local-first home inventory management system with barcode scanning and Open Food Facts product data.

## Overview

Track what's in your home and what you need to buy. No cloud, no accounts—just scan barcodes with your phone.

**Core concept:**
- Items are either in **Inventory** (at home), on the **Grocery List** (need to buy), or **Archived** (neither)
- Scan a barcode to instantly move items between lists
- New barcodes prompt you to name the item
- Product data (name, brands, ingredients, allergens, nutrition) is loaded from [Open Food Facts](https://world.openfoodfacts.org/)
- AI-powered recipe suggestions based on your inventory (Gemini)
- Recipe nutrition and allergens are summed from linked inventory products

## Quick Start

### Using Docker (Recommended)

```bash
docker-compose up -d
docker-compose logs -f
docker-compose down
```

Access at `http://<your-machine-ip>:4269`

### Without Docker

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 4269
```

## How It Works

### Barcode Scanning

1. Open the web app on your phone
2. Select scan mode: **Inventory** or **Grocery List**
3. Tap "Start Scanner" to activate your camera
4. Point at a barcode

**If the barcode is known:** The item moves to your selected list, that barcode becomes the item's **active** barcode, and missing product data can be fetched automatically.

**If the barcode is new:** Name the item or link it to an existing one.

### Active barcode

An item can have multiple barcodes. The last scanned barcode becomes active automatically. Tap an item to open the edit modal and pick another barcode as active (used for nutrition/allergens on recipes).

### Managing items

From the Inventory or Grocery tabs:
- Tap **Boodschappen** to move an item to the grocery list
- Tap **Voorraad** to move an item to inventory
- Tap **Archief** to archive (remove from both lists, item stays in database)
- Tap **Bewerk** to edit item name or delete it entirely
- Click on item name to open edit modal

### Settings (⚙)

- Auto-fetch product data from Open Food Facts
- Translate ingredients / hierarchy to Dutch via Gemini
- Reload all barcodes from Open Food Facts

### Recipes

- Gemini recipe ideas from inventory (Discover tab)
- Favorites with ingredient availability
- On the recipe page: summed energy/macros (when amounts are in grams) and a combined allergens list from linked products' active barcodes

## API highlights

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/barcode/{code}` | Lookup + mark scanned/active (+ optional OFF fetch) |
| `POST` | `/api/barcode/associate` | Link barcode to item |
| `POST` | `/api/items/{id}/active-barcode` | Manually set active barcode |
| `POST` | `/api/barcodes/reload-all` | Refresh all barcodes from Open Food Facts |
| `POST` | `/api/barcodes/{id}/fetch` | Refresh one barcode |
| `GET`/`PATCH` | `/api/settings` | App settings |
| `GET` | `/api/recipes/{id}` | Recipe including `nutrition` summary |

Home Assistant endpoints (`/api/inventory`, `/api/grocery`) are unchanged in shape; items now include `active_barcode_id` and richer barcode product fields.

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GEMINI_API_KEY` | No | Google Gemini API key (recipe suggestions + Dutch ingredient translation) |
| `OFF_USER_AGENT` | No | User-Agent for Open Food Facts requests |
| `DATABASE_PATH` | No | SQLite path (default `./data/inventory.db`, Docker: `/data/inventory.db`) |

**Gemini key:** [Google AI Studio](https://aistudio.google.com/app/apikey)

## Data Storage

- SQLite at `/data/inventory.db` (Docker volume `home_inventory_data`)
- Backup: `docker cp home-inventory:/data/inventory.db ./backup.db`

### Schema migrations

On startup the app:

1. Creates any **missing tables** via SQLAlchemy (`create_all` — never alters existing tables)
2. Runs **versioned migrations** in `app/migrations/versions/` (recorded in `schema_migrations`)

Migrations are additive only (`ADD COLUMN` nullable / `CREATE TABLE IF NOT EXISTS`). Existing rows stay intact; new columns default to `NULL`. Already-applied versions are skipped.

To add a schema change: create `app/migrations/versions/00N_short_name.py` with `VERSION` + `upgrade(conn)`, using helpers from `app/migrations/helpers.py`.

## Development

```bash
uvicorn app.main:app --host 0.0.0.0 --port 4269 --reload
.venv/bin/python -m pytest
```

Docs: `http://localhost:4269/docs`

## Camera Access

Barcode scanning needs **HTTPS** or **localhost**. See certs via `generate-cert.sh` for local HTTPS.

## License

MIT
