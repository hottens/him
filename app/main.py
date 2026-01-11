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

from .database import engine, get_db, Base
from .models import Item, Barcode, ItemLocation, Recipe, RecipeIngredient, RecipeStep
from . import schemas
from . import gemini_service
from . import spoonacular_service

# Create database tables
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Home Inventory Manager",
    description="Local-first inventory and grocery list management with barcode scanning",
    version="2.0.0"
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
        "spoonacular_configured": spoonacular_service.is_configured()
    }


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


@app.post("/api/items/merge", response_model=schemas.ItemResponse)
async def merge_items(
    request: schemas.ItemMergeRequest,
    db: Session = Depends(get_db)
):
    """
    Merge multiple items into one.
    
    - Transfers all barcodes from source items to target item
    - Updates all recipe ingredient links to point to target item
    - Deletes the source items
    """
    # Validate target exists
    target = db.query(Item).filter(Item.id == request.target_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Target item not found")
    
    # Validate source items exist
    for source_id in request.source_ids:
        if source_id == request.target_id:
            raise HTTPException(
                status_code=400,
                detail="Target item cannot be in source items"
            )
        source = db.query(Item).filter(Item.id == source_id).first()
        if not source:
            raise HTTPException(
                status_code=404,
                detail=f"Source item with id {source_id} not found"
            )
    
    # Transfer barcodes from source items to target
    for source_id in request.source_ids:
        db.query(Barcode).filter(Barcode.item_id == source_id).update(
            {"item_id": request.target_id}
        )
    
    # Update recipe ingredient links
    for source_id in request.source_ids:
        db.query(RecipeIngredient).filter(
            RecipeIngredient.item_id == source_id
        ).update({"item_id": request.target_id})
    
    # Delete source items
    for source_id in request.source_ids:
        source = db.query(Item).filter(Item.id == source_id).first()
        if source:
            db.delete(source)
    
    db.commit()
    db.refresh(target)
    
    return target


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
    """Remove an item from both inventory and grocery list (set to neither)."""
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
    return schemas.RecipeListResponse(count=len(recipes), recipes=recipes)


@app.post("/api/recipes", response_model=schemas.RecipeResponse)
async def create_recipe(recipe: schemas.RecipeCreate, db: Session = Depends(get_db)):
    """Create a new recipe."""
    db_recipe = Recipe(
        name=recipe.name,
        description=recipe.description,
        servings=recipe.servings,
        prep_time_minutes=recipe.prep_time_minutes,
        cook_time_minutes=recipe.cook_time_minutes,
        is_favorite=recipe.is_favorite
    )
    db.add(db_recipe)
    db.flush()
    
    # Add ingredients
    for ing in recipe.ingredients:
        db_ingredient = RecipeIngredient(
            recipe_id=db_recipe.id,
            name=ing.name,
            amount=ing.amount,
            unit=ing.unit,
            notes=ing.notes,
            item_id=ing.item_id  # Optional link to inventory item
        )
        db.add(db_ingredient)
    
    # Add steps
    for step in recipe.steps:
        db_step = RecipeStep(
            recipe_id=db_recipe.id,
            step_number=step.step_number,
            instruction=step.instruction
        )
        db.add(db_step)
    
    db.commit()
    db.refresh(db_recipe)
    
    return db_recipe


@app.get("/api/recipes/{recipe_id}", response_model=schemas.RecipeResponse)
async def get_recipe(recipe_id: int, db: Session = Depends(get_db)):
    """Get a single recipe by ID."""
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found")
    return recipe


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
    
    return recipe


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
    
    # Update basic fields
    update_data = update.model_dump(exclude_unset=True)
    
    for field in ['name', 'description', 'servings', 'prep_time_minutes', 'cook_time_minutes', 'is_favorite']:
        if field in update_data and update_data[field] is not None:
            setattr(recipe, field, update_data[field])
    
    # Update ingredients if provided
    if update.ingredients is not None:
        # Delete existing ingredients
        db.query(RecipeIngredient).filter(RecipeIngredient.recipe_id == recipe_id).delete()
        # Add new ingredients
        for ing in update.ingredients:
            db_ingredient = RecipeIngredient(
                recipe_id=recipe_id,
                name=ing.name,
                amount=ing.amount,
                unit=ing.unit,
                notes=ing.notes,
                item_id=ing.item_id  # Optional link to inventory item
            )
            db.add(db_ingredient)
    
    # Update steps if provided
    if update.steps is not None:
        # Delete existing steps
        db.query(RecipeStep).filter(RecipeStep.recipe_id == recipe_id).delete()
        # Add new steps
        for step in update.steps:
            db_step = RecipeStep(
                recipe_id=recipe_id,
                step_number=step.step_number,
                instruction=step.instruction
            )
            db.add(db_step)
    
    db.commit()
    db.refresh(recipe)
    
    return recipe


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
    
    return recipe


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


# --- Spoonacular API Endpoints ---
# Uses search_by_ingredients as the primary discovery method

@app.get("/api/spoonacular/recipe/{recipe_id}")
async def spoonacular_get_recipe(recipe_id: int):
    """
    Get detailed recipe information from Spoonacular.
    
    Requires SPOONACULAR_API_KEY environment variable to be set.
    """
    if not spoonacular_service.is_configured():
        raise HTTPException(
            status_code=503,
            detail="Spoonacular API is not configured. Set SPOONACULAR_API_KEY environment variable."
        )
    
    result = spoonacular_service.get_recipe_details(recipe_id)
    
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    
    return result


@app.post("/api/spoonacular/discover")
async def spoonacular_discover_recipes(
    request: schemas.SpoonacularByIngredientsRequest,
    db: Session = Depends(get_db)
):
    """
    Discover recipes based on current inventory ingredients.
    
    This is the primary way to find recipes - based on what you have.
    Translates ingredients to English using Gemini before searching.
    Requires SPOONACULAR_API_KEY environment variable to be set.
    """
    if not spoonacular_service.is_configured():
        raise HTTPException(
            status_code=503,
            detail="Spoonacular API is not configured. Set SPOONACULAR_API_KEY environment variable."
        )
    
    # Get inventory items
    inventory_items = db.query(Item).filter(
        Item.location == ItemLocation.INVENTORY
    ).all()
    ingredient_names = [item.name for item in inventory_items]
    
    if not ingredient_names:
        raise HTTPException(
            status_code=400,
            detail="No items in inventory. Add some items first."
        )
    
    # Translate ingredients to English using Gemini if configured
    if gemini_service.is_configured():
        english_ingredients = gemini_service.translate_ingredients_to_english(ingredient_names)
    else:
        english_ingredients = ingredient_names
    
    result = spoonacular_service.search_by_ingredients(
        ingredients=english_ingredients,
        number=request.number
    )
    
    return {
        "recipes": result,
        "ingredients_used": ingredient_names,
        "ingredients_english": english_ingredients
    }


@app.post("/api/spoonacular/import/{recipe_id}", response_model=schemas.RecipeResponse)
async def import_spoonacular_recipe(recipe_id: int, db: Session = Depends(get_db)):
    """
    Import a Spoonacular recipe into the local database.
    
    Fetches recipe details from Spoonacular, uses Gemini to parse it
    into our clean format, then saves locally.
    """
    if not spoonacular_service.is_configured():
        raise HTTPException(
            status_code=503,
            detail="Spoonacular API is not configured. Set SPOONACULAR_API_KEY environment variable."
        )
    
    # Get recipe details from Spoonacular
    spoon_recipe = spoonacular_service.get_recipe_details(recipe_id)
    
    if "error" in spoon_recipe:
        raise HTTPException(status_code=500, detail=spoon_recipe["error"])
    
    # Use Gemini to parse if configured, otherwise fall back to basic parsing
    if gemini_service.is_configured():
        local_data = gemini_service.parse_spoonacular_recipe(spoon_recipe)
    else:
        local_data = spoonacular_service.convert_to_local_recipe(spoon_recipe)
    
    # Create the recipe
    db_recipe = Recipe(
        name=local_data["name"],
        description=local_data.get("description"),
        servings=local_data.get("servings", 4),
        prep_time_minutes=local_data.get("prep_time_minutes"),
        cook_time_minutes=local_data.get("cook_time_minutes"),
        is_favorite=False
    )
    db.add(db_recipe)
    db.flush()
    
    # Add ingredients
    for ing in local_data.get("ingredients", []):
        db_ingredient = RecipeIngredient(
            recipe_id=db_recipe.id,
            name=ing["name"],
            amount=ing.get("amount"),
            unit=ing.get("unit"),
            notes=ing.get("notes")
        )
        db.add(db_ingredient)
    
    # Add steps
    for step in local_data.get("steps", []):
        db_step = RecipeStep(
            recipe_id=db_recipe.id,
            step_number=step["step_number"],
            instruction=step["instruction"]
        )
        db.add(db_step)
    
    db.commit()
    db.refresh(db_recipe)
    
    return db_recipe


class ImportUrlRequest(schemas.BaseModel):
    """Request to import a recipe from a URL."""
    url: str


@app.post("/api/recipes/import-url", response_model=schemas.RecipeResponse)
async def import_recipe_from_url(request: ImportUrlRequest, db: Session = Depends(get_db)):
    """
    Import a recipe from any website URL.
    
    Uses Spoonacular to extract recipe data from the URL,
    then uses Gemini to parse it into our clean format.
    """
    if not spoonacular_service.is_configured():
        raise HTTPException(
            status_code=503,
            detail="Spoonacular API is not configured. Set SPOONACULAR_API_KEY environment variable."
        )
    
    # Extract recipe from URL using Spoonacular
    extracted = spoonacular_service.extract_recipe_from_url(request.url)
    
    if "error" in extracted:
        raise HTTPException(status_code=500, detail=f"Failed to extract recipe: {extracted['error']}")
    
    if not extracted.get("title"):
        raise HTTPException(status_code=400, detail="Could not extract recipe from this URL")
    
    # Use Gemini to parse if configured, otherwise fall back to basic parsing
    if gemini_service.is_configured():
        local_data = gemini_service.parse_spoonacular_recipe(extracted)
    else:
        local_data = spoonacular_service.convert_to_local_recipe(extracted)
    
    # Create the recipe
    db_recipe = Recipe(
        name=local_data["name"],
        description=local_data.get("description"),
        servings=local_data.get("servings", 4),
        prep_time_minutes=local_data.get("prep_time_minutes"),
        cook_time_minutes=local_data.get("cook_time_minutes"),
        is_favorite=False
    )
    db.add(db_recipe)
    db.flush()
    
    # Add ingredients
    for ing in local_data.get("ingredients", []):
        db_ingredient = RecipeIngredient(
            recipe_id=db_recipe.id,
            name=ing.get("name", ""),
            amount=ing.get("amount"),
            unit=ing.get("unit"),
            notes=ing.get("notes")
        )
        db.add(db_ingredient)
    
    # Add steps
    for step in local_data.get("steps", []):
        db_step = RecipeStep(
            recipe_id=db_recipe.id,
            step_number=step.get("step_number", 1),
            instruction=step.get("instruction", "")
        )
        db.add(db_step)
    
    db.commit()
    db.refresh(db_recipe)
    
    return db_recipe


# --- Beautiful Recipe View Page ---

@app.get("/recipe/{recipe_id}", response_class=HTMLResponse, include_in_schema=False)
async def view_recipe_page(recipe_id: int, db: Session = Depends(get_db)):
    """Serve a beautiful, user-friendly recipe viewing page."""
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found")
    
    # Get all items for dropdown (including location info)
    all_items = db.query(Item).order_by(Item.name).all()
    # Get inventory items for fallback name-based matching
    inventory_items = db.query(Item).filter(Item.location == ItemLocation.INVENTORY).all()
    inventory_names = {item.name.lower(): item for item in inventory_items}
    
    # Sort steps by step_number
    sorted_steps = sorted(recipe.steps, key=lambda s: s.step_number)
    
    # Generate ingredients HTML with availability status
    # Prioritize matched_item for availability, fallback to name matching
    ingredients_html = ""
    missing_ingredients = []
    ingredient_data = []  # For JS
    for ing in recipe.ingredients:
        amount_str = f"{ing.amount} " if ing.amount else ""
        unit_str = f"{ing.unit} " if ing.unit else ""
        notes_str = f" <span class='notes'>({ing.notes})</span>" if ing.notes else ""
        
        # Determine availability: prioritize matched_item, fallback to name match
        matched_item_name = None
        if ing.matched_item:
            is_available = ing.matched_item.location == ItemLocation.INVENTORY
            matched_item_name = ing.matched_item.name
        elif ing.name.lower() in inventory_names:
            is_available = True
        else:
            is_available = False
        
        status_icon = "✓" if is_available else "✗"
        status_class = "available" if is_available else "missing"
        
        if not is_available:
            missing_ingredients.append({
                "name": ing.name,
                "item_id": ing.item_id
            })
        
        # Store ingredient data for JS edit modal
        ingredient_data.append({
            "id": ing.id,
            "name": ing.name,
            "amount": ing.amount or "",
            "unit": ing.unit or "",
            "notes": ing.notes or "",
            "item_id": ing.item_id
        })
        
        # Show matched item name if different from ingredient name
        match_info = ""
        if matched_item_name and matched_item_name.lower() != ing.name.lower():
            match_info = f" <span class='matched-to'>→ {matched_item_name}</span>"
        
        ingredients_html += f"<li class='{status_class}' data-ing-id='{ing.id}'><span class='status-icon'>{status_icon}</span> {amount_str}{unit_str}{ing.name}{notes_str}{match_info}</li>"
    
    # Generate steps HTML
    steps_html = ""
    for step in sorted_steps:
        steps_html += f"<li>{step.instruction}</li>"
    
    # Calculate total time
    total_time = (recipe.prep_time_minutes or 0) + (recipe.cook_time_minutes or 0)
    time_str = f"{total_time} min" if total_time else "—"
    
    # JSON data for JavaScript
    import json
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
        
        .back-link {{
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
            color: var(--text-muted);
            text-decoration: none;
            font-size: 0.875rem;
            margin-bottom: 2rem;
        }}
        
        .back-link:hover {{ color: var(--accent); }}
        
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
        }}
        
        .ingredients li:last-child {{ border-bottom: none; }}
        
        .ingredients li.available .status-icon {{ color: var(--accent-green); }}
        .ingredients li.missing .status-icon {{ color: var(--accent-red); }}
        .ingredients li.missing {{ opacity: 0.7; }}
        
        .matched-to {{
            color: var(--text-muted);
            font-size: 0.85rem;
            font-style: italic;
        }}
        
        .ingredients-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 0.5rem;
        }}
        
        .edit-btn {{
            background: transparent;
            border: 1px solid var(--border);
            color: var(--text-muted);
            padding: 0.4rem 0.8rem;
            border-radius: 6px;
            font-size: 0.8rem;
            cursor: pointer;
            transition: all 0.2s;
        }}
        
        .edit-btn:hover {{
            border-color: var(--accent);
            color: var(--accent);
        }}
        
        .modal-overlay {{
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(0,0,0,0.5);
            display: none;
            align-items: center;
            justify-content: center;
            z-index: 1000;
            padding: 1rem;
        }}
        
        .modal-overlay.active {{ display: flex; }}
        
        .modal {{
            background: var(--bg);
            border-radius: 12px;
            max-width: 500px;
            width: 100%;
            max-height: 80vh;
            overflow-y: auto;
            box-shadow: 0 10px 40px rgba(0,0,0,0.2);
        }}
        
        .modal-header {{
            padding: 1rem 1.5rem;
            border-bottom: 1px solid var(--border);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        
        .modal-header h3 {{
            font-family: 'Crimson Pro', serif;
            font-size: 1.3rem;
            margin: 0;
        }}
        
        .modal-close {{
            background: none;
            border: none;
            font-size: 1.5rem;
            cursor: pointer;
            color: var(--text-muted);
        }}
        
        .modal-body {{
            padding: 1.5rem;
        }}
        
        .match-item {{
            padding: 0.75rem 0;
            border-bottom: 1px solid var(--border);
        }}
        
        .match-item:last-child {{ border-bottom: none; }}
        
        .match-item-name {{
            font-weight: 500;
            margin-bottom: 0.4rem;
        }}
        
        .match-item select {{
            width: 100%;
            padding: 0.5rem;
            border: 1px solid var(--border);
            border-radius: 6px;
            font-size: 0.9rem;
            background: #fff;
        }}
        
        .modal-footer {{
            padding: 1rem 1.5rem;
            border-top: 1px solid var(--border);
            display: flex;
            gap: 0.5rem;
            justify-content: flex-end;
        }}
        
        .modal-footer button {{
            padding: 0.6rem 1.2rem;
            border-radius: 6px;
            font-size: 0.9rem;
            cursor: pointer;
            transition: all 0.2s;
        }}
        
        .btn-cancel {{
            background: transparent;
            border: 1px solid var(--border);
            color: var(--text-muted);
        }}
        
        .btn-save {{
            background: var(--accent);
            border: none;
            color: #fff;
        }}
        
        .btn-save:disabled {{
            opacity: 0.5;
            cursor: not-allowed;
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
        
        @media (max-width: 480px) {{
            h1 {{ font-size: 2rem; }}
            .meta {{ gap: 1rem; flex-wrap: wrap; }}
            .availability-banner {{ flex-direction: column; align-items: stretch; text-align: center; }}
        }}
    </style>
</head>
<body>
    <a href="/" class="back-link">← Back to Inventory</a>
    
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
    
    <div class="ingredients-header">
        <h2>Ingredients</h2>
        <button class="edit-btn" onclick="openMatchModal()">✎ Match Items</button>
    </div>
    {availability_html}
    <div class="ingredients">
        <ul>
            {ingredients_html}
        </ul>
    </div>
    
    <!-- Ingredient Match Modal -->
    <div class="modal-overlay" id="match-modal">
        <div class="modal">
            <div class="modal-header">
                <h3>Match Ingredients to Inventory</h3>
                <button class="modal-close" onclick="closeMatchModal()">&times;</button>
            </div>
            <div class="modal-body" id="match-modal-body">
                <!-- Populated by JS -->
            </div>
            <div class="modal-footer">
                <button class="btn-cancel" onclick="closeMatchModal()">Cancel</button>
                <button class="btn-save" onclick="saveMatches()" id="save-matches-btn">Save Matches</button>
            </div>
        </div>
    </div>
    
    <h2>Instructions</h2>
    <div class="steps">
        <ol>
            {steps_html}
        </ol>
    </div>
    
    <button class="favorite" onclick="toggleFavorite()" title="{'Remove from favorites' if recipe.is_favorite else 'Add to favorites'}">
        {'★' if recipe.is_favorite else '☆'}
    </button>
    
    <div class="toast" id="toast"></div>
    
    <script>
        const missingIngredients = {missing_json};
        const ingredientData = {ingredients_json};
        const allItems = {items_json};
        const recipeId = {recipe.id};
        
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
        
        // ========== Ingredient Matching Modal ==========
        function openMatchModal() {{
            const body = document.getElementById('match-modal-body');
            
            // Build options for each ingredient
            let html = '<p style="margin-bottom: 1rem; color: var(--text-muted); font-size: 0.9rem;">Link ingredients to inventory items for accurate tracking.</p>';
            
            for (const ing of ingredientData) {{
                const amountStr = ing.amount ? `${{ing.amount}} ` : '';
                const unitStr = ing.unit ? `${{ing.unit}} ` : '';
                
                html += `
                    <div class="match-item">
                        <div class="match-item-name">${{amountStr}}${{unitStr}}${{ing.name}}</div>
                        <select data-ingredient-id="${{ing.id}}">
                            <option value="">-- No match --</option>
                            ${{allItems.map(item => `
                                <option value="${{item.id}}" ${{ing.item_id === item.id ? 'selected' : ''}}>
                                    ${{item.name}} (${{item.location === 'inventory' ? '🏠' : item.location === 'grocery_list' ? '🛒' : '📦'}})
                                </option>
                            `).join('')}}
                        </select>
                    </div>
                `;
            }}
            
            body.innerHTML = html;
            document.getElementById('match-modal').classList.add('active');
        }}
        
        function closeMatchModal() {{
            document.getElementById('match-modal').classList.remove('active');
        }}
        
        async function saveMatches() {{
            const btn = document.getElementById('save-matches-btn');
            btn.disabled = true;
            btn.textContent = 'Saving...';
            
            // Collect all ingredient matches
            const selects = document.querySelectorAll('#match-modal-body select');
            const updatedIngredients = ingredientData.map(ing => {{
                const select = document.querySelector(`select[data-ingredient-id="${{ing.id}}"]`);
                const itemId = select && select.value ? parseInt(select.value) : null;
                return {{
                    name: ing.name,
                    amount: ing.amount || null,
                    unit: ing.unit || null,
                    notes: ing.notes || null,
                    item_id: itemId
                }};
            }});
            
            try {{
                const response = await fetch(`/api/recipes/${{recipeId}}`, {{
                    method: 'PUT',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ ingredients: updatedIngredients }})
                }});
                
                if (!response.ok) throw new Error('Failed to save');
                
                showToast('Ingredient matches saved!');
                closeMatchModal();
                
                // Reload to show updated availability
                setTimeout(() => location.reload(), 1000);
            }} catch (err) {{
                showToast('Failed to save matches');
                btn.disabled = false;
                btn.textContent = 'Save Matches';
            }}
        }}
        
        function showToast(message) {{
            const toast = document.getElementById('toast');
            toast.textContent = message;
            toast.classList.add('show');
            setTimeout(() => toast.classList.remove('show'), 3000);
        }}
    </script>
</body>
</html>
"""
    return HTMLResponse(content=html)
