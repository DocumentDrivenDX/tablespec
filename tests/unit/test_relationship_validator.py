"""Unit tests for relationship_validator module."""

import pytest

from tablespec.models import (
    ForeignKey,
    IncomingRelationship,
    Relationships,
    UMF,
    UMFColumn,
)
from tablespec.relationship_validator import RelationshipValidator

pytestmark = [pytest.mark.no_spark, pytest.mark.fast]


def _make_umf(
    table_name: str,
    columns: list[str],
    foreign_keys: list[ForeignKey] | None = None,
    incoming: list[IncomingRelationship] | None = None,
    aliases: list[str] | None = None,
) -> UMF:
    """Helper to create a minimal UMF with given columns and relationships."""
    cols = [UMFColumn(name=c, data_type="VARCHAR") for c in columns]
    relationships = None
    if foreign_keys or incoming:
        relationships = Relationships(foreign_keys=foreign_keys, incoming=incoming)
    return UMF(
        table_name=table_name,
        version="1.0",
        columns=cols,
        relationships=relationships,
        aliases=aliases,
    )


class TestValidateForeignKeys:
    """Tests for validate_foreign_keys method."""

    def test_no_relationships_returns_empty(self):
        """Table with no relationships should return no errors."""
        umf = _make_umf("orders", ["id", "customer_id"])
        validator = RelationshipValidator()
        errors = validator.validate_foreign_keys(umf, {})
        assert errors == []

    def test_valid_foreign_key(self):
        """Valid FK referencing existing table and column should pass."""
        fk = ForeignKey(
            column="customer_id", references_table="customers", references_column="id"
        )
        orders = _make_umf("orders", ["id", "customer_id"], foreign_keys=[fk])
        customers = _make_umf("customers", ["id", "name"])

        validator = RelationshipValidator()
        errors = validator.validate_foreign_keys(orders, {"customers": customers})
        assert errors == []

    def test_missing_source_column(self):
        """FK referencing a column that doesn't exist in source table."""
        fk = ForeignKey(
            column="nonexistent", references_table="customers", references_column="id"
        )
        orders = _make_umf("orders", ["id", "customer_id"], foreign_keys=[fk])
        customers = _make_umf("customers", ["id", "name"])

        validator = RelationshipValidator()
        errors = validator.validate_foreign_keys(orders, {"customers": customers})
        assert len(errors) == 1
        assert errors[0][0] == "missing_source_column"
        assert "nonexistent" in errors[0][1]

    def test_missing_referenced_table(self):
        """FK referencing a table that doesn't exist."""
        fk = ForeignKey(
            column="customer_id", references_table="nonexistent", references_column="id"
        )
        orders = _make_umf("orders", ["id", "customer_id"], foreign_keys=[fk])

        validator = RelationshipValidator()
        errors = validator.validate_foreign_keys(orders, {})
        assert len(errors) == 1
        assert errors[0][0] == "missing_referenced_table"
        assert "nonexistent" in errors[0][1]

    def test_missing_referenced_column(self):
        """FK referencing a column that doesn't exist in the referenced table."""
        fk = ForeignKey(
            column="customer_id",
            references_table="customers",
            references_column="nonexistent",
        )
        orders = _make_umf("orders", ["id", "customer_id"], foreign_keys=[fk])
        customers = _make_umf("customers", ["id", "name"])

        validator = RelationshipValidator()
        errors = validator.validate_foreign_keys(orders, {"customers": customers})
        assert len(errors) == 1
        assert errors[0][0] == "missing_referenced_column"
        assert "nonexistent" in errors[0][1]

    def test_referenced_table_found_via_alias(self):
        """FK should resolve tables by alias when direct name lookup fails."""
        fk = ForeignKey(
            column="customer_id", references_table="cust", references_column="id"
        )
        orders = _make_umf("orders", ["id", "customer_id"], foreign_keys=[fk])
        customers = _make_umf("customers", ["id", "name"], aliases=["cust"])

        validator = RelationshipValidator()
        errors = validator.validate_foreign_keys(orders, {"customers": customers})
        assert errors == []

    def test_case_insensitive_column_match(self):
        """FK column matching should be case-insensitive."""
        fk = ForeignKey(
            column="Customer_ID", references_table="customers", references_column="ID"
        )
        orders = _make_umf("orders", ["id", "customer_id"], foreign_keys=[fk])
        customers = _make_umf("customers", ["id", "name"])

        validator = RelationshipValidator()
        errors = validator.validate_foreign_keys(orders, {"customers": customers})
        assert errors == []

    def test_multiple_foreign_keys(self):
        """Multiple FKs should each be validated independently."""
        fk1 = ForeignKey(
            column="customer_id", references_table="customers", references_column="id"
        )
        fk2 = ForeignKey(
            column="product_id", references_table="products", references_column="id"
        )
        orders = _make_umf(
            "orders", ["id", "customer_id", "product_id"], foreign_keys=[fk1, fk2]
        )
        customers = _make_umf("customers", ["id", "name"])
        # products table missing

        validator = RelationshipValidator()
        errors = validator.validate_foreign_keys(orders, {"customers": customers})
        assert len(errors) == 1
        assert errors[0][0] == "missing_referenced_table"
        assert "products" in errors[0][1]

    def test_errors_reset_between_calls(self):
        """Errors list should reset on each call to validate_foreign_keys."""
        fk = ForeignKey(
            column="bad_col", references_table="customers", references_column="id"
        )
        orders = _make_umf("orders", ["id"], foreign_keys=[fk])

        validator = RelationshipValidator()
        errors1 = validator.validate_foreign_keys(
            orders, {"customers": _make_umf("customers", ["id"])}
        )
        assert len(errors1) == 1

        # Second call with valid data
        fk2 = ForeignKey(
            column="id", references_table="customers", references_column="id"
        )
        orders2 = _make_umf("orders", ["id"], foreign_keys=[fk2])
        errors2 = validator.validate_foreign_keys(
            orders2, {"customers": _make_umf("customers", ["id"])}
        )
        assert errors2 == []


class TestValidateIncomingRelationships:
    """Tests for validate_incoming_relationships method."""

    def test_no_incoming_returns_empty(self):
        """Table with no incoming relationships should return no errors."""
        umf = _make_umf("customers", ["id", "name"])
        validator = RelationshipValidator()
        errors = validator.validate_incoming_relationships(umf, {})
        assert errors == []

    def test_valid_incoming_relationship(self):
        """Valid incoming relationship should pass."""
        inc = IncomingRelationship(
            source_table="orders",
            source_column="customer_id",
            target_column="id",
            type="foreign_key",
            confidence=0.9,
        )
        customers = _make_umf("customers", ["id", "name"], incoming=[inc])
        orders = _make_umf("orders", ["id", "customer_id"])

        validator = RelationshipValidator()
        errors = validator.validate_incoming_relationships(
            customers, {"orders": orders}
        )
        assert errors == []

    def test_missing_source_table(self):
        """Incoming relationship from non-existent table should error."""
        inc = IncomingRelationship(
            source_table="nonexistent",
            source_column="customer_id",
            target_column="id",
            type="foreign_key",
            confidence=0.9,
        )
        customers = _make_umf("customers", ["id", "name"], incoming=[inc])

        validator = RelationshipValidator()
        errors = validator.validate_incoming_relationships(customers, {})
        assert len(errors) == 1
        assert errors[0][0] == "missing_source_table_for_incoming"
        assert "nonexistent" in errors[0][1]

    def test_missing_source_column(self):
        """Incoming relationship referencing non-existent column in source table."""
        inc = IncomingRelationship(
            source_table="orders",
            source_column="nonexistent",
            target_column="id",
            type="foreign_key",
            confidence=0.9,
        )
        customers = _make_umf("customers", ["id", "name"], incoming=[inc])
        orders = _make_umf("orders", ["id", "product_id"])

        validator = RelationshipValidator()
        errors = validator.validate_incoming_relationships(
            customers, {"orders": orders}
        )
        assert len(errors) == 1
        assert errors[0][0] == "missing_source_column_for_incoming"
        assert "nonexistent" in errors[0][1]

    def test_source_table_found_via_alias(self):
        """Incoming relationship should resolve source table by alias."""
        inc = IncomingRelationship(
            source_table="ord",
            source_column="customer_id",
            target_column="id",
            type="foreign_key",
            confidence=0.9,
        )
        customers = _make_umf("customers", ["id", "name"], incoming=[inc])
        orders = _make_umf("orders", ["id", "customer_id"], aliases=["ord"])

        validator = RelationshipValidator()
        errors = validator.validate_incoming_relationships(
            customers, {"orders": orders}
        )
        assert errors == []


class TestValidateAllRelationships:
    """Tests for validate_all_relationships method."""

    def test_empty_table_list(self):
        """Empty table list should return empty results."""
        validator = RelationshipValidator()
        results = validator.validate_all_relationships([])
        assert results == {}

    def test_tables_with_no_relationships(self):
        """Tables without relationships should return empty results."""
        t1 = _make_umf("table_a", ["id", "name"])
        t2 = _make_umf("table_b", ["id", "value"])

        validator = RelationshipValidator()
        results = validator.validate_all_relationships([t1, t2])
        assert results == {}

    def test_valid_cross_table_relationships(self):
        """Valid FK between two tables should return empty results."""
        fk = ForeignKey(
            column="customer_id", references_table="customers", references_column="id"
        )
        orders = _make_umf("orders", ["id", "customer_id"], foreign_keys=[fk])
        customers = _make_umf("customers", ["id", "name"])

        validator = RelationshipValidator()
        results = validator.validate_all_relationships([orders, customers])
        assert results == {}

    def test_invalid_fk_detected_in_batch(self):
        """Invalid FK in batch validation should report errors for that table."""
        fk = ForeignKey(
            column="customer_id", references_table="nonexistent", references_column="id"
        )
        orders = _make_umf("orders", ["id", "customer_id"], foreign_keys=[fk])
        customers = _make_umf("customers", ["id", "name"])

        validator = RelationshipValidator()
        results = validator.validate_all_relationships([orders, customers])
        assert "orders" in results
        assert any("nonexistent" in msg for _, msg in results["orders"])

    def test_alias_lookup_in_batch(self):
        """Batch validation should resolve table aliases."""
        fk = ForeignKey(
            column="customer_id", references_table="cust", references_column="id"
        )
        orders = _make_umf("orders", ["id", "customer_id"], foreign_keys=[fk])
        customers = _make_umf("customers", ["id", "name"], aliases=["cust"])

        validator = RelationshipValidator()
        results = validator.validate_all_relationships([orders, customers])
        assert results == {}

    def test_both_fk_and_incoming_validated(self):
        """Both foreign keys and incoming relationships should be validated."""
        fk = ForeignKey(
            column="bad_col", references_table="customers", references_column="id"
        )
        inc = IncomingRelationship(
            source_table="nonexistent",
            source_column="x",
            target_column="id",
            type="foreign_key",
            confidence=0.9,
        )
        orders = _make_umf("orders", ["id"], foreign_keys=[fk], incoming=[inc])
        customers = _make_umf("customers", ["id", "name"])

        validator = RelationshipValidator()
        results = validator.validate_all_relationships([orders, customers])
        assert "orders" in results
        error_types = [et for et, _ in results["orders"]]
        assert "missing_source_column" in error_types
        assert "missing_source_table_for_incoming" in error_types
