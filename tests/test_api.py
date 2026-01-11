"""
Unit tests for the REST API endpoints.

Tests all API endpoints for the home inventory management application.
"""

import pytest


class TestHealthCheck:
    """Tests for the health check endpoint."""

    def test_health_check(self, client):
        """Test that health check returns healthy status."""
        response = client.get("/api/health")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "gemini_configured" in data


class TestBarcodeLookup:
    """Tests for barcode lookup functionality."""

    def test_lookup_unknown_barcode(self, client):
        """Test looking up a barcode that doesn't exist."""
        response = client.get("/api/barcode/unknown123")
        
        assert response.status_code == 200
        data = response.json()
        assert data["found"] is False
        assert data["barcode"] == "unknown123"
        assert data["item"] is None

    def test_lookup_known_barcode(self, client, sample_item):
        """Test looking up a barcode that exists."""
        response = client.get("/api/barcode/123456789")
        
        assert response.status_code == 200
        data = response.json()
        assert data["found"] is True
        assert data["barcode"] == "123456789"
        assert data["item"]["name"] == "Milk"

    def test_lookup_special_characters_in_barcode(self, client):
        """Test looking up a barcode with special characters."""
        # Create an item with a barcode containing special chars (no slashes - they cause path issues)
        client.post(
            "/api/items",
            json={"name": "Special Item", "barcode": "ABC-123_456.789"}
        )
        
        response = client.get("/api/barcode/ABC-123_456.789")
        
        assert response.status_code == 200
        assert response.json()["found"] is True
        assert response.json()["item"]["name"] == "Special Item"


class TestBarcodeAssociation:
    """Tests for associating barcodes with items."""

    def test_associate_barcode_success(self, client, sample_item):
        """Test successfully associating a new barcode with an existing item."""
        response = client.post(
            "/api/barcode/associate",
            json={"barcode": "NEW_BARCODE", "item_id": sample_item["id"]}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Milk"
        assert len(data["barcodes"]) == 2
        barcode_codes = {b["code"] for b in data["barcodes"]}
        assert "123456789" in barcode_codes
        assert "NEW_BARCODE" in barcode_codes

    def test_associate_duplicate_barcode(self, client, sample_item):
        """Test that associating an existing barcode fails."""
        response = client.post(
            "/api/barcode/associate",
            json={"barcode": "123456789", "item_id": sample_item["id"]}
        )
        
        assert response.status_code == 400
        assert "already associated" in response.json()["detail"]

    def test_associate_barcode_nonexistent_item(self, client):
        """Test associating a barcode with a non-existent item."""
        response = client.post(
            "/api/barcode/associate",
            json={"barcode": "NEW_BARCODE", "item_id": 99999}
        )
        
        assert response.status_code == 404
        assert "Item not found" in response.json()["detail"]


class TestItemCRUD:
    """Tests for Item Create, Read, Update, Delete operations."""

    def test_create_item_minimal(self, client):
        """Test creating an item with minimal data."""
        response = client.post(
            "/api/items",
            json={"name": "Simple Item"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Simple Item"
        assert data["location"] == "neither"
        assert data["barcodes"] == []

    def test_create_item_with_location(self, client):
        """Test creating an item with a specific location."""
        response = client.post(
            "/api/items",
            json={"name": "Inventory Item", "location": "inventory"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["location"] == "inventory"

    def test_create_item_with_barcode(self, client):
        """Test creating an item with an associated barcode."""
        response = client.post(
            "/api/items",
            json={"name": "Barcoded Item", "barcode": "ITEM_BARCODE_123"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["barcodes"]) == 1
        assert data["barcodes"][0]["code"] == "ITEM_BARCODE_123"

    def test_create_item_duplicate_name(self, client, sample_item):
        """Test that creating an item with duplicate name fails."""
        response = client.post(
            "/api/items",
            json={"name": "Milk"}
        )
        
        assert response.status_code == 400
        assert "already exists" in response.json()["detail"]

    def test_create_item_duplicate_barcode(self, client, sample_item):
        """Test that creating an item with existing barcode fails."""
        response = client.post(
            "/api/items",
            json={"name": "Different Item", "barcode": "123456789"}
        )
        
        assert response.status_code == 400
        assert "Barcode already associated" in response.json()["detail"]

    def test_get_item(self, client, sample_item):
        """Test getting a single item by ID."""
        response = client.get(f"/api/items/{sample_item['id']}")
        
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Milk"
        assert data["id"] == sample_item["id"]

    def test_get_item_not_found(self, client):
        """Test getting a non-existent item."""
        response = client.get("/api/items/99999")
        
        assert response.status_code == 404
        assert "Item not found" in response.json()["detail"]

    def test_list_all_items(self, client, sample_items):
        """Test listing all items."""
        response = client.get("/api/items")
        
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 6  # 3 inventory + 2 grocery + 1 neither

    def test_list_items_by_location(self, client, sample_items):
        """Test filtering items by location."""
        # Test inventory
        response = client.get("/api/items?location=inventory")
        assert response.status_code == 200
        assert len(response.json()) == 3
        
        # Test grocery list
        response = client.get("/api/items?location=grocery_list")
        assert response.status_code == 200
        assert len(response.json()) == 2
        
        # Test neither
        response = client.get("/api/items?location=neither")
        assert response.status_code == 200
        assert len(response.json()) == 1

    def test_update_item_name(self, client, sample_item):
        """Test updating an item's name."""
        response = client.patch(
            f"/api/items/{sample_item['id']}",
            json={"name": "Whole Milk"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Whole Milk"

    def test_update_item_location(self, client, sample_item):
        """Test updating an item's location."""
        response = client.patch(
            f"/api/items/{sample_item['id']}",
            json={"location": "grocery_list"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["location"] == "grocery_list"

    def test_update_item_duplicate_name(self, client, sample_items):
        """Test that updating to a duplicate name fails."""
        milk = next(i for i in sample_items if i["name"] == "Milk")
        
        response = client.patch(
            f"/api/items/{milk['id']}",
            json={"name": "Eggs"}  # Eggs already exists
        )
        
        assert response.status_code == 400
        assert "already exists" in response.json()["detail"]

    def test_update_item_not_found(self, client):
        """Test updating a non-existent item."""
        response = client.patch(
            "/api/items/99999",
            json={"name": "New Name"}
        )
        
        assert response.status_code == 404

    def test_delete_item(self, client, sample_item):
        """Test deleting an item."""
        response = client.delete(f"/api/items/{sample_item['id']}")
        
        assert response.status_code == 200
        data = response.json()
        assert data["deleted"] is True
        assert data["id"] == sample_item["id"]
        
        # Verify item is gone
        response = client.get(f"/api/items/{sample_item['id']}")
        assert response.status_code == 404

    def test_delete_item_not_found(self, client):
        """Test deleting a non-existent item."""
        response = client.delete("/api/items/99999")
        
        assert response.status_code == 404

    def test_delete_item_removes_barcodes(self, client, sample_item):
        """Test that deleting an item also removes its barcodes."""
        # Add another barcode to the item
        client.post(
            "/api/barcode/associate",
            json={"barcode": "SECOND_BARCODE", "item_id": sample_item["id"]}
        )
        
        # Delete the item
        client.delete(f"/api/items/{sample_item['id']}")
        
        # Verify barcodes are gone
        response = client.get("/api/barcode/123456789")
        assert response.json()["found"] is False
        
        response = client.get("/api/barcode/SECOND_BARCODE")
        assert response.json()["found"] is False


class TestMoveItemShortcuts:
    """Tests for the move item shortcut endpoints."""

    def test_move_to_inventory(self, client, sample_item):
        """Test moving an item to inventory."""
        # First move to grocery
        client.patch(
            f"/api/items/{sample_item['id']}",
            json={"location": "grocery_list"}
        )
        
        # Use shortcut to move to inventory
        response = client.post(f"/api/items/{sample_item['id']}/to-inventory")
        
        assert response.status_code == 200
        assert response.json()["location"] == "inventory"

    def test_move_to_grocery(self, client, sample_item):
        """Test moving an item to grocery list."""
        response = client.post(f"/api/items/{sample_item['id']}/to-grocery")
        
        assert response.status_code == 200
        assert response.json()["location"] == "grocery_list"

    def test_remove_from_lists(self, client, sample_item):
        """Test removing an item from both lists."""
        response = client.post(f"/api/items/{sample_item['id']}/remove")
        
        assert response.status_code == 200
        assert response.json()["location"] == "neither"

    def test_move_nonexistent_item(self, client):
        """Test moving a non-existent item."""
        response = client.post("/api/items/99999/to-inventory")
        assert response.status_code == 404
        
        response = client.post("/api/items/99999/to-grocery")
        assert response.status_code == 404
        
        response = client.post("/api/items/99999/remove")
        assert response.status_code == 404


class TestHomeAssistantEndpoints:
    """Tests for Home Assistant compatible endpoints."""

    def test_get_inventory(self, client, sample_items):
        """Test getting inventory list."""
        response = client.get("/api/inventory")
        
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 3
        assert len(data["items"]) == 3
        
        # Verify all items are in inventory
        for item in data["items"]:
            assert item["location"] == "inventory"

    def test_get_grocery(self, client, sample_items):
        """Test getting grocery list."""
        response = client.get("/api/grocery")
        
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 2
        assert len(data["items"]) == 2
        
        # Verify all items are in grocery list
        for item in data["items"]:
            assert item["location"] == "grocery_list"

    def test_inventory_empty(self, client):
        """Test getting empty inventory."""
        response = client.get("/api/inventory")
        
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 0
        assert data["items"] == []

    def test_grocery_empty(self, client):
        """Test getting empty grocery list."""
        response = client.get("/api/grocery")
        
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 0
        assert data["items"] == []

    def test_inventory_sorted_alphabetically(self, client, sample_items):
        """Test that inventory items are sorted alphabetically."""
        response = client.get("/api/inventory")
        
        data = response.json()
        names = [item["name"] for item in data["items"]]
        assert names == sorted(names)

    def test_grocery_sorted_alphabetically(self, client, sample_items):
        """Test that grocery items are sorted alphabetically."""
        response = client.get("/api/grocery")
        
        data = response.json()
        names = [item["name"] for item in data["items"]]
        assert names == sorted(names)


class TestSearch:
    """Tests for the search functionality."""

    def test_search_by_name(self, client, sample_items):
        """Test searching items by name."""
        response = client.get("/api/search?q=milk")
        
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "Milk"

    def test_search_case_insensitive(self, client, sample_items):
        """Test that search is case-insensitive."""
        response = client.get("/api/search?q=MILK")
        
        assert response.status_code == 200
        assert len(response.json()) == 1

    def test_search_partial_match(self, client, sample_items):
        """Test that search matches partial strings."""
        response = client.get("/api/search?q=il")  # Matches "Milk"
        
        assert response.status_code == 200
        assert len(response.json()) >= 1

    def test_search_no_results(self, client, sample_items):
        """Test search with no matching results."""
        response = client.get("/api/search?q=nonexistent")
        
        assert response.status_code == 200
        assert response.json() == []

    def test_search_multiple_results(self, client):
        """Test search returning multiple results."""
        # Create items with similar names
        client.post("/api/items", json={"name": "Apple Juice"})
        client.post("/api/items", json={"name": "Apple Sauce"})
        client.post("/api/items", json={"name": "Apple Cider"})
        
        response = client.get("/api/search?q=apple")
        
        assert response.status_code == 200
        assert len(response.json()) == 3

    def test_search_sorted_alphabetically(self, client):
        """Test that search results are sorted alphabetically."""
        client.post("/api/items", json={"name": "Zebra Cookies"})
        client.post("/api/items", json={"name": "Apple Cookies"})
        client.post("/api/items", json={"name": "Mango Cookies"})
        
        response = client.get("/api/search?q=cookies")
        
        data = response.json()
        names = [item["name"] for item in data]
        assert names == sorted(names)


class TestWorkflow:
    """Tests for complete user workflows."""

    def test_new_barcode_workflow(self, client):
        """Test the complete workflow for a new barcode."""
        # 1. Scan barcode - not found
        response = client.get("/api/barcode/NEW_PRODUCT_123")
        assert response.json()["found"] is False
        
        # 2. Create new item with barcode
        response = client.post(
            "/api/items",
            json={
                "name": "New Product",
                "location": "inventory",
                "barcode": "NEW_PRODUCT_123"
            }
        )
        assert response.status_code == 200
        item_id = response.json()["id"]
        
        # 3. Scan barcode again - found
        response = client.get("/api/barcode/NEW_PRODUCT_123")
        data = response.json()
        assert data["found"] is True
        assert data["item"]["name"] == "New Product"

    def test_inventory_to_grocery_workflow(self, client, sample_item):
        """Test moving an item from inventory to grocery list."""
        # Item starts in inventory
        assert sample_item["location"] == "inventory"
        
        # Use up the item - move to grocery
        response = client.post(f"/api/items/{sample_item['id']}/to-grocery")
        assert response.json()["location"] == "grocery_list"
        
        # Verify in grocery list
        response = client.get("/api/grocery")
        assert any(i["name"] == "Milk" for i in response.json()["items"])
        
        # Verify not in inventory
        response = client.get("/api/inventory")
        assert not any(i["name"] == "Milk" for i in response.json()["items"])

    def test_restock_workflow(self, client, sample_item):
        """Test the restock workflow (grocery back to inventory)."""
        # Move to grocery first
        client.post(f"/api/items/{sample_item['id']}/to-grocery")
        
        # Simulate restocking by scanning and moving to inventory
        response = client.get("/api/barcode/123456789")
        item_id = response.json()["item"]["id"]
        
        response = client.post(f"/api/items/{item_id}/to-inventory")
        assert response.json()["location"] == "inventory"

    def test_add_second_barcode_workflow(self, client, sample_item):
        """Test adding a second barcode to an existing item."""
        # Scan new barcode for same product (different size/package)
        response = client.get("/api/barcode/LARGE_SIZE_123")
        assert response.json()["found"] is False
        
        # Associate with existing item
        response = client.post(
            "/api/barcode/associate",
            json={"barcode": "LARGE_SIZE_123", "item_id": sample_item["id"]}
        )
        assert response.status_code == 200
        assert len(response.json()["barcodes"]) == 2
        
        # Both barcodes now resolve to same item
        response1 = client.get("/api/barcode/123456789")
        response2 = client.get("/api/barcode/LARGE_SIZE_123")
        
        assert response1.json()["item"]["id"] == response2.json()["item"]["id"]


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_empty_item_name(self, client):
        """Test that empty item names are handled."""
        response = client.post("/api/items", json={"name": ""})
        # Should either fail validation or succeed with empty name
        # Depending on business rules

    def test_very_long_item_name(self, client):
        """Test creating an item with a very long name."""
        long_name = "A" * 1000
        response = client.post("/api/items", json={"name": long_name})
        
        assert response.status_code == 200
        assert response.json()["name"] == long_name

    def test_very_long_barcode(self, client):
        """Test creating an item with a very long barcode."""
        long_barcode = "1" * 1000
        response = client.post(
            "/api/items",
            json={"name": "Long Barcode Item", "barcode": long_barcode}
        )
        
        assert response.status_code == 200
        assert response.json()["barcodes"][0]["code"] == long_barcode

    def test_unicode_item_name(self, client):
        """Test creating an item with Unicode characters."""
        response = client.post(
            "/api/items",
            json={"name": "日本酒 🍶"}
        )
        
        assert response.status_code == 200
        assert response.json()["name"] == "日本酒 🍶"

    def test_unicode_barcode(self, client):
        """Test creating an item with Unicode barcode."""
        response = client.post(
            "/api/items",
            json={"name": "Unicode Barcode", "barcode": "αβγ-123"}
        )
        
        assert response.status_code == 200
        
        # Verify lookup works
        response = client.get("/api/barcode/αβγ-123")
        assert response.json()["found"] is True

    def test_whitespace_handling(self, client):
        """Test handling of whitespace in names."""
        response = client.post(
            "/api/items",
            json={"name": "  Spaces  Around  "}
        )
        
        assert response.status_code == 200
        # The name is stored as-is (no trimming)

    def test_concurrent_same_barcode(self, client):
        """Test that concurrent attempts to create same barcode fail."""
        # First creation succeeds
        response1 = client.post(
            "/api/items",
            json={"name": "Item 1", "barcode": "SAME_CODE"}
        )
        assert response1.status_code == 200
        
        # Second creation fails
        response2 = client.post(
            "/api/items",
            json={"name": "Item 2", "barcode": "SAME_CODE"}
        )
        assert response2.status_code == 400


class TestRecipeCRUD:
    """Tests for Recipe Create, Read, Update, Delete operations."""

    def test_create_recipe(self, client):
        """Test creating a recipe with ingredients and steps."""
        recipe_data = {
            "name": "Test Recipe",
            "description": "A test recipe",
            "servings": 2,
            "prep_time_minutes": 5,
            "cook_time_minutes": 10,
            "ingredients": [
                {"name": "Ingredient 1", "amount": "1", "unit": "cup"},
                {"name": "Ingredient 2", "amount": "2", "unit": "tbsp"}
            ],
            "steps": [
                {"step_number": 1, "instruction": "Do step 1"},
                {"step_number": 2, "instruction": "Do step 2"}
            ]
        }
        
        response = client.post("/api/recipes", json=recipe_data)
        
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Test Recipe"
        assert data["servings"] == 2
        assert len(data["ingredients"]) == 2
        assert len(data["steps"]) == 2

    def test_create_recipe_minimal(self, client):
        """Test creating a recipe with minimal data."""
        response = client.post(
            "/api/recipes",
            json={"name": "Minimal Recipe"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Minimal Recipe"
        assert data["servings"] == 4  # default
        assert data["ingredients"] == []
        assert data["steps"] == []

    def test_list_recipes(self, client, sample_recipe):
        """Test listing all recipes."""
        response = client.get("/api/recipes")
        
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert len(data["recipes"]) == 1
        assert data["recipes"][0]["name"] == "Simple Pasta"

    def test_list_recipes_favorites_only(self, client):
        """Test filtering recipes by favorites."""
        # Create non-favorite
        client.post("/api/recipes", json={"name": "Normal Recipe"})
        # Create favorite
        client.post("/api/recipes", json={"name": "Favorite Recipe", "is_favorite": True})
        
        response = client.get("/api/recipes?favorites_only=true")
        
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert data["recipes"][0]["name"] == "Favorite Recipe"

    def test_get_recipe(self, client, sample_recipe):
        """Test getting a single recipe."""
        response = client.get(f"/api/recipes/{sample_recipe['id']}")
        
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Simple Pasta"
        assert len(data["ingredients"]) == 3
        assert len(data["steps"]) == 3

    def test_get_recipe_not_found(self, client):
        """Test getting a non-existent recipe."""
        response = client.get("/api/recipes/99999")
        
        assert response.status_code == 404

    def test_update_recipe(self, client, sample_recipe):
        """Test updating a recipe."""
        response = client.patch(
            f"/api/recipes/{sample_recipe['id']}",
            json={"name": "Updated Pasta", "servings": 6}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Updated Pasta"
        assert data["servings"] == 6

    def test_delete_recipe(self, client, sample_recipe):
        """Test deleting a recipe."""
        response = client.delete(f"/api/recipes/{sample_recipe['id']}")
        
        assert response.status_code == 200
        assert response.json()["deleted"] is True
        
        # Verify deleted
        response = client.get(f"/api/recipes/{sample_recipe['id']}")
        assert response.status_code == 404

    def test_toggle_favorite(self, client, sample_recipe):
        """Test toggling recipe favorite status."""
        # Initially not favorite
        assert sample_recipe["is_favorite"] is False
        
        # Toggle to favorite
        response = client.post(f"/api/recipes/{sample_recipe['id']}/favorite")
        assert response.status_code == 200
        assert response.json()["is_favorite"] is True
        
        # Toggle back
        response = client.post(f"/api/recipes/{sample_recipe['id']}/favorite")
        assert response.json()["is_favorite"] is False


class TestRecipeView:
    """Tests for the recipe view page."""

    def test_view_recipe_page(self, client, sample_recipe):
        """Test that the recipe view page returns HTML."""
        response = client.get(f"/recipe/{sample_recipe['id']}")
        
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "Simple Pasta" in response.text

    def test_view_recipe_page_not_found(self, client):
        """Test viewing a non-existent recipe."""
        response = client.get("/recipe/99999")
        
        assert response.status_code == 404


class TestHealthCheckExtended:
    """Extended health check tests."""

    def test_health_check_includes_gemini_status(self, client):
        """Test that health check includes Gemini configuration status."""
        response = client.get("/api/health")
        
        assert response.status_code == 200
        data = response.json()
        assert "gemini_configured" in data
        # Will be False in test environment without API key
        assert data["gemini_configured"] is False

    def test_health_check_includes_spoonacular_status(self, client):
        """Test that health check includes Spoonacular configuration status."""
        response = client.get("/api/health")
        
        assert response.status_code == 200
        data = response.json()
        assert "spoonacular_configured" in data
        # Will be False in test environment without API key
        assert data["spoonacular_configured"] is False


class TestRecipeFullUpdate:
    """Tests for the full recipe update endpoint."""

    def test_update_recipe_with_ingredients(self, client, sample_recipe):
        """Test updating recipe including ingredients."""
        response = client.put(
            f"/api/recipes/{sample_recipe['id']}",
            json={
                "name": "Updated Pasta",
                "ingredients": [
                    {"name": "Spaghetti", "amount": "500", "unit": "g"},
                    {"name": "Olive Oil", "amount": "2", "unit": "tbsp"}
                ]
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Updated Pasta"
        assert len(data["ingredients"]) == 2
        assert data["ingredients"][0]["name"] == "Spaghetti"

    def test_update_recipe_with_steps(self, client, sample_recipe):
        """Test updating recipe including steps."""
        response = client.put(
            f"/api/recipes/{sample_recipe['id']}",
            json={
                "steps": [
                    {"step_number": 1, "instruction": "Boil water"},
                    {"step_number": 2, "instruction": "Add pasta"},
                    {"step_number": 3, "instruction": "Serve"}
                ]
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["steps"]) == 3

    def test_update_recipe_not_found(self, client):
        """Test updating a non-existent recipe."""
        response = client.put(
            "/api/recipes/99999",
            json={"name": "New Name"}
        )
        
        assert response.status_code == 404


class TestSpoonacularEndpoints:
    """Tests for Spoonacular API endpoints (without actual API calls)."""

    def test_spoonacular_recipe_detail_no_api_key(self, client):
        """Test getting Spoonacular recipe detail when API key is not set."""
        response = client.get("/api/spoonacular/recipe/12345")
        
        assert response.status_code == 503

    def test_spoonacular_discover_no_api_key(self, client, sample_items):
        """Test discovering recipes by ingredients when API key is not set."""
        response = client.post(
            "/api/spoonacular/discover",
            json={"number": 5}
        )
        
        assert response.status_code == 503

    def test_spoonacular_import_no_api_key(self, client):
        """Test importing Spoonacular recipe when API key is not set."""
        response = client.post("/api/spoonacular/import/12345")
        
        assert response.status_code == 503

    def test_import_url_no_api_key(self, client):
        """Test importing recipe from URL when API key is not set."""
        response = client.post(
            "/api/recipes/import-url",
            json={"url": "https://example.com/recipe"}
        )
        
        assert response.status_code == 503


class TestAIEndpoints:
    """Tests for AI endpoints (without actual API calls)."""

    def test_recipe_suggestions_no_api_key(self, client, sample_items):
        """Test recipe suggestions when Gemini API key is not set."""
        response = client.post("/api/ai/recipe-suggestions", json={})
        
        # Should return 503 when API key not configured
        assert response.status_code == 503
        assert "not configured" in response.json()["detail"].lower()

    def test_recipe_suggestions_with_query_no_api_key(self, client, sample_items):
        """Test recipe suggestions with query when Gemini API key is not set."""
        response = client.post(
            "/api/ai/recipe-suggestions",
            json={"query": "soup recipes"}
        )
        
        # Should return 503 when API key not configured
        assert response.status_code == 503

    def test_grocery_suggestions_no_api_key(self, client, sample_items):
        """Test grocery suggestions when Gemini API key is not set."""
        response = client.post("/api/ai/grocery-suggestions")
        
        # Should return 503 when API key not configured
        assert response.status_code == 503
        assert "not configured" in response.json()["detail"].lower()

