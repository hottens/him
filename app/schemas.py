"""Pydantic schemas for API request/response validation."""

from pydantic import BaseModel
from typing import Optional
from datetime import datetime
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


# --- Recipe Schemas ---

class RecipeIngredientBase(BaseModel):
    name: str
    amount: Optional[str] = None
    unit: Optional[str] = None
    notes: Optional[str] = None


class RecipeIngredientCreate(RecipeIngredientBase):
    pass


class RecipeIngredientResponse(RecipeIngredientBase):
    id: int
    recipe_id: int

    class Config:
        from_attributes = True


class RecipeStepBase(BaseModel):
    step_number: int
    instruction: str


class RecipeStepCreate(RecipeStepBase):
    pass


class RecipeStepResponse(RecipeStepBase):
    id: int
    recipe_id: int

    class Config:
        from_attributes = True


class RecipeBase(BaseModel):
    name: str
    description: Optional[str] = None
    servings: int = 4
    prep_time_minutes: Optional[int] = None
    cook_time_minutes: Optional[int] = None


class RecipeCreate(RecipeBase):
    ingredients: list[RecipeIngredientCreate] = []
    steps: list[RecipeStepCreate] = []
    is_favorite: bool = False


class RecipeResponse(RecipeBase):
    id: int
    is_favorite: bool
    created_at: datetime
    ingredients: list[RecipeIngredientResponse] = []
    steps: list[RecipeStepResponse] = []

    class Config:
        from_attributes = True


class RecipeUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    servings: Optional[int] = None
    prep_time_minutes: Optional[int] = None
    cook_time_minutes: Optional[int] = None
    is_favorite: Optional[bool] = None


class RecipeListResponse(BaseModel):
    """List of recipes."""
    count: int
    recipes: list[RecipeResponse]


# --- Gemini Suggestion Schemas ---

class GeminiRecipeSuggestion(BaseModel):
    """A single recipe suggestion from Gemini."""
    name: str
    description: str
    servings: int = 4
    prep_time_minutes: Optional[int] = None
    cook_time_minutes: Optional[int] = None
    ingredients: list[RecipeIngredientCreate]
    steps: list[RecipeStepCreate]


class GeminiRecipeSuggestionsResponse(BaseModel):
    """Response containing recipe suggestions from Gemini."""
    suggestions: list[GeminiRecipeSuggestion]
    inventory_used: list[str]  # Items from inventory that were considered


class GeminiGrocerySuggestion(BaseModel):
    """A single grocery suggestion."""
    item_name: str
    reason: str  # Why this is suggested (e.g., "needed for Pasta Carbonara")


class GeminiGrocerySuggestionsResponse(BaseModel):
    """Response containing grocery suggestions from Gemini."""
    suggestions: list[GeminiGrocerySuggestion]
    based_on_recipes: list[str]  # Recipe names considered
    current_inventory: list[str]  # What's already in inventory


# --- Spoonacular Schemas ---

class SpoonacularByIngredientsRequest(BaseModel):
    """Request for discovering recipes by ingredients."""
    number: int = 10


# --- Recipe Full Update Schema ---

class RecipeFullUpdate(BaseModel):
    """Full update for a recipe including ingredients and steps."""
    name: Optional[str] = None
    description: Optional[str] = None
    servings: Optional[int] = None
    prep_time_minutes: Optional[int] = None
    cook_time_minutes: Optional[int] = None
    is_favorite: Optional[bool] = None
    ingredients: Optional[list[RecipeIngredientCreate]] = None
    steps: Optional[list[RecipeStepCreate]] = None
