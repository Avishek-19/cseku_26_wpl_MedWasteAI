from decimal import Decimal

from app.models.waste_enums import WasteUnit

LB_TO_KG = Decimal("0.45359237")


def quantity_to_kg(quantity: Decimal | float | str, unit: WasteUnit | str) -> Decimal | None:
    """Convert supported mass units to kg.

    Litres and pieces are intentionally not guessed into kg because the domain
    model has no density/item-weight data. Callers should route those batches to
    manual review when a kg-based capacity decision is required.
    """
    q = Decimal(str(quantity))
    value = unit.value if isinstance(unit, WasteUnit) else str(unit).lower()
    if value == "kg":
        return q
    if value == "lb":
        return q * LB_TO_KG
    return None
