"""
Gemini AI Service for recipe and grocery suggestions.

Requires GEMINI_API_KEY environment variable to be set.
"""

import os
import json
import google.generativeai as genai
from typing import Optional

# Configure Gemini
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)


def get_model():
    """Get the Gemini model instance."""
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY environment variable is not set")
    return genai.GenerativeModel('gemini-2.5-flash-lite')


def generate_recipe_suggestions(inventory_items: list[str], query: Optional[str] = None) -> dict:
    """
    Generate 3 recipe suggestions based on available inventory.
    
    Args:
        inventory_items: List of item names currently in inventory
        query: Optional search query to guide suggestions (e.g., "soup", "quick meals", "Italian")
    
    Returns:
        Dict containing recipe suggestions in structured format
    """
    model = get_model()
    
    inventory_str = ", ".join(inventory_items) if inventory_items else "No items in inventory"
    
    # Build the query/filter instruction
    if query:
        query_instruction = f"""
SPECIFIC REQUEST: {query}
Focus on recipes that match this request. For example:
- If the request mentions a cuisine (Italian, Asian, etc.), suggest dishes from that cuisine
- If it mentions a dish type (soup, salad, pasta, etc.), suggest that type of dish
- If it mentions dietary needs (vegetarian, low-carb, etc.), respect those constraints
- If it mentions time (quick, 30 minutes, etc.), suggest faster recipes
"""
    else:
        query_instruction = ""
    
    prompt = f"""You are a helpful cooking assistant. Based on the following inventory items, suggest 3 recipes for 4 servings that can be made.

INVENTORY ITEMS:
{inventory_str}
{query_instruction}
COOKING EQUIPMENT:
Assume a standard home kitchen with the following equipment:
    oven, stove, blender, pots, pans, utensils, airfryer, mortar, cake pan, tosti machine, toaster
    
For each recipe, provide:
1. A creative but descriptive name
2. A brief description (1-2 sentences)
3. Number of servings
4. Prep time in minutes
5. Cook time in minutes
6. List of ingredients with amounts and units (European standard units)
7. Step-by-step cooking instructions

IMPORTANT: Respond ONLY with valid JSON in this exact format:
{{
  "suggestions": [
    {{
      "name": "Recipe Name",
      "description": "Brief description of the dish IN DUTCH",
      "servings": 4,
      "prep_time_minutes": 15,
      "cook_time_minutes": 30,
      "ingredients": [
        {{"name": "ingredient name", "amount": "2", "unit": "grams", "notes": "diced"}}
      ],
      "steps": [
        {{"step_number": 1, "instruction": "First step..."}}
      ]
    }}
  ],
  "inventory_used": ["item1", "item2"]
}}

Every text should be in DUTCH.

Provide exactly 3 recipe suggestions. Use ingredients from the inventory when possible, but you can suggest additional ingredients when required."""

    try:
        response = model.generate_content(prompt)
        response_text = response.text.strip()
        
        # Try to extract JSON from the response
        # Sometimes Gemini wraps JSON in markdown code blocks
        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0].strip()
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0].strip()
        
        return json.loads(response_text)
    except json.JSONDecodeError as e:
        # Return a structured error response
        return {
            "error": f"Failed to parse Gemini response: {str(e)}",
            "raw_response": response.text if response else None,
            "suggestions": [],
            "inventory_used": []
        }
    except Exception as e:
        return {
            "error": str(e),
            "suggestions": [],
            "inventory_used": []
        }


def generate_grocery_suggestions(
    inventory_items: list[str],
    favorite_recipes: list[dict],
    preferences: Optional[str] = None
) -> dict:
    """
    Generate grocery suggestions based on inventory and favorite recipes.
    
    Args:
        inventory_items: List of item names currently in inventory
        favorite_recipes: List of favorite recipe dicts with name and ingredients
        preferences: Optional dietary preferences
    
    Returns:
        Dict containing grocery suggestions in structured format
    """
    model = get_model()
    
    inventory_str = ", ".join(inventory_items) if inventory_items else "No items in inventory"
    
    recipes_str = ""
    recipe_names = []
    if favorite_recipes:
        for recipe in favorite_recipes:
            recipe_names.append(recipe.get("name", "Unknown"))
            ingredients = recipe.get("ingredients", [])
            ing_list = ", ".join([i.get("name", "") for i in ingredients])
            recipes_str += f"- {recipe['name']}: {ing_list}\n"
    else:
        recipes_str = "No favorite recipes saved"
    
    pref_str = f"\n\nDietary preferences: {preferences}" if preferences else ""
    
    prompt = f"""You are a helpful grocery shopping assistant. Based on the current inventory and favorite recipes, suggest items to add to the grocery list.

CURRENT INVENTORY:
{inventory_str}

FAVORITE RECIPES:
{recipes_str}
{pref_str}

Analyze what ingredients are missing to make the favorite recipes, and suggest common staples that might be running low.

IMPORTANT: Respond ONLY with valid JSON in this exact format:
{{
  "suggestions": [
    {{
      "item_name": "item to buy",
      "reason": "needed for Recipe Name, or general reason"
    }}
  ],
  "based_on_recipes": ["Recipe 1", "Recipe 2"],
  "current_inventory": ["item1", "item2"]
}}

Suggest 5-10 practical grocery items. Prioritize ingredients needed for favorite recipes that aren't in inventory."""

    try:
        response = model.generate_content(prompt)
        response_text = response.text.strip()
        
        # Extract JSON from potential markdown wrapping
        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0].strip()
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0].strip()
        
        result = json.loads(response_text)
        # Ensure required fields exist
        if "based_on_recipes" not in result:
            result["based_on_recipes"] = recipe_names
        if "current_inventory" not in result:
            result["current_inventory"] = inventory_items
        
        return result
    except json.JSONDecodeError as e:
        return {
            "error": f"Failed to parse Gemini response: {str(e)}",
            "raw_response": response.text if response else None,
            "suggestions": [],
            "based_on_recipes": recipe_names,
            "current_inventory": inventory_items
        }
    except Exception as e:
        return {
            "error": str(e),
            "suggestions": [],
            "based_on_recipes": recipe_names,
            "current_inventory": inventory_items
        }


def is_configured() -> bool:
    """Check if Gemini API is configured."""
    return GEMINI_API_KEY is not None and len(GEMINI_API_KEY) > 0


def _extract_json_text(response_text: str) -> str:
    text = response_text.strip()
    if "```json" in text:
        return text.split("```json")[1].split("```")[0].strip()
    if "```" in text:
        return text.split("```")[1].split("```")[0].strip()
    return text


def translate_ingredients_to_dutch(
    ingredients: list[str],
    hierarchy: Optional[list[str]] = None,
) -> dict:
    """
    Translate English ingredient labels and hierarchy tags to Dutch.

    Returns:
        {
          "ingredients_nl": [...],
          "ingredients_hierarchy_nl": [...]
        }
    """
    ingredients = ingredients or []
    hierarchy = hierarchy or []
    if not ingredients and not hierarchy:
        return {"ingredients_nl": [], "ingredients_hierarchy_nl": []}

    if not is_configured():
        return {
            "ingredients_nl": list(ingredients),
            "ingredients_hierarchy_nl": list(hierarchy),
        }

    model = get_model()
    prompt = f"""Translate these Open Food Facts ingredient labels from English to Dutch.
Keep food taxonomy sense (e.g. "milk" → "melk", "animal based rennet" → "dierlijk stremsel").
Preserve list length and order exactly. If already Dutch, keep as-is.

INGREDIENTS (JSON array):
{json.dumps(ingredients, ensure_ascii=False)}

HIERARCHY (JSON array):
{json.dumps(hierarchy, ensure_ascii=False)}

Respond ONLY with valid JSON:
{{
  "ingredients_nl": ["..."],
  "ingredients_hierarchy_nl": ["..."]
}}"""

    try:
        response = model.generate_content(prompt)
        result = json.loads(_extract_json_text(response.text))
        ingredients_nl = result.get("ingredients_nl")
        hierarchy_nl = result.get("ingredients_hierarchy_nl")
        if not isinstance(ingredients_nl, list):
            ingredients_nl = list(ingredients)
        if not isinstance(hierarchy_nl, list):
            hierarchy_nl = list(hierarchy)
        # Pad/truncate to original lengths
        ingredients_nl = [str(x) for x in ingredients_nl][: len(ingredients)]
        while len(ingredients_nl) < len(ingredients):
            ingredients_nl.append(ingredients[len(ingredients_nl)])
        hierarchy_nl = [str(x) for x in hierarchy_nl][: len(hierarchy)]
        while len(hierarchy_nl) < len(hierarchy):
            hierarchy_nl.append(hierarchy[len(hierarchy_nl)])
        return {
            "ingredients_nl": ingredients_nl,
            "ingredients_hierarchy_nl": hierarchy_nl,
        }
    except Exception as e:
        print(f"Dutch translation failed: {e}")
        return {
            "ingredients_nl": list(ingredients),
            "ingredients_hierarchy_nl": list(hierarchy),
        }



def parse_recipe_from_url_content(url: str, page_text: str) -> dict:
    """
    Parse a recipe webpage into our local Dutch/metric recipe format via Gemini.
    """
    if not is_configured():
        raise ValueError("GEMINI_API_KEY environment variable is not set")

    model = get_model()
    clipped = (page_text or "")[:20000]
    prompt = f"""Parse this recipe webpage into a clean structured recipe.
Translate EVERYTHING to Dutch and convert measurements to European metric units
(gram, ml, stuks, eetlepel, theelepel).

SOURCE URL: {url}

PAGE TEXT:
{clipped}

Respond ONLY with valid JSON:
{{
  "name": "Nederlandse receptnaam",
  "description": "Korte beschrijving in het Nederlands",
  "servings": 4,
  "prep_time_minutes": null,
  "cook_time_minutes": null,
  "ingredients": [
    {{"name": "ingrediënt", "amount": "200", "unit": "gram", "notes": null}}
  ],
  "steps": [
    {{"step_number": 1, "instruction": "Nederlandse instructie..."}}
  ]
}}"""

    try:
        response = model.generate_content(prompt)
        result = json.loads(_extract_json_text(response.text))
        result["source_url"] = url
        if not result.get("name"):
            result["name"] = "Geïmporteerd recept"
        if not isinstance(result.get("ingredients"), list):
            result["ingredients"] = []
        if not isinstance(result.get("steps"), list):
            result["steps"] = []
        return result
    except Exception as e:
        return {
            "error": str(e),
            "name": "Geïmporteerd recept",
            "description": None,
            "servings": 4,
            "prep_time_minutes": None,
            "cook_time_minutes": None,
            "ingredients": [],
            "steps": [],
            "source_url": url,
        }


def translate_recipe_content(recipe: dict, target_lang: str) -> dict:
    """
    Translate recipe name/description/ingredients/steps between Dutch and English.

    ``target_lang`` is ``en`` or ``nl``.
    """
    if not is_configured():
        raise ValueError("GEMINI_API_KEY environment variable is not set")

    lang_name = "English" if target_lang == "en" else "Dutch"
    model = get_model()
    prompt = f"""Translate this recipe to {lang_name}.
Keep amounts and units as-is (do not convert units). Only translate text fields.
Preserve list lengths and step numbers exactly.

RECIPE JSON:
{json.dumps(recipe, ensure_ascii=False)}

Respond ONLY with valid JSON in this shape:
{{
  "name": "...",
  "description": "... or null",
  "ingredients": [
    {{"name": "...", "notes": "... or null"}}
  ],
  "steps": [
    {{"step_number": 1, "instruction": "..."}}
  ]
}}"""

    try:
        response = model.generate_content(prompt)
        result = json.loads(_extract_json_text(response.text))
        # Preserve lengths / step numbers from the source recipe
        src_ings = recipe.get("ingredients") or []
        src_steps = recipe.get("steps") or []
        out_ings = result.get("ingredients") if isinstance(result.get("ingredients"), list) else []
        out_steps = result.get("steps") if isinstance(result.get("steps"), list) else []
        ingredients = []
        for i, src in enumerate(src_ings):
            translated = out_ings[i] if i < len(out_ings) and isinstance(out_ings[i], dict) else {}
            ingredients.append({
                "name": translated.get("name") or src.get("name"),
                "notes": translated.get("notes") if "notes" in translated else src.get("notes"),
            })
        steps = []
        for i, src in enumerate(src_steps):
            translated = out_steps[i] if i < len(out_steps) and isinstance(out_steps[i], dict) else {}
            steps.append({
                "step_number": src.get("step_number", i + 1),
                "instruction": translated.get("instruction") or src.get("instruction"),
            })
        return {
            "name": result.get("name") or recipe.get("name"),
            "description": result.get("description", recipe.get("description")),
            "ingredients": ingredients,
            "steps": steps,
        }
    except Exception as e:
        return {"error": str(e)}
