"""
Unit tests for Open Food Facts parsing and recipe nutrition aggregation.
"""

from app.openfoodfacts_service import parse_product
from app.nutrition import (
    aggregate_recipe_nutrition,
    parse_amount_grams,
    ingredient_contribution,
)


class TestParseProduct:
    def test_prefers_english_product_name(self):
        product = parse_product(
            {
                "product_name": "Biologische Parmigiano",
                "product_name_en": "Organic Parmigiano Reggiano",
                "brands": "JUMBO",
                "_keywords": ["cheese", "parmesan"],
                "ingredients_tags": ["en:milk", "en:salt", "en:animal-based-rennet"],
                "ingredients_hierarchy": ["en:milk", "en:dairy", "en:salt"],
                "allergens_tags": ["en:milk"],
                "nutriments": {
                    "energy-kcal_100g": 402,
                    "energy-kcal_serving": 60.3,
                    "proteins_100g": 32.4,
                    "fat_100g": 29.7,
                    "carbohydrates_100g": 0,
                    "salt_100g": 1.5,
                },
            }
        )

        assert product["product_name"] == "Organic Parmigiano Reggiano"
        assert product["brands"] == "JUMBO"
        assert product["keywords"] == ["cheese", "parmesan"]
        assert product["ingredients_en"] == ["milk", "salt", "animal based rennet"]
        assert "dairy" in product["ingredients_hierarchy_en"]
        assert product["allergens"] == ["milk"]
        assert product["energy_kcal_100g"] == 402
        assert product["energy_kcal_serving"] == 60.3
        assert product["nutriments"]["proteins_100g"] == 32.4

    def test_falls_back_to_local_name(self):
        product = parse_product({"product_name": "Aardappelen", "nutriments": {}})
        assert product["product_name"] == "Aardappelen"
        assert product["ingredients_en"] == []
        assert product["allergens"] == []


class TestNutritionHelpers:
    def test_parse_amount_grams(self):
        assert parse_amount_grams("200", "g") == 200.0
        assert parse_amount_grams("1", "kg") == 1000.0
        assert parse_amount_grams("1/2", "g") == 0.5
        assert parse_amount_grams("2", "cups") is None
        assert parse_amount_grams("2", None) is None

    def test_ingredient_contribution_scales_100g(self):
        contrib = ingredient_contribution(
            amount="50",
            unit="g",
            energy_kcal_100g=400,
            energy_kcal_serving=60,
            nutriments={"proteins_100g": 20, "fat_100g": 10},
        )
        assert contrib["energy_kcal"] == 200.0
        assert contrib["proteins"] == 10.0
        assert contrib["fat"] == 5.0

    def test_aggregate_sums_and_allergens(self):
        result = aggregate_recipe_nutrition(
            [
                {
                    "name": "Cheese",
                    "amount": "50",
                    "unit": "g",
                    "product": {
                        "energy_kcal_100g": 400,
                        "energy_kcal_serving": 60,
                        "nutriments": {"proteins_100g": 20, "fat_100g": 30},
                        "allergens": ["milk"],
                    },
                },
                {
                    "name": "Sesame",
                    "amount": "10",
                    "unit": "g",
                    "product": {
                        "energy_kcal_100g": 580,
                        "energy_kcal_serving": None,
                        "nutriments": {"proteins_100g": 21, "fat_100g": 54},
                        "allergens": ["sesame seeds"],
                    },
                },
                {
                    "name": "Salt",
                    "amount": "1",
                    "unit": "tsp",
                    "product": None,
                },
            ]
        )

        assert result["totals"]["energy_kcal"] == 258.0  # 200 + 58
        assert result["allergens"] == ["milk", "sesame seeds"]
        assert "Cheese" in result["ingredients_included"]
        assert "Salt" in result["ingredients_skipped"]
        # Weighted per 100g: (400*50 + 580*10) / 60 = 430
        assert result["per_100g"]["energy_kcal"] == 430.0

    def test_per_100g_without_gram_amounts(self):
        result = aggregate_recipe_nutrition(
            [
                {
                    "name": "Oil",
                    "amount": "2",
                    "unit": "tbsp",
                    "product": {
                        "energy_kcal_100g": 900,
                        "nutriments": {"fat_100g": 100},
                        "allergens": [],
                    },
                }
            ]
        )
        assert result["totals"] == {}
        assert result["per_100g"]["energy_kcal"] == 900.0
        assert result["per_100g"]["fat"] == 100.0
        assert "Oil" in result["ingredients_included"]
