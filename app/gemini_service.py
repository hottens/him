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
    
    prompt = f"""You are a helpful professional cook. Based on the following inventory items, suggest 3 recipes that can be made.
Considering my inventory, take the following into account:
1. Prioritize classic pairings. Only suggest recipes that follow established culinary themes.
2. Do a flavor profile sanity check. Before outputting, evaluate if the ingredients are balanced and complementary. Remove weird combinations.
3. Mandatory omissions: Do not feel obligated to use every ingredient in the inventory.

INVENTORY ITEMS:
{inventory_str}
{query_instruction}
For each recipe, provide:
1. A creative but descriptive name
2. A brief description (1-2 sentences)
3. Number of servings
4. Prep time in minutes
5. Cook time in minutes
6. List of ingredients with amounts and units
7. Step-by-step cooking instructions

IMPORTANT: Respond ONLY with valid JSON in this exact format:
{{
  "suggestions": [
    {{
      "name": "Recipe Name",
      "description": "Brief description of the dish",
      "servings": 4,
      "prep_time_minutes": 15,
      "cook_time_minutes": 30,
      "ingredients": [
        {{"name": "ingredient name", "amount": "2", "unit": "cups", "notes": "diced"}}
      ],
      "steps": [
        {{"step_number": 1, "instruction": "First step..."}}
      ]
    }}
  ],
  "inventory_used": ["item1", "item2"]
}}

Provide exactly 3 recipe suggestions. Use ingredients from the inventory when possible, but you can suggest additional common pantry items if needed."""

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


def translate_ingredients_to_english(ingredients: list[str]) -> list[str]:
    """
    Translate ingredient names to English for Spoonacular API compatibility.
    
    Args:
        ingredients: List of ingredient names (possibly in other languages)
    
    Returns:
        List of ingredient names translated to English
    """
    if not ingredients:
        return []
    
    model = get_model()
    
    ingredients_str = "\n".join([f"- {ing}" for ing in ingredients])
    
    prompt = f"""Translate these ingredient/food item names to English. 
If they are already in English, keep them as-is.
Return ONLY a JSON array of strings with the English names, nothing else.

Items to translate:
{ingredients_str}

Example output format:
["milk", "eggs", "flour", "chicken breast"]

Respond with ONLY the JSON array, no explanation."""

    try:
        response = model.generate_content(prompt)
        response_text = response.text.strip()
        
        # Extract JSON from potential markdown wrapping
        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0].strip()
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0].strip()
        
        import json
        translated = json.loads(response_text)
        
        # Ensure we got a list of strings
        if isinstance(translated, list):
            return [str(item) for item in translated]
        else:
            return ingredients  # Fall back to original
    except Exception as e:
        # If translation fails, return original ingredients
        print(f"Translation failed: {e}")
        return ingredients


def parse_spoonacular_recipe(spoonacular_data: dict) -> dict:
    """
    Use Gemini to parse a Spoonacular recipe into our clean local format.
    
    Args:
        spoonacular_data: Raw recipe data from Spoonacular API
    
    Returns:
        Dict containing parsed recipe in our format
    """
    model = get_model()
    
    # Extract key information from Spoonacular data
    title = spoonacular_data.get("title", "Unknown Recipe")
    summary = spoonacular_data.get("summary", "")
    instructions = spoonacular_data.get("instructions", "")
    extended_ingredients = spoonacular_data.get("extendedIngredients", [])
    analyzed_instructions = spoonacular_data.get("analyzedInstructions", [])
    ready_in_minutes = spoonacular_data.get("readyInMinutes", 0)
    servings = spoonacular_data.get("servings", 4)
    
    # Build ingredient text for Gemini
    ingredients_text = "\n".join([
        f"- {ing.get('original', ing.get('name', ''))}" 
        for ing in extended_ingredients
    ])
    
    # Build instructions text
    if analyzed_instructions:
        steps_text = "\n".join([
            f"{step.get('number', i+1)}. {step.get('step', '')}"
            for instr in analyzed_instructions
            for i, step in enumerate(instr.get("steps", []))
        ])
    else:
        steps_text = instructions or "No instructions provided."
    
    prompt = f"""Parse this recipe into a clean, structured format.

RECIPE: {title}

SUMMARY:
{summary[:500] if summary else 'No summary available.'}

INGREDIENTS:
{ingredients_text or 'No ingredients listed.'}

INSTRUCTIONS:
{steps_text}

COOKING TIME: {ready_in_minutes} minutes total
SERVINGS: {servings}

Parse this into our structured format. For ingredients:
- Extract the ingredient name (just the food item, no amounts or preparation)
- Extract the amount as a string
- Extract the unit (cups, tbsp, oz, etc.)
- Add any preparation notes (diced, chopped, etc.)

For steps:
- Break down into clear, numbered steps
- Each step should be a single action

IMPORTANT: Respond ONLY with valid JSON in this exact format:
{{
  "name": "{title}",
  "description": "A brief 1-2 sentence description of the dish",
  "servings": {servings},
  "prep_time_minutes": null,
  "cook_time_minutes": {ready_in_minutes or 'null'},
  "ingredients": [
    {{"name": "ingredient name only", "amount": "20", "unit": "grams", "notes": "diced"}}
  ],
  "steps": [
    {{"step_number": 1, "instruction": "Clear instruction..."}}
  ]
}}

Make the description appetizing but concise. Ensure all ingredients are parsed correctly."""

    try:
        response = model.generate_content(prompt)
        response_text = response.text.strip()
        
        # Extract JSON from potential markdown wrapping
        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0].strip()
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0].strip()
        
        result = json.loads(response_text)
        
        # Add source info
        result["source_url"] = spoonacular_data.get("sourceUrl")
        result["image_url"] = spoonacular_data.get("image")
        result["spoonacular_id"] = spoonacular_data.get("id")
        
        return result
    except json.JSONDecodeError as e:
        # Fall back to basic parsing if Gemini fails
        return {
            "error": f"Gemini parsing failed: {str(e)}",
            "name": title,
            "description": summary[:200] if summary else None,
            "servings": servings,
            "prep_time_minutes": None,
            "cook_time_minutes": ready_in_minutes,
            "ingredients": [
                {"name": ing.get("name", ""), "amount": str(ing.get("amount", "")), 
                 "unit": ing.get("unit", ""), "notes": None}
                for ing in extended_ingredients
            ],
            "steps": [
                {"step_number": i+1, "instruction": step.get("step", "")}
                for instr in analyzed_instructions
                for i, step in enumerate(instr.get("steps", []))
            ] if analyzed_instructions else [{"step_number": 1, "instruction": instructions or "See source for instructions."}],
            "source_url": spoonacular_data.get("sourceUrl"),
            "image_url": spoonacular_data.get("image"),
            "spoonacular_id": spoonacular_data.get("id")
        }
    except Exception as e:
        return {
            "error": str(e),
            "name": title,
            "description": None,
            "servings": servings,
            "prep_time_minutes": None,
            "cook_time_minutes": ready_in_minutes,
            "ingredients": [],
            "steps": [],
            "source_url": spoonacular_data.get("sourceUrl"),
            "image_url": spoonacular_data.get("image"),
            "spoonacular_id": spoonacular_data.get("id")
        }

