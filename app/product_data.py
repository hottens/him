"""Helpers for serializing product JSON fields on barcodes and resolving active barcodes."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from .models import Barcode, Item, Setting


DEFAULT_SETTINGS = {
    "auto_fetch_products": "true",
    "translate_ingredients": "true",
}


def dumps_json(value: Any) -> Optional[str]:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


def loads_json(value: Optional[str], default: Any = None) -> Any:
    if value is None or value == "":
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def barcode_product_dict(barcode: Barcode) -> dict:
    """Public product payload for API responses."""
    return {
        "id": barcode.id,
        "code": barcode.code,
        "item_id": barcode.item_id,
        "product_name": barcode.product_name,
        "brands": barcode.brands,
        "keywords": loads_json(barcode.keywords, []),
        "ingredients_en": loads_json(barcode.ingredients_en, []),
        "ingredients_hierarchy_en": loads_json(barcode.ingredients_hierarchy_en, []),
        "ingredients_nl": loads_json(barcode.ingredients_nl, []),
        "ingredients_hierarchy_nl": loads_json(barcode.ingredients_hierarchy_nl, []),
        "allergens": loads_json(barcode.allergens, []),
        "nutriments": loads_json(barcode.nutriments, {}),
        "energy_kcal_100g": barcode.energy_kcal_100g,
        "energy_kcal_serving": barcode.energy_kcal_serving,
        "last_scanned_at": barcode.last_scanned_at,
        "product_fetched_at": barcode.product_fetched_at,
    }


def apply_product_data(barcode: Barcode, product: dict) -> None:
    """Write Open Food Facts fields onto a barcode row."""
    barcode.product_name = product.get("product_name")
    barcode.brands = product.get("brands")
    barcode.keywords = dumps_json(product.get("keywords") or [])
    barcode.ingredients_en = dumps_json(product.get("ingredients_en") or [])
    barcode.ingredients_hierarchy_en = dumps_json(product.get("ingredients_hierarchy_en") or [])
    if "ingredients_nl" in product:
        barcode.ingredients_nl = dumps_json(product.get("ingredients_nl") or [])
    if "ingredients_hierarchy_nl" in product:
        barcode.ingredients_hierarchy_nl = dumps_json(product.get("ingredients_hierarchy_nl") or [])
    barcode.allergens = dumps_json(product.get("allergens") or [])
    barcode.nutriments = dumps_json(product.get("nutriments") or {})
    barcode.energy_kcal_100g = product.get("energy_kcal_100g")
    barcode.energy_kcal_serving = product.get("energy_kcal_serving")
    barcode.product_fetched_at = datetime.utcnow()


def mark_barcode_scanned(db: Session, barcode: Barcode) -> None:
    """Mark barcode as last scanned and set it as the item's active barcode."""
    barcode.last_scanned_at = datetime.utcnow()
    item = barcode.item or db.query(Item).filter(Item.id == barcode.item_id).first()
    if item:
        item.active_barcode_id = barcode.id


def get_active_barcode(item: Item) -> Optional[Barcode]:
    """Return the active barcode for an item, falling back to most recently scanned."""
    if not item.barcodes:
        return None
    if item.active_barcode_id:
        for barcode in item.barcodes:
            if barcode.id == item.active_barcode_id:
                return barcode
    # Fallback: most recently scanned, else first
    with_scan = [b for b in item.barcodes if b.last_scanned_at]
    if with_scan:
        return max(with_scan, key=lambda b: b.last_scanned_at)
    return item.barcodes[0]


def get_setting(db: Session, key: str) -> str:
    row = db.query(Setting).filter(Setting.key == key).first()
    if row:
        return row.value
    return DEFAULT_SETTINGS.get(key, "")


def get_all_settings(db: Session) -> dict[str, str]:
    settings = dict(DEFAULT_SETTINGS)
    for row in db.query(Setting).all():
        settings[row.key] = row.value
    return settings


def set_setting(db: Session, key: str, value: str) -> None:
    row = db.query(Setting).filter(Setting.key == key).first()
    if row:
        row.value = value
    else:
        db.add(Setting(key=key, value=value))


def setting_is_true(db: Session, key: str) -> bool:
    return get_setting(db, key).lower() in {"1", "true", "yes", "on"}
