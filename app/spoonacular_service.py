"""
Spoonacular API Service for recipe browsing and search.

Requires SPOONACULAR_API_KEY environment variable to be set.
"""

import os
import requests
from typing import Optional

SPOONACULAR_API_KEY = os.environ.get("SPOONACULAR_API_KEY")
BASE_URL = "https://api.spoonacular.com"


def is_configured() -> bool:
    """Check if Spoonacular API is configured."""
    return SPOONACULAR_API_KEY is not None and len(SPOONACULAR_API_KEY) > 0


def search_recipes(
    query: str,
    cuisine: Optional[str] = None,
    diet: Optional[str] = None,
    max_ready_time: Optional[int] = None,
    number: int = 10
) -> dict:
    """
    Search for recipes using Spoonacular API.
    
    Args:
        query: Search query (e.g., "pasta", "chicken soup")
        cuisine: Cuisine type (e.g., "italian", "mexican")
        diet: Diet type (e.g., "vegetarian", "vegan", "gluten free")
        max_ready_time: Maximum preparation time in minutes
        number: Number of results to return (max 100)
    
    Returns:
        Dict containing search results
    """
    if not is_configured():
        raise ValueError("SPOONACULAR_API_KEY environment variable is not set")
    
    params = {
        "apiKey": SPOONACULAR_API_KEY,
        "query": query,
        "number": min(number, 100),
        "addRecipeInformation": True,
        "fillIngredients": True
    }
    
    if cuisine:
        params["cuisine"] = cuisine
    if diet:
        params["diet"] = diet
    if max_ready_time:
        params["maxReadyTime"] = max_ready_time
    
    try:
        response = requests.get(
            f"{BASE_URL}/recipes/complexSearch",
            params=params,
            timeout=10
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        return {"error": str(e), "results": []}


def get_recipe_details(recipe_id: int) -> dict:
    """
    Get detailed information about a specific recipe.
    
    Args:
        recipe_id: Spoonacular recipe ID
    
    Returns:
        Dict containing recipe details
    """
    if not is_configured():
        raise ValueError("SPOONACULAR_API_KEY environment variable is not set")
    
    try:
        response = requests.get(
            f"{BASE_URL}/recipes/{recipe_id}/information",
            params={
                "apiKey": SPOONACULAR_API_KEY,
                "includeNutrition": False
            },
            timeout=10
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        return {"error": str(e)}


def get_random_recipes(
    tags: Optional[str] = None,
    number: int = 5
) -> dict:
    """
    Get random recipes.
    
    Args:
        tags: Comma-separated tags (e.g., "vegetarian,dessert")
        number: Number of recipes to return
    
    Returns:
        Dict containing random recipes
    """
    if not is_configured():
        raise ValueError("SPOONACULAR_API_KEY environment variable is not set")
    
    params = {
        "apiKey": SPOONACULAR_API_KEY,
        "number": min(number, 10)
    }
    
    if tags:
        params["tags"] = tags
    
    try:
        response = requests.get(
            f"{BASE_URL}/recipes/random",
            params=params,
            timeout=10
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        return {"error": str(e), "recipes": []}


def search_by_ingredients(
    ingredients: list[str],
    number: int = 10,
    ranking: int = 2  # 1 = maximize used ingredients, 2 = minimize missing
) -> list:
    """
    Find recipes by ingredients you have.
    
    Args:
        ingredients: List of ingredient names
        number: Number of results
        ranking: 1 to maximize used ingredients, 2 to minimize missing
    
    Returns:
        List of matching recipes
    """
    if not is_configured():
        raise ValueError("SPOONACULAR_API_KEY environment variable is not set")
    
    try:
        response = requests.get(
            f"{BASE_URL}/recipes/findByIngredients",
            params={
                "apiKey": SPOONACULAR_API_KEY,
                "ingredients": ",".join(ingredients),
                "number": min(number, 100),
                "ranking": ranking,
                "ignorePantry": True
            },
            timeout=10
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        return []


def extract_recipe_from_url(url: str) -> dict:
    """
    Extract recipe data from a website URL using Spoonacular.
    
    Args:
        url: URL of the recipe page to extract
    
    Returns:
        Dict containing extracted recipe data
    """
    if not is_configured():
        raise ValueError("SPOONACULAR_API_KEY environment variable is not set")
    
    try:
        response = requests.get(
            f"{BASE_URL}/recipes/extract",
            params={
                "apiKey": SPOONACULAR_API_KEY,
                "url": url,
                "forceExtraction": True,
                "analyze": True
            },
            timeout=30  # URL extraction can take longer
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        return {"error": str(e)}


def convert_to_local_recipe(spoonacular_recipe: dict) -> dict:
    """
    Convert a Spoonacular recipe to our local recipe format.
    
    Args:
        spoonacular_recipe: Recipe data from Spoonacular API
    
    Returns:
        Dict in our local recipe format
    """
    # Extract ingredients
    ingredients = []
    extended_ingredients = spoonacular_recipe.get("extendedIngredients", [])
    for ing in extended_ingredients:
        ingredients.append({
            "name": ing.get("name", ing.get("original", "")),
            "amount": str(ing.get("amount", "")) if ing.get("amount") else None,
            "unit": ing.get("unit", None),
            "notes": ing.get("meta", [None])[0] if ing.get("meta") else None
        })
    
    # Extract steps
    steps = []
    analyzed_instructions = spoonacular_recipe.get("analyzedInstructions", [])
    if analyzed_instructions:
        for instruction in analyzed_instructions:
            for step in instruction.get("steps", []):
                steps.append({
                    "step_number": step.get("number", len(steps) + 1),
                    "instruction": step.get("step", "")
                })
    
    # If no analyzed instructions, use the summary or instructions text
    if not steps and spoonacular_recipe.get("instructions"):
        # Split by common delimiters
        instructions_text = spoonacular_recipe.get("instructions", "")
        # Remove HTML tags
        import re
        clean_text = re.sub(r'<[^>]+>', '', instructions_text)
        # Split by periods followed by space or newlines
        raw_steps = re.split(r'(?<=[.!?])\s+', clean_text)
        for i, step_text in enumerate(raw_steps, 1):
            if step_text.strip():
                steps.append({
                    "step_number": i,
                    "instruction": step_text.strip()
                })
    
    return {
        "name": spoonacular_recipe.get("title", "Untitled Recipe"),
        "description": spoonacular_recipe.get("summary", "")[:500] if spoonacular_recipe.get("summary") else None,
        "servings": spoonacular_recipe.get("servings", 4),
        "prep_time_minutes": spoonacular_recipe.get("preparationMinutes"),
        "cook_time_minutes": spoonacular_recipe.get("cookingMinutes") or spoonacular_recipe.get("readyInMinutes"),
        "ingredients": ingredients,
        "steps": steps,
        "source_url": spoonacular_recipe.get("sourceUrl"),
        "image_url": spoonacular_recipe.get("image"),
        "spoonacular_id": spoonacular_recipe.get("id")
    }

