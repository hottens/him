"""
Open Food Facts client for barcode product lookup.

Uses the public v2 API. No API key required; a descriptive User-Agent is mandatory.
"""

from __future__ import annotations

import os
from typing import Any, Optional

import requests

BASE_URL = "https://world.openfoodfacts.org/api/v2"
USER_AGENT = os.environ.get(
    "OFF_USER_AGENT",
    "HomeInventoryManager/1.0 (local; contact@localhost)",
)

PRODUCT_FIELDS = ",".join(
    [
        "code",
        "product_name",
        "product_name_en",
        "brands",
        "_keywords",
        "ingredients",
        "ingredients_tags",
        "ingredients_hierarchy",
        "ingredients_text",
        "ingredients_text_en",
        "allergens_tags",
        "nutriments",
        "nutrition_data_per",
        "serving_size",
        "serving_quantity",
    ]
)

NUTRIENT_KEYS = (
    "proteins_100g",
    "carbohydrates_100g",
    "fat_100g",
    "saturated-fat_100g",
    "sugars_100g",
    "fiber_100g",
    "salt_100g",
)


def _strip_lang_prefix(tag: str) -> str:
    if ":" in tag:
        return tag.split(":", 1)[1].replace("-", " ")
    return tag.replace("-", " ")


def _english_ingredient_labels(product: dict) -> list[str]:
    """Prefer English taxonomy tags; fall back to ingredient text entries."""
    tags = product.get("ingredients_tags") or []
    english = [_strip_lang_prefix(t) for t in tags if str(t).startswith("en:")]
    if english:
        return english

    structured = product.get("ingredients") or []
    labels = []
    for entry in structured:
        if not isinstance(entry, dict):
            continue
        text = entry.get("text") or entry.get("id")
        if text:
            labels.append(_strip_lang_prefix(str(text)))
    if labels:
        return labels

    text = product.get("ingredients_text_en") or product.get("ingredients_text")
    if text:
        return [part.strip() for part in text.split(",") if part.strip()]
    return []


def _english_hierarchy(product: dict) -> list[str]:
    hierarchy = product.get("ingredients_hierarchy") or []
    return [_strip_lang_prefix(str(t)) for t in hierarchy]


def _pick_nutriments(raw: dict) -> dict[str, Optional[float]]:
    return {key: raw.get(key) for key in NUTRIENT_KEYS if raw.get(key) is not None}


def parse_product(product: dict) -> dict[str, Any]:
    """Normalize an OFF product payload into our barcode product fields."""
    nutriments = product.get("nutriments") or {}
    name = product.get("product_name_en") or product.get("product_name")
    allergens = [
        _strip_lang_prefix(str(tag))
        for tag in (product.get("allergens_tags") or [])
    ]
    keywords = product.get("_keywords") or []
    if not isinstance(keywords, list):
        keywords = []

    return {
        "product_name": name,
        "brands": product.get("brands") or None,
        "keywords": keywords,
        "ingredients_en": _english_ingredient_labels(product),
        "ingredients_hierarchy_en": _english_hierarchy(product),
        "allergens": allergens,
        "nutriments": _pick_nutriments(nutriments),
        "energy_kcal_100g": nutriments.get("energy-kcal_100g"),
        "energy_kcal_serving": nutriments.get("energy-kcal_serving"),
    }


def fetch_product(barcode: str, timeout: float = 10.0) -> Optional[dict[str, Any]]:
    """
    Fetch and parse a product by barcode.

    Returns None when the product is not found.
    Raises requests.RequestException on network/HTTP errors (except 404).
    """
    url = f"{BASE_URL}/product/{barcode}"
    response = requests.get(
        url,
        params={"fields": PRODUCT_FIELDS},
        headers={"User-Agent": USER_AGENT},
        timeout=timeout,
    )
    if response.status_code == 404:
        return None
    response.raise_for_status()
    data = response.json()
    if data.get("status") != 1 or not data.get("product"):
        return None
    return parse_product(data["product"])
