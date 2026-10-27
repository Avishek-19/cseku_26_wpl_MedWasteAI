from dataclasses import dataclass, field


@dataclass
class ClassificationRule:
    category_code: str
    keywords: tuple[str, ...]


# Order matters: when a description matches keywords for more than one
# category, the earliest (highest-priority) match wins. Safety-critical
# categories are listed first so ambiguous descriptions err toward caution.
RULES: tuple[ClassificationRule, ...] = (
    ClassificationRule("SHARPS", ("needle", "syringe", "blade", "lancet", "scalpel")),
    ClassificationRule(
        "PATHOLOGICAL", ("tissue", "organ", "specimen", "anatomical", "biopsy")
    ),
    ClassificationRule(
        "INFECTIOUS", ("blood", "fluid", "contaminated", "infected", "culture", "pathogen")
    ),
    ClassificationRule(
        "CHEMICAL", ("chemical", "solvent", "reagent", "disinfectant", "formaldehyde")
    ),
    ClassificationRule(
        "PHARMACEUTICAL", ("expired medication", "medication", "drug", "pharmaceutical", "pills")
    ),
    ClassificationRule(
        "RECYCLABLE", ("plastic packaging", "packaging", "recyclable", "cardboard")
    ),
)


@dataclass
class RuleMatch:
    category_code: str
    matched_keywords: list[str] = field(default_factory=list)


@dataclass
class ClassificationResult:
    suggested_category_code: str
    confidence: str  # "high" | "medium" | "low"
    matched_rules: list[RuleMatch]
    explanation: str


def classify(*, description: str | None, reported_category_code: str) -> ClassificationResult:
    """Suggests a category from keyword matches in the description.

    This is intentionally simple, deterministic, and fully explainable —
    no machine learning or external API involved (spec section 5).
    """
    text = (description or "").lower()

    matches: list[RuleMatch] = []
    for rule in RULES:
        hits = [kw for kw in rule.keywords if kw in text]
        if hits:
            matches.append(RuleMatch(category_code=rule.category_code, matched_keywords=hits))

    if not matches:
        return ClassificationResult(
            suggested_category_code=reported_category_code,
            confidence="low",
            matched_rules=[],
            explanation=(
                "No classification keywords were found in the description. "
                "Defaulting to the reported category — manual review recommended."
            ),
        )

    top_match = matches[0]  # earliest = highest priority

    if len(matches) == 1 and top_match.category_code == reported_category_code:
        confidence = "high"
        explanation = (
            f"Description matches keywords for '{top_match.category_code}' "
            "and agrees with the reported category."
        )
    elif len(matches) == 1:
        confidence = "medium"
        explanation = (
            f"Description matches keywords for '{top_match.category_code}', "
            f"which differs from the reported category. Review recommended."
        )
    else:
        other_codes = ", ".join(m.category_code for m in matches[1:])
        confidence = "medium"
        explanation = (
            f"Description matches multiple categories ('{top_match.category_code}' and "
            f"{other_codes}). Suggesting the higher-priority match — review recommended."
        )

    return ClassificationResult(
        suggested_category_code=top_match.category_code,
        confidence=confidence,
        matched_rules=matches,
        explanation=explanation,
    )
