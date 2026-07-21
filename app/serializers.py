"""Convert ORM objects to API response schemas."""

from __future__ import annotations

from typing import Optional

from . import schemas
from .models import Barcode, Item, Recipe
from .nutrition import aggregate_recipe_nutrition
from .product_data import barcode_product_dict, get_active_barcode, loads_json


def serialize_barcode(barcode: Barcode, active_barcode_id: Optional[int] = None) -> schemas.BarcodeResponse:
    data = barcode_product_dict(barcode)
    data["is_active"] = (
        active_barcode_id is not None and barcode.id == active_barcode_id
    )
    return schemas.BarcodeResponse(**data)


def serialize_item(item: Item) -> schemas.ItemResponse:
    active_id = item.active_barcode_id
    if active_id is None:
        active = get_active_barcode(item)
        active_id = active.id if active else None
    return schemas.ItemResponse(
        id=item.id,
        name=item.name,
        location=item.location,
        active_barcode_id=active_id,
        barcodes=[serialize_barcode(b, active_id) for b in (item.barcodes or [])],
    )


def product_payload_for_nutrition(barcode: Optional[Barcode]) -> Optional[dict]:
    if barcode is None or barcode.product_fetched_at is None:
        # Still allow allergens/nutrition if any product fields present
        if barcode is None:
            return None
        if not any(
            [
                barcode.energy_kcal_100g is not None,
                barcode.energy_kcal_serving is not None,
                barcode.nutriments,
                barcode.allergens,
            ]
        ):
            return None
    return {
        "energy_kcal_100g": barcode.energy_kcal_100g,
        "energy_kcal_serving": barcode.energy_kcal_serving,
        "nutriments": loads_json(barcode.nutriments, {}),
        "allergens": loads_json(barcode.allergens, []),
    }


def recipe_nutrition_summary(recipe: Recipe) -> schemas.RecipeNutritionSummary:
    ingredients = []
    for ing in recipe.ingredients:
        product = None
        if ing.matched_item is not None:
            active = get_active_barcode(ing.matched_item)
            product = product_payload_for_nutrition(active)
        ingredients.append(
            {
                "name": ing.name,
                "amount": ing.amount,
                "unit": ing.unit,
                "product": product,
            }
        )
    result = aggregate_recipe_nutrition(ingredients)
    return schemas.RecipeNutritionSummary(**result)


def serialize_recipe(recipe: Recipe, *, include_nutrition: bool = True) -> schemas.RecipeResponse:
    nutrition = recipe_nutrition_summary(recipe) if include_nutrition else None
    return schemas.RecipeResponse(
        id=recipe.id,
        name=recipe.name,
        description=recipe.description,
        servings=recipe.servings,
        prep_time_minutes=recipe.prep_time_minutes,
        cook_time_minutes=recipe.cook_time_minutes,
        source_url=recipe.source_url,
        is_favorite=recipe.is_favorite,
        created_at=recipe.created_at,
        ingredients=recipe.ingredients,
        steps=recipe.steps,
        nutrition=nutrition,
    )
