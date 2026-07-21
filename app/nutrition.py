"""Aggregate recipe nutrition and allergens from linked inventory products."""

from __future__ import annotations

import json
from typing import Any, Optional


GRAM_UNITS = {"g", "gram", "grams", "gr", "gramme", "grammes"}

NUTRIENT_KEYS = (
    "proteins_100g",
    "carbohydrates_100g",
    "fat_100g",
    "saturated-fat_100g",
    "sugars_100g",
    "fiber_100g",
    "salt_100g",
)


def _as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []


def _as_dict(value: Any) -> dict:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def parse_amount_grams(amount: Optional[str], unit: Optional[str]) -> Optional[float]:
    """Convert an ingredient amount/unit to grams when possible."""
    if amount is None or str(amount).strip() == "":
        return None

    raw = str(amount).strip().replace(",", ".")
    try:
        value = float(raw)
    except ValueError:
        # Handle simple fractions like 1/2
        if "/" in raw:
            parts = raw.split("/")
            if len(parts) == 2:
                try:
                    value = float(parts[0]) / float(parts[1])
                except (ValueError, ZeroDivisionError):
                    return None
            else:
                return None
        else:
            return None

    unit_norm = (unit or "").strip().lower()
    if unit_norm in GRAM_UNITS or unit_norm == "":
        # Bare number without unit: treat as grams only when unit was explicitly g-family.
        # Empty unit → unknown scale; skip.
        if unit_norm == "":
            return None
        return value
    if unit_norm in {"kg", "kilogram", "kilograms"}:
        return value * 1000
    if unit_norm in {"mg", "milligram", "milligrams"}:
        return value / 1000
    return None


def scale_from_100g(per_100g: Optional[float], grams: float) -> Optional[float]:
    if per_100g is None:
        return None
    return round(per_100g * grams / 100.0, 2)


def ingredient_contribution(
    *,
    amount: Optional[str],
    unit: Optional[str],
    energy_kcal_100g: Optional[float],
    energy_kcal_serving: Optional[float],
    nutriments: Any,
) -> Optional[dict[str, float]]:
    """
    Nutrition contribution for one ingredient.

    Prefers scaling per-100g values by grams. If amount is exactly 1 serving
    (unit contains 'serving'), uses energy_kcal_serving and skips other macros
    unless per-100g + grams is available.
    """
    grams = parse_amount_grams(amount, unit)
    nutrients = _as_dict(nutriments)
    contrib: dict[str, float] = {}

    if grams is not None:
        kcal = scale_from_100g(energy_kcal_100g, grams)
        if kcal is not None:
            contrib["energy_kcal"] = kcal
        for key in NUTRIENT_KEYS:
            scaled = scale_from_100g(nutrients.get(key), grams)
            if scaled is not None:
                # Store without _100g suffix in totals
                out_key = key.replace("_100g", "")
                contrib[out_key] = scaled
        return contrib or None

    unit_norm = (unit or "").strip().lower()
    if unit_norm in {"serving", "servings", "portie", "porties"} and energy_kcal_serving is not None:
        try:
            qty = float(str(amount).replace(",", ".")) if amount else 1.0
        except ValueError:
            qty = 1.0
        return {"energy_kcal": round(energy_kcal_serving * qty, 2)}

    return None


def aggregate_recipe_nutrition(ingredients: list[dict]) -> dict:
    """
    Sum nutrition and collect allergens from recipe ingredients.

    Each ingredient dict may include:
      - amount, unit
      - product: dict with energy_kcal_100g, energy_kcal_serving, nutriments, allergens
      - name (for incomplete tracking)
    """
    totals: dict[str, float] = {}
    allergens: set[str] = set()
    included: list[str] = []
    skipped: list[str] = []

    for ing in ingredients:
        product = ing.get("product")
        name = ing.get("name") or "unknown"

        if not product:
            skipped.append(name)
            continue

        for tag in _as_list(product.get("allergens")):
            clean = str(tag).replace("en:", "").replace("-", " ").strip()
            if clean:
                allergens.add(clean)

        contrib = ingredient_contribution(
            amount=ing.get("amount"),
            unit=ing.get("unit"),
            energy_kcal_100g=product.get("energy_kcal_100g"),
            energy_kcal_serving=product.get("energy_kcal_serving"),
            nutriments=product.get("nutriments"),
        )
        if not contrib:
            skipped.append(name)
            continue

        included.append(name)
        for key, value in contrib.items():
            totals[key] = round(totals.get(key, 0.0) + value, 2)

    return {
        "totals": totals,
        "allergens": sorted(allergens),
        "ingredients_included": included,
        "ingredients_skipped": skipped,
    }
