"""SQLAlchemy database models for inventory management."""

from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    ForeignKey,
    Enum as SQLEnum,
    Text,
    Boolean,
    DateTime,
)
from sqlalchemy.orm import relationship
from datetime import datetime
import enum

from .database import Base


class ItemLocation(str, enum.Enum):
    """Where an item currently resides."""
    INVENTORY = "inventory"      # Item is at home
    GROCERY_LIST = "grocery_list"  # Item needs to be restocked
    NEITHER = "neither"          # Item exists but not tracked in either list


class Item(Base):
    """
    An item that can be tracked in inventory or grocery list.

    One item can have multiple barcodes (e.g., different sizes of same product).
    The active barcode is the last scanned one, and can be overridden manually.
    """
    __tablename__ = "items"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, unique=True, index=True)
    location = Column(
        SQLEnum(ItemLocation),
        default=ItemLocation.NEITHER,
        nullable=False
    )
    # No FK constraint — avoids circular dependency with barcodes.item_id
    active_barcode_id = Column(Integer, nullable=True)

    barcodes = relationship("Barcode", back_populates="item", cascade="all, delete-orphan")

    def __repr__(self):
        loc = self.location.value if self.location else None
        return f"<Item(id={self.id}, name='{self.name}', location={loc})>"


class Barcode(Base):
    """
    A barcode that uniquely maps to one item, with optional Open Food Facts data.
    """
    __tablename__ = "barcodes"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, nullable=False, unique=True, index=True)
    item_id = Column(Integer, ForeignKey("items.id"), nullable=False)

    # Open Food Facts product data (English source + Dutch translations)
    product_name = Column(String, nullable=True)
    brands = Column(String, nullable=True)
    keywords = Column(Text, nullable=True)  # JSON list
    ingredients_en = Column(Text, nullable=True)  # JSON list
    ingredients_hierarchy_en = Column(Text, nullable=True)  # JSON list
    ingredients_nl = Column(Text, nullable=True)  # JSON list
    ingredients_hierarchy_nl = Column(Text, nullable=True)  # JSON list
    allergens = Column(Text, nullable=True)  # JSON list
    nutriments = Column(Text, nullable=True)  # JSON object
    energy_kcal_100g = Column(Float, nullable=True)
    energy_kcal_serving = Column(Float, nullable=True)

    last_scanned_at = Column(DateTime, nullable=True)
    product_fetched_at = Column(DateTime, nullable=True)

    item = relationship("Item", back_populates="barcodes")

    def __repr__(self):
        return f"<Barcode(id={self.id}, code='{self.code}', item_id={self.item_id})>"


class Setting(Base):
    """Simple key/value application settings."""
    __tablename__ = "settings"

    key = Column(String, primary_key=True)
    value = Column(String, nullable=False)


class Recipe(Base):
    """
    A saved recipe with ingredients and cooking steps.
    """
    __tablename__ = "recipes"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, index=True)
    description = Column(Text, nullable=True)
    servings = Column(Integer, default=4)
    prep_time_minutes = Column(Integer, nullable=True)
    cook_time_minutes = Column(Integer, nullable=True)
    is_favorite = Column(Boolean, default=False)
    source_url = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    ingredients = relationship("RecipeIngredient", back_populates="recipe", cascade="all, delete-orphan")
    steps = relationship("RecipeStep", back_populates="recipe", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Recipe(id={self.id}, name='{self.name}')>"


class RecipeIngredient(Base):
    """
    An ingredient in a recipe with amount and unit.
    Can optionally be linked to an inventory Item for availability and nutrition.
    """
    __tablename__ = "recipe_ingredients"

    id = Column(Integer, primary_key=True, index=True)
    recipe_id = Column(Integer, ForeignKey("recipes.id"), nullable=False)
    name = Column(String, nullable=False)
    amount = Column(String, nullable=True)
    unit = Column(String, nullable=True)
    notes = Column(String, nullable=True)
    item_id = Column(Integer, ForeignKey("items.id"), nullable=True)

    recipe = relationship("Recipe", back_populates="ingredients")
    matched_item = relationship("Item", foreign_keys=[item_id])

    def __repr__(self):
        return f"<RecipeIngredient(id={self.id}, name='{self.name}', item_id={self.item_id})>"


class RecipeStep(Base):
    """A cooking step in a recipe."""
    __tablename__ = "recipe_steps"

    id = Column(Integer, primary_key=True, index=True)
    recipe_id = Column(Integer, ForeignKey("recipes.id"), nullable=False)
    step_number = Column(Integer, nullable=False)
    instruction = Column(Text, nullable=False)

    recipe = relationship("Recipe", back_populates="steps")

    def __repr__(self):
        return f"<RecipeStep(id={self.id}, step={self.step_number})>"
