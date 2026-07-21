"""Regression tests for recipes import-url endpoint."""

from unittest.mock import patch


class FakePageResponse:
    text = "<html><body><h1>Pasta</h1><p>200g pasta</p></body></html>"

    def raise_for_status(self):
        return None


class TestRecipeImportUrl:
    def test_import_url_requires_gemini(self, client):
        response = client.post(
            "/api/recipes/import-url",
            json={"url": "https://example.com/recipe"},
        )
        assert response.status_code == 503

    def test_import_url_parses_via_gemini(self, client):
        with patch("app.main.gemini_service.is_configured", return_value=True), patch(
            "app.main.gemini_service.parse_recipe_from_url_content",
            return_value={
                "name": "Pasta",
                "description": "Simpel",
                "servings": 2,
                "prep_time_minutes": 5,
                "cook_time_minutes": 10,
                "ingredients": [{"name": "Pasta", "amount": "200", "unit": "gram"}],
                "steps": [{"step_number": 1, "instruction": "Kook de pasta"}],
                "source_url": "https://example.com/recipe",
            },
        ), patch("requests.get", return_value=FakePageResponse()):
            response = client.post(
                "/api/recipes/import-url",
                json={"url": "https://example.com/recipe"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Pasta"
        assert len(data["ingredients"]) == 1
        assert data["source_url"] == "https://example.com/recipe"


class TestRecipesStillListed:
    def test_list_recipes_returns_saved(self, client, sample_recipe):
        response = client.get("/api/recipes")
        assert response.status_code == 200
        names = [r["name"] for r in response.json()["recipes"]]
        assert sample_recipe["name"] in names
