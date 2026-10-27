from app.models.waste_enums import RiskLevel, SuggestedHandling

PROCESSING_METHODS = (
    "AUTOCLAVE",
    "INCINERATION",
    "CHEMICAL_TREATMENT",
    "MICROWAVE_TREATMENT",
    "SHARPS_DESTRUCTION",
    "PHARMACEUTICAL_TREATMENT",
    "RECYCLING",
    "MATERIAL_RECOVERY",
    "FINAL_DISPOSAL",
    "SPECIALIZED_TREATMENT",
)


def required_processing(*, category_code: str, risk_level: RiskLevel, handling: SuggestedHandling) -> tuple[str, list[str]]:
    code = category_code.upper()
    if handling == SuggestedHandling.RECYCLE or code == "RECYCLABLE":
        return "RECYCLING", ["RECYCLING", "MATERIAL_RECOVERY"]
    if code == "SHARPS":
        return "SHARPS_DESTRUCTION", ["SHARPS_DESTRUCTION", "AUTOCLAVE", "INCINERATION"]
    if code == "PHARMACEUTICAL":
        return "PHARMACEUTICAL_TREATMENT", ["PHARMACEUTICAL_TREATMENT", "INCINERATION"]
    if code == "CHEMICAL":
        return "CHEMICAL_TREATMENT", ["CHEMICAL_TREATMENT", "INCINERATION"]
    if code == "PATHOLOGICAL":
        return "SPECIALIZED_TREATMENT", ["INCINERATION", "SPECIALIZED_TREATMENT"]
    if handling == SuggestedHandling.DISPOSE:
        return "FINAL_DISPOSAL", ["FINAL_DISPOSAL", "INCINERATION"]
    return "SPECIALIZED_TREATMENT", ["AUTOCLAVE", "INCINERATION", "SPECIALIZED_TREATMENT"]
