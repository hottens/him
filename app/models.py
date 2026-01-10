"""SQLAlchemy database models for inventory management."""

from sqlalchemy import Column, Integer, String, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import relationship
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

