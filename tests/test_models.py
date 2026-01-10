"""
Unit tests for database models.

Tests the Item and Barcode models and their relationships.
"""

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import Item, Barcode, ItemLocation


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

