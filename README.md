# Home Inventory Manager

A minimal, local-first home inventory management system with barcode scanning.

## Overview

Track what's in your home and what you need to buy. No cloud, no accounts—just scan barcodes with your phone.

**Core concept:**
- Items are either in **Inventory** (at home) or on the **Grocery List** (need to buy)
- Scan a barcode to instantly move items between lists
- New barcodes prompt you to name the item

## Quick Start

### Using Docker (Recommended)

```bash
# Build and run
docker-compose up -d

# View logs
docker-compose logs -f

# Stop
docker-compose down
```

Access at `http://<your-machine-ip>:4269`

### Without Docker

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows

# Install dependencies
pip install -r requirements.txt

# Run
uvicorn app.main:app --host 0.0.0.0 --port 4269
```

## How It Works

### Barcode Scanning

1. Open the web app on your phone
2. Select scan mode: **Inventory** or **Grocery List**
3. Tap "Start Scanner" to activate your camera
4. Point at a barcode

**If the barcode is known:** The item instantly moves to your selected list.

**If the barcode is new:** A dialog appears where you can:
- Name the new item, or
- Search and select an existing item (to add a second barcode)
- Choose which list to add it to

### Managing Items

From the Inventory or Grocery tabs:
- Tap 🛒 to move an item to the grocery list
- Tap 🏠 to move an item to inventory
- Tap ✕ to remove from both lists (item stays in database for future scans)

## API Reference

All endpoints return JSON. Base URL: `http://<host>:4269/api`

### Home Assistant Endpoints

These return clean, stable JSON for REST sensors:

| Endpoint | Description |
|----------|-------------|
| `GET /api/inventory` | Items currently at home |
| `GET /api/grocery` | Items on grocery list |

**Response format:**
```json
{
  "count": 5,
  "items": [
    {
      "id": 1,
      "name": "Milk",
      "location": "inventory",
      "barcodes": [{"id": 1, "code": "012345678901", "item_id": 1}]
    }
  ]
}
```

### Item Management

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/items` | List all items |
| `GET` | `/api/items?location=inventory` | Filter by location |
| `POST` | `/api/items` | Create new item |
| `GET` | `/api/items/{id}` | Get single item |
| `PATCH` | `/api/items/{id}` | Update item |
| `DELETE` | `/api/items/{id}` | Delete item |

### Quick Actions

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/items/{id}/to-inventory` | Move to inventory |
| `POST` | `/api/items/{id}/to-grocery` | Move to grocery list |
| `POST` | `/api/items/{id}/remove` | Remove from both lists |

### Barcode Operations

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/barcode/{code}` | Look up barcode |
| `POST` | `/api/barcode/associate` | Link barcode to item |

### Search

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/search?q=milk` | Search items by name |

## Home Assistant Integration

### REST Sensors

Add to `configuration.yaml`:

```yaml
sensor:
  # Grocery list count
  - platform: rest
    name: Grocery List Count
    resource: http://192.168.1.100:4269/api/grocery
    value_template: "{{ value_json.count }}"
    scan_interval: 60

  # Inventory count
  - platform: rest
    name: Home Inventory Count
    resource: http://192.168.1.100:4269/api/inventory
    value_template: "{{ value_json.count }}"
    scan_interval: 60

  # Grocery items as attribute
  - platform: rest
    name: Grocery List
    resource: http://192.168.1.100:4269/api/grocery
    value_template: "{{ value_json.count }} items"
    json_attributes:
      - items
    scan_interval: 60
```

### Template Sensor for Item Names

```yaml
template:
  - sensor:
      - name: "Grocery Items"
        state: "{{ state_attr('sensor.grocery_list', 'items') | length }} items"
        attributes:
          items: >
            {{ state_attr('sensor.grocery_list', 'items') 
               | map(attribute='name') | list }}
```

### Automation Example

Notify when grocery list gets long:

```yaml
automation:
  - alias: "Grocery List Reminder"
    trigger:
      - platform: numeric_state
        entity_id: sensor.grocery_list_count
        above: 5
    action:
      - service: notify.mobile_app
        data:
          title: "Shopping Time"
          message: "You have {{ states('sensor.grocery_list_count') }} items on your grocery list"
```

### Lovelace Card

```yaml
type: entities
title: Grocery List
entities:
  - entity: sensor.grocery_list_count
    name: Items to buy
```

Or for a more detailed list using auto-entities card:

```yaml
type: markdown
title: Grocery List
content: |
  {% set items = state_attr('sensor.grocery_list', 'items') %}
  {% if items %}
    {% for item in items %}
  - {{ item.name }}
    {% endfor %}
  {% else %}
  _List is empty_
  {% endif %}
```

## Data Storage

- SQLite database stored at `/data/inventory.db` (in Docker)
- Database persists via Docker volume `home_inventory_data`
- To backup: `docker cp home-inventory:/data/inventory.db ./backup.db`
- To restore: `docker cp ./backup.db home-inventory:/data/inventory.db`

## Development

Enable hot reload:

```bash
# Without Docker
uvicorn app.main:app --host 0.0.0.0 --port 4269 --reload

# With Docker - uncomment dev volumes in docker-compose.yml
docker-compose up
```

API documentation available at:
- Swagger UI: `http://localhost:4269/docs`
- ReDoc: `http://localhost:4269/redoc`

## Camera Access

The barcode scanner requires:
- **HTTPS** or **localhost** (browsers block camera on plain HTTP)
- For local network access, either:
  - Access via `localhost` on the same machine
  - Set up a reverse proxy with HTTPS (e.g., Caddy, nginx)
  - On some browsers, add the IP to allowed insecure origins

### Chrome Insecure Origin Flag (Development Only)

```
chrome://flags/#unsafely-treat-insecure-origin-as-secure
```

Add your server URL (e.g., `http://192.168.1.100:4269`) and restart Chrome.

## Troubleshooting

**Camera not working?**
- Check browser permissions
- Ensure HTTPS or localhost access
- Try a different browser

**Barcode not scanning?**
- Ensure good lighting
- Hold steady, fill the scan area
- Try different angles

**Database issues?**
- Check volume mounts: `docker volume inspect home_inventory_data`
- Verify permissions on `/data` directory

## License

MIT - Use freely for personal projects.

