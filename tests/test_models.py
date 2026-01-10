"""
Unit tests for database models.

Tests the Item, Barcode, Recipe, RecipeIngredient, and RecipeStep models.
"""

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import Item, Barcode, ItemLocation, Recipe, RecipeIngredient, RecipeStep


class TestItemModel:
    """Tests for the Item model."""

    def test_create_item(self, db_session):
        """Test creating a basic item."""
        item = Item(name="Test Item", location=ItemLocation.INVENTORY)
        db_session.add(item)
        db_session.commit()

        assert item.id is not None
        assert item.name == "Test Item"
        assert item.location == ItemLocation.INVENTORY

    def test_item_default_location(self, db_session):
        """Test that item defaults to NEITHER location."""
        item = Item(name="Test Item")
        db_session.add(item)
        db_session.commit()

        assert item.location == ItemLocation.NEITHER

    def test_item_unique_name(self, db_session):
        """Test that item names must be unique."""
        item1 = Item(name="Duplicate", location=ItemLocation.INVENTORY)
        db_session.add(item1)
        db_session.commit()

        item2 = Item(name="Duplicate", location=ItemLocation.GROCERY_LIST)
        db_session.add(item2)
        
        with pytest.raises(IntegrityError):
            db_session.commit()

    def test_item_locations(self, db_session):
        """Test all valid item locations."""
        for location in ItemLocation:
            item = Item(name=f"Item_{location.value}", location=location)
            db_session.add(item)
        
        db_session.commit()
        
        items = db_session.query(Item).all()
        assert len(items) == 3
        
        locations = {item.location for item in items}
        assert locations == {ItemLocation.INVENTORY, ItemLocation.GROCERY_LIST, ItemLocation.NEITHER}

    def test_item_repr(self, db_session):
        """Test the string representation of an item."""
        item = Item(name="Milk", location=ItemLocation.INVENTORY)
        db_session.add(item)
        db_session.commit()

        repr_str = repr(item)
        assert "Milk" in repr_str
        assert "inventory" in repr_str


class TestBarcodeModel:
    """Tests for the Barcode model."""

    def test_create_barcode(self, db_session):
        """Test creating a barcode associated with an item."""
        item = Item(name="Test Item", location=ItemLocation.INVENTORY)
        db_session.add(item)
        db_session.flush()

        barcode = Barcode(code="123456789", item_id=item.id)
        db_session.add(barcode)
        db_session.commit()

        assert barcode.id is not None
        assert barcode.code == "123456789"
        assert barcode.item_id == item.id

    def test_barcode_unique_code(self, db_session):
        """Test that barcode codes must be unique."""
        item = Item(name="Test Item", location=ItemLocation.INVENTORY)
        db_session.add(item)
        db_session.flush()

        barcode1 = Barcode(code="123456789", item_id=item.id)
        db_session.add(barcode1)
        db_session.commit()

        barcode2 = Barcode(code="123456789", item_id=item.id)
        db_session.add(barcode2)
        
        with pytest.raises(IntegrityError):
            db_session.commit()

    def test_barcode_repr(self, db_session):
        """Test the string representation of a barcode."""
        item = Item(name="Test Item", location=ItemLocation.INVENTORY)
        db_session.add(item)
        db_session.flush()

        barcode = Barcode(code="123456789", item_id=item.id)
        db_session.add(barcode)
        db_session.commit()

        repr_str = repr(barcode)
        assert "123456789" in repr_str


class TestItemBarcodeRelationship:
    """Tests for the one-to-many relationship between Item and Barcode."""

    def test_item_has_barcodes(self, db_session):
        """Test that an item can have multiple barcodes."""
        item = Item(name="Product", location=ItemLocation.INVENTORY)
        db_session.add(item)
        db_session.flush()

        barcode1 = Barcode(code="111111", item_id=item.id)
        barcode2 = Barcode(code="222222", item_id=item.id)
        barcode3 = Barcode(code="333333", item_id=item.id)
        
        db_session.add_all([barcode1, barcode2, barcode3])
        db_session.commit()

        db_session.refresh(item)
        assert len(item.barcodes) == 3
        assert {b.code for b in item.barcodes} == {"111111", "222222", "333333"}

    def test_barcode_belongs_to_item(self, db_session):
        """Test that a barcode belongs to exactly one item."""
        item = Item(name="Product", location=ItemLocation.INVENTORY)
        db_session.add(item)
        db_session.flush()

        barcode = Barcode(code="123456789", item_id=item.id)
        db_session.add(barcode)
        db_session.commit()

        db_session.refresh(barcode)
        assert barcode.item is not None
        assert barcode.item.name == "Product"

    def test_cascade_delete(self, db_session):
        """Test that deleting an item also deletes its barcodes."""
        item = Item(name="Product", location=ItemLocation.INVENTORY)
        db_session.add(item)
        db_session.flush()

        barcode1 = Barcode(code="111111", item_id=item.id)
        barcode2 = Barcode(code="222222", item_id=item.id)
        db_session.add_all([barcode1, barcode2])
        db_session.commit()

        # Verify barcodes exist
        assert db_session.query(Barcode).count() == 2

        # Delete the item
        db_session.delete(item)
        db_session.commit()

        # Verify barcodes are also deleted
        assert db_session.query(Barcode).count() == 0
        assert db_session.query(Item).count() == 0

    def test_item_without_barcodes(self, db_session):
        """Test that an item can exist without any barcodes."""
        item = Item(name="No Barcode Item", location=ItemLocation.INVENTORY)
        db_session.add(item)
        db_session.commit()

        db_session.refresh(item)
        assert len(item.barcodes) == 0


class TestRecipeModel:
    """Tests for the Recipe model."""

    def test_create_recipe(self, db_session):
        """Test creating a basic recipe."""
        recipe = Recipe(
            name="Test Recipe",
            description="A test recipe",
            servings=4,
            prep_time_minutes=10,
            cook_time_minutes=20
        )
        db_session.add(recipe)
        db_session.commit()

        assert recipe.id is not None
        assert recipe.name == "Test Recipe"
        assert recipe.servings == 4
        assert recipe.is_favorite is False

    def test_recipe_default_values(self, db_session):
        """Test recipe default values."""
        recipe = Recipe(name="Minimal Recipe")
        db_session.add(recipe)
        db_session.commit()

        assert recipe.servings == 4
        assert recipe.is_favorite is False
        assert recipe.created_at is not None

    def test_recipe_with_ingredients(self, db_session):
        """Test creating a recipe with ingredients."""
        recipe = Recipe(name="Recipe With Ingredients")
        db_session.add(recipe)
        db_session.flush()

        ing1 = RecipeIngredient(
            recipe_id=recipe.id,
            name="Flour",
            amount="2",
            unit="cups"
        )
        ing2 = RecipeIngredient(
            recipe_id=recipe.id,
            name="Sugar",
            amount="1",
            unit="cup",
            notes="granulated"
        )
        db_session.add_all([ing1, ing2])
        db_session.commit()

        db_session.refresh(recipe)
        assert len(recipe.ingredients) == 2
        assert {i.name for i in recipe.ingredients} == {"Flour", "Sugar"}

    def test_recipe_with_steps(self, db_session):
        """Test creating a recipe with steps."""
        recipe = Recipe(name="Recipe With Steps")
        db_session.add(recipe)
        db_session.flush()

        step1 = RecipeStep(recipe_id=recipe.id, step_number=1, instruction="First step")
        step2 = RecipeStep(recipe_id=recipe.id, step_number=2, instruction="Second step")
        step3 = RecipeStep(recipe_id=recipe.id, step_number=3, instruction="Third step")
        db_session.add_all([step1, step2, step3])
        db_session.commit()

        db_session.refresh(recipe)
        assert len(recipe.steps) == 3

    def test_recipe_cascade_delete(self, db_session):
        """Test that deleting a recipe also deletes ingredients and steps."""
        recipe = Recipe(name="Recipe To Delete")
        db_session.add(recipe)
        db_session.flush()

        ing = RecipeIngredient(recipe_id=recipe.id, name="Test Ingredient")
        step = RecipeStep(recipe_id=recipe.id, step_number=1, instruction="Test step")
        db_session.add_all([ing, step])
        db_session.commit()

        # Verify they exist
        assert db_session.query(RecipeIngredient).count() == 1
        assert db_session.query(RecipeStep).count() == 1

        # Delete recipe
        db_session.delete(recipe)
        db_session.commit()

        # Verify cascade delete
        assert db_session.query(Recipe).count() == 0
        assert db_session.query(RecipeIngredient).count() == 0
        assert db_session.query(RecipeStep).count() == 0

    def test_recipe_repr(self, db_session):
        """Test the string representation of a recipe."""
        recipe = Recipe(name="Repr Test")
        db_session.add(recipe)
        db_session.commit()

        repr_str = repr(recipe)
        assert "Repr Test" in repr_str

