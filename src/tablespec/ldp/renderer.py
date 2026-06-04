"""The LDP implementation of the core :class:`TableRenderer` seam (PROTOTYPE).

``LdpRefRenderer`` turns a physical relation name the SQL generator wants to
inline into an LDP (Lakeflow Declarative Pipelines, the rebrand of Delta Live
Tables) dataset reference, using the SAME planner
:class:`~tablespec.dbt.registry.NodeRegistry` the dbt path consumes.

Where the dbt renderer emits a Jinja ``{{ ref('ingested_x') }}`` literal so dbt's
parser sees a static edge, the LDP renderer emits the *bare dataset name*
(``ingested_x``). In an LDP pipeline a dataset reference is just the dataset's
name -- Databricks resolves the DAG from those references and owns ordering /
incrementalisation. (Historically DLT spelled an in-pipeline reference
``LIVE.<name>``; modern LDP accepts the bare name, which is what we emit so the
generated SQL reads like ordinary SQL with declarative dataset names.)

Two invariants mirror the dbt renderer exactly (the point of the prototype is to
prove the core seam is target-agnostic, so the routing logic is identical -- only
the emitted literal differs):

  * **Semantic, not string-rewriting.** We map a relation *name* -> node -> dataset
    reference; we never inspect or substitute SQL aliases.
  * **Fail closed.** An unknown relation raises :class:`UnknownDatasetError`. A
    cross-pipeline external relation is emitted as its registered external dataset
    name only because the UMF explicitly marked it external (an external SOURCE
    node exists for it); it never becomes a phantom dataset.

Encapsulation: this module imports ONLY ``tablespec.core`` (the IR roles) and the
shared ``tablespec.dbt.registry`` is NOT imported here -- the registry is passed
in by the caller, typed structurally, so ``tablespec.ldp`` never imports
``tablespec.dbt``. See :mod:`tablespec.ldp.registry_port`.
"""

from __future__ import annotations

from typing import Protocol

from tablespec.core.ir import NodeRole


class UnknownDatasetError(LookupError):
    """Raised when a relation name resolves to no LDP dataset and is not external."""


class _ResolvedLike(Protocol):
    """Structural view of a registry hit (node id + role + external flag).

    Declared here so the LDP renderer never imports ``tablespec.dbt``; any object
    exposing these three attributes (the dbt ``ResolvedNode``) satisfies it.
    """

    @property
    def node_id(self) -> str: ...
    @property
    def role(self) -> NodeRole: ...
    @property
    def external(self) -> bool: ...


class _RegistryLike(Protocol):
    """Structural view of the planner registry the renderer needs.

    Only ``resolve`` is required, so the concrete ``tablespec.dbt.NodeRegistry``
    (or any equivalent) can be injected without an import dependency.
    """

    def resolve(self, physical_name: str) -> _ResolvedLike | None: ...


class LdpRefRenderer:
    """Render relation names as bare LDP dataset references (PROTOTYPE).

    Implements :class:`tablespec.core.relations.TableRenderer`. Injected into
    ``SQLPlanGenerator`` so a gold materialized-view body carries LDP dataset
    references (``ingested_claims``) instead of dbt ``{{ ref() }}`` literals.
    """

    def __init__(self, registry: _RegistryLike) -> None:
        self._registry = registry

    def render(self, physical_name: str) -> str:
        resolved = self._registry.resolve(physical_name)
        if resolved is None:
            msg = (
                f"Unknown relation {physical_name!r}: it maps to no UMF table and "
                f"is not marked external. Refusing to emit a phantom LDP dataset "
                f"reference (fail closed). Add the table to the UMF set or mark the "
                f"reference external explicitly."
            )
            raise UnknownDatasetError(msg)
        # SOURCE (raw landing OR external), INGESTED and GOLD all become a bare
        # dataset name in LDP -- Databricks resolves the DAG from the names. The
        # role still matters to the project emitter (it decides the dataset's
        # materialization), but the *reference* is uniformly the node id.
        if resolved.role is NodeRole.SOURCE and not resolved.external:
            # A local raw landing dataset (raw_<t>): still a bare dataset name.
            return resolved.node_id
        return resolved.node_id


__all__ = ["LdpRefRenderer", "UnknownDatasetError"]
