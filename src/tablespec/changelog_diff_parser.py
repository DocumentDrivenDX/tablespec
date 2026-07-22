"""Parse YAML diffs to detect specific changes in validation rules, columns, and relationships."""

from dataclasses import dataclass
from typing import Any

from ruamel.yaml import YAML


@dataclass
class ValidationChange:
    """Specific change to a validation rule."""

    rule_id: str
    column: str | None
    rule_type: str
    rule_index: int | None
    change_field: str  # 'severity', 'kwargs.key', 'added', 'removed'
    old_value: Any
    new_value: Any
    table_name: str | None = None  # Name of the table being changed

    def format_description(self) -> str:
        """Format as human-readable description."""
        rule_str = f"{self.rule_type}"
        if self.rule_index is not None:
            rule_str += f".{self.rule_index}"

        # Build key: table.column.rule_type.index
        if self.column:
            key_str = f"{self.column}.{rule_str}"
            if self.table_name:
                key_str = f"{self.table_name}.{key_str}"
        else:
            key_str = rule_str
            if self.table_name:
                key_str = f"{self.table_name}.{key_str}"

        if self.change_field == "severity":
            return (
                f"Changed {key_str} severity from {self.old_value} to {self.new_value}"
            )
        if self.change_field.startswith("kwargs."):
            field_name = self.change_field.split(".", 1)[1]
            return f"Changed {key_str} {field_name} from {self.old_value} to {self.new_value}"
        if self.change_field == "added":
            return f"Added {key_str}"
        if self.change_field == "removed":
            return f"Removed {key_str}"
        return f"Changed {key_str} {self.change_field} from {self.old_value} to {self.new_value}"


@dataclass
class ColumnChange:
    """Specific change to a column definition."""

    column_name: str
    change_field: str  # 'data_type', 'length', 'nullable', 'description', etc.
    old_value: Any
    new_value: Any
    table_name: str | None = None  # Name of the table being changed

    def format_description(self) -> str:
        """Format as human-readable description."""
        col_ref = (
            f"{self.table_name}.{self.column_name}"
            if self.table_name
            else self.column_name
        )
        if self.change_field == "data_type":
            return f"Changed {col_ref} type from {self.old_value} to {self.new_value}"
        if self.change_field == "nullable":
            return (
                f"Changed {col_ref} nullable from {self.old_value} to {self.new_value}"
            )
        return f"Changed {col_ref} {self.change_field} from {self.old_value} to {self.new_value}"


@dataclass
class RelationshipChange:
    """Specific change to a relationship definition."""

    fk_column: str
    change_field: str  # 'references_table', 'references_column', 'confidence'
    old_value: Any
    new_value: Any
    table_name: str | None = None  # Name of the table being changed

    def format_description(self) -> str:
        """Format as human-readable description."""
        fk_ref = (
            f"{self.table_name}.{self.fk_column}" if self.table_name else self.fk_column
        )
        if self.change_field == "added":
            return f"Added foreign key {fk_ref} → {self.new_value}"
        if self.change_field == "removed":
            return f"Removed foreign key {fk_ref}"
        if self.change_field == "references_table":
            return f"Changed foreign key {fk_ref} table from {self.old_value} to {self.new_value}"
        if self.change_field == "references_column":
            return f"Changed foreign key {fk_ref} column from {self.old_value} to {self.new_value}"
        return (
            f"Changed foreign key {fk_ref} {self.change_field} "
            f"from {self.old_value} to {self.new_value}"
        )


@dataclass
class MetadataChange:
    """Specific change to table metadata."""

    change_field: str  # 'table_name', 'description', 'canonical_name', 'version', etc.
    old_value: Any
    new_value: Any

    def format_description(self) -> str:
        """Format as human-readable description."""
        return f"Changed {self.change_field} from {self.old_value} to {self.new_value}"


@dataclass
class DerivationChange:
    """Specific change to derivation/survivorship rules."""

    target_column: str
    change_field: str  # 'mappings', 'strategy', 'candidates', etc.
    old_value: Any
    new_value: Any
    table_name: str | None = None  # Name of the table being changed

    def format_description(self) -> str:
        """Format as human-readable description."""
        col_ref = (
            f"{self.table_name}.{self.target_column}"
            if self.table_name
            else self.target_column
        )
        if self.change_field == "strategy":
            return f"Changed {col_ref} survivorship strategy from {self.old_value} to {self.new_value}"
        if self.change_field == "candidates":
            return f"Modified {col_ref} source candidates"
        return f"Changed {col_ref} {self.change_field}"


class YAMLDiffParser:
    """Parse YAML diffs to extract semantic changes."""

    def __init__(self) -> None:
        """Initialize YAML parser."""
        self.yaml = YAML()

    def parse_validation_changes(
        self,
        old_content: str,
        new_content: str,
        table_name: str = "unknown",
    ) -> list[ValidationChange]:
        """Parse validation YAML diff and detect specific rule changes.

        Args:
            old_content: Old YAML content as string
            new_content: New YAML content as string
            table_name: Table name for composite key generation

        Returns:
            List of ValidationChange objects

        """
        try:
            old_data = self.yaml.load(old_content) if old_content else {}
            new_data = self.yaml.load(new_content) if new_content else {}
        except Exception:
            return []

        changes = []

        old_expectations = old_data.get("expectations", []) if old_data else []
        new_expectations = new_data.get("expectations", []) if new_data else []

        # Build maps for easier lookup using composite keys: table.column.type.index
        # Sort expectations for stable indexing: by column, rule_type, description
        old_sorted = sorted(
            enumerate(old_expectations),
            key=lambda x: (
                x[1].get("kwargs", {}).get("column", ""),
                x[1].get("type", ""),
                x[1].get("meta", {}).get("description", ""),
            ),
        )
        new_sorted = sorted(
            enumerate(new_expectations),
            key=lambda x: (
                x[1].get("kwargs", {}).get("column", ""),
                x[1].get("type", ""),
                x[1].get("meta", {}).get("description", ""),
            ),
        )

        old_by_rule_id = {
            self._get_composite_key(exp, table_name, i): exp
            for i, (_, exp) in enumerate(old_sorted)
        }
        new_by_rule_id = {
            self._get_composite_key(exp, table_name, i): exp
            for i, (_, exp) in enumerate(new_sorted)
        }

        # Find added rules
        for rule_id, new_exp in new_by_rule_id.items():
            if rule_id not in old_by_rule_id:
                changes.append(
                    ValidationChange(
                        rule_id=rule_id,
                        column=new_exp.get("kwargs", {}).get("column"),
                        rule_type=self._get_rule_type(new_exp),
                        rule_index=self._get_rule_index(new_exp),
                        change_field="added",
                        old_value=None,
                        new_value=None,
                        table_name=table_name,
                    )
                )

        # Find removed rules
        for rule_id, old_exp in old_by_rule_id.items():
            if rule_id not in new_by_rule_id:
                changes.append(
                    ValidationChange(
                        rule_id=rule_id,
                        column=old_exp.get("kwargs", {}).get("column"),
                        rule_type=self._get_rule_type(old_exp),
                        rule_index=self._get_rule_index(old_exp),
                        change_field="removed",
                        old_value=None,
                        new_value=None,
                        table_name=table_name,
                    )
                )

        # Find modified rules
        for rule_id, new_exp in new_by_rule_id.items():
            if rule_id not in old_by_rule_id:
                continue

            old_exp = old_by_rule_id[rule_id]

            # Check metadata changes
            old_meta = old_exp.get("meta", {})
            new_meta = new_exp.get("meta", {})

            for field in ["severity", "description"]:
                old_val = old_meta.get(field)
                new_val = new_meta.get(field)
                if old_val != new_val:
                    changes.append(
                        ValidationChange(
                            rule_id=rule_id,
                            column=new_exp.get("kwargs", {}).get("column"),
                            rule_type=self._get_rule_type(new_exp),
                            rule_index=self._get_rule_index(new_exp),
                            change_field=field,
                            old_value=old_val,
                            new_value=new_val,
                            table_name=table_name,
                        )
                    )

            # Check kwargs changes
            old_kwargs = old_exp.get("kwargs", {})
            new_kwargs = new_exp.get("kwargs", {})

            for key in set(list(old_kwargs.keys()) + list(new_kwargs.keys())):
                old_val = old_kwargs.get(key)
                new_val = new_kwargs.get(key)
                if old_val != new_val:
                    changes.append(
                        ValidationChange(
                            rule_id=rule_id,
                            column=new_kwargs.get("column"),
                            rule_type=self._get_rule_type(new_exp),
                            rule_index=self._get_rule_index(new_exp),
                            change_field=f"kwargs.{key}",
                            old_value=old_val,
                            new_value=new_val,
                            table_name=table_name,
                        )
                    )

        return changes

    def parse_column_changes(
        self,
        old_content: str,
        new_content: str,
        table_name: str = "unknown",
    ) -> list[ColumnChange]:
        """Parse column YAML diff and detect specific field changes.

        Args:
            old_content: Old YAML content as string
            new_content: New YAML content as string

        Returns:
            List of ColumnChange objects

        """
        try:
            old_data = self.yaml.load(old_content) if old_content else {}
            new_data = self.yaml.load(new_content) if new_content else {}
        except Exception:
            return []

        changes = []

        old_columns = old_data.get("columns", []) if old_data else []
        new_columns = new_data.get("columns", []) if new_data else []

        # Build maps by column name
        old_by_name = {col.get("name"): col for col in old_columns}
        new_by_name = {col.get("name"): col for col in new_columns}

        # Find added/removed/modified columns
        for col_name in set(list(old_by_name.keys()) + list(new_by_name.keys())):
            old_col = old_by_name.get(col_name)
            new_col = new_by_name.get(col_name)

            if old_col and new_col:
                # Check for field changes
                for field in ["data_type", "length", "description", "nullable"]:
                    old_val = old_col.get(field)
                    new_val = new_col.get(field)
                    if old_val != new_val:
                        changes.append(
                            ColumnChange(
                                column_name=col_name,
                                change_field=field,
                                old_value=old_val,
                                new_value=new_val,
                                table_name=table_name,
                            )
                        )

        return changes

    def parse_relationship_changes(
        self,
        old_content: str,
        new_content: str,
        table_name: str = "unknown",
    ) -> list[RelationshipChange]:
        """Parse relationship YAML diff and detect specific changes.

        Args:
            old_content: Old YAML content as string
            new_content: New YAML content as string

        Returns:
            List of RelationshipChange objects

        """
        try:
            old_data = self.yaml.load(old_content) if old_content else {}
            new_data = self.yaml.load(new_content) if new_content else {}
        except Exception:
            return []

        changes = []

        old_fks = old_data.get("foreign_keys", []) if old_data else []
        new_fks = new_data.get("foreign_keys", []) if new_data else []

        # Build maps by column name
        old_by_col = {fk.get("column"): fk for fk in old_fks}
        new_by_col = {fk.get("column"): fk for fk in new_fks}

        # Find added/removed/modified relationships
        for col_name in set(list(old_by_col.keys()) + list(new_by_col.keys())):
            old_fk = old_by_col.get(col_name)
            new_fk = new_by_col.get(col_name)

            if old_fk and not new_fk:
                # Relationship was removed
                changes.append(
                    RelationshipChange(
                        fk_column=col_name,
                        change_field="removed",
                        old_value=f"{old_fk.get('references_table')}.{old_fk.get('references_column')}",
                        new_value=None,
                        table_name=table_name,
                    )
                )
            elif not old_fk and new_fk:
                # Relationship was added
                changes.append(
                    RelationshipChange(
                        fk_column=col_name,
                        change_field="added",
                        old_value=None,
                        new_value=f"{new_fk.get('references_table')}.{new_fk.get('references_column')}",
                        table_name=table_name,
                    )
                )
            elif old_fk and new_fk:
                # Check for field changes
                for field in ["references_table", "references_column", "confidence"]:
                    old_val = old_fk.get(field)
                    new_val = new_fk.get(field)
                    if old_val != new_val:
                        changes.append(
                            RelationshipChange(
                                fk_column=col_name,
                                change_field=field,
                                old_value=old_val,
                                new_value=new_val,
                                table_name=table_name,
                            )
                        )

        return changes

    def parse_metadata_changes(
        self,
        old_content: str,
        new_content: str,
    ) -> list[MetadataChange]:
        """Parse table metadata changes.

        Args:
            old_content: Old YAML content as string
            new_content: New YAML content as string

        Returns:
            List of MetadataChange objects

        """
        try:
            old_data = self.yaml.load(old_content) if old_content else {}
            new_data = self.yaml.load(new_content) if new_content else {}
        except Exception:
            return []

        changes = []

        # Check metadata fields
        for field in [
            "table_name",
            "description",
            "canonical_name",
            "version",
            "table_type",
        ]:
            old_val = old_data.get(field) if old_data else None
            new_val = new_data.get(field) if new_data else None

            if old_val != new_val:
                changes.append(
                    MetadataChange(
                        change_field=field,
                        old_value=old_val,
                        new_value=new_val,
                    )
                )

        return changes

    def parse_derivation_changes(
        self,
        old_content: str,
        new_content: str,
        table_name: str = "unknown",
    ) -> list[DerivationChange]:
        """Parse derivation/survivorship rule changes.

        Args:
            old_content: Old YAML content as string
            new_content: New YAML content as string
            table_name: Table name for context

        Returns:
            List of DerivationChange objects

        """
        try:
            old_data = self.yaml.load(old_content) if old_content else {}
            new_data = self.yaml.load(new_content) if new_content else {}
        except Exception:
            return []

        changes = []

        old_derivations = old_data.get("derivations", {}) if old_data else {}
        new_derivations = new_data.get("derivations", {}) if new_data else {}

        old_mappings = old_derivations.get("mappings", {})
        new_mappings = new_derivations.get("mappings", {})

        # Check for added/removed/modified mappings
        for col_name in set(list(old_mappings.keys()) + list(new_mappings.keys())):
            old_mapping = old_mappings.get(col_name)
            new_mapping = new_mappings.get(col_name)

            if old_mapping and new_mapping:
                # Check survivorship strategy
                old_strategy = old_mapping.get("survivorship", {}).get("strategy")
                new_strategy = new_mapping.get("survivorship", {}).get("strategy")
                if old_strategy != new_strategy:
                    changes.append(
                        DerivationChange(
                            target_column=col_name,
                            change_field="strategy",
                            old_value=old_strategy,
                            new_value=new_strategy,
                            table_name=table_name,
                        )
                    )

                # Check candidates
                old_candidates = old_mapping.get("candidates")
                new_candidates = new_mapping.get("candidates")
                if old_candidates != new_candidates:
                    changes.append(
                        DerivationChange(
                            target_column=col_name,
                            change_field="candidates",
                            old_value=len(old_candidates) if old_candidates else 0,
                            new_value=len(new_candidates) if new_candidates else 0,
                            table_name=table_name,
                        )
                    )

        return changes

    def _get_composite_key(
        self, expectation: dict, table_name: str, position: int
    ) -> str:
        """Create composite key: table.column.type.position.

        This ensures uniqueness even when rule_id is not present or not unique.
        Format: table_name.column.rule_type.position_in_yaml_array
        Example: outreach_list.birth_date.column_to_exist.0

        Args:
            expectation: Expectation dict from YAML
            table_name: Name of the table
            position: Position of expectation in the expectations array

        """
        column = expectation.get("kwargs", {}).get("column", "table")
        rule_type = self._get_rule_type(expectation)
        return f"{table_name}.{column}.{rule_type}.{position}"

    def _get_rule_id(self, expectation: dict) -> str:
        """Extract rule_id from expectation metadata.

        NOTE: This method is deprecated. Use _get_composite_key() instead,
        as many expectations don't have rule_id in metadata.
        """
        return expectation.get("meta", {}).get("rule_id", "unknown")

    def _get_rule_type(self, expectation: dict) -> str:
        """Extract rule type (without 'expect_' prefix)."""
        exp_type = expectation.get("type", "unknown")
        return exp_type.replace("expect_", "")

    def _get_rule_index(self, expectation: dict) -> int | None:
        """Extract rule index from expectation metadata."""
        return expectation.get("meta", {}).get("rule_index")
