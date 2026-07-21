"""
API tests for Open Food Facts enrichment, active barcode, settings, and recipe nutrition.
"""

from datetime import datetime
from unittest.mock import patch

from app.models import Barcode, Item, ItemLocation
from app.product_data import apply_product_data, dumps_json


SAMPLE_OFF_PRODUCT = {
    "product_name": "Organic Parmigiano Reggiano",
    "brands": "JUMBO",
    "keywords": ["cheese"],
    "ingredients_en": ["milk", "salt"],
    "ingredients_hierarchy_en": ["milk", "dairy", "salt"],
    "allergens": ["milk"],
    "nutriments": {"proteins_100g": 32.4, "fat_100g": 29.7, "carbohydrates_100g": 0},
    "energy_kcal_100g": 402.0,
    "energy_kcal_serving": 60.3,
}


class TestHealthCheckOff:
    def test_health_check_no_spoonacular(self, client):
        response = client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert "spoonacular_configured" not in data
        assert "gemini_configured" in data


class TestSettings:
    def test_get_default_settings(self, client):
        response = client.get("/api/settings")
        assert response.status_code == 200
        data = response.json()
        # conftest disables auto-fetch/translate to keep tests offline
        assert "auto_fetch_products" in data
        assert "translate_ingredients" in data
        assert data["gemini_configured"] is False

    def test_update_settings(self, client):
        response = client.patch(
            "/api/settings",
            json={"auto_fetch_products": True, "translate_ingredients": True},
        )
        assert response.status_code == 200
        assert response.json()["auto_fetch_products"] is True
        assert response.json()["translate_ingredients"] is True

        again = client.get("/api/settings").json()
        assert again["auto_fetch_products"] is True


class TestActiveBarcode:
    def test_scan_sets_active_barcode(self, client, db_session):
        item = client.post(
            "/api/items",
            json={"name": "Milk", "location": "inventory", "barcode": "111"},
        ).json()
        client.post(
            "/api/barcode/associate",
            json={"barcode": "222", "item_id": item["id"]},
        )

        # Disable auto-fetch to avoid network in tests
        client.patch("/api/settings", json={"auto_fetch_products": False})

        with patch("app.main.enrichment.enrich_barcode"):
            lookup = client.get("/api/barcode/111")
        assert lookup.status_code == 200
        data = lookup.json()
        assert data["found"] is True
        assert data["item"]["active_barcode_id"] is not None
        active = next(b for b in data["item"]["barcodes"] if b["is_active"])
        assert active["code"] == "111"

        with patch("app.main.enrichment.enrich_barcode"):
            lookup2 = client.get("/api/barcode/222")
        active2 = next(b for b in lookup2.json()["item"]["barcodes"] if b["is_active"])
        assert active2["code"] == "222"

    def test_set_active_barcode_manually(self, client):
        client.patch("/api/settings", json={"auto_fetch_products": False})
        item = client.post(
            "/api/items",
            json={"name": "Cheese", "location": "inventory", "barcode": "AAA"},
        ).json()
        client.post(
            "/api/barcode/associate",
            json={"barcode": "BBB", "item_id": item["id"]},
        )
        item = client.get(f"/api/items/{item['id']}").json()
        other = next(b for b in item["barcodes"] if not b["is_active"])

        response = client.post(
            f"/api/items/{item['id']}/active-barcode",
            json={"barcode_id": other["id"]},
        )
        assert response.status_code == 200
        assert response.json()["active_barcode_id"] == other["id"]
        assert next(b for b in response.json()["barcodes"] if b["id"] == other["id"])["is_active"]


class TestBarcodeEnrichment:
    def test_unknown_barcode_suggests_openfoodfacts_name(self, client):
        with patch(
            "app.main.openfoodfacts_service.fetch_product",
            return_value=SAMPLE_OFF_PRODUCT,
        ) as mock_fetch:
            response = client.get("/api/barcode/8718452839025")

        assert response.status_code == 200
        data = response.json()
        assert data["found"] is False
        assert data["suggested_name"] == "Organic Parmigiano Reggiano"
        assert data["suggested_brands"] == "JUMBO"
        mock_fetch.assert_called_once_with("8718452839025")

    def test_unknown_barcode_without_product_has_no_suggestion(self, client):
        with patch(
            "app.main.openfoodfacts_service.fetch_product",
            return_value=None,
        ):
            response = client.get("/api/barcode/0000000000000")

        assert response.status_code == 200
        data = response.json()
        assert data["found"] is False
        assert data["suggested_name"] is None

    def test_reload_all_uses_openfoodfacts(self, client, db_session):
        client.patch("/api/settings", json={"auto_fetch_products": False, "translate_ingredients": False})
        item = client.post(
            "/api/items",
            json={"name": "Parm", "location": "inventory", "barcode": "8718452839025"},
        ).json()

        with patch(
            "app.enrichment.openfoodfacts_service.fetch_product",
            return_value=SAMPLE_OFF_PRODUCT,
        ) as mock_fetch, patch(
            "app.enrichment.gemini_service.translate_ingredients_to_dutch",
            return_value={
                "ingredients_nl": ["melk", "zout"],
                "ingredients_hierarchy_nl": ["melk", "zuivel", "zout"],
            },
        ):
            # Force translate off so gemini not required; still mock fetch
            response = client.post("/api/barcodes/reload-all")

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["updated"] == 1
        mock_fetch.assert_called()

        refreshed = client.get(f"/api/items/{item['id']}").json()
        bc = refreshed["barcodes"][0]
        assert bc["product_name"] == "Organic Parmigiano Reggiano"
        assert bc["brands"] == "JUMBO"
        assert bc["allergens"] == ["milk"]
        assert bc["energy_kcal_100g"] == 402.0
        assert "milk" in bc["ingredients_en"]


class TestRecipeNutritionApi:
    def test_recipe_includes_nutrition_from_active_barcode(self, client, db_session):
        client.patch("/api/settings", json={"auto_fetch_products": False})
        item_resp = client.post(
            "/api/items",
            json={"name": "Parmesan", "location": "inventory", "barcode": "999"},
        ).json()
        item = db_session.query(Item).filter(Item.id == item_resp["id"]).one()
        barcode = db_session.query(Barcode).filter(Barcode.item_id == item.id).one()
        apply_product_data(barcode, SAMPLE_OFF_PRODUCT)
        item.active_barcode_id = barcode.id
        db_session.commit()

        recipe = client.post(
            "/api/recipes",
            json={
                "name": "Cheese snack",
                "servings": 2,
                "ingredients": [
                    {
                        "name": "Parmesan",
                        "amount": "50",
                        "unit": "g",
                        "item_id": item.id,
                    }
                ],
                "steps": [{"step_number": 1, "instruction": "Eat"}],
            },
        ).json()

        assert recipe["nutrition"] is not None
        assert recipe["nutrition"]["totals"]["energy_kcal"] == 201.0  # 402 * 50/100
        assert recipe["nutrition"]["per_100g"]["energy_kcal"] == 402.0
        assert recipe["nutrition"]["allergens"] == ["milk"]
        assert "Parmesan" in recipe["nutrition"]["ingredients_included"]

        page = client.get(f"/recipe/{recipe['id']}")
        assert page.status_code == 200
        assert "Per 100 g" in page.text
        assert "Voedingswaarden" in page.text
        assert "lang-nl" in page.text and "lang-en" in page.text


class TestBarcodeManualUpdate:
    def test_patch_barcode_updates_nutrition_fields(self, client, db_session):
        client.patch("/api/settings", json={"auto_fetch_products": False})
        item = client.post(
            "/api/items",
            json={"name": "Yoghurt", "location": "inventory", "barcode": "111"},
        ).json()
        barcode_id = item["barcodes"][0]["id"]

        response = client.patch(
            f"/api/barcodes/{barcode_id}",
            json={
                "product_name": "Griekse yoghurt",
                "brands": "AH",
                "energy_kcal_100g": 97.0,
                "energy_kcal_serving": 145.5,
                "allergens": ["milk"],
                "nutriments": {
                    "proteins_100g": 9.0,
                    "carbohydrates_100g": 3.5,
                    "fat_100g": 5.0,
                    "salt_100g": 0.1,
                },
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["product_name"] == "Griekse yoghurt"
        assert data["brands"] == "AH"
        assert data["energy_kcal_100g"] == 97.0
        assert data["energy_kcal_serving"] == 145.5
        assert data["allergens"] == ["milk"]
        assert data["nutriments"]["proteins_100g"] == 9.0
        assert data["nutriments"]["fat_100g"] == 5.0


class TestRecipeTranslateApi:
    def test_translate_recipe_returns_english_ui(self, client):
        recipe = client.post(
            "/api/recipes",
            json={
                "name": "Pannenkoeken",
                "description": "Lekkere pannenkoeken",
                "servings": 4,
                "ingredients": [
                    {"name": "bloem", "amount": "200", "unit": "g"},
                    {"name": "melk", "amount": "300", "unit": "ml"},
                ],
                "steps": [{"step_number": 1, "instruction": "Mix alles"}],
            },
        ).json()

        with patch("app.main.gemini_service.is_configured", return_value=True), patch(
            "app.main.gemini_service.translate_recipe_content",
            return_value={
                "name": "Pancakes",
                "description": "Tasty pancakes",
                "ingredients": [
                    {"name": "flour", "notes": None},
                    {"name": "milk", "notes": None},
                ],
                "steps": [{"step_number": 1, "instruction": "Mix everything"}],
            },
        ):
            response = client.post(
                f"/api/recipes/{recipe['id']}/translate",
                json={"lang": "en"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["lang"] == "en"
        assert data["name"] == "Pancakes"
        assert data["ingredients"][0]["name"] == "flour"
        assert data["ui"]["ingredients"] == "Ingredients"
        assert data["ui"]["per_100g"] == "Per 100 g"

    def test_translate_requires_gemini(self, client):
        recipe = client.post(
            "/api/recipes",
            json={
                "name": "Soep",
                "servings": 2,
                "ingredients": [],
                "steps": [],
            },
        ).json()
        with patch("app.main.gemini_service.is_configured", return_value=False):
            response = client.post(
                f"/api/recipes/{recipe['id']}/translate",
                json={"lang": "en"},
            )
        assert response.status_code == 503
