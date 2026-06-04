"""Backward-compatibility re-export of the (now core) logical-plan registry.

The IR builder ``NodeRegistry`` is framework-agnostic and is shared by every
backend (dbt and the prototype LDP emitter), so it lives in
:mod:`tablespec.core.registry`. This shim preserves the historical
``tablespec.dbt.registry`` import path used across the dbt emitter and its tests.

Encapsulation note: ``tablespec.core`` does NOT import this shim -- it owns the
implementation directly. This module exists only so existing
``from tablespec.dbt.registry import ...`` call sites keep working.
"""

from __future__ import annotations

from tablespec.core.registry import (
    NodeRegistry,
    NodeRegistryError,
    ResolvedNode,
)

__all__ = ["NodeRegistry", "NodeRegistryError", "ResolvedNode"]
