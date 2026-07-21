"""Pydantic schemas for API request/response validation."""

from pydantic import BaseModel, Field
from typing import Optional, Any
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
    product_name: Optional[str] = None
    brands: Optional[str] = None
    keywords: list[str] = []
    ingredients_en: list[str] = []
    ingredients_hierarchy_en: list[str] = []
    ingredients_nl: list[str] = []
    ingredients_hierarchy_nl: list[str] = []
    allergens: list[str] = []
    nutriments: dict[str, Any] = {}
    energy_kcal_100g: Optional[float] = None
    energy_kcal_serving: Optional[float] = None
    last_scanned_at: Optional[datetime] = None
    product_fetched_at: Optional[datetime] = None
    is_active: bool = False

    class Config:
        from_attributes = True


# --- Item Schemas ---

class ItemBase(BaseModel):
    name: str


class ItemCreate(ItemBase):
    location: ItemLocation = ItemLocation.NEITHER
    barcode: Optional[str] = None


class ItemResponse(ItemBase):
    id: int
    location: ItemLocation
    active_barcode_id: Optional[int] = None
    barcodes: list[BarcodeResponse] = []

    class Config:
        from_attributes = True


class ItemUpdate(BaseModel):
    name: Optional[str] = None
    location: Optional[ItemLocation] = None
    active_barcode_id: Optional[int] = None


class SetActiveBarcodeRequest(BaseModel):
    barcode_id: int


# --- Barcode Lookup Response ---

class BarcodeLookupResponse(BaseModel):
    found: bool
    barcode: Optional[str] = None
    item: Optional[ItemResponse] = None
    # Populated when barcode is unknown but Open Food Facts has a match
    suggested_name: Optional[str] = None
    suggested_brands: Optional[str] = None


class MoveItemRequest(BaseModel):
    location: ItemLocation


class AssociateBarcodeRequest(BaseModel):
    barcode: str
    item_id: int


class InventoryListResponse(BaseModel):
    count: int
    items: list[ItemResponse]


class GroceryListResponse(BaseModel):
    count: int
    items: list[ItemResponse]


# --- Settings ---

class SettingsResponse(BaseModel):
    auto_fetch_products: bool = True
    translate_ingredients: bool = True
    gemini_configured: bool = False


class SettingsUpdate(BaseModel):
    auto_fetch_products: Optional[bool] = None
    translate_ingredients: Optional[bool] = None


class BarcodeReloadResult(BaseModel):
    total: int
    updated: int
    not_found: int
    errors: int


# --- Recipe Schemas ---

class RecipeIngredientBase(BaseModel):
    name: str
    amount: Optional[str] = None
    unit: Optional[str] = None
    notes: Optional[str] = None


class RecipeIngredientCreate(RecipeIngredientBase):
    item_id: Optional[int] = None


class MatchedItemInfo(BaseModel):
    id: int
    name: str
    location: ItemLocation

    class Config:
        from_attributes = True


class RecipeIngredientResponse(RecipeIngredientBase):
    id: int
    recipe_id: int
    item_id: Optional[int] = None
    matched_item: Optional[MatchedItemInfo] = None

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


class RecipeNutritionSummary(BaseModel):
    totals: dict[str, float] = Field(default_factory=dict)
    per_100g: dict[str, float] = Field(default_factory=dict)
    allergens: list[str] = Field(default_factory=list)
    ingredients_included: list[str] = Field(default_factory=list)
    ingredients_skipped: list[str] = Field(default_factory=list)


class BarcodeUpdate(BaseModel):
    """Manual edits for Open Food Facts fields stored on a barcode."""
    product_name: Optional[str] = None
    brands: Optional[str] = None
    keywords: Optional[list[str]] = None
    ingredients_en: Optional[list[str]] = None
    ingredients_hierarchy_en: Optional[list[str]] = None
    ingredients_nl: Optional[list[str]] = None
    ingredients_hierarchy_nl: Optional[list[str]] = None
    allergens: Optional[list[str]] = None
    nutriments: Optional[dict[str, Any]] = None
    energy_kcal_100g: Optional[float] = None
    energy_kcal_serving: Optional[float] = None


class RecipeTranslateRequest(BaseModel):
    lang: str = "en"  # "en" or "nl"


class RecipeTranslateResponse(BaseModel):
    lang: str
    name: str
    description: Optional[str] = None
    ingredients: list[dict[str, Any]] = Field(default_factory=list)
    steps: list[dict[str, Any]] = Field(default_factory=list)
    ui: dict[str, str] = Field(default_factory=dict)


class RecipeBase(BaseModel):
    name: str
    description: Optional[str] = None
    servings: int = 4
    prep_time_minutes: Optional[int] = None
    cook_time_minutes: Optional[int] = None
    source_url: Optional[str] = None


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
    nutrition: Optional[RecipeNutritionSummary] = None

    class Config:
        from_attributes = True


class RecipeUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    servings: Optional[int] = None
    prep_time_minutes: Optional[int] = None
    cook_time_minutes: Optional[int] = None
    is_favorite: Optional[bool] = None
    source_url: Optional[str] = None


class RecipeListResponse(BaseModel):
    count: int
    recipes: list[RecipeResponse]


class GeminiRecipeSuggestion(BaseModel):
    name: str
    description: str
    servings: int = 4
    prep_time_minutes: Optional[int] = None
    cook_time_minutes: Optional[int] = None
    ingredients: list[RecipeIngredientCreate]
    steps: list[RecipeStepCreate]


class GeminiRecipeSuggestionsResponse(BaseModel):
    suggestions: list[GeminiRecipeSuggestion]
    inventory_used: list[str]


class GeminiGrocerySuggestion(BaseModel):
    item_name: str
    reason: str


class GeminiGrocerySuggestionsResponse(BaseModel):
    suggestions: list[GeminiGrocerySuggestion]
    based_on_recipes: list[str]
    current_inventory: list[str]


class RecipeFullUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    servings: Optional[int] = None
    prep_time_minutes: Optional[int] = None
    cook_time_minutes: Optional[int] = None
    is_favorite: Optional[bool] = None
    source_url: Optional[str] = None
    ingredients: Optional[list[RecipeIngredientCreate]] = None
    steps: Optional[list[RecipeStepCreate]] = None
