"""Explicit mixed-pack assembly: trusted generation plus fixed local source rows."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from shutil import copyfile
from tempfile import TemporaryDirectory

from tablespec.umf_loader import UMFLoader
from .config import GenerationConfig
from .domains import read_domain_pack
from .ingest import ImportedDataset, checked_source, local_artifact, validate_profile
from .streaming import GeneratedDataset, plan_counts


class MixedDataset(ImportedDataset):
    """Build and verify both subsets before any SQL target write.

    Observed rows are never replayed or assigned synthetic entity relationships.
    Local-use admission retains unknown rights; ZIP export still requires clearance.
    """

    def batches(self, table: str, batch_size: int = 500):
        # Preserve the generator's native numeric carriers; only imported CSV
        # decimals use ImportedDataset's exact lexical Decimal recovery.
        if table in (self.run_metadata or {}).get("generated_tables", []):
            yield from GeneratedDataset.batches(self, table, batch_size)
        else:
            yield from ImportedDataset.batches(self, table, batch_size)

    def __init__(
        self,
        path: Path,
        pack_path: Path,
        scale: str = "small",
        seed: int = 42,
        source_policy: str = "redistribution",
    ) -> None:
        metadata = read_domain_pack(pack_path)
        validate_profile(metadata)
        profile = metadata["execution_profile"]
        if profile["mode"] != "fixed":
            raise ValueError("Mixed assembly requires fixed observed inputs")
        selected = set(profile["targets"]["tabular"])
        bindings = {}
        for binding in metadata.get("source_bindings", []):
            if binding["role"] == "rows" and binding["schema_id"] in selected:
                if binding["schema_id"] in bindings:
                    raise ValueError("Mixed tables require exactly one row source")
                bindings[binding["schema_id"]] = binding["source_id"]
        if set(bindings) != selected:
            raise ValueError("Mixed tables require complete row bindings")
        generated = {
            n
            for n, s in bindings.items()
            if metadata["sources"][s]["kind"] == "synthetic"
        }
        observed = selected - generated
        if not generated or not observed:
            raise ValueError("Mixed assembly requires synthetic and external rows")
        for name in generated:
            source = metadata["sources"][bindings[name]]
            if source["data_kind"] != "fabricated" or source.get(
                "generator"
            ) != metadata.get("generator"):
                raise ValueError(
                    "Synthetic subset must resolve the declared trusted generator"
                )
        root = pack_path.resolve().parent
        schemas = {s["id"]: s for s in metadata["schemas"]}
        specs = {}
        artifacts = {}
        for name in selected:
            entry = schemas[name]
            if entry["format"] != "tablespec":
                raise ValueError("Mixed assembly requires TableSpec schemas")
            artifact = local_artifact(root, entry["reference"])
            if artifact.stat().st_size > 10 * 1024 * 1024:
                raise ValueError("Schema exceeds byte budget")
            spec = UMFLoader().load(artifact).model_dump(mode="json", exclude_none=True)
            if spec["table_name"] != name:
                raise ValueError("Schema identity must match its table name")
            # Cross-subset relationships need a separately authored merge policy.
            for fk in spec.get("relationships", {}).get("foreign_keys", []):
                parent = fk["references_table"]
                if parent not in selected or (name in generated) != (
                    parent in generated
                ):
                    raise ValueError("Unsupported cross-source relationship")
            specs[name] = spec
            artifacts[entry["reference"]] = artifact
        # Retain non-tabular schema artifacts without interpreting their semantics.
        for entry in metadata["schemas"]:
            if entry["reference"] not in artifacts:
                artifact = local_artifact(root, entry["reference"])
                if artifact.stat().st_size > 10 * 1024 * 1024:
                    raise ValueError("Schema exceeds byte budget")
                artifacts[entry["reference"]] = artifact
        with TemporaryDirectory(prefix="tablespec-mixed-inputs-") as temp:
            stage = Path(temp)
            for reference, artifact in artifacts.items():
                target = stage / reference
                target.parent.mkdir(parents=True, exist_ok=True)
                copyfile(artifact, target)
            included = set(profile["include_sources"]) | {bindings[n] for n in observed}
            source_artifacts = {}
            total = 0
            for id in included:
                source = metadata["sources"][id]
                reference = source.get("reference", "")
                if source["kind"] != "external" or not reference or ":" in reference:
                    continue
                artifact = checked_source(root, source, source_policy)
                total += artifact.stat().st_size
                if (
                    artifact.stat().st_size > 10 * 1024 * 1024
                    or total > 100 * 1024 * 1024
                ):
                    raise ValueError("Included sources exceed byte budget")
                target = stage / reference
                target.parent.mkdir(parents=True, exist_ok=True)
                copyfile(artifact, target)
                source_artifacts[reference] = artifact

            def subset(names, external):
                result = deepcopy(metadata)
                result["schemas"] = [schemas[n] for n in sorted(names)]
                result["source_bindings"] = [
                    b for b in metadata["source_bindings"] if b["schema_id"] in names
                ]
                result["execution_profile"]["targets"] = {"tabular": sorted(names)}
                result["execution_profile"]["include_sources"] = sorted(
                    included if external else {bindings[n] for n in names}
                )
                if not external:
                    result["sources"] = {
                        s: metadata["sources"][s] for s in {bindings[n] for n in names}
                    }
                destination = stage / (
                    "observed.json" if external else "generated.json"
                )
                destination.write_text(json.dumps(result))
                return destination

            generated_pack = subset(generated, False)
            observed_pack = subset(observed, True)
            config = GenerationConfig(
                domain=metadata["id"], domain_pack_path=generated_pack, random_seed=seed
            )
            presets = metadata.get("scale_presets")
            if presets and scale in presets:
                config.relationship_distributions = {
                    n: e.get("distribution", "skewed")
                    for n, e in presets[scale]["children"].items()
                }
            synthetic_specs = {n: specs[n] for n in generated}
            synthetic = GeneratedDataset(
                stage / "generated.sqlite",
                synthetic_specs,
                plan_counts(synthetic_specs, scale, presets=presets),
                config,
            )
            try:
                synthetic.generate()
                external = ImportedDataset(
                    stage / "observed.sqlite", observed_pack, source_policy
                )
                try:
                    GeneratedDataset.__init__(
                        self,
                        path,
                        specs,
                        {**synthetic.counts, **external.counts},
                        GenerationConfig(domain=metadata["id"], random_seed=seed),
                    )
                    try:
                        for dataset in (synthetic, external):
                            for name in dataset.specs:
                                for idx, body in dataset.db.execute(
                                    "SELECT idx,body FROM rows WHERE tbl=? ORDER BY idx",
                                    (name,),
                                ):
                                    self.db.execute(
                                        "INSERT INTO rows VALUES (?,?,?)",
                                        (name, idx, body),
                                    )
                        self.report = {**synthetic.report, **external.report}
                        self.source_metadata = metadata
                        self.source_artifacts = source_artifacts
                        self.schema_artifacts = artifacts
                        self.artifact_hashes = {
                            str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                            for p in [*artifacts.values(), *source_artifacts.values()]
                        }
                        self.run_metadata = {
                            "origin": "mixed",
                            "source_policy": source_policy,
                            "scale": scale,
                            "seed": seed,
                            "generated_tables": sorted(generated),
                            "fixed_tables": sorted(observed),
                            "pack_sha256": hashlib.sha256(
                                pack_path.read_bytes()
                            ).hexdigest(),
                        }
                        self.verify_foreign_keys()
                        self.db.commit()
                        self.verified = True
                    except BaseException:
                        self.close()
                        raise
                finally:
                    external.close()
            finally:
                synthetic.close()
