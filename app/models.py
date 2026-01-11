"""SQLAlchemy database models for inventory management."""

from sqlalchemy import Column, Integer, String, ForeignKey, Enum as SQLEnum, Text, Boolean, DateTime
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
    """
    __tablename__ = "items"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, unique=True, index=True)
    location = Column(
        SQLEnum(ItemLocation),
        default=ItemLocation.NEITHER,
        nullable=False
    )

    # One-to-many: one item can have multiple barcodes
    barcodes = relationship("Barcode", back_populates="item", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Item(id={self.id}, name='{self.name}', location={self.location})>"


class Barcode(Base):
    """
    A barcode that uniquely maps to one item.
    
    The barcode value is the scanned string (e.g., UPC, EAN, etc.).
    """
    __tablename__ = "barcodes"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, nullable=False, unique=True, index=True)
    item_id = Column(Integer, ForeignKey("items.id"), nullable=False)

    # Many-to-one: many barcodes can belong to one item
    item = relationship("Item", back_populates="barcodes")

    def __repr__(self):
        return f"<Barcode(id={self.id}, code='{self.code}', item_id={self.item_id})>"


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
    created_at = Column(DateTime, default=datetime.utcnow)

    # One-to-many: one recipe has multiple ingredients
    ingredients = relationship("RecipeIngredient", back_populates="recipe", cascade="all, delete-orphan")
    # One-to-many: one recipe has multiple steps
    steps = relationship("RecipeStep", back_populates="recipe", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Recipe(id={self.id}, name='{self.name}')>"


class RecipeIngredient(Base):
    """
    An ingredient in a recipe with amount and unit.
    Can optionally be linked to an Item for inventory matching.
    """
    __tablename__ = "recipe_ingredients"

    id = Column(Integer, primary_key=True, index=True)
    recipe_id = Column(Integer, ForeignKey("recipes.id"), nullable=False)
    name = Column(String, nullable=False)  # Ingredient name (may or may not match an Item)
    amount = Column(String, nullable=True)  # e.g., "2", "1/2"
    unit = Column(String, nullable=True)    # e.g., "cups", "tbsp", "pieces"
    notes = Column(String, nullable=True)   # e.g., "diced", "room temperature"
    # Optional link to inventory item for matching
    item_id = Column(Integer, ForeignKey("items.id"), nullable=True)

    recipe = relationship("Recipe", back_populates="ingredients")
    matched_item = relationship("Item", foreign_keys=[item_id])

    def __repr__(self):
        return f"<RecipeIngredient(id={self.id}, name='{self.name}', item_id={self.item_id})>"


class RecipeStep(Base):
    """
    A cooking step in a recipe.
    """
    __tablename__ = "recipe_steps"

    id = Column(Integer, primary_key=True, index=True)
    recipe_id = Column(Integer, ForeignKey("recipes.id"), nullable=False)
    step_number = Column(Integer, nullable=False)
    instruction = Column(Text, nullable=False)

    recipe = relationship("Recipe", back_populates="steps")

    def __repr__(self):
        return f"<RecipeStep(id={self.id}, step={self.step_number})>"
