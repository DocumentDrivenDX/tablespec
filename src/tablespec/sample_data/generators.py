"""Healthcare-specific data generators for sample data generation.

This module uses the standard `random` module for sample data generation,
not the `secrets` module, as the generated data is synthetic/test data and does
not require cryptographic security.
"""

from datetime import UTC, datetime, timedelta
import hashlib
import logging
import math
import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import GenerationConfig
    from .registry import KeyRegistry


class HealthcareDataGenerators:
    """Healthcare-specific data generators."""

    def __init__(
        self, config: "GenerationConfig", key_registry: "KeyRegistry | None" = None
    ) -> None:
        self.config = config
        self.key_registry = key_registry
        self.logger = logging.getLogger(self.__class__.__name__)
        self.member_ids: set[str] = set()
        self.base_date = config.get_reference_date() - timedelta(
            days=config.temporal_range_days
        )

        # Healthcare domain data
        # Complete list of US states and territories
        self.states = [
            "AL",
            "AK",
            "AZ",
            "AR",
            "CA",
            "CO",
            "CT",
            "DE",
            "FL",
            "GA",
            "HI",
            "ID",
            "IL",
            "IN",
            "IA",
            "KS",
            "KY",
            "LA",
            "ME",
            "MD",
            "MA",
            "MI",
            "MN",
            "MS",
            "MO",
            "MT",
            "NE",
            "NV",
            "NH",
            "NJ",
            "NM",
            "NY",
            "NC",
            "ND",
            "OH",
            "OK",
            "OR",
            "PA",
            "RI",
            "SC",
            "SD",
            "TN",
            "TX",
            "UT",
            "VT",
            "VA",
            "WA",
            "WV",
            "WI",
            "WY",
            "DC",
            "PR",
            "VI",
            "GU",
            "AS",
            "MP",
        ]
        self.lobs = ["MEDICAID", "MEDICARE", "MARKETPLACE", "DUALS"]
        self.genders = ["M", "F", "U", "N"]
        self.population_types = {
            "MEDICARE": [
                "CND",
                "GI",
                "CNA",
                "CFD",
                "CPA",
                "DI",
                "GNE",
                "NE",
                "CPD",
                "DNE",
                "GC",
                "SNPNE",
                "INS",
                "CFA",
            ],
            "MEDICAID": ["DA", "DC", "AA", "AC"],
            "MARKETPLACE": ["Adult", "Child", "Infant"],
            "DUALS": ["CFD", "CFA", "CPD", "CPA"],
        }

        # Common names for realistic data
        # Include names with special characters (apostrophes) to test quote preservation
        self.first_names = [
            "James",
            "Mary",
            "John",
            "Patricia",
            "Robert",
            "Jennifer",
            "Michael",
            "Linda",
            "William",
            "Elizabeth",
            "David",
            "Barbara",
            "Richard",
            "Susan",
            "Joseph",
            "Jessica",
            "O'Brien",  # Test apostrophe
            "D'Angelo",  # Test apostrophe
        ]
        self.last_names = [
            "Smith",
            "Johnson",
            "Williams",
            "Brown",
            "Jones",
            "Garcia",
            "Miller",
            "Davis",
            "Rodriguez",
            "Martinez",
            "Hernandez",
            "Lopez",
            "Gonzalez",
            "Wilson",
            "Anderson",
            "Thomas",
            "O'Connor",  # Test apostrophe
            "D'Amato",  # Test apostrophe
            "O'Malley",  # Test apostrophe
        ]

        # Medical codes
        self.icd10_codes = [
            "Z00.00",
            "Z12.11",
            "I10",
            "E11.9",
            "F17.210",
            "M79.3",
            "R06.02",
            "N18.6",
            "I25.10",
            "F32.9",
            "G47.33",
            "K21.9",
            "M25.50",
            "H52.4",
            "J44.1",
            "E78.5",
        ]
        self.cpt_codes = [
            "99213",
            "99214",
            "99215",
            "99396",
            "99397",
            "80053",
            "85025",
            "80061",
            "93000",
            "71020",
            "76700",
            "99401",
            "99402",
            "96116",
            "90791",
            "90834",
        ]

    def generate_client_member_id(self) -> str:
        r"""Generate ClientMemberId from finite pool or fallback to unique generation.

        Generates format: ^[A-Z]{2}\d{11}$ (2 uppercase letters + 11 digits)
        Example: AB12345678901
        """
        # Use key registry pool if available
        if self.key_registry:
            key = self.key_registry.get_key_from_pool("ClientMemberID")
            if key:
                return str(key)  # Ensure string return type

        # Fallback to unique generation matching regex pattern ^[A-Z]{2}\d{11}$
        import string

        while True:
            # Generate 2 uppercase letters
            letters = "".join(random.choice(string.ascii_uppercase) for _ in range(2))
            # Generate 11 digits
            digits = "".join(str(random.randint(0, 9)) for _ in range(11))
            member_id = f"{letters}{digits}"

            if member_id not in self.member_ids:
                self.member_ids.add(member_id)
                return member_id

    def generate_govt_id(self, lob: str) -> str:
        """Generate government ID based on line of business."""
        if lob == "MEDICARE":
            # Medicare Beneficiary ID format
            return f"1{random.choice(['A', 'B', 'C'])}{random.randint(10000, 99999)}{random.choice(['A', 'B', 'C'])}"
        if lob == "MEDICAID":
            # State Medicaid number
            return f"{random.choice(self.states)}{random.randint(1000000, 9999999)}"
        if lob == "MARKETPLACE":
            # Member Exchange Number
            return f"EX{random.randint(100000000, 999999999)}"
        # DUALS
        return f"DL{random.randint(100000000, 999999999)}"

    def generate_name(self) -> tuple[str, str, str]:
        """Generate realistic first, middle, last name."""
        first_name = random.choice(self.first_names)
        last_name = random.choice(self.last_names)
        middle_name = random.choice(self.first_names) if random.random() < 0.3 else ""
        return first_name, middle_name, last_name

    def generate_address(self) -> dict[str, str]:
        """Generate realistic address components."""
        street_names = [
            "Main St",
            "Oak Ave",
            "First St",
            "Second St",
            "Park Ave",
            "Elm St",
        ]
        counties = [
            "Cook County",
            "Harris County",
            "Los Angeles County",
            "Maricopa County",
        ]

        return {
            "address_line1": f"{random.randint(100, 9999)} {random.choice(street_names)}",
            "address_line2": f"Apt {random.randint(1, 999)}"
            if random.random() < 0.2
            else "",
            "city": random.choice(
                ["Chicago", "Houston", "Los Angeles", "Phoenix", "Philadelphia"]
            ),
            "state": random.choice(self.states),
            "zipcode": f"{random.randint(10000, 99999)}",
            "county": random.choice(counties),
        }

    def generate_date_in_range(
        self, days_back: int | None = None, date_format: str = "%Y-%m-%d"
    ) -> str:
        """Generate random date within specified range.

        Args:
            days_back: Number of days back from base_date to generate dates
            date_format: Python strftime format string (default: %Y-%m-%d)

        Returns:
            Formatted date string

        """
        if days_back is None:
            days_back = self.config.temporal_range_days

        random_days = random.randint(0, days_back)
        date = self.base_date + timedelta(days=random_days)

        # Enforce minimum date to prevent Spark Parquet errors (dates < 1900-01-01)
        min_date = datetime(1900, 1, 1, tzinfo=UTC)
        date = max(date, min_date)

        return date.strftime(date_format)

    def generate_date_in_range_with_constraints(
        self,
        min_date_str: str | None = None,
        max_date_str: str | None = None,
        date_format: str = "%Y-%m-%d",
    ) -> str:
        """Generate random date within specified min/max constraints.

        Args:
            min_date_str: Minimum date in YYYY-MM-DD format (default: 1900-01-01)
            max_date_str: Maximum date in YYYY-MM-DD format (default: today)
            date_format: Python strftime format string for output (default: %Y-%m-%d)

        Returns:
            Formatted date string

        """
        # Parse min date
        if min_date_str:
            # Try multiple formats: date only, datetime with time, datetime with T separator
            for fmt in ["%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"]:
                try:
                    min_date = datetime.strptime(min_date_str.strip(), fmt).replace(
                        tzinfo=UTC
                    )
                    break
                except ValueError:
                    continue
            else:
                # If none of the formats work, try parsing just the date part
                min_date = datetime.strptime(
                    min_date_str.strip().split()[0], "%Y-%m-%d"
                ).replace(tzinfo=UTC)
        else:
            min_date = datetime(1900, 1, 1, tzinfo=UTC)

        # Parse max date
        if max_date_str:
            # Try multiple formats: date only, datetime with time, datetime with T separator
            for fmt in ["%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"]:
                try:
                    max_date = datetime.strptime(max_date_str.strip(), fmt).replace(
                        tzinfo=UTC
                    )
                    break
                except ValueError:
                    continue
            else:
                # If none of the formats work, try parsing just the date part
                max_date = datetime.strptime(
                    max_date_str.strip().split()[0], "%Y-%m-%d"
                ).replace(tzinfo=UTC)
        else:
            max_date = self.config.get_reference_date()

        # Generate random date between min and max
        time_delta = max_date - min_date
        random_days = random.randint(0, time_delta.days)
        date = min_date + timedelta(days=random_days)

        return date.strftime(date_format)

    def generate_birth_date(self, date_format: str = "%Y-%m-%d") -> str:
        """Generate realistic birth date (18-120 years old from today).

        Args:
            date_format: Python strftime format string (default: %Y-%m-%d)

        Returns:
            Formatted date string

        """
        today = self.config.get_reference_date()

        # Generate age between 18 and 120 years
        # Most people are 18-90 (80% probability), some are 90-120 (20% probability)
        years_old = (
            random.randint(18, 90) if random.random() < 0.8 else random.randint(90, 120)
        )

        # Calculate birth date
        birth_year = today.year - years_old
        birth_month = random.randint(1, 12)

        # Handle days in month (simplified - use 28 for Feb, 30 for Apr/Jun/Sep/Nov, 31 for others)
        if birth_month == 2:
            birth_day = random.randint(1, 28)
        elif birth_month in [4, 6, 9, 11]:
            birth_day = random.randint(1, 30)
        else:
            birth_day = random.randint(1, 31)

        birth_date = datetime(birth_year, birth_month, birth_day, tzinfo=UTC)

        # Ensure not in the future and >= 1900-01-01
        min_date = datetime(1900, 1, 1, tzinfo=UTC)
        birth_date = max(birth_date, min_date)
        birth_date = min(birth_date, today)

        return birth_date.strftime(date_format)

    def generate_risk_score(self) -> float:
        """Generate realistic risk adjustment factor."""
        # Most members have low risk (0.5-2.0), some high risk (2.0-8.0)
        if random.random() < 0.8:
            return round(random.uniform(0.5, 2.0), 2)
        return round(random.uniform(2.0, 8.0), 2)

    def generate_rank(self) -> int:
        """Generate member ranking based on risk distribution."""
        # 60% active outreach (1-6), 40% passive (>6)
        if random.random() < 0.6:
            return random.randint(1, 6)
        return random.choice([99, 100, 115, 120])

    def generate_email(self) -> str:
        """Generate a realistic email address."""
        # Common email providers
        providers = ["gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "aol.com"]

        # Generate username (3-12 chars)
        username_length = random.randint(3, 12)
        username = "".join(
            random.choices("abcdefghijklmnopqrstuvwxyz0123456789._", k=username_length)
        )

        # Sometimes add numbers to username
        if random.random() < 0.3:
            username += str(random.randint(1, 999))

        return f"{username}@{random.choice(providers)}"

    def generate_npi(self) -> str:
        """Generate a 10-digit National Provider Identifier."""
        return "".join([str(random.randint(0, 9)) for _ in range(10)])

    def generate_zip_code(self) -> str:
        """Generate a US ZIP code in 5-digit or ZIP+4 format."""
        zip5 = f"{random.randint(10000, 99999)}"
        # 30% chance of ZIP+4 format
        if random.random() < 0.3:
            zip4 = f"{random.randint(1000, 9999)}"
            return f"{zip5}-{zip4}"
        return zip5

    def generate_loinc(self) -> str:
        r"""Generate a valid LOINC code matching the pattern ^\d{1,7}-\d$.

        LOINC (Logical Observation Identifiers Names and Codes) format:
        - Numeric part: 1-7 digits (we use 5-7 for realism)
        - Separator: hyphen
        - Check digit: single digit (0-9)

        Returns:
            A synthetic LOINC code (e.g., "13955-0", "2085-9")

        """
        # Generate 5-7 digit numeric part for realistic codes
        numeric_part = random.randint(10000, 9999999)
        check_digit = random.randint(0, 9)
        return f"{numeric_part}-{check_digit}"

    def generate_procedure_code(self, code_type: str = "CPT") -> str:
        """Generate a realistic procedure code.

        Args:
            code_type: Type of code (CPT, HCPCS)

        Returns:
            A procedure code string

        """
        if code_type == "HCPCS":
            # HCPCS format: Letter + 4 digits
            letter = random.choice("ABCDEFGHJKLMPQRSTUV")  # Common HCPCS prefixes
            return f"{letter}{random.randint(1000, 9999)}"
        # CPT codes - return one from our list
        return random.choice(self.cpt_codes)

    def generate_diagnosis_code(self) -> str:
        """Generate a realistic diagnosis code (ICD-10).

        Returns:
            An ICD-10 code from our list

        """
        return random.choice(self.icd10_codes)

    def generate_service_type(self) -> str:
        """Generate a healthcare service type for IHA disposition reporting.

        Returns:
            A service type string (IHA, TEL, AUD, RET)

        """
        service_types = [
            "IHA",  # In home assessment
            "TEL",  # Video & Audio Assessment (Tele health)
            "AUD",  # Audio only completions
            "RET",  # Retail clinic
        ]
        return random.choice(service_types)

    def generate_disposition_status(self) -> str:
        """Generate a disposition status.

        Returns:
            A disposition status string (defaults to "PENDING FIRST CALL")

        """
        return "PENDING FIRST CALL"

    def generate_assessment_type(self) -> str:
        """Generate an assessment type.

        Returns:
            An assessment type string

        """
        types = [
            "INITIAL",
            "ANNUAL",
            "FOLLOWUP",
            "COMPREHENSIVE",
            "FOCUSED",
            "TELEPHONIC",
            "IN_HOME",
            "VIRTUAL",
            "BEHAVIORAL",
            "PHYSICAL",
            "COGNITIVE",
            "FUNCTIONAL",
            "NUTRITIONAL",
            "MEDICATION",
            "SOCIAL",
        ]
        return random.choice(types)

    def generate_provider_type(self) -> str:
        """Generate a provider type.

        Returns:
            A provider type string

        """
        types = [
            "PCP",
            "SPECIALIST",
            "HOSPITAL",
            "CLINIC",
            "URGENT_CARE",
            "PHARMACY",
            "LAB",
            "IMAGING",
            "DME",
            "HOME_HEALTH",
            "HOSPICE",
            "SNF",
            "BEHAVIORAL",
            "DENTAL",
            "VISION",
        ]
        return random.choice(types)

    def generate_vendor_name(self) -> str:
        """Generate a healthcare vendor name.

        Returns:
            A vendor name string

        """
        vendors = [
            "SIGNIFY",
            "INOVALON",
            "MATRIX",
            "HARMONY",
            "MEDXM",
            "ADVANTMED",
            "CCS",
            "HCMG",
            "DIRECT-SIGNIFY",
            "HARMONY-CCS",
            "CVS-HEALTH",
            "OPTUM",
            "CENTENE",
            "ANTHEM",
            "HUMANA",
        ]
        return random.choice(vendors)

    def generate_pcp_type(self) -> str:
        """Generate a PCP (Primary Care Provider) type code.

        Used for pcp_type columns in outreach files to indicate:
        - IMP: Imputed PCP (derived/inferred from data)
        - P4Q: Assigned PCP (Pay for Quality program)
        - FUL: Full risk provider

        Returns:
            One of: IMP, P4Q, FUL

        """
        # IMP is most common (50%), P4Q second (35%), FUL least common (15%)
        rand = random.random()
        if rand < 0.50:
            return "IMP"
        if rand < 0.85:
            return "P4Q"
        return "FUL"

    def generate_plan_code(self) -> str:
        """Generate a plan code (2 digit + Amisys number).

        Returns:
            A plan code string (e.g., "12A5678")

        """
        return f"{random.randint(10, 99)}A{random.randint(1000, 9999)}"

    def generate_state_code(self) -> str:
        """Generate a US state code (2-letter abbreviation).

        Returns:
            A state code from the complete list of US states and territories

        """
        return random.choice(self.states)

    def generate_lob(self) -> str:
        """Generate a Line of Business code.

        Returns:
            One of: MEDICAID, MEDICARE, MARKETPLACE, DUALS

        """
        return random.choice(self.lobs)

    def generate_gender(self) -> str:
        """Generate a gender code.

        Returns:
            One of: M (Male), F (Female), U (Unknown), N (Not Applicable)

        """
        return random.choice(self.genders)

    def generate_phone_number(self) -> str:
        """Generate a US phone number in 10-digit format.

        Returns:
            10-digit phone number (e.g., "5551234567")

        """
        return f"{random.randint(200, 999)}{random.randint(2000000, 9999999)}"

    def generate_address_line_1(self) -> str:
        """Generate a street address line.

        Returns:
            Street address (e.g., "1234 Main St")

        """
        street_names = [
            "Main St",
            "Oak Ave",
            "First St",
            "Second St",
            "Park Ave",
            "Elm St",
            "Maple Dr",
            "Oak St",
            "Cedar Ave",
            "Pine St",
            "Birch Rd",
            "Spruce Way",
        ]
        return f"{random.randint(100, 9999)} {random.choice(street_names)}"

    def generate_city(self) -> str:
        """Generate a city name.

        Returns:
            A city name

        """
        cities = [
            "Chicago",
            "Houston",
            "Los Angeles",
            "Phoenix",
            "Philadelphia",
            "San Antonio",
            "San Diego",
            "Dallas",
            "San Jose",
            "Austin",
            "Jacksonville",
            "Fort Worth",
            "Columbus",
            "Indianapolis",
            "Charlotte",
            "Seattle",
            "Denver",
            "Boston",
            "El Paso",
            "Nashville",
        ]
        return random.choice(cities)

    def generate_service_date(self, date_format: str = "%Y-%m-%d") -> str:
        """Generate a service/encounter date.

        Args:
            date_format: Python strftime format string (default: %Y-%m-%d)

        Returns:
            Formatted date string

        """
        return self.generate_date_in_range(date_format=date_format)

    def generate_timestamp(self, date_format: str = "%Y-%m-%d %H:%M:%S") -> str:
        """Generate a timestamp with time component.

        Args:
            date_format: Python strftime format string (default: %Y-%m-%d %H:%M:%S)

        Returns:
            Formatted timestamp string

        """
        date = self.base_date + timedelta(
            days=random.randint(0, self.config.temporal_range_days)
        )
        # Add random time component
        hour = random.randint(0, 23)
        minute = random.randint(0, 59)
        second = random.randint(0, 59)
        date = date.replace(hour=hour, minute=minute, second=second)
        return date.strftime(date_format)

    def generate_embedding(
        self, dimension: int, *, seed: str | int | None = None
    ) -> list[float]:
        """Generate a deterministic pseudo-embedding of the requested dimension."""
        if dimension < 1:
            msg = "dimension must be at least 1"
            raise ValueError(msg)

        seed_material = (
            f"{seed!r}:{dimension}" if seed is not None else f"embedding:{dimension}"
        )
        digest = hashlib.sha256(seed_material.encode("utf-8")).digest()
        seed_value = int.from_bytes(digest[:8], "big", signed=False)
        rng = random.Random(seed_value)

        values = [rng.uniform(-1.0, 1.0) for _ in range(dimension)]
        norm = math.sqrt(sum(v * v for v in values))
        if norm == 0.0:
            values[0] = 1.0
            norm = 1.0
        return [round(v / norm, 8) for v in values]

    def generate_project_code(self) -> int:
        """Generate a project/plan identifier code.

        Used for plan_dim_ck and similar plan dimension keys.
        Generates realistic 4-6 digit plan identifiers.

        Returns:
            Integer plan identifier (1000-999999)

        """
        return random.randint(1000, 999999)

    def generate_calendar_year(self) -> int:
        """Generate a calendar year.

        Returns recent years around the current date for realistic test data.

        Returns:
            4-digit year (current year +/- 2 years)

        """
        current_year = self.config.get_reference_date().year
        # Generate years around current year (e.g., 2024-2028 if current is 2026)
        return random.randint(current_year - 2, current_year + 2)

    def generate_visit_count(self) -> int:
        """Generate healthcare visit count.

        Represents number of visits or encounters (e.g., ER stays) in a time period.
        Most members have 0-3 visits (80%), some have 4-10 (15%), rare cases 11-20 (5%).

        Returns:
            Non-negative integer count of visits

        """
        # Realistic distribution: most people have few ER visits
        rand = random.random()
        if rand < 0.80:
            return random.randint(0, 3)  # 80% have 0-3 visits
        if rand < 0.95:
            return random.randint(4, 10)  # 15% have 4-10 visits
        return random.randint(11, 20)  # 5% have 11-20 visits


__all__ = ["HealthcareDataGenerators"]
