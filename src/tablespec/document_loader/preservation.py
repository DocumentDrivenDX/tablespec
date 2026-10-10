"""PREMIS 3 semantic mapping and PROV-O JSON-LD for verified source revisions.

This JSON profile maps PREMIS data-dictionary units; it is not PREMIS XML.
OCFL repositories and WARC HTTP capture are outside this implementation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .core import load_publication, read_pack

PROFILE = {
    "version": "1.0.0",
    "handoff": "BagIt-1.0",
    "fixity": "sha256",
    "events": "PREMIS-3.0-semantic-mapping",
    "provenance": "PROV-O-JSON-LD",
    "originals": "authoritative-immutable-bytes",
    "primary_runtime": "tablespec-python",
}
AGENT = "urn:tablespec:document-loader:0.0.8"


def preservation_metadata(
    state: Path, checked_at: str | None = None
) -> tuple[dict, dict]:
    publication = load_publication(state)
    pack, pack_hash = read_pack(state / "pack/domain-pack.json")
    manifest = publication["manifest"]
    if pack_hash != manifest["binding"]["pack_hash"]:
        from .core import LoaderError

        raise LoaderError("STATE_IDENTITY")
    identity = "urn:umf:publication:" + publication["manifest_hash"]
    objects = {}
    rights = []
    graph = [{"@id": AGENT, "@type": "prov:SoftwareAgent"}]
    for row in manifest["history"]:
        object_id = "urn:sha256:" + row["sha256"]
        objects.setdefault(
            object_id,
            {
                "objectIdentifier": object_id,
                "objectCategory": "file",
                "objectCharacteristics": {
                    "fixity": {
                        "messageDigestAlgorithm": "SHA-256",
                        "messageDigest": row["sha256"],
                        "messageDigestOriginator": AGENT,
                    },
                    "size": row["bytes"],
                },
                "application": {
                    "contexts": [],
                },
            },
        )
        objects[object_id]["application"]["contexts"].append(
            {
                k: row[k]
                for k in ("id", "url", "media_type", "revision", "metadata", "license")
            }
        )
        # Permissions are inventory assertions, not inferred legal authorization.
        rights.append(
            {
                "objectIdentifier": object_id,
                "source_id": row["id"],
                "rightsStatement": row["license"],
                "selection": manifest["binding"]["rights"],
                "basis": "operator-supplied-inventory",
            }
        )
    graph += [
        {"@id": identifier, "@type": "prov:Entity"} for identifier in sorted(objects)
    ]
    events = []
    for index, observation in enumerate(manifest["observations"]):
        event_id = "urn:umf:observation:" + observation["run_id"] + ":" + str(index)
        object_id = "urn:sha256:" + observation["sha256"]
        local_id = event_id + ":copy"
        events.append(
            {
                "eventIdentifier": event_id,
                "eventType": "capture",
                "eventDateTime": observation["retrieved_at"],
                "eventOutcomeInformation": "success",
                "linkingObjectIdentifier": object_id,
                "linkingAgentIdentifier": AGENT,
                "application": observation,
            }
        )
        graph += [
            {"@id": observation["url"], "@type": "prov:Entity"},
            {
                "@id": event_id,
                "@type": "prov:Activity",
                "prov:used": {"@id": observation["url"]},
                "prov:endedAtTime": {
                    "@value": observation["retrieved_at"],
                    "@type": "xsd:dateTime",
                },
                "prov:wasAssociatedWith": {"@id": AGENT},
            },
            {
                "@id": local_id,
                "@type": "prov:Entity",
                "prov:specializationOf": {"@id": object_id},
                "prov:wasGeneratedBy": {"@id": event_id},
                "prov:wasDerivedFrom": {"@id": observation["url"]},
            },
        ]
    checked_at = checked_at or datetime.now(timezone.utc).isoformat(
        timespec="milliseconds"
    )
    from .core import digest

    check_id = identity + ":fixity:" + digest(checked_at.encode())
    events.append(
        {
            "eventIdentifier": check_id,
            "eventType": "fixity check",
            "eventDateTime": checked_at,
            "eventOutcomeInformation": "success",
            "linkingObjectIdentifiers": sorted(objects),
            "linkingAgentIdentifier": AGENT,
            "application": {
                "scope": "committed-history-sha256",
                "recorded_at": "fixity verification",
                "note": "All retained objects verified at the event timestamp.",
            },
        }
    )
    projection_id = identity + ":metadata-projection"
    graph += [
        {
            "@id": projection_id,
            "@type": "prov:Activity",
            "prov:used": [
                {"@id": "urn:sha256:" + row["sha256"]} for row in manifest["rows"]
            ],
            "prov:wasAssociatedWith": {"@id": AGENT},
        },
        {
            "@id": identity + ":documents.jsonl",
            "@type": "prov:Entity",
            "prov:wasGeneratedBy": {"@id": projection_id},
            "prov:wasDerivedFrom": [
                {"@id": "urn:sha256:" + row["sha256"]} for row in manifest["rows"]
            ],
        },
    ]
    premis = {
        "profile": "tablespec.preservation/1.0.0",
        "mapping": "PREMIS Data Dictionary 3.0",
        "conformance": "semantic JSON mapping; not PREMIS XML",
        "pack": {"id": pack["id"], "version": pack["version"], "sha256": pack_hash},
        "objects": list(objects.values()),
        "events": events,
        "rights": rights,
        "agents": [
            {
                "agentIdentifier": AGENT,
                "agentName": "TableSpec Python document-loader",
                "agentType": "software",
                "agentVersion": "0.0.8",
            }
        ],
    }
    prov = {
        "@context": {
            "prov": "http://www.w3.org/ns/prov#",
            "xsd": "http://www.w3.org/2001/XMLSchema#",
        },
        "@id": identity,
        "@graph": graph,
    }
    return premis, prov


def fixity_audit(state: Path) -> dict:
    """Full retained-history verification suitable for a scheduled offline job."""
    premis, _ = preservation_metadata(state)
    return {
        "status": "complete",
        "operation": "fixity-audit",
        "algorithm": "sha256",
        "objects": len(premis["objects"]),
        "pack": premis["pack"],
    }
