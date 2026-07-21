"""Enrich barcodes with Open Food Facts data and optional Gemini Dutch translations."""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from . import gemini_service
from . import openfoodfacts_service
from .models import Barcode
from .product_data import apply_product_data, setting_is_true


def enrich_barcode(
    db: Session,
    barcode: Barcode,
    *,
    translate: Optional[bool] = None,
) -> dict:
    """
    Fetch product data from Open Food Facts and store it on the barcode.

    Returns a status dict: {"ok": bool, "found": bool, "error": optional str}
    """
    try:
        product = openfoodfacts_service.fetch_product(barcode.code)
    except Exception as e:
        return {"ok": False, "found": False, "error": str(e)}

    if not product:
        return {"ok": True, "found": False, "error": None}

    should_translate = (
        translate
        if translate is not None
        else setting_is_true(db, "translate_ingredients")
    )
    if should_translate and gemini_service.is_configured():
        translated = gemini_service.translate_ingredients_to_dutch(
            product.get("ingredients_en") or [],
            product.get("ingredients_hierarchy_en") or [],
        )
        product["ingredients_nl"] = translated["ingredients_nl"]
        product["ingredients_hierarchy_nl"] = translated["ingredients_hierarchy_nl"]
    else:
        product.setdefault("ingredients_nl", [])
        product.setdefault("ingredients_hierarchy_nl", [])

    apply_product_data(barcode, product)
    db.add(barcode)
    return {"ok": True, "found": True, "error": None}
