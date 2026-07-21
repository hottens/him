"""
Home Inventory Management API

A minimal, local-first application to track home inventory and grocery lists
using barcode scanning, with AI-powered recipe suggestions.
"""

from fastapi import FastAPI, HTTPException, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy.orm import Session
from typing import Optional
import os

from sqlalchemy import text

from .database import engine, get_db, Base
from .models import Item, Barcode, ItemLocation, Recipe, RecipeIngredient, RecipeStep
from . import schemas
from . import gemini_service
from . import enrichment
from . import product_data
from . import openfoodfacts_service
from .serializers import serialize_item, serialize_recipe, serialize_barcode, recipe_nutrition_summary

# Create database tables
Base.metadata.create_all(bind=engine)


def _add_column_if_missing(conn, table: str, column: str, col_type: str) -> None:
    result = conn.execute(text(f"PRAGMA table_info({table})"))
    columns = [row[1] for row in result.fetchall()]
    if column not in columns:
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))


def run_migrations():
    """Add new columns to existing tables if they don't exist."""
    with engine.connect() as conn:
        _add_column_if_missing(conn, "recipes", "source_url", "VARCHAR")
        _add_column_if_missing(conn, "items", "active_barcode_id", "INTEGER")
        for col, typ in [
            ("product_name", "VARCHAR"),
            ("brands", "VARCHAR"),
            ("keywords", "TEXT"),
            ("ingredients_en", "TEXT"),
            ("ingredients_hierarchy_en", "TEXT"),
            ("ingredients_nl", "TEXT"),
            ("ingredients_hierarchy_nl", "TEXT"),
            ("allergens", "TEXT"),
            ("nutriments", "TEXT"),
            ("energy_kcal_100g", "FLOAT"),
            ("energy_kcal_serving", "FLOAT"),
            ("last_scanned_at", "DATETIME"),
            ("product_fetched_at", "DATETIME"),
        ]:
            _add_column_if_missing(conn, "barcodes", col, typ)
        conn.commit()


run_migrations()

app = FastAPI(
    title="Home Inventory Manager",
    description="Local-first inventory and grocery list management with barcode scanning",
    version="2.1.0"
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
    return {
        "status": "healthy",
        "gemini_configured": gemini_service.is_configured(),
    }


# --- Settings ---

@app.get("/api/settings", response_model=schemas.SettingsResponse)
async def get_settings(db: Session = Depends(get_db)):
    settings = product_data.get_all_settings(db)
    return schemas.SettingsResponse(
        auto_fetch_products=settings.get("auto_fetch_products", "true").lower() in {"1", "true", "yes", "on"},
        translate_ingredients=settings.get("translate_ingredients", "true").lower() in {"1", "true", "yes", "on"},
        gemini_configured=gemini_service.is_configured(),
    )


@app.patch("/api/settings", response_model=schemas.SettingsResponse)
async def update_settings(update: schemas.SettingsUpdate, db: Session = Depends(get_db)):
    if update.auto_fetch_products is not None:
        product_data.set_setting(db, "auto_fetch_products", "true" if update.auto_fetch_products else "false")
    if update.translate_ingredients is not None:
        product_data.set_setting(db, "translate_ingredients", "true" if update.translate_ingredients else "false")
    db.commit()
    return await get_settings(db)


# --- Barcode Endpoints ---

@app.get("/api/barcode/{code}", response_model=schemas.BarcodeLookupResponse)
async def lookup_barcode(code: str, db: Session = Depends(get_db)):
    """
    Look up a barcode and return the associated item if found.

    Marks the barcode as last-scanned (active) and optionally enriches from Open Food Facts.
    """
    barcode = db.query(Barcode).filter(Barcode.code == code).first()

    if barcode:
        product_data.mark_barcode_scanned(db, barcode)
        if product_data.setting_is_true(db, "auto_fetch_products") and barcode.product_fetched_at is None:
            enrichment.enrich_barcode(db, barcode)
        db.commit()
        db.refresh(barcode.item)
        return schemas.BarcodeLookupResponse(
            found=True,
            barcode=code,
            item=serialize_item(barcode.item),
        )

    # Unknown barcode: ask Open Food Facts so the UI can pre-fill the name
    suggested_name = None
    suggested_brands = None
    try:
        product = openfoodfacts_service.fetch_product(code)
        if product:
            suggested_name = product.get("product_name") or None
            suggested_brands = product.get("brands") or None
    except Exception:
        pass

    return schemas.BarcodeLookupResponse(
        found=False,
        barcode=code,
        suggested_name=suggested_name,
        suggested_brands=suggested_brands,
    )


@app.post("/api/barcode/associate", response_model=schemas.ItemResponse)
async def associate_barcode(
    request: schemas.AssociateBarcodeRequest,
    db: Session = Depends(get_db)
):
    """Associate a barcode with an existing item."""
    existing = db.query(Barcode).filter(Barcode.code == request.barcode).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Barcode already associated with item: {existing.item.name}"
        )

    item = db.query(Item).filter(Item.id == request.item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    barcode = Barcode(code=request.barcode, item_id=item.id)
    db.add(barcode)
    db.flush()
    product_data.mark_barcode_scanned(db, barcode)
    if product_data.setting_is_true(db, "auto_fetch_products"):
        enrichment.enrich_barcode(db, barcode)
    db.commit()
    db.refresh(item)
    return serialize_item(item)


@app.post("/api/barcodes/reload-all", response_model=schemas.BarcodeReloadResult)
async def reload_all_barcodes(db: Session = Depends(get_db)):
    """Fetch Open Food Facts data for every barcode (settings → reload)."""
    barcodes = db.query(Barcode).all()
    updated = not_found = errors = 0
    for barcode in barcodes:
        result = enrichment.enrich_barcode(db, barcode)
        if not result["ok"]:
            errors += 1
        elif result["found"]:
            updated += 1
        else:
            not_found += 1
    db.commit()
    return schemas.BarcodeReloadResult(
        total=len(barcodes),
        updated=updated,
        not_found=not_found,
        errors=errors,
    )


@app.post("/api/barcodes/{barcode_id}/fetch", response_model=schemas.BarcodeResponse)
async def fetch_barcode_product(barcode_id: int, db: Session = Depends(get_db)):
    """Fetch/refresh Open Food Facts data for a single barcode."""
    barcode = db.query(Barcode).filter(Barcode.id == barcode_id).first()
    if not barcode:
        raise HTTPException(status_code=404, detail="Barcode not found")
    result = enrichment.enrich_barcode(db, barcode)
    if not result["ok"]:
        raise HTTPException(status_code=502, detail=result.get("error") or "Fetch failed")
    db.commit()
    db.refresh(barcode)
    active_id = barcode.item.active_barcode_id if barcode.item else None
    return serialize_barcode(barcode, active_id)


# --- Item Endpoints ---

@app.get("/api/items", response_model=list[schemas.ItemResponse])
async def list_items(
    location: Optional[ItemLocation] = None,
    db: Session = Depends(get_db)
):
    """List all items, optionally filtered by location."""
    query = db.query(Item)
    if location:
        query = query.filter(Item.location == location)
    return [serialize_item(item) for item in query.order_by(Item.name).all()]


@app.post("/api/items", response_model=schemas.ItemResponse)
async def create_item(item: schemas.ItemCreate, db: Session = Depends(get_db)):
    """Create a new item, optionally with an associated barcode."""
    existing = db.query(Item).filter(Item.name == item.name).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Item with name '{item.name}' already exists"
        )

    if item.barcode:
        existing_barcode = db.query(Barcode).filter(Barcode.code == item.barcode).first()
        if existing_barcode:
            raise HTTPException(
                status_code=400,
                detail=f"Barcode already associated with item: {existing_barcode.item.name}"
            )

    db_item = Item(name=item.name, location=item.location)
    db.add(db_item)
    db.flush()

    if item.barcode:
        barcode = Barcode(code=item.barcode, item_id=db_item.id)
        db.add(barcode)
        db.flush()
        product_data.mark_barcode_scanned(db, barcode)
        if product_data.setting_is_true(db, "auto_fetch_products"):
            enrichment.enrich_barcode(db, barcode)

    db.commit()
    db.refresh(db_item)
    return serialize_item(db_item)


@app.get("/api/items/{item_id}", response_model=schemas.ItemResponse)
async def get_item(item_id: int, db: Session = Depends(get_db)):
    """Get a specific item by ID."""
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return serialize_item(item)


@app.patch("/api/items/{item_id}", response_model=schemas.ItemResponse)
async def update_item(
    item_id: int,
    update: schemas.ItemUpdate,
    db: Session = Depends(get_db)
):
    """Update an item's name, location, or active barcode."""
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    if update.name is not None:
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

    if update.active_barcode_id is not None:
        barcode = db.query(Barcode).filter(
            Barcode.id == update.active_barcode_id,
            Barcode.item_id == item.id,
        ).first()
        if not barcode:
            raise HTTPException(status_code=400, detail="Barcode does not belong to this item")
        item.active_barcode_id = barcode.id

    db.commit()
    db.refresh(item)
    return serialize_item(item)


@app.post("/api/items/{item_id}/active-barcode", response_model=schemas.ItemResponse)
async def set_active_barcode(
    item_id: int,
    request: schemas.SetActiveBarcodeRequest,
    db: Session = Depends(get_db),
):
    """Manually set which barcode is active for an item."""
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    barcode = db.query(Barcode).filter(
        Barcode.id == request.barcode_id,
        Barcode.item_id == item.id,
    ).first()
    if not barcode:
        raise HTTPException(status_code=400, detail="Barcode does not belong to this item")
    item.active_barcode_id = barcode.id
    db.commit()
    db.refresh(item)
    return serialize_item(item)


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
    return serialize_item(item)


@app.post("/api/items/{item_id}/to-grocery", response_model=schemas.ItemResponse)
async def move_to_grocery(item_id: int, db: Session = Depends(get_db)):
    """Move an item to grocery list (needs restocking)."""
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    item.location = ItemLocation.GROCERY_LIST
    db.commit()
    db.refresh(item)
    return serialize_item(item)


@app.post("/api/items/{item_id}/remove", response_model=schemas.ItemResponse)
async def remove_from_lists(item_id: int, db: Session = Depends(get_db)):
    """Remove an item from both inventory and grocery list (set to neither)."""
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    item.location = ItemLocation.NEITHER
    db.commit()
    db.refresh(item)
    return serialize_item(item)


# --- Home Assistant Friendly Endpoints ---

@app.get("/api/inventory", response_model=schemas.InventoryListResponse)
async def get_inventory(db: Session = Depends(get_db)):
    """Get all items currently in inventory."""
    items = db.query(Item).filter(
        Item.location == ItemLocation.INVENTORY
    ).order_by(Item.name).all()
    return schemas.InventoryListResponse(
        count=len(items),
        items=[serialize_item(i) for i in items],
    )


@app.get("/api/grocery", response_model=schemas.GroceryListResponse)
async def get_grocery_list(db: Session = Depends(get_db)):
    """Get all items on the grocery list."""
    items = db.query(Item).filter(
        Item.location == ItemLocation.GROCERY_LIST
    ).order_by(Item.name).all()
    return schemas.GroceryListResponse(
        count=len(items),
        items=[serialize_item(i) for i in items],
    )


# --- Search ---

@app.get("/api/search", response_model=list[schemas.ItemResponse])
async def search_items(q: str, db: Session = Depends(get_db)):
    """Search items by name (case-insensitive partial match)."""
    items = db.query(Item).filter(
        Item.name.ilike(f"%{q}%")
    ).order_by(Item.name).all()
    return [serialize_item(i) for i in items]


# --- Recipe Endpoints ---

@app.get("/api/recipes", response_model=schemas.RecipeListResponse)
async def list_recipes(
    favorites_only: bool = False,
    db: Session = Depends(get_db)
):
    """List all saved recipes."""
    query = db.query(Recipe)
    if favorites_only:
        query = query.filter(Recipe.is_favorite.is_(True))
    recipes = query.order_by(Recipe.created_at.desc()).all()
    return schemas.RecipeListResponse(
        count=len(recipes),
        recipes=[serialize_recipe(r) for r in recipes],
    )


@app.post("/api/recipes", response_model=schemas.RecipeResponse)
async def create_recipe(recipe: schemas.RecipeCreate, db: Session = Depends(get_db)):
    """Create a new recipe."""
    db_recipe = Recipe(
        name=recipe.name,
        description=recipe.description,
        servings=recipe.servings,
        prep_time_minutes=recipe.prep_time_minutes,
        cook_time_minutes=recipe.cook_time_minutes,
        source_url=recipe.source_url,
        is_favorite=recipe.is_favorite
    )
    db.add(db_recipe)
    db.flush()

    for ing in recipe.ingredients:
        db.add(RecipeIngredient(
            recipe_id=db_recipe.id,
            name=ing.name,
            amount=ing.amount,
            unit=ing.unit,
            notes=ing.notes,
            item_id=ing.item_id
        ))

    for step in recipe.steps:
        db.add(RecipeStep(
            recipe_id=db_recipe.id,
            step_number=step.step_number,
            instruction=step.instruction
        ))

    db.commit()
    db.refresh(db_recipe)
    return serialize_recipe(db_recipe)


@app.get("/api/recipes/{recipe_id}", response_model=schemas.RecipeResponse)
async def get_recipe(recipe_id: int, db: Session = Depends(get_db)):
    """Get a single recipe by ID."""
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found")
    return serialize_recipe(recipe)


@app.patch("/api/recipes/{recipe_id}", response_model=schemas.RecipeResponse)
async def update_recipe(
    recipe_id: int,
    update: schemas.RecipeUpdate,
    db: Session = Depends(get_db)
):
    """Update a recipe's metadata (not ingredients/steps)."""
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found")

    for field, value in update.model_dump(exclude_unset=True).items():
        setattr(recipe, field, value)

    db.commit()
    db.refresh(recipe)
    return serialize_recipe(recipe)


@app.put("/api/recipes/{recipe_id}", response_model=schemas.RecipeResponse)
async def update_recipe_full(
    recipe_id: int,
    update: schemas.RecipeFullUpdate,
    db: Session = Depends(get_db)
):
    """Update a recipe including ingredients and steps."""
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found")

    update_data = update.model_dump(exclude_unset=True)

    for field in ['name', 'description', 'servings', 'prep_time_minutes', 'cook_time_minutes', 'is_favorite', 'source_url']:
        if field in update_data and update_data[field] is not None:
            setattr(recipe, field, update_data[field])

    if update.ingredients is not None:
        db.query(RecipeIngredient).filter(RecipeIngredient.recipe_id == recipe_id).delete()
        for ing in update.ingredients:
            db.add(RecipeIngredient(
                recipe_id=recipe_id,
                name=ing.name,
                amount=ing.amount,
                unit=ing.unit,
                notes=ing.notes,
                item_id=ing.item_id
            ))

    if update.steps is not None:
        db.query(RecipeStep).filter(RecipeStep.recipe_id == recipe_id).delete()
        for step in update.steps:
            db.add(RecipeStep(
                recipe_id=recipe_id,
                step_number=step.step_number,
                instruction=step.instruction
            ))

    db.commit()
    db.refresh(recipe)
    return serialize_recipe(recipe)


@app.delete("/api/recipes/{recipe_id}")
async def delete_recipe(recipe_id: int, db: Session = Depends(get_db)):
    """Delete a recipe."""
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found")

    db.delete(recipe)
    db.commit()
    return {"deleted": True, "id": recipe_id}


@app.post("/api/recipes/{recipe_id}/favorite", response_model=schemas.RecipeResponse)
async def toggle_favorite(recipe_id: int, db: Session = Depends(get_db)):
    """Toggle a recipe's favorite status."""
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found")

    recipe.is_favorite = not recipe.is_favorite
    db.commit()
    db.refresh(recipe)
    return serialize_recipe(recipe)


# --- Gemini AI Endpoints ---

class RecipeSuggestionRequest(schemas.BaseModel):
    """Request body for recipe suggestions."""
    query: Optional[str] = None  # e.g., "soup recipes", "quick dinner", "vegetarian"


@app.post("/api/ai/recipe-suggestions", response_model=schemas.GeminiRecipeSuggestionsResponse)
async def get_recipe_suggestions(
    request: Optional[RecipeSuggestionRequest] = None,
    db: Session = Depends(get_db)
):
    """
    Get AI-powered recipe suggestions based on current inventory.
    
    Optionally provide a query for guided suggestions (e.g., "soup", "quick meals").
    Requires GEMINI_API_KEY environment variable to be set.
    """
    if not gemini_service.is_configured():
        raise HTTPException(
            status_code=503,
            detail="Gemini API is not configured. Set GEMINI_API_KEY environment variable."
        )
    
    # Get inventory items
    inventory_items = db.query(Item).filter(
        Item.location == ItemLocation.INVENTORY
    ).all()
    item_names = [item.name for item in inventory_items]
    
    if not item_names:
        raise HTTPException(
            status_code=400,
            detail="No items in inventory. Add some items first."
        )
    
    # Extract query from request
    query = request.query if request else None
    
    # Get suggestions from Gemini
    result = gemini_service.generate_recipe_suggestions(item_names, query)
    
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    
    return result


@app.post("/api/ai/grocery-suggestions", response_model=schemas.GeminiGrocerySuggestionsResponse)
async def get_grocery_suggestions(
    preferences: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Get AI-powered grocery suggestions based on inventory and favorite recipes.
    
    Requires GEMINI_API_KEY environment variable to be set.
    """
    if not gemini_service.is_configured():
        raise HTTPException(
            status_code=503,
            detail="Gemini API is not configured. Set GEMINI_API_KEY environment variable."
        )
    
    # Get inventory items
    inventory_items = db.query(Item).filter(
        Item.location == ItemLocation.INVENTORY
    ).all()
    item_names = [item.name for item in inventory_items]
    
    # Get favorite recipes with their ingredients
    favorite_recipes = db.query(Recipe).filter(Recipe.is_favorite.is_(True)).all()
    recipes_data = []
    for recipe in favorite_recipes:
        recipes_data.append({
            "name": recipe.name,
            "ingredients": [
                {"name": ing.name, "amount": ing.amount, "unit": ing.unit}
                for ing in recipe.ingredients
            ]
        })
    
    # Get suggestions from Gemini
    result = gemini_service.generate_grocery_suggestions(item_names, recipes_data, preferences)
    
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    
    return result



# --- Beautiful Recipe View Page ---

@app.get("/recipe/{recipe_id}", response_class=HTMLResponse, include_in_schema=False)
async def view_recipe_page(recipe_id: int, db: Session = Depends(get_db)):
    """Serve a beautiful, user-friendly recipe viewing page."""
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found")
    
    # Get all items for dropdown (sorted by name)
    all_items = db.query(Item).order_by(Item.name).all()
    # Get inventory item IDs for availability check
    inventory_item_ids = {item.id for item in all_items if item.location == ItemLocation.INVENTORY}
    inventory_names = {item.name.lower() for item in all_items if item.location == ItemLocation.INVENTORY}
    
    # Sort steps by step_number
    sorted_steps = sorted(recipe.steps, key=lambda s: s.step_number)
    
    # Build ingredient data for JSON and HTML
    import json
    ingredient_data = []
    ingredients_html = ""
    missing_ingredients = []
    
    for ing in recipe.ingredients:
        amount_str = f"{ing.amount} " if ing.amount else ""
        unit_str = f"{ing.unit} " if ing.unit else ""
        notes_str = f" <span class='notes'>({ing.notes})</span>" if ing.notes else ""
        
        # Check availability: prefer item_id match, fallback to name match
        if ing.item_id and ing.matched_item:
            is_available = ing.item_id in inventory_item_ids
            matched_name = ing.matched_item.name
        else:
            is_available = ing.name.lower() in inventory_names
            matched_name = None
        
        status_icon = "✓" if is_available else "✗"
        status_class = "available" if is_available else "missing"
        
        # Show matched item if different from ingredient name
        match_info = ""
        if matched_name and matched_name.lower() != ing.name.lower():
            match_info = f" <span class='matched-to'>→ {matched_name}</span>"
        
        if not is_available:
            missing_ingredients.append({
                "name": ing.name,
                "item_id": ing.item_id
            })
        
        ingredients_html += f"""<li class='{status_class}' data-ing-id='{ing.id}'>
            <span class='status-icon'>{status_icon}</span>
            <div class='ingredient-content' onclick='openIngredientDropdown({ing.id})'>
                {amount_str}{unit_str}{ing.name}{notes_str}{match_info}
            </div>
            <div class='ingredient-dropdown' id='dropdown-{ing.id}'></div>
        </li>"""
        
        # Store ingredient data for JS
        ingredient_data.append({
            "id": ing.id,
            "name": ing.name,
            "amount": ing.amount or "",
            "unit": ing.unit or "",
            "notes": ing.notes or "",
            "item_id": ing.item_id
        })
    
    # Generate steps HTML
    steps_html = ""
    for step in sorted_steps:
        steps_html += f"<li>{step.instruction}</li>"
    
    # Calculate total time
    total_time = (recipe.prep_time_minutes or 0) + (recipe.cook_time_minutes or 0)
    time_str = f"{total_time} min" if total_time else "—"
    
    # JSON data for JavaScript
    missing_json = json.dumps(missing_ingredients)
    ingredients_json = json.dumps(ingredient_data)
    items_json = json.dumps([
        {"id": item.id, "name": item.name, "location": item.location.value}
        for item in all_items
    ])
    
    # Availability summary
    total_ingredients = len(recipe.ingredients)
    available_count = total_ingredients - len(missing_ingredients)
    
    if total_ingredients == 0:
        availability_html = ""
    elif len(missing_ingredients) == 0:
        availability_html = f'<div class="availability-banner complete">✓ All {total_ingredients} ingredients in stock!</div>'
    else:
        availability_html = f'''
        <div class="availability-banner partial">
            <span>◐ {available_count}/{total_ingredients} ingredients in stock</span>
            <button class="add-missing-btn" onclick="addMissingToGrocery()">
                🛒 Add {len(missing_ingredients)} missing to grocery
            </button>
        </div>
        '''

    nutrition = recipe_nutrition_summary(recipe)
    totals = nutrition.totals
    nutrition_rows = []
    labels = [
        ("energy_kcal", "Energy", "kcal"),
        ("proteins", "Protein", "g"),
        ("carbohydrates", "Carbs", "g"),
        ("fat", "Fat", "g"),
        ("saturated-fat", "Saturated fat", "g"),
        ("sugars", "Sugars", "g"),
        ("fiber", "Fiber", "g"),
        ("salt", "Salt", "g"),
    ]
    for key, label, unit in labels:
        if key in totals:
            nutrition_rows.append(
                f"<div class='nutrition-row'><span>{label}</span><span>{totals[key]} {unit}</span></div>"
            )
    allergens_html = ""
    if nutrition.allergens:
        chips = "".join(f"<span class='allergen-chip'>{a}</span>" for a in nutrition.allergens)
        allergens_html = f"<div class='allergens'><div class='allergens-label'>Allergens</div><div class='allergen-chips'>{chips}</div></div>"
    if nutrition_rows or allergens_html:
        skipped_note = ""
        if nutrition.ingredients_skipped:
            skipped_note = (
                f"<p class='nutrition-note'>Geen voedingswaarde meegenomen voor: "
                f"{', '.join(nutrition.ingredients_skipped)}</p>"
            )
        nutrition_html = f"""
        <h2>Nutrition</h2>
        <p class="nutrition-note">Opgeteld uit gekoppelde producten (actieve barcode), waar hoeveelheid in gram beschikbaar is.</p>
        <div class="nutrition-box">
            {''.join(nutrition_rows) if nutrition_rows else '<p class="nutrition-note">Nog geen kcal/macros beschikbaar.</p>'}
        </div>
        {allergens_html}
        {skipped_note}
        """
    else:
        nutrition_html = ""

    html = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{recipe.name}</title>
    <link href="https://fonts.googleapis.com/css2?family=Crimson+Pro:wght@400;600&family=Inter:wght@400;500&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg: #faf9f7;
            --text: #1a1a1a;
            --text-muted: #666;
            --accent: #c45c26;
            --accent-green: #3fb950;
            --accent-red: #f85149;
            --accent-blue: #58a6ff;
            --border: #e5e3df;
        }}
        
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        
        body {{
            font-family: 'Inter', sans-serif;
            background: var(--bg);
            color: var(--text);
            line-height: 1.7;
            padding: 2rem 1rem;
            max-width: 680px;
            margin: 0 auto;
            padding-bottom: 5rem;
        }}
        
        .header-row {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 2rem;
        }}
        
        .back-link {{
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
            color: var(--text-muted);
            text-decoration: none;
            font-size: 0.875rem;
        }}
        
        .back-link:hover {{ color: var(--accent); }}
        
        .edit-btn {{
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
            padding: 0.5rem 1rem;
            background: #fff;
            border: 1px solid var(--border);
            border-radius: 8px;
            color: var(--text);
            font-size: 0.875rem;
            cursor: pointer;
            transition: all 0.2s;
        }}
        
        .edit-btn:hover {{
            border-color: var(--accent);
            color: var(--accent);
        }}
        
        .edit-btn.active {{
            background: var(--accent);
            border-color: var(--accent);
            color: #fff;
        }}
        
        h1 {{
            font-family: 'Crimson Pro', serif;
            font-size: 2.5rem;
            font-weight: 600;
            margin-bottom: 0.5rem;
            line-height: 1.2;
        }}
        
        .description {{
            color: var(--text-muted);
            font-size: 1.1rem;
            margin-bottom: 1.5rem;
        }}
        
        .meta {{
            display: flex;
            gap: 2rem;
            padding: 1rem 0;
            border-top: 1px solid var(--border);
            border-bottom: 1px solid var(--border);
            margin-bottom: 2rem;
        }}
        
        .meta-item {{
            display: flex;
            flex-direction: column;
        }}
        
        .meta-label {{
            font-size: 0.75rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: var(--text-muted);
        }}
        
        .meta-value {{
            font-size: 1.125rem;
            font-weight: 500;
        }}
        
        h2 {{
            font-family: 'Crimson Pro', serif;
            font-size: 1.5rem;
            font-weight: 600;
            margin: 2rem 0 1rem;
            color: var(--accent);
        }}
        
        .availability-banner {{
            padding: 0.75rem 1rem;
            border-radius: 8px;
            margin-bottom: 1rem;
            display: flex;
            align-items: center;
            justify-content: space-between;
            flex-wrap: wrap;
            gap: 0.5rem;
        }}
        
        .availability-banner.complete {{
            background: rgba(63, 185, 80, 0.15);
            color: var(--accent-green);
        }}
        
        .availability-banner.partial {{
            background: rgba(210, 153, 34, 0.15);
            color: #bf8a1f;
        }}
        
        .add-missing-btn {{
            background: var(--accent);
            color: #fff;
            border: none;
            padding: 0.5rem 1rem;
            border-radius: 6px;
            font-size: 0.85rem;
            cursor: pointer;
            transition: all 0.2s;
        }}
        
        .add-missing-btn:hover {{
            opacity: 0.9;
            transform: scale(1.02);
        }}
        
        .add-missing-btn:disabled {{
            opacity: 0.5;
            cursor: not-allowed;
        }}
        
        .ingredients {{
            background: #fff;
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 1.5rem;
        }}
        
        .ingredients ul {{
            list-style: none;
        }}
        
        .ingredients li {{
            padding: 0.5rem 0;
            border-bottom: 1px solid var(--border);
            display: flex;
            align-items: flex-start;
            gap: 0.5rem;
            position: relative;
        }}
        
        .ingredients li:last-child {{ border-bottom: none; }}
        
        .ingredients li.available .status-icon {{ color: var(--accent-green); }}
        .ingredients li.missing .status-icon {{ color: var(--accent-red); }}
        .ingredients li.missing {{ color: var(--text-muted); }}
        
        .matched-to {{
            color: var(--text-muted);
            font-size: 0.85rem;
            font-style: italic;
        }}

        .nutrition-box {{
            background: var(--card);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 1rem 1.25rem;
            margin-bottom: 1rem;
        }}
        .nutrition-row {{
            display: flex;
            justify-content: space-between;
            padding: 0.4rem 0;
            border-bottom: 1px solid var(--border);
            font-size: 0.95rem;
        }}
        .nutrition-row:last-child {{ border-bottom: none; }}
        .nutrition-note {{
            font-size: 0.8rem;
            color: var(--text-muted);
            margin: 0.5rem 0 1rem;
        }}
        .allergens {{ margin: 1rem 0; }}
        .allergens-label {{
            font-size: 0.8rem;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 0.5rem;
        }}
        .allergen-chips {{ display: flex; flex-wrap: wrap; gap: 0.4rem; }}
        .allergen-chip {{
            background: #fde8e4;
            color: #9a3412;
            padding: 0.25rem 0.6rem;
            border-radius: 999px;
            font-size: 0.8rem;
        }}
        
        /* Clickable ingredient styling */
        .ingredient-content {{
            flex: 1;
            cursor: pointer;
            padding: 0.25rem 0.5rem;
            margin: -0.25rem 0;
            border-radius: 6px;
            transition: background 0.15s;
            position: relative;
        }}
        
        .ingredient-content:hover {{
            background: rgba(196, 92, 38, 0.08);
        }}
        
        .ingredient-content::after {{
            content: '✎';
            position: absolute;
            right: 0.5rem;
            top: 50%;
            transform: translateY(-50%);
            opacity: 0;
            font-size: 0.8rem;
            color: var(--text-muted);
            transition: opacity 0.15s;
        }}
        
        .ingredient-content:hover::after {{
            opacity: 1;
        }}
        
        /* Ingredient dropdown */
        .ingredient-dropdown {{
            position: absolute;
            top: 100%;
            left: 0;
            right: 0;
            background: #fff;
            border: 1px solid var(--border);
            border-radius: 8px;
            box-shadow: 0 8px 24px rgba(0,0,0,0.15);
            z-index: 100;
            margin-top: 4px;
            display: none;
        }}
        
        .ingredient-dropdown.active {{
            display: block;
        }}
        
        .dropdown-search {{
            padding: 0.75rem;
            border-bottom: 1px solid var(--border);
        }}
        
        .dropdown-search input {{
            width: 100%;
            padding: 0.5rem 0.75rem;
            border: 1px solid var(--border);
            border-radius: 6px;
            font-size: 0.9rem;
            outline: none;
        }}
        
        .dropdown-search input:focus {{
            border-color: var(--accent);
        }}
        
        .dropdown-items {{
            max-height: 200px;
            overflow-y: auto;
        }}
        
        .dropdown-item {{
            padding: 0.6rem 0.75rem;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 0.5rem;
            transition: background 0.1s;
        }}
        
        .dropdown-item:hover {{
            background: rgba(196, 92, 38, 0.08);
        }}
        
        .dropdown-item.selected {{
            background: rgba(196, 92, 38, 0.15);
        }}
        
        .dropdown-item .item-icon {{
            font-size: 0.9rem;
        }}
        
        .dropdown-item .item-name {{
            flex: 1;
        }}
        
        .dropdown-item.no-match {{
            color: var(--text-muted);
            font-style: italic;
        }}
        
        .dropdown-footer {{
            padding: 0.75rem;
            border-top: 1px solid var(--border);
            display: flex;
            gap: 0.5rem;
        }}
        
        .dropdown-footer button {{
            flex: 1;
            padding: 0.5rem;
            border-radius: 6px;
            font-size: 0.85rem;
            cursor: pointer;
            transition: all 0.15s;
        }}
        
        .btn-add-grocery {{
            background: var(--accent);
            color: #fff;
            border: none;
        }}
        
        .btn-add-grocery:hover {{
            opacity: 0.9;
        }}
        
        .btn-clear-match {{
            background: transparent;
            border: 1px solid var(--border);
            color: var(--text-muted);
        }}
        
        .btn-clear-match:hover {{
            border-color: var(--accent-red);
            color: var(--accent-red);
        }}
        
        .ingredients .notes {{
            color: var(--text-muted);
            font-size: 0.9rem;
        }}
        
        .steps ol {{
            padding-left: 1.5rem;
        }}
        
        .steps li {{
            padding: 0.75rem 0;
            padding-left: 0.5rem;
        }}
        
        .steps li::marker {{
            color: var(--accent);
            font-weight: 600;
        }}
        
        .favorite {{
            position: fixed;
            bottom: 2rem;
            right: 2rem;
            width: 56px;
            height: 56px;
            border-radius: 50%;
            background: {'var(--accent)' if recipe.is_favorite else '#fff'};
            color: {'#fff' if recipe.is_favorite else 'var(--accent)'};
            border: 2px solid var(--accent);
            font-size: 1.5rem;
            cursor: pointer;
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
            transition: all 0.2s;
        }}
        
        .favorite:hover {{
            transform: scale(1.1);
        }}
        
        .toast {{
            position: fixed;
            bottom: 6rem;
            left: 50%;
            transform: translateX(-50%);
            background: #333;
            color: #fff;
            padding: 0.75rem 1.5rem;
            border-radius: 8px;
            font-size: 0.9rem;
            display: none;
            z-index: 1000;
        }}
        
        .toast.show {{
            display: block;
            animation: fadeInUp 0.3s ease-out;
        }}
        
        @keyframes fadeInUp {{
            from {{ opacity: 0; transform: translate(-50%, 1rem); }}
            to {{ opacity: 1; transform: translate(-50%, 0); }}
        }}
        
        /* Edit Mode Styles */
        .edit-form-group {{
            margin-bottom: 1rem;
        }}
        
        .edit-label {{
            display: block;
            font-size: 0.8rem;
            color: var(--text-muted);
            margin-bottom: 0.25rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }}
        
        .edit-input, .edit-textarea {{
            width: 100%;
            padding: 0.75rem;
            font-size: 1rem;
            font-family: inherit;
            border: 1px solid var(--border);
            border-radius: 8px;
            background: #fff;
            color: var(--text);
            transition: border-color 0.2s;
        }}
        
        .edit-input:focus, .edit-textarea:focus {{
            outline: none;
            border-color: var(--accent);
        }}
        
        .edit-textarea {{
            min-height: 80px;
            resize: vertical;
        }}
        
        .edit-input-small {{
            width: 100px;
            padding: 0.5rem;
            font-size: 0.9rem;
        }}
        
        .edit-row {{
            display: flex;
            gap: 1rem;
            flex-wrap: wrap;
        }}
        
        .edit-row .edit-form-group {{
            flex: 1;
            min-width: 80px;
        }}
        
        .edit-section {{
            background: #fff;
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 1.5rem;
            margin-bottom: 1.5rem;
        }}
        
        .edit-section-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 1rem;
        }}
        
        .edit-section-title {{
            font-family: 'Crimson Pro', serif;
            font-size: 1.25rem;
            font-weight: 600;
            color: var(--accent);
        }}
        
        .add-btn {{
            display: inline-flex;
            align-items: center;
            gap: 0.25rem;
            padding: 0.4rem 0.75rem;
            background: var(--accent);
            color: #fff;
            border: none;
            border-radius: 6px;
            font-size: 0.8rem;
            cursor: pointer;
            transition: opacity 0.2s;
        }}
        
        .add-btn:hover {{
            opacity: 0.9;
        }}
        
        .edit-item {{
            display: flex;
            gap: 0.5rem;
            align-items: flex-start;
            padding: 0.75rem;
            background: var(--bg);
            border-radius: 8px;
            margin-bottom: 0.5rem;
        }}
        
        .edit-item-content {{
            flex: 1;
            display: flex;
            flex-direction: column;
            gap: 0.5rem;
        }}
        
        .edit-item-row {{
            display: flex;
            gap: 0.5rem;
        }}
        
        .edit-item-row input {{
            flex: 1;
            padding: 0.5rem;
            font-size: 0.9rem;
            border: 1px solid var(--border);
            border-radius: 6px;
            background: #fff;
        }}
        
        .edit-item-row input:focus {{
            outline: none;
            border-color: var(--accent);
        }}
        
        .edit-item-row input.amount-input {{ max-width: 70px; }}
        .edit-item-row input.unit-input {{ max-width: 80px; }}
        
        .remove-btn {{
            padding: 0.5rem;
            background: transparent;
            border: 1px solid var(--border);
            border-radius: 6px;
            color: var(--text-muted);
            cursor: pointer;
            transition: all 0.2s;
        }}
        
        .remove-btn:hover {{
            border-color: var(--accent-red);
            color: var(--accent-red);
        }}
        
        .step-number {{
            display: flex;
            align-items: center;
            justify-content: center;
            width: 28px;
            height: 28px;
            background: var(--accent);
            color: #fff;
            border-radius: 50%;
            font-size: 0.85rem;
            font-weight: 600;
            flex-shrink: 0;
        }}
        
        .step-textarea {{
            flex: 1;
            padding: 0.5rem;
            font-size: 0.9rem;
            font-family: inherit;
            border: 1px solid var(--border);
            border-radius: 6px;
            background: #fff;
            min-height: 60px;
            resize: vertical;
        }}
        
        .step-textarea:focus {{
            outline: none;
            border-color: var(--accent);
        }}
        
        .save-bar {{
            position: fixed;
            bottom: 0;
            left: 0;
            right: 0;
            background: #fff;
            border-top: 1px solid var(--border);
            padding: 1rem;
            display: flex;
            justify-content: center;
            gap: 1rem;
            z-index: 200;
            box-shadow: 0 -4px 12px rgba(0,0,0,0.1);
        }}
        
        .save-bar button {{
            padding: 0.75rem 2rem;
            font-size: 1rem;
            border-radius: 8px;
            cursor: pointer;
            transition: all 0.2s;
        }}
        
        .cancel-btn {{
            background: #fff;
            border: 1px solid var(--border);
            color: var(--text);
        }}
        
        .cancel-btn:hover {{
            border-color: var(--accent-red);
            color: var(--accent-red);
        }}
        
        .save-btn {{
            background: var(--accent-green);
            border: none;
            color: #fff;
        }}
        
        .save-btn:hover {{
            opacity: 0.9;
        }}
        
        .save-btn:disabled {{
            opacity: 0.5;
            cursor: not-allowed;
        }}
        
        /* View mode hidden when editing */
        .view-mode {{ display: block; }}
        .edit-mode {{ display: none; }}
        
        body.editing .view-mode {{ display: none; }}
        body.editing .edit-mode {{ display: block; }}
        body.editing .favorite {{ display: none; }}
        
        .delete-recipe-btn {{
            background: transparent;
            border: 1px solid var(--accent-red);
            color: var(--accent-red);
            padding: 0.5rem 1rem;
            border-radius: 6px;
            font-size: 0.85rem;
            cursor: pointer;
            transition: all 0.2s;
            margin-top: 1rem;
        }}
        
        .delete-recipe-btn:hover {{
            background: var(--accent-red);
            color: #fff;
        }}
        
        .source-link {{
            margin-top: 2rem;
            padding: 1rem;
            background: #fff;
            border: 1px solid var(--border);
            border-radius: 8px;
            text-align: center;
        }}
        
        .source-link a {{
            color: var(--accent);
            text-decoration: none;
            font-size: 0.9rem;
            font-weight: 500;
            transition: opacity 0.2s;
        }}
        
        .source-link a:hover {{
            opacity: 0.8;
            text-decoration: underline;
        }}
        
        @media (max-width: 480px) {{
            h1 {{ font-size: 2rem; }}
            .meta {{ gap: 1rem; flex-wrap: wrap; }}
            .availability-banner {{ flex-direction: column; align-items: stretch; text-align: center; }}
            .edit-row {{ flex-direction: column; }}
            .edit-item-row {{ flex-wrap: wrap; }}
        }}
    </style>
</head>
<body>
    <div class="header-row">
        <a href="/" class="back-link">← Back to Inventory</a>
        <button class="edit-btn" onclick="toggleEditMode()" id="edit-toggle-btn">
            ✏️ Edit
        </button>
    </div>
    
    <!-- VIEW MODE -->
    <div class="view-mode">
        <h1>{recipe.name}</h1>
        
        {'<p class="description">' + recipe.description + '</p>' if recipe.description else ''}
        
        <div class="meta">
            <div class="meta-item">
                <span class="meta-label">Servings</span>
                <span class="meta-value">{recipe.servings}</span>
            </div>
            <div class="meta-item">
                <span class="meta-label">Prep</span>
                <span class="meta-value">{recipe.prep_time_minutes or '—'} min</span>
            </div>
            <div class="meta-item">
                <span class="meta-label">Cook</span>
                <span class="meta-value">{recipe.cook_time_minutes or '—'} min</span>
            </div>
            <div class="meta-item">
                <span class="meta-label">Total</span>
                <span class="meta-value">{time_str}</span>
            </div>
        </div>
        
        <h2>Ingredients</h2>
        <p style="font-size: 0.8rem; color: var(--text-muted); margin-bottom: 0.75rem;">Click an ingredient to link it to an inventory item</p>
        {availability_html}
        <div class="ingredients">
            <ul>
                {ingredients_html}
            </ul>
        </div>

        {nutrition_html}
        
        <h2>Instructions</h2>
        <div class="steps">
            <ol>
                {steps_html}
            </ol>
        </div>
        
        {'<div class="source-link"><a href="' + recipe.source_url + '" target="_blank" rel="noopener noreferrer">📎 View original recipe →</a></div>' if recipe.source_url else ''}
    </div>
    
    <!-- EDIT MODE -->
    <div class="edit-mode">
        <div class="edit-section">
            <div class="edit-section-title">Recipe Details</div>
            
            <div class="edit-form-group">
                <label class="edit-label">Name</label>
                <input type="text" class="edit-input" id="edit-name" value="{recipe.name}">
            </div>
            
            <div class="edit-form-group">
                <label class="edit-label">Description</label>
                <textarea class="edit-textarea" id="edit-description">{recipe.description or ''}</textarea>
            </div>
            
            <div class="edit-row">
                <div class="edit-form-group">
                    <label class="edit-label">Servings</label>
                    <input type="number" class="edit-input edit-input-small" id="edit-servings" value="{recipe.servings}">
                </div>
                <div class="edit-form-group">
                    <label class="edit-label">Prep (min)</label>
                    <input type="number" class="edit-input edit-input-small" id="edit-prep" value="{recipe.prep_time_minutes or ''}">
                </div>
                <div class="edit-form-group">
                    <label class="edit-label">Cook (min)</label>
                    <input type="number" class="edit-input edit-input-small" id="edit-cook" value="{recipe.cook_time_minutes or ''}">
                </div>
            </div>
        </div>
        
        <div class="edit-section">
            <div class="edit-section-header">
                <div class="edit-section-title">Ingredients</div>
                <button class="add-btn" onclick="addIngredient()">+ Add</button>
            </div>
            <div id="edit-ingredients-list"></div>
        </div>
        
        <div class="edit-section">
            <div class="edit-section-header">
                <div class="edit-section-title">Instructions</div>
                <button class="add-btn" onclick="addStep()">+ Add Step</button>
            </div>
            <div id="edit-steps-list"></div>
        </div>
        
        <button class="delete-recipe-btn" onclick="deleteRecipe()">🗑 Delete Recipe</button>
        
        <div class="save-bar">
            <button class="cancel-btn" onclick="cancelEdit()">Cancel</button>
            <button class="save-btn" onclick="saveRecipe()" id="save-btn">Save Changes</button>
        </div>
    </div>
    
    <button class="favorite view-mode" onclick="toggleFavorite()" title="{'Remove from favorites' if recipe.is_favorite else 'Add to favorites'}">
        {'★' if recipe.is_favorite else '☆'}
    </button>
    
    <div class="toast" id="toast"></div>
    
    <script>
        const missingIngredients = {missing_json};
        const ingredientData = {ingredients_json};
        const allItems = {items_json};
        const recipeId = {recipe.id};
        
        // Edit mode state
        let editIngredients = JSON.parse(JSON.stringify(ingredientData));
        let editSteps = {json.dumps([{"step_number": s.step_number, "instruction": s.instruction} for s in sorted_steps])};
        
        function toggleEditMode() {{
            const body = document.body;
            const btn = document.getElementById('edit-toggle-btn');
            
            if (body.classList.contains('editing')) {{
                body.classList.remove('editing');
                btn.textContent = '✏️ Edit';
                btn.classList.remove('active');
            }} else {{
                body.classList.add('editing');
                btn.textContent = '✏️ Editing';
                btn.classList.add('active');
                renderEditIngredients();
                renderEditSteps();
            }}
        }}
        
        function cancelEdit() {{
            // Reset to original data
            editIngredients = JSON.parse(JSON.stringify(ingredientData));
            editSteps = {json.dumps([{"step_number": s.step_number, "instruction": s.instruction} for s in sorted_steps])};
            document.body.classList.remove('editing');
            document.getElementById('edit-toggle-btn').textContent = '✏️ Edit';
            document.getElementById('edit-toggle-btn').classList.remove('active');
        }}
        
        function renderEditIngredients() {{
            const container = document.getElementById('edit-ingredients-list');
            if (editIngredients.length === 0) {{
                container.innerHTML = '<p style="color: var(--text-muted); font-size: 0.9rem;">No ingredients yet. Click "Add" to add one.</p>';
                return;
            }}
            
            container.innerHTML = editIngredients.map((ing, idx) => `
                <div class="edit-item" data-idx="${{idx}}">
                    <div class="edit-item-content">
                        <div class="edit-item-row">
                            <input type="text" class="amount-input" placeholder="Amt" value="${{ing.amount || ''}}" onchange="updateIngredient(${{idx}}, 'amount', this.value)">
                            <input type="text" class="unit-input" placeholder="Unit" value="${{ing.unit || ''}}" onchange="updateIngredient(${{idx}}, 'unit', this.value)">
                            <input type="text" placeholder="Ingredient name" value="${{ing.name}}" onchange="updateIngredient(${{idx}}, 'name', this.value)">
                        </div>
                        <div class="edit-item-row">
                            <input type="text" placeholder="Notes (optional)" value="${{ing.notes || ''}}" onchange="updateIngredient(${{idx}}, 'notes', this.value)" style="flex: 1;">
                        </div>
                    </div>
                    <button class="remove-btn" onclick="removeIngredient(${{idx}})" title="Remove">✕</button>
                </div>
            `).join('');
        }}
        
        function updateIngredient(idx, field, value) {{
            editIngredients[idx][field] = value;
        }}
        
        function addIngredient() {{
            editIngredients.push({{
                name: '',
                amount: '',
                unit: '',
                notes: '',
                item_id: null
            }});
            renderEditIngredients();
        }}
        
        function removeIngredient(idx) {{
            editIngredients.splice(idx, 1);
            renderEditIngredients();
        }}
        
        function renderEditSteps() {{
            const container = document.getElementById('edit-steps-list');
            if (editSteps.length === 0) {{
                container.innerHTML = '<p style="color: var(--text-muted); font-size: 0.9rem;">No steps yet. Click "Add Step" to add one.</p>';
                return;
            }}
            
            container.innerHTML = editSteps.map((step, idx) => `
                <div class="edit-item" data-idx="${{idx}}">
                    <span class="step-number">${{idx + 1}}</span>
                    <textarea class="step-textarea" placeholder="Describe this step..." onchange="updateStep(${{idx}}, this.value)">${{step.instruction}}</textarea>
                    <button class="remove-btn" onclick="removeStep(${{idx}})" title="Remove">✕</button>
                </div>
            `).join('');
        }}
        
        function updateStep(idx, value) {{
            editSteps[idx].instruction = value;
        }}
        
        function addStep() {{
            editSteps.push({{
                step_number: editSteps.length + 1,
                instruction: ''
            }});
            renderEditSteps();
        }}
        
        function removeStep(idx) {{
            editSteps.splice(idx, 1);
            // Renumber steps
            editSteps.forEach((step, i) => step.step_number = i + 1);
            renderEditSteps();
        }}
        
        async function saveRecipe() {{
            const saveBtn = document.getElementById('save-btn');
            saveBtn.disabled = true;
            saveBtn.textContent = 'Saving...';
            
            // Gather form data
            const name = document.getElementById('edit-name').value.trim();
            const description = document.getElementById('edit-description').value.trim();
            const servings = parseInt(document.getElementById('edit-servings').value) || 4;
            const prepTime = parseInt(document.getElementById('edit-prep').value) || null;
            const cookTime = parseInt(document.getElementById('edit-cook').value) || null;
            
            if (!name) {{
                showToast('Recipe name is required');
                saveBtn.disabled = false;
                saveBtn.textContent = 'Save Changes';
                return;
            }}
            
            // Filter out empty ingredients
            const ingredients = editIngredients
                .filter(ing => ing.name.trim())
                .map(ing => ({{
                    name: ing.name.trim(),
                    amount: ing.amount || null,
                    unit: ing.unit || null,
                    notes: ing.notes || null,
                    item_id: ing.item_id || null
                }}));
            
            // Filter out empty steps and renumber
            const steps = editSteps
                .filter(step => step.instruction.trim())
                .map((step, idx) => ({{
                    step_number: idx + 1,
                    instruction: step.instruction.trim()
                }}));
            
            try {{
                const response = await fetch(`/api/recipes/${{recipeId}}`, {{
                    method: 'PUT',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{
                        name,
                        description: description || null,
                        servings,
                        prep_time_minutes: prepTime,
                        cook_time_minutes: cookTime,
                        ingredients,
                        steps
                    }})
                }});
                
                if (!response.ok) {{
                    const err = await response.json();
                    throw new Error(err.detail || 'Failed to save');
                }}
                
                showToast('Recipe saved!');
                setTimeout(() => location.reload(), 800);
            }} catch (err) {{
                showToast(err.message);
                saveBtn.disabled = false;
                saveBtn.textContent = 'Save Changes';
            }}
        }}
        
        async function deleteRecipe() {{
            if (!confirm('Are you sure you want to delete this recipe? This cannot be undone.')) {{
                return;
            }}
            
            try {{
                const response = await fetch(`/api/recipes/${{recipeId}}`, {{
                    method: 'DELETE'
                }});
                
                if (!response.ok) throw new Error('Failed to delete');
                
                showToast('Recipe deleted');
                setTimeout(() => window.location.href = '/', 800);
            }} catch (err) {{
                showToast('Failed to delete recipe');
            }}
        }}
        
        async function toggleFavorite() {{
            await fetch('/api/recipes/{recipe.id}/favorite', {{ method: 'POST' }});
            location.reload();
        }}
        
        async function addMissingToGrocery() {{
            const btn = document.querySelector('.add-missing-btn');
            btn.disabled = true;
            btn.textContent = 'Adding...';
            
            let added = 0;
            for (const ingredient of missingIngredients) {{
                try {{
                    const ingredientName = ingredient.name;
                    const itemId = ingredient.item_id;
                    
                    if (itemId) {{
                        // Move matched item to grocery
                        await fetch(`/api/items/${{itemId}}/to-grocery`, {{ method: 'POST' }});
                        added++;
                    }} else {{
                        // Search for item by name
                        const searchRes = await fetch(`/api/search?q=${{encodeURIComponent(ingredientName)}}`);
                        const searchData = await searchRes.json();
                        
                        const exactMatch = searchData.find(item => 
                            item.name.toLowerCase() === ingredientName.toLowerCase()
                        );
                        
                        if (exactMatch) {{
                            await fetch(`/api/items/${{exactMatch.id}}/to-grocery`, {{ method: 'POST' }});
                        }} else {{
                            await fetch('/api/items', {{
                                method: 'POST',
                                headers: {{ 'Content-Type': 'application/json' }},
                                body: JSON.stringify({{
                                    name: ingredientName,
                                    location: 'grocery_list'
                                }})
                            }});
                        }}
                        added++;
                    }}
                }} catch (err) {{
                    console.error(`Failed to add ${{ingredient.name}}:`, err);
                }}
            }}
            
            showToast(`Added ${{added}} items to grocery list`);
            btn.textContent = '✓ Added to grocery';
            
            // Reload after a moment to show updated status
            setTimeout(() => location.reload(), 1500);
        }}
        
        // ========== Ingredient Dropdown Matching ==========
        let activeDropdown = null;
        
        function openIngredientDropdown(ingId) {{
            // Close any open dropdown
            closeAllDropdowns();
            
            const dropdown = document.getElementById(`dropdown-${{ingId}}`);
            const ing = ingredientData.find(i => i.id === ingId);
            if (!dropdown || !ing) return;
            
            // Build dropdown content
            dropdown.innerHTML = `
                <div class="dropdown-search">
                    <input type="text" placeholder="Search items..." oninput="filterDropdownItems(${{ingId}}, this.value)" autofocus>
                </div>
                <div class="dropdown-items" id="dropdown-items-${{ingId}}">
                    ${{renderDropdownItems(ingId, '')}}
                </div>
                <div class="dropdown-footer">
                    ${{ing.item_id ? `<button class="btn-clear-match" onclick="clearMatch(${{ingId}})">✕ Clear match</button>` : ''}}
                    <button class="btn-add-grocery" onclick="addIngredientToGrocery(${{ingId}})">🛒 Add "${{ing.name}}" to grocery</button>
                </div>
            `;
            
            dropdown.classList.add('active');
            activeDropdown = ingId;
            
            // Focus search input
            setTimeout(() => dropdown.querySelector('input')?.focus(), 50);
            
            // Stop event propagation
            event.stopPropagation();
        }}
        
        function renderDropdownItems(ingId, search) {{
            const ing = ingredientData.find(i => i.id === ingId);
            const searchLower = search.toLowerCase();
            
            const filtered = allItems.filter(item => 
                item.name.toLowerCase().includes(searchLower)
            );
            
            if (filtered.length === 0) {{
                return '<div class="dropdown-item no-match">No items found</div>';
            }}
            
            return filtered.map(item => {{
                const icon = item.location === 'inventory' ? '🏠' : 
                             item.location === 'grocery_list' ? '🛒' : '📦';
                const isSelected = ing.item_id === item.id;
                return `
                    <div class="dropdown-item ${{isSelected ? 'selected' : ''}}" onclick="selectItemMatch(${{ingId}}, ${{item.id}})">
                        <span class="item-icon">${{icon}}</span>
                        <span class="item-name">${{item.name}}</span>
                        ${{isSelected ? '<span style="color: var(--accent);">✓</span>' : ''}}
                    </div>
                `;
            }}).join('');
        }}
        
        function filterDropdownItems(ingId, search) {{
            const container = document.getElementById(`dropdown-items-${{ingId}}`);
            if (container) {{
                container.innerHTML = renderDropdownItems(ingId, search);
            }}
        }}
        
        async function selectItemMatch(ingId, itemId) {{
            const ing = ingredientData.find(i => i.id === ingId);
            if (!ing) return;
            
            // Update local data
            ing.item_id = itemId;
            
            // Save to server
            await saveIngredientMatch(ingId, itemId);
            
            closeAllDropdowns();
        }}
        
        async function clearMatch(ingId) {{
            const ing = ingredientData.find(i => i.id === ingId);
            if (!ing) return;
            
            ing.item_id = null;
            await saveIngredientMatch(ingId, null);
            closeAllDropdowns();
        }}
        
        async function saveIngredientMatch(ingId, itemId) {{
            // Rebuild all ingredients with updated match
            const updatedIngredients = ingredientData.map(ing => ({{
                name: ing.name,
                amount: ing.amount || null,
                unit: ing.unit || null,
                notes: ing.notes || null,
                item_id: ing.item_id
            }}));
            
            try {{
                const response = await fetch(`/api/recipes/${{recipeId}}`, {{
                    method: 'PUT',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ ingredients: updatedIngredients }})
                }});
                
                if (!response.ok) throw new Error('Failed to save');
                
                showToast('Match saved!');
                setTimeout(() => location.reload(), 800);
            }} catch (err) {{
                showToast('Failed to save match');
            }}
        }}
        
        async function addIngredientToGrocery(ingId) {{
            const ing = ingredientData.find(i => i.id === ingId);
            if (!ing) return;
            
            try {{
                // Create new item in grocery list
                const response = await fetch('/api/items', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{
                        name: ing.name,
                        location: 'grocery_list'
                    }})
                }});
                
                if (!response.ok) {{
                    const err = await response.json();
                    throw new Error(err.detail || 'Failed to add item');
                }}
                
                const newItem = await response.json();
                
                // Link this ingredient to the new item
                ing.item_id = newItem.id;
                await saveIngredientMatch(ingId, newItem.id);
                
                showToast(`Added "${{ing.name}}" to grocery list`);
                closeAllDropdowns();
            }} catch (err) {{
                showToast(err.message);
            }}
        }}
        
        function closeAllDropdowns() {{
            document.querySelectorAll('.ingredient-dropdown').forEach(d => {{
                d.classList.remove('active');
                d.innerHTML = '';
            }});
            activeDropdown = null;
        }}
        
        // Close dropdown when clicking outside
        document.addEventListener('click', (e) => {{
            if (activeDropdown && !e.target.closest('.ingredient-dropdown') && !e.target.closest('.ingredient-content')) {{
                closeAllDropdowns();
            }}
        }});
        
        function showToast(message) {{
            const toast = document.getElementById('toast');
            toast.textContent = message;
            toast.classList.add('show');
            setTimeout(() => toast.classList.remove('show'), 3000);
        }}
        
        // Check if we should auto-enter edit mode (from ?edit=1 query param)
        if (new URLSearchParams(window.location.search).get('edit') === '1') {{
            toggleEditMode();
            // Clean up URL
            window.history.replaceState({{}}, '', window.location.pathname);
        }}
    </script>
</body>
</html>
"""
    return HTMLResponse(content=html)

