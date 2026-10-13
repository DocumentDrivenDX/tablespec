"""Trusted component replay through the existing verified disk spool and sinks."""

from copy import deepcopy
import json
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from .config import GenerationConfig
from .ingest import ImportedDataset, validate_profile
from .domains import read_domain_pack
from .streaming import GeneratedDataset


class ReplayDataset(ImportedDataset):
    """Replicate bounded fabricated components; this is not population simulation."""

    def __init__(
        self, path: Path, pack_path: Path, scale: str = "small", seed: int = 42
    ) -> None:
        metadata = read_domain_pack(pack_path)
        if "execution_profile" not in metadata:
            raise ValueError("Replay requires an authored execution profile")
        validate_profile(metadata)
        profile = metadata["execution_profile"]
        if profile["mode"] != "scenario-replay" or scale not in profile["scales"]:
            raise ValueError("Unavailable replay mode or scale")
        if type(seed) is not int or not -(2**53 - 1) <= seed <= 2**53 - 1:
            raise ValueError("Seed must be a safe integer")
        sources = metadata["sources"]
        for binding in metadata.get("source_bindings", []):
            if (
                binding["role"] == "rows"
                and binding["schema_id"] in profile["targets"]["tabular"]
            ):
                if sources[binding["source_id"]]["data_kind"] != "fabricated":
                    raise ValueError("Only authored fabricated templates can replay")
        with TemporaryDirectory(prefix="tablespec-template-") as temp:
            template = ImportedDataset(Path(temp) / "template.sqlite", pack_path)
            try:
                self._initialize(path, template, metadata, scale, seed, pack_path)
            finally:
                template.close()

    def _initialize(
        self,
        path: Path,
        template: ImportedDataset,
        metadata: dict[str, Any],
        scale: str,
        seed: int,
        pack_path: Path,
    ) -> None:
        profile = metadata["execution_profile"]
        components = profile["scales"][scale]
        if sum(template.counts.values()) * components > 1000000:
            raise ValueError("Expanded rows exceed budget")
        for name, spec in template.specs.items():
            primary = spec.get("primary_key", [])
            foreign = spec.get("relationships", {}).get("foreign_keys", [])
            columns = {c["name"]: c for c in spec["columns"]}
            expected = set(primary) | {fk["column"] for fk in foreign}
            if len(primary) != 1 or set(profile["identity_columns"][name]) != expected:
                raise ValueError(
                    "Replay requires exact primary/foreign identity columns"
                )
            if any(columns[c]["data_type"] != "VARCHAR" for c in expected):
                raise ValueError("Replay supports string identity columns only")
            for fk in foreign:
                parent = template.specs[fk["references_table"]]
                if parent.get("primary_key") != [fk["references_column"]]:
                    raise ValueError("Replay foreign key must target primary identity")
        GeneratedDataset.__init__(
            self,
            path,
            template.specs,
            dict.fromkeys(template.specs, 0),
            GenerationConfig(random_seed=seed),
        )
        self.config.domain = metadata["id"]
        self.source_artifacts = dict(template.source_artifacts)
        self.schema_artifacts = dict(template.schema_artifacts)
        self.artifact_hashes = dict(template.artifact_hashes)
        self.source_metadata = deepcopy(metadata)
        input_hashes = {
            name: source.get("checksum")
            for name, source in metadata["sources"].items()
            if source.get("reference") in self.source_artifacts
        }
        self.run_metadata = {
            "origin": "synthetic",
            "seed": seed,
            "generator": {"id": "tablespec.scenario-replay", "version": "1.0.0"},
            "scale": scale,
            "components": components,
            "input_hashes": input_hashes,
            "source_pack": {
                "id": metadata["id"],
                "version": metadata["version"],
                "sha256": hashlib.sha256(pack_path.read_bytes()).hexdigest(),
            },
            "schema_hashes": {
                reference: hashlib.sha256(path.read_bytes()).hexdigest()
                for reference, path in self.schema_artifacts.items()
            },
        }
        generated_id = "scenario_replay_output"
        if generated_id in self.source_metadata["sources"]:
            self.close()
            raise ValueError("Reserved replay source identity conflict")
        self.source_metadata["sources"][generated_id] = {
            "kind": "synthetic",
            "data_kind": "fabricated",
            "generator": self.run_metadata["generator"],
            "parameters": {"seed": seed, "components": components},
            "provenance": {
                "source_ids": sorted(input_hashes),
                "transformations": [
                    "Trusted independent-component replay with consistent identity remapping; source values unchanged."
                ],
            },
        }
        self.source_metadata["template_source_bindings"] = deepcopy(
            metadata.get("source_bindings", [])
        )
        self.source_metadata["template_fixture_counts"] = deepcopy(
            metadata.get("fixture_counts", {})
        )
        for binding in self.source_metadata.get("source_bindings", []):
            if binding["role"] == "rows" and binding["schema_id"] in template.specs:
                binding["source_id"] = generated_id
        try:
            for name, spec in self.specs.items():
                columns = [c for c in spec["columns"] if not c.get("internal")]
                unique, rules = self._constraints(spec, columns)
                index = 0
                for component in range(components):
                    for batch in template.batches(name):
                        for source_row in batch:
                            row = {
                                key: json.dumps(
                                    [seed, component, value],
                                    ensure_ascii=False,
                                    separators=(",", ":"),
                                )
                                if key in profile["identity_columns"][name]
                                and value is not None
                                else value
                                for key, value in source_row.items()
                            }
                            self._check(name, row, columns, unique, rules)
                            self.db.execute(
                                "INSERT INTO rows VALUES (?,?,?)",
                                (name, index, json.dumps(row, default=str)),
                            )
                            index += 1
                self.counts[name] = index
                self.report[name] = {
                    "row_count": index,
                    "fk_orphan_count": 0,
                    "null_violations": 0,
                    "uniqueness_violations": 0,
                }
            self.verify_foreign_keys()  # Same disk-backed FK checker.
            self.source_metadata["fixture_counts"] = dict(self.counts)
            self.db.commit()
            self.verified = True
        except BaseException:
            self.close()
            raise

    def batches(self, table: str, batch_size: int = 500):
        yield from ImportedDataset.batches(self, table, batch_size)

    def generate(self) -> dict[str, Any]:
        raise ValueError(
            "Replay is materialized at construction; generic generation is unavailable"
        )
