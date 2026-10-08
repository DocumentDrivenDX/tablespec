"""Run-selectable domain packs; registration never changes the default pack."""

from dataclasses import dataclass
from typing import Any, Callable

from tablespec.inference.domain_types import DomainTypeRegistry

from .generators import HealthcareDataGenerators
from .legal import LegalDataGenerators, LEGAL_TYPES


@dataclass(frozen=True)
class DomainPack:
    """Bind a value-generator factory to its matching domain-type registry."""

    generators: Callable[..., Any]
    registry: Callable[[], DomainTypeRegistry]


_PACKS = {
    "healthcare": DomainPack(HealthcareDataGenerators, DomainTypeRegistry),
    "legal": DomainPack(
        LegalDataGenerators,
        lambda: DomainTypeRegistry(registry_data={"domain_types": LEGAL_TYPES}),
    ),
}


def register_domain_pack(name: str, pack: DomainPack) -> None:
    """Register an application pack explicitly; reject accidental replacement."""
    if not name or name in _PACKS:
        raise ValueError(f"Domain pack already registered or empty: {name}")
    _PACKS[name] = pack


def get_domain_pack(name: str) -> DomainPack:
    """Resolve a pack, failing before generation on unknown names."""
    try:
        return _PACKS[name]
    except KeyError as exc:
        raise ValueError(
            f"Unknown domain pack {name}; choose from {sorted(_PACKS)}"
        ) from exc
