"""Pydantic schemas for API request/response validation."""

from pydantic import BaseModel
from typing import Optional
from .models import ItemLocation


# --- Barcode Schemas ---

class BarcodeBase(BaseModel):
    code: str


class BarcodeCreate(BarcodeBase):
    pass


class BarcodeResponse(BarcodeBase):
    id: int
    item_id: int

    class Config:
        from_attributes = True


# --- Item Schemas ---

class ItemBase(BaseModel):
    name: str


class ItemCreate(ItemBase):
    location: ItemLocation = ItemLocation.NEITHER
    barcode: Optional[str] = None  # Optional barcode to associate on creation


class ItemResponse(ItemBase):
    id: int
    location: ItemLocation
    barcodes: list[BarcodeResponse] = []

    class Config:
        from_attributes = True


class ItemUpdate(BaseModel):
    name: Optional[str] = None
    location: Optional[ItemLocation] = None


# --- Barcode Lookup Response ---

class BarcodeLookupResponse(BaseModel):
    """Response when looking up a barcode."""
    found: bool
    barcode: Optional[str] = None
    item: Optional[ItemResponse] = None


# --- Move Item Request ---

class MoveItemRequest(BaseModel):
    """Request to move an item to a different location."""
    location: ItemLocation


# --- Associate Barcode Request ---

class AssociateBarcodeRequest(BaseModel):
    """Request to associate a barcode with an existing item."""
    barcode: str
    item_id: int


# --- Home Assistant Compatible Responses ---

class InventoryListResponse(BaseModel):
    """Clean response for Home Assistant REST sensors."""
    count: int
    items: list[ItemResponse]


class GroceryListResponse(BaseModel):
    """Clean response for Home Assistant REST sensors."""
    count: int
    items: list[ItemResponse]

