"""
Home Inventory Management API

A minimal, local-first application to track home inventory and grocery lists
using barcode scanning.
"""

from fastapi import FastAPI, HTTPException, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from typing import Optional
import os

from .database import engine, get_db, Base
from .models import Item, Barcode, ItemLocation
from . import schemas

# Create database tables
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Home Inventory Manager",
    description="Local-first inventory and grocery list management with barcode scanning",
    version="1.0.0"
)

# --- Static Files ---

static_path = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_path):
    app.mount("/static", StaticFiles(directory=static_path), name="static")


@app.get("/", include_in_schema=False)
async def root():
    """Serve the main web interface."""
    return FileResponse(os.path.join(static_path, "index.html"))


# --- Health Check ---

@app.get("/api/health")
async def health_check():
    """Health check endpoint for container orchestration."""
    return {"status": "healthy"}


# --- Barcode Endpoints ---

@app.get("/api/barcode/{code}", response_model=schemas.BarcodeLookupResponse)
async def lookup_barcode(code: str, db: Session = Depends(get_db)):
    """
    Look up a barcode and return the associated item if found.
    
    Used by the scanner to check if a barcode is already registered.
    """
    barcode = db.query(Barcode).filter(Barcode.code == code).first()
    
    if barcode:
        return schemas.BarcodeLookupResponse(
            found=True,
            barcode=code,
            item=barcode.item
        )
    
    return schemas.BarcodeLookupResponse(found=False, barcode=code)


@app.post("/api/barcode/associate", response_model=schemas.ItemResponse)
async def associate_barcode(
    request: schemas.AssociateBarcodeRequest,
    db: Session = Depends(get_db)
):
    """
    Associate a barcode with an existing item.
    
    Used when scanning a new barcode for an item that already exists.
    """
    # Check if barcode already exists
    existing = db.query(Barcode).filter(Barcode.code == request.barcode).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Barcode already associated with item: {existing.item.name}"
        )
    
    # Find the item
    item = db.query(Item).filter(Item.id == request.item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    
    # Create the barcode association
    barcode = Barcode(code=request.barcode, item_id=item.id)
    db.add(barcode)
    db.commit()
    db.refresh(item)
    
    return item


# --- Item Endpoints ---

@app.get("/api/items", response_model=list[schemas.ItemResponse])
async def list_items(
    location: Optional[ItemLocation] = None,
    db: Session = Depends(get_db)
):
    """
    List all items, optionally filtered by location.
    """
    query = db.query(Item)
    if location:
        query = query.filter(Item.location == location)
    return query.order_by(Item.name).all()


@app.post("/api/items", response_model=schemas.ItemResponse)
async def create_item(item: schemas.ItemCreate, db: Session = Depends(get_db)):
    """
    Create a new item, optionally with an associated barcode.
    """
    # Check if item name already exists
    existing = db.query(Item).filter(Item.name == item.name).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Item with name '{item.name}' already exists"
        )
    
    # Check if barcode already exists
    if item.barcode:
        existing_barcode = db.query(Barcode).filter(Barcode.code == item.barcode).first()
        if existing_barcode:
            raise HTTPException(
                status_code=400,
                detail=f"Barcode already associated with item: {existing_barcode.item.name}"
            )
    
    # Create the item
    db_item = Item(name=item.name, location=item.location)
    db.add(db_item)
    db.flush()  # Get the item ID
    
    # Associate barcode if provided
    if item.barcode:
        barcode = Barcode(code=item.barcode, item_id=db_item.id)
        db.add(barcode)
    
    db.commit()
    db.refresh(db_item)
    
    return db_item


@app.get("/api/items/{item_id}", response_model=schemas.ItemResponse)
async def get_item(item_id: int, db: Session = Depends(get_db)):
    """Get a specific item by ID."""
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return item


@app.patch("/api/items/{item_id}", response_model=schemas.ItemResponse)
async def update_item(
    item_id: int,
    update: schemas.ItemUpdate,
    db: Session = Depends(get_db)
):
    """Update an item's name or location."""
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    
    if update.name is not None:
        # Check for duplicate name
        existing = db.query(Item).filter(
            Item.name == update.name,
            Item.id != item_id
        ).first()
        if existing:
            raise HTTPException(
                status_code=400,
                detail=f"Item with name '{update.name}' already exists"
            )
        item.name = update.name
    
    if update.location is not None:
        item.location = update.location
    
    db.commit()
    db.refresh(item)
    
    return item


@app.delete("/api/items/{item_id}")
async def delete_item(item_id: int, db: Session = Depends(get_db)):
    """Delete an item and all associated barcodes."""
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    
    db.delete(item)
    db.commit()
    
    return {"deleted": True, "id": item_id}


# --- Move Item Shortcuts ---

@app.post("/api/items/{item_id}/to-inventory", response_model=schemas.ItemResponse)
async def move_to_inventory(item_id: int, db: Session = Depends(get_db)):
    """Move an item to inventory (it's now at home)."""
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    
    item.location = ItemLocation.INVENTORY
    db.commit()
    db.refresh(item)
    
    return item


@app.post("/api/items/{item_id}/to-grocery", response_model=schemas.ItemResponse)
async def move_to_grocery(item_id: int, db: Session = Depends(get_db)):
    """Move an item to grocery list (needs restocking)."""
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    
    item.location = ItemLocation.GROCERY_LIST
    db.commit()
    db.refresh(item)
    
    return item


@app.post("/api/items/{item_id}/remove", response_model=schemas.ItemResponse)
async def remove_from_lists(item_id: int, db: Session = Depends(get_db)):
    """Remove an item from both inventory and grocery list."""
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    
    item.location = ItemLocation.NEITHER
    db.commit()
    db.refresh(item)
    
    return item


# --- Home Assistant Friendly Endpoints ---

@app.get("/api/inventory", response_model=schemas.InventoryListResponse)
async def get_inventory(db: Session = Depends(get_db)):
    """
    Get all items currently in inventory.
    
    Returns a clean JSON response suitable for Home Assistant REST sensors.
    """
    items = db.query(Item).filter(
        Item.location == ItemLocation.INVENTORY
    ).order_by(Item.name).all()
    
    return schemas.InventoryListResponse(count=len(items), items=items)


@app.get("/api/grocery", response_model=schemas.GroceryListResponse)
async def get_grocery_list(db: Session = Depends(get_db)):
    """
    Get all items on the grocery list.
    
    Returns a clean JSON response suitable for Home Assistant REST sensors.
    """
    items = db.query(Item).filter(
        Item.location == ItemLocation.GROCERY_LIST
    ).order_by(Item.name).all()
    
    return schemas.GroceryListResponse(count=len(items), items=items)


# --- Search ---

@app.get("/api/search", response_model=list[schemas.ItemResponse])
async def search_items(q: str, db: Session = Depends(get_db)):
    """Search items by name (case-insensitive partial match)."""
    items = db.query(Item).filter(
        Item.name.ilike(f"%{q}%")
    ).order_by(Item.name).all()
    
    return items

