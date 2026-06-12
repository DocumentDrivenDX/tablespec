"""Unit tests for sample_data.generators module - HealthcareDataGenerators."""

import re

import pytest

from tablespec.sample_data.config import GenerationConfig
from tablespec.sample_data.generators import HealthcareDataGenerators

pytestmark = pytest.mark.fast


@pytest.fixture
def config():
    return GenerationConfig(random_seed=42)


@pytest.fixture
def generators(config):
    return HealthcareDataGenerators(config=config)


class TestClientMemberId:
    def test_format(self, generators):
        member_id = generators.generate_client_member_id()
        assert re.fullmatch(r"[A-Z]{2}\d{11}", member_id)

    def test_uniqueness(self, generators):
        ids = {generators.generate_client_member_id() for _ in range(100)}
        assert len(ids) == 100

    def test_uses_key_registry_pool(self, config, mocker):
        key_registry = mocker.Mock()
        key_registry.get_key_from_pool.return_value = "AB12345678901"
        gen = HealthcareDataGenerators(config=config, key_registry=key_registry)
        result = gen.generate_client_member_id()
        assert result == "AB12345678901"
        key_registry.get_key_from_pool.assert_called_once_with("ClientMemberID")

    def test_fallback_when_pool_empty(self, config, mocker):
        key_registry = mocker.Mock()
        key_registry.get_key_from_pool.return_value = None
        gen = HealthcareDataGenerators(config=config, key_registry=key_registry)
        result = gen.generate_client_member_id()
        assert re.fullmatch(r"[A-Z]{2}\d{11}", result)


class TestGovtId:
    def test_medicare(self, generators):
        result = generators.generate_govt_id("MEDICARE")
        assert result[0] == "1"
        assert result[1] in "ABC"

    def test_medicaid(self, generators):
        result = generators.generate_govt_id("MEDICAID")
        assert result[:2].isalpha()
        assert result[2:].isdigit()

    def test_marketplace(self, generators):
        result = generators.generate_govt_id("MARKETPLACE")
        assert result.startswith("EX")

    def test_duals(self, generators):
        result = generators.generate_govt_id("DUALS")
        assert result.startswith("DL")


class TestName:
    def test_returns_tuple(self, generators):
        first, middle, last = generators.generate_name()
        assert isinstance(first, str)
        assert isinstance(middle, str)
        assert isinstance(last, str)
        assert first in generators.first_names
        assert last in generators.last_names


class TestAddress:
    def test_returns_dict_with_keys(self, generators):
        addr = generators.generate_address()
        assert "address_line1" in addr
        assert "city" in addr
        assert "state" in addr
        assert "zipcode" in addr
        assert "county" in addr
        assert addr["state"] in generators.states


class TestDateGeneration:
    def test_date_in_range_default(self, generators):
        date_str = generators.generate_date_in_range()
        # Should be valid YYYY-MM-DD
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_str)

    def test_date_in_range_custom_format(self, generators):
        date_str = generators.generate_date_in_range(date_format="%m/%d/%Y")
        assert re.fullmatch(r"\d{2}/\d{2}/\d{4}", date_str)

    def test_date_with_constraints(self, generators):
        date_str = generators.generate_date_in_range_with_constraints(
            min_date_str="2020-01-01",
            max_date_str="2020-12-31",
        )
        assert date_str.startswith("2020-")

    def test_date_with_datetime_format_constraints(self, generators):
        date_str = generators.generate_date_in_range_with_constraints(
            min_date_str="2020-01-01 00:00:00",
            max_date_str="2020-12-31 23:59:59",
        )
        assert date_str.startswith("2020-")

    def test_date_with_iso_format_constraints(self, generators):
        date_str = generators.generate_date_in_range_with_constraints(
            min_date_str="2020-01-01T00:00:00",
            max_date_str="2020-12-31T23:59:59",
        )
        assert date_str.startswith("2020-")

    def test_date_with_no_constraints(self, generators):
        date_str = generators.generate_date_in_range_with_constraints()
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_str)

    def test_birth_date_reasonable_range(self, generators):
        date_str = generators.generate_birth_date()
        year = int(date_str[:4])
        assert 1900 <= year <= 2025

    def test_service_date(self, generators):
        date_str = generators.generate_service_date()
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_str)

    def test_timestamp(self, generators):
        ts = generators.generate_timestamp()
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", ts)


class TestMedicalCodes:
    def test_npi_format(self, generators):
        npi = generators.generate_npi()
        assert len(npi) == 10
        assert npi.isdigit()

    def test_loinc_format(self, generators):
        loinc = generators.generate_loinc()
        assert re.fullmatch(r"\d{1,7}-\d", loinc)

    def test_procedure_code_cpt(self, generators):
        code = generators.generate_procedure_code("CPT")
        assert code in generators.cpt_codes

    def test_procedure_code_hcpcs(self, generators):
        code = generators.generate_procedure_code("HCPCS")
        assert re.fullmatch(r"[A-Z]\d{4}", code)

    def test_diagnosis_code(self, generators):
        code = generators.generate_diagnosis_code()
        assert code in generators.icd10_codes


class TestSimpleGenerators:
    def test_risk_score_range(self, generators):
        for _ in range(100):
            score = generators.generate_risk_score()
            assert 0.5 <= score <= 8.0

    def test_rank(self, generators):
        for _ in range(100):
            rank = generators.generate_rank()
            assert isinstance(rank, int)
            assert rank >= 1

    def test_email_format(self, generators):
        email = generators.generate_email()
        assert "@" in email
        assert "." in email.split("@")[1]

    def test_zip_code(self, generators):
        for _ in range(100):
            z = generators.generate_zip_code()
            assert re.fullmatch(r"\d{5}(-\d{4})?", z)

    def test_phone_number(self, generators):
        phone = generators.generate_phone_number()
        assert len(phone) == 10
        assert phone.isdigit()

    def test_state_code(self, generators):
        state = generators.generate_state_code()
        assert state in generators.states
        assert len(state) == 2

    def test_lob(self, generators):
        lob = generators.generate_lob()
        assert lob in generators.lobs

    def test_gender(self, generators):
        gender = generators.generate_gender()
        assert gender in generators.genders

    def test_address_line_1(self, generators):
        addr = generators.generate_address_line_1()
        assert isinstance(addr, str)
        assert len(addr) > 0

    def test_city(self, generators):
        city = generators.generate_city()
        assert isinstance(city, str)

    def test_service_type(self, generators):
        st = generators.generate_service_type()
        assert st in ["IHA", "TEL", "AUD", "RET"]

    def test_disposition_status(self, generators):
        assert generators.generate_disposition_status() == "PENDING FIRST CALL"

    def test_assessment_type(self, generators):
        at = generators.generate_assessment_type()
        assert isinstance(at, str)
        assert len(at) > 0

    def test_embedding_is_deterministic(self, generators):
        first = generators.generate_embedding(8, seed="test_table.embedding")
        second = generators.generate_embedding(8, seed="test_table.embedding")
        assert first == second
        assert len(first) == 8
        assert abs(sum(value * value for value in first) - 1.0) < 1e-6

    def test_provider_type(self, generators):
        pt = generators.generate_provider_type()
        assert isinstance(pt, str)

    def test_vendor_name(self, generators):
        vn = generators.generate_vendor_name()
        assert isinstance(vn, str)

    def test_pcp_type(self, generators):
        for _ in range(100):
            pt = generators.generate_pcp_type()
            assert pt in ["IMP", "P4Q", "FUL"]

    def test_plan_code(self, generators):
        pc = generators.generate_plan_code()
        assert re.fullmatch(r"\d{2}A\d{4}", pc)

    def test_project_code(self, generators):
        pc = generators.generate_project_code()
        assert 1000 <= pc <= 999999

    def test_calendar_year(self, generators):
        cy = generators.generate_calendar_year()
        assert 2023 <= cy <= 2027

    def test_visit_count(self, generators):
        for _ in range(100):
            vc = generators.generate_visit_count()
            assert 0 <= vc <= 20
