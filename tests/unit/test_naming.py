# @covers US-027-AC1
"""Tests for table naming utilities."""

import pytest

from tablespec.naming import (
    excel_column_to_number,
    position_sort_key,
    to_snake_case,
    to_spark_identifier,
)

pytestmark = [pytest.mark.no_spark, pytest.mark.fast]


class TestToSnakeCase:
    """Test snake_case conversion function."""

    def test_pascal_case(self):
        """Convert PascalCase to snake_case."""
        assert to_snake_case("OutreachList") == "outreach_list"
        assert to_snake_case("DisenrollmentFile") == "disenrollment_file"
        assert to_snake_case("MemberData") == "member_data"

    def test_camel_case(self):
        """Convert camelCase to snake_case."""
        assert to_snake_case("outreachList") == "outreach_list"
        assert to_snake_case("memberData") == "member_data"

    def test_with_existing_underscores(self):
        """Handle names with existing underscores."""
        assert to_snake_case("VAP_OutreachListPCP") == "vap_outreach_list_pcp"
        assert to_snake_case("VAP_Outreachlist") == "vap_outreachlist"
        assert to_snake_case("OutreachListPCP") == "outreach_list_pcp"

    def test_mixed_case_with_underscores(self):
        """Handle mixed case with underscores."""
        assert to_snake_case("Centene_Disposition_V_4_0") == "centene_disposition_v_4_0"
        assert to_snake_case("X1_OM_CallLog") == "x1_om_call_log"
        assert to_snake_case("Test_Disposition") == "test_disposition"

    def test_all_caps_with_underscores(self):
        """Handle ALL_CAPS with underscores."""
        assert to_snake_case("VAP_OPTOUT") == "vap_optout"
        assert to_snake_case("FILE_VERSION_HISTORY") == "file_version_history"

    def test_already_snake_case(self):
        """Handle names already in snake_case."""
        assert to_snake_case("outreach_list") == "outreach_list"
        assert to_snake_case("member_data") == "member_data"
        assert to_snake_case("vap_optout") == "vap_optout"

    def test_single_word(self):
        """Handle single words."""
        assert to_snake_case("Member") == "member"
        assert to_snake_case("member") == "member"
        assert to_snake_case("MEMBER") == "member"

    def test_acronyms(self):
        """Handle acronyms properly."""
        assert to_snake_case("HTTPResponse") == "http_response"
        assert to_snake_case("XMLParser") == "xml_parser"
        assert to_snake_case("IOError") == "io_error"

    def test_leading_trailing_underscores(self):
        """Remove leading/trailing underscores."""
        assert to_snake_case("_OutreachList") == "outreach_list"
        assert to_snake_case("OutreachList_") == "outreach_list"
        assert to_snake_case("_OutreachList_") == "outreach_list"

    def test_multiple_consecutive_underscores(self):
        """Collapse multiple consecutive underscores."""
        assert to_snake_case("Outreach__List") == "outreach_list"
        assert to_snake_case("VAP___Outreach") == "vap_outreach"

    def test_numbers(self):
        """Handle numbers in names."""
        assert to_snake_case("Table2") == "table2"
        assert to_snake_case("V4_0") == "v4_0"
        assert to_snake_case("Member2024") == "member2024"

    def test_periods(self):
        """Handle periods in names (e.g., version numbers)."""
        assert to_snake_case("V4.0") == "v4_0"
        assert to_snake_case("Version.1.2.3") == "version_1_2_3"
        assert to_snake_case("File.v2.5") == "file_v2_5"
        # Real-world case from centene_2026_iha
        assert to_snake_case("Centene_Disposition_V_4.0") == "centene_disposition_v_4_0"

    def test_real_world_examples(self):
        """Test with real-world table names from the project."""
        # From centene2026
        assert to_snake_case("Centene_Disposition_V_4_0") == "centene_disposition_v_4_0"
        assert to_snake_case("Centene_VAP_Disposition") == "centene_vap_disposition"
        assert to_snake_case("DisenrollmentFile") == "disenrollment_file"
        assert to_snake_case("Disposition_Error_Files") == "disposition_error_files"
        assert to_snake_case("Disposition_Statuses") == "disposition_statuses"
        assert to_snake_case("IN_IHA_VAP_Crosswalk") == "in_iha_vap_crosswalk"
        assert to_snake_case("IncentiveUpdate") == "incentive_update"
        assert to_snake_case("Lab_File") == "lab_file"
        assert to_snake_case("Medical_Claims") == "medical_claims"
        assert to_snake_case("OptoutList") == "optout_list"
        assert to_snake_case("OutreachList") == "outreach_list"
        assert to_snake_case("OutreachListDiags") == "outreach_list_diags"
        assert to_snake_case("OutreachListGaps") == "outreach_list_gaps"
        assert to_snake_case("OutreachListGuardian") == "outreach_list_guardian"
        assert to_snake_case("OutreachListPCP") == "outreach_list_pcp"
        assert to_snake_case("Pharmacy_Claims") == "pharmacy_claims"
        assert to_snake_case("SupplementalContact") == "supplemental_contact"
        assert to_snake_case("SupplementalEmail") == "supplemental_email"
        assert to_snake_case("SupplementalPhone") == "supplemental_phone"
        assert to_snake_case("VAP_DisenrollmentFile") == "vap_disenrollment_file"
        assert to_snake_case("VAP_Optout") == "vap_optout"
        assert to_snake_case("VAP_OutreachListPCP") == "vap_outreach_list_pcp"
        assert to_snake_case("VAP_Outreachlist") == "vap_outreachlist"
        assert to_snake_case("VAP_SupplementalContact") == "vap_supplemental_contact"

        # From testdata
        assert to_snake_case("DispositionReport_Test") == "disposition_report_test"
        assert to_snake_case("Test_Disposition") == "test_disposition"


class TestToSparkIdentifier:
    """Test Spark/SQL identifier conversion."""

    def test_spaces_to_underscores(self):
        """Spaces become underscores."""
        assert to_spark_identifier("Member ID") == "member_id"
        assert to_spark_identifier("First Name Last Name") == "first_name_last_name"

    def test_hyphens_and_special_chars(self):
        """Hyphens and special characters become underscores."""
        assert (
            to_spark_identifier("Inbound Only-Warm Transfer")
            == "inbound_only_warm_transfer"
        )
        assert to_spark_identifier("ICD9/10") == "icd9_10"

    def test_pascal_case(self):
        """PascalCase is converted to snake_case."""
        assert to_spark_identifier("OutreachList") == "outreach_list"
        assert to_spark_identifier("MemberData") == "member_data"

    def test_digit_prefix(self):
        """Names starting with digit get 'col_' prefix."""
        assert to_spark_identifier("123_column") == "col_123_column"
        assert to_spark_identifier("1st_field") == "col_1st_field"

    def test_empty_string(self):
        """Empty string returns 'unknown'."""
        assert to_spark_identifier("") == "unknown"

    def test_already_valid(self):
        """Already valid identifiers pass through."""
        assert to_spark_identifier("member_id") == "member_id"

    def test_leading_trailing_underscores(self):
        """Leading/trailing underscores are removed."""
        assert to_spark_identifier("_member_") == "member"
        assert to_spark_identifier("__test__") == "test"

    def test_multiple_underscores(self):
        """Multiple underscores are collapsed."""
        assert to_spark_identifier("a___b") == "a_b"

    def test_all_special_chars(self):
        """String of only special chars returns 'unknown'."""
        assert to_spark_identifier("---") == "unknown"
        assert to_spark_identifier("///") == "unknown"

    def test_mixed_special_and_camel(self):
        """Mixed special characters and camelCase."""
        assert to_spark_identifier("Hello World!") == "hello_world"
        assert to_spark_identifier("Col#1") == "col_1"


class TestExcelColumnToNumber:
    """Test Excel column letter to number conversion."""

    def test_single_letters(self):
        """Single letters A-Z map to 1-26."""
        assert excel_column_to_number("A") == 1
        assert excel_column_to_number("B") == 2
        assert excel_column_to_number("Z") == 26

    def test_double_letters(self):
        """Double letters AA-AZ map to 27-52."""
        assert excel_column_to_number("AA") == 27
        assert excel_column_to_number("AB") == 28
        assert excel_column_to_number("AZ") == 52

    def test_case_insensitive(self):
        """Lowercase letters are converted to uppercase."""
        assert excel_column_to_number("a") == 1
        assert excel_column_to_number("aa") == 27

    def test_triple_letters(self):
        """Triple letters like AAA work correctly."""
        assert excel_column_to_number("BA") == 53
        assert excel_column_to_number("AAA") == 703

    def test_empty_string(self):
        """Empty string returns 0."""
        assert excel_column_to_number("") == 0


class TestPositionSortKey:
    """Test position sort key generation."""

    def test_numeric_position(self):
        """Numeric strings sort by integer value."""
        assert position_sort_key("1") == (0, 1)
        assert position_sort_key("10") == (0, 10)
        assert position_sort_key("100") == (0, 100)

    def test_excel_column_position(self):
        """Excel column letters sort in Excel order."""
        assert position_sort_key("A") == (0, 1)
        assert position_sort_key("Z") == (0, 26)
        assert position_sort_key("AA") == (0, 27)

    def test_none_position(self):
        """None positions sort after valid positions."""
        assert position_sort_key(None) == (1, 0)
        assert position_sort_key(None, fallback_index=5) == (1, 5)

    def test_unparseable_string(self):
        """Unparseable strings sort last."""
        assert position_sort_key("abc123") == (2, 0)
        assert position_sort_key("abc123", fallback_index=3) == (2, 3)

    def test_sort_order(self):
        """Valid positions sort before None, which sorts before unparseable."""
        valid = position_sort_key("1")
        none_pos = position_sort_key(None)
        unparseable = position_sort_key("xyz123")
        assert valid < none_pos < unparseable

    def test_numeric_vs_excel_sorting(self):
        """Numeric positions and Excel columns both get priority 0."""
        numeric = position_sort_key("5")
        excel = position_sort_key("E")  # E = 5
        assert numeric[0] == excel[0] == 0
        assert numeric[1] == excel[1] == 5
