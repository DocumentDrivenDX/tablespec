"""Configuration for sample data generation."""

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class GenerationConfig:
    """Configuration for sample data generation."""

    num_members: int = 10000  # Backward-compatible root count alias
    relationship_density: float = 0.7  # % of optional relationships populated
    temporal_range_days: int = 365  # Date range for temporal fields
    null_percentage: dict[str, float] = field(default_factory=dict)

    # Random seed for reproducible generation (None = random)
    random_seed: int | None = 42

    # Key pool configuration for joinable foreign keys
    key_pool_size: int = 500  # Number of unique keys in the pool
    key_distribution_80_20: bool = True  # Use 80/20 distribution pattern
    high_frequency_key_ratio: float = 0.8  # Portion of references to top 20% of keys

    # Reference date for deterministic generation (None = auto-select based on seed)
    reference_date: datetime | None = None

    root_entity_count: int | None = None
    domain: str = "healthcare"
    skew_exponent: float = 0.8
    matter_duration_min_days: int = 30
    matter_duration_max_days: int = 1095
    open_matter_fraction: float = 0.15
    relationship_distributions: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Resolve the neutral root count and validate configuration."""
        if self.root_entity_count is None:
            self.root_entity_count = self.num_members
        elif self.num_members != 10000 and self.num_members != self.root_entity_count:
            raise ValueError("Conflicting root_entity_count and num_members")
        self.num_members = self.root_entity_count
        if not 0 <= self.skew_exponent <= 0.95:
            raise ValueError("skew_exponent must be between 0 and 0.95")
        if not 1 <= self.matter_duration_min_days <= self.matter_duration_max_days:
            raise ValueError("Invalid matter duration range")
        if not 0 <= self.open_matter_fraction <= 1:
            raise ValueError("open_matter_fraction must be between zero and one")
        if not 0 <= self.high_frequency_key_ratio <= 1:
            raise ValueError("high_frequency_key_ratio must be between zero and one")
        if any(
            d not in ("skewed", "uniform")
            for d in self.relationship_distributions.values()
        ):
            raise ValueError("Relationship distribution must be skewed or uniform")
        if self.root_entity_count < 0:
            raise ValueError("root_entity_count must be nonnegative")

    @property
    def entity_count(self) -> int:
        """Return the resolved root-entity count."""
        return self.num_members

    def get_reference_date(self) -> datetime:
        """Get reference date for deterministic generation.

        When random_seed is set, returns a fixed date for reproducibility.
        Otherwise returns the current datetime.
        """
        if self.reference_date is not None:
            return self.reference_date
        if self.random_seed is not None:
            # Fixed reference date for deterministic generation
            return datetime(2025, 1, 15, 12, 0, 0, tzinfo=UTC)
        return datetime.now(tz=UTC)


__all__ = ["GenerationConfig"]
