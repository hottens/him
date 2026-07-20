"""
Open Food Facts API service.

Looks up product information by barcode to enrich inventory items.
Open Food Facts is a free, open database and requires no API key, but does
ask clients to identify themselves via a descriptive User-Agent.

See: https://openfoodfacts.github.io/openfoodfacts-server/api/
"""

import requests

BASE_URL = "https://world.openfoodfacts.org/api/v2/product"
USER_AGENT = "HomeInventoryManager/2.0 (local-first inventory app)"

# Only request the fields we actually store, to keep responses small.
_FIELDS = ",".join([
    "product_name",
    "categories",
    "categories_tags",
    "nutriments",
    "nutriscore_grade",
    "ingredients_text",
    "allergens",
])


def _primary_category(product: dict) -> str | None:
    """
    Pick the most specific human-readable category.

    Open Food Facts orders categories from generic to specific, so the last
    entry is the most descriptive. ``categories`` is a comma-separated string;
    ``categories_tags`` is a list of language-prefixed slugs as a fallback.
    """
    categories = product.get("categories")
    if categories:
        parts = [c.strip() for c in categories.split(",") if c.strip()]
        if parts:
            return parts[-1]

    tags = product.get("categories_tags")
    if tags:
        # e.g. "en:sweet-snacks" -> "sweet snacks"
        slug = tags[-1].split(":", 1)[-1]
        return slug.replace("-", " ").strip() or None

    return None


def lookup_product(barcode: str) -> dict | None:
    """
    Look up a product by barcode.

    Returns a dict with ``name`` (derived from the category), ``category``,
    ``nutri_score``, ``nutriments``, ``ingredients_text`` and ``allergens``,
    or ``None`` if the product is unknown or the request fails.
    """
    try:
        response = requests.get(
            f"{BASE_URL}/{barcode}.json",
            params={"fields": _FIELDS},
            headers={"User-Agent": USER_AGENT},
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError):
        return None

    # status == 1 means the product was found.
    if data.get("status") != 1:
        return None

    product = data.get("product") or {}
    category = _primary_category(product)
    # Use the category as the name, falling back to the product name.
    name = category or (product.get("product_name") or "").strip() or None

    return {
        "name": name,
        "category": category,
        "nutri_score": (product.get("nutriscore_grade") or "").strip().upper() or None,
        "nutriments": product.get("nutriments") or None,
        "ingredients_text": (product.get("ingredients_text") or "").strip() or None,
        "allergens": (product.get("allergens") or "").strip() or None,
    }
