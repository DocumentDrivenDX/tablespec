"""Validation rule processor for GX-aware sample data generation."""

import logging
import random
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .generators import HealthcareDataGenerators


class ValidationRuleProcessor:
    """Process validation rules to generate compliant sample data."""

    def __init__(self, generators: "HealthcareDataGenerators") -> None:
        self.generators = generators
        self.logger = logging.getLogger(self.__class__.__name__)

    def apply_validation_rules(
        self, col_name: str, validation_rules: dict[str, Any]
    ) -> str | int | float | bool | None:
        """Generate data that complies with validation rules."""
        try:
            # Handle value constraints (enumerated values)
            value_constraints = validation_rules.get("value_constraints", [])
            if value_constraints:
                # Look for enumerated values like "Valid values: A, B, C"
                for constraint in value_constraints:
                    if "valid values" in constraint.lower():
                        # Extract values from constraints like "Valid values: MEDICAID, MEDICARE, DUALS"
                        values_part = constraint.split(":", 1)[-1].strip()
                        if values_part:
                            valid_values = [v.strip() for v in values_part.split(",")]
                            if valid_values:
                                return random.choice(valid_values)

            # Handle format rules
            format_rules = validation_rules.get("format_rules", [])
            for rule in format_rules:
                rule_lower = rule.lower()

                # Plan code format: "2 digit length+Amisys number"
                if "plan code" in rule_lower and "2 digit" in rule_lower:
                    return f"{random.randint(10, 99)}A{random.randint(1000, 9999)}"

                # Member ID formats
                if "member" in rule_lower and "id" in rule_lower:
                    if "medicare" in rule_lower:
                        # Medicare Beneficiary ID format (MBI)
                        return self._generate_medicare_id()
                    if "medicaid" in rule_lower:
                        # Medicaid ID format
                        return f"MCD{random.randint(1000000, 9999999)}"

                # Always patterns
                if "always" in rule_lower and "digit" in rule_lower:
                    # Extract digit count
                    digit_match = re.search(r"(\d+)\s*digit", rule_lower)
                    if digit_match:
                        digit_count = int(digit_match.group(1))
                        return "".join(
                            [str(random.randint(0, 9)) for _ in range(digit_count)]
                        )

            # Handle length constraints
            length_constraints = validation_rules.get("length_constraints", [])
            for constraint in length_constraints:
                if "exactly" in constraint.lower():
                    # Extract exact length requirement
                    length_match = re.search(r"exactly\s+(\d+)", constraint.lower())
                    if length_match:
                        length = int(length_match.group(1))
                        return "".join(
                            [str(random.randint(0, 9)) for _ in range(length)]
                        )

            # Handle business rules
            business_rules = validation_rules.get("business_rules", [])
            for rule in business_rules:
                rule_lower = rule.lower()

                # Note: LOINC generation removed - now handled by dedicated
                # generators.generate_loinc() method in engine.py domain patterns

                if "icd" in rule_lower:
                    # Generate ICD-10 code format
                    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                    return f"{random.choice(letters)}{random.randint(10, 99)}.{random.randint(0, 9)}"

            # Handle conditional rules (simplified - just note them for now)
            conditional_rules = validation_rules.get("conditional_rules", [])
            if conditional_rules:
                self.logger.debug(
                    f"Column {col_name} has conditional rules: {conditional_rules}"
                )

            return None  # No specific rule applied

        except Exception as e:
            self.logger.warning(f"Failed to apply validation rules for {col_name}: {e}")
            return None

    def _generate_medicare_id(self) -> str:
        """Generate Medicare Beneficiary Identifier (MBI) format."""
        # MBI format: 1A2B3C4D5E6F7G8H9 (alternating numbers and letters, excluding certain letters)
        valid_letters = "ACDEFGHJKMNPQRTUVWXY"  # Excludes B, I, L, O, S, Z
        mbi = ""

        for i in range(11):
            if i % 2 == 0:  # Positions 1, 3, 5, 7, 9, 11 are numbers
                mbi += str(random.randint(0, 9))
            else:  # Positions 2, 4, 6, 8, 10 are letters
                mbi += random.choice(valid_letters)

        return mbi


__all__ = ["ValidationRuleProcessor"]
