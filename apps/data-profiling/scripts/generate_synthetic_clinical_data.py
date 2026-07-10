"""
Generate one nightly load batch for the prod_main_clinical schema (Tuva Input Layer).

Produces 10 pipe-delimited PSV files that simulate the rows a nightly ETL job
would append on LOAD_DATE.  All primary keys are stable across reruns (fixed SEED).

Tables generated:
  practitioner   -- reference (no encounter FK)
  location       -- reference (no encounter FK)
  encounter      -- base entity; all clinical tables link to this
  condition
  procedure
  lab_result
  observation
  medication
  immunization
  appointment

Output:
  data/synthetic/prod_main_clinical/<table>_<YYYYMMDD>.csv

Usage:
  python scripts/generate_synthetic_clinical_data.py
  python scripts/generate_synthetic_clinical_data.py --date 2026-06-18 --encounters 200
"""

from __future__ import annotations

import argparse
import csv
import os
from datetime import date, datetime, time, timedelta
from typing import Any

import numpy as np
import pandas as pd

# ── CLI ───────────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser()
parser.add_argument("--date", default="2026-06-18", help="Load date YYYY-MM-DD")
parser.add_argument(
    "--encounters", default=200, type=int, help="Number of encounter rows"
)
parser.add_argument("--seed", default=42, type=int, help="Random seed")
parser.add_argument(
    "--out", default="data/synthetic/prod_main_clinical", help="Output directory"
)
args = parser.parse_args()

LOAD_DATE = date.fromisoformat(args.date)
LOAD_DTTM = datetime(LOAD_DATE.year, LOAD_DATE.month, LOAD_DATE.day, 2, 0, 0)
N_ENC = args.encounters
SEED = args.seed
OUT_DIR = args.out
DATE_TAG = LOAD_DATE.strftime("%Y%m%d")
DATA_SOURCE = "SynaptiqPOC"

rng = np.random.default_rng(SEED)

os.makedirs(OUT_DIR, exist_ok=True)

# ── Reference pools (match simulate_nightly_loads.py constants) ───────────────
N_PRACTITIONERS = 200
N_LOCATIONS = 50
N_PERSONS = 5_000  # existing patient pool

PRAC_IDS = [f"PR{i:05d}" for i in range(1, N_PRACTITIONERS + 1)]
PRAC_NPIS = [f"{1_000_000_000 + i}" for i in range(1, N_PRACTITIONERS + 1)]
LOC_IDS = [f"L{i:04d}" for i in range(1, N_LOCATIONS + 1)]
LOC_NPIS = [f"{1_500_000_000 + i}" for i in range(1, N_LOCATIONS + 1)]
PERSON_IDS = [f"PER-{i:06d}" for i in range(1, N_PERSONS + 1)]

ICD10_CODES = [
    "M54.5",
    "I10",
    "E11.9",
    "J06.9",
    "K21.0",
    "Z00.00",
    "Z12.31",
    "F32.9",
    "J44.1",
    "N39.0",
    "Z23",
    "R05",
    "R51",
    "G43.909",
    "E78.5",
    "I25.10",
    "J18.9",
    "S93.401",
    "M17.11",
    "Z87.891",
    "E11.65",
    "I50.9",
    "J45.909",
    "F41.9",
    "M79.3",
]

CPT_CODES = [
    "99213",
    "99214",
    "99203",
    "99232",
    "99283",
    "93000",
    "71046",
    "36415",
    "80053",
    "85025",
    "80061",
    "82947",
    "97110",
    "99395",
]

NDC_DRUGS: dict[str, str] = {
    "00071015223": "Lisinopril 10mg",
    "00093721956": "Metformin 500mg",
    "00054418925": "Atorvastatin 20mg",
    "65862001705": "Omeprazole 20mg",
    "00781107905": "Amlodipine 5mg",
    "00378395305": "Levothyroxine 50mcg",
    "00093310505": "Sertraline 50mg",
    "63304082805": "Metoprolol 25mg",
    "00247100552": "Albuterol Inhaler",
    "00006098154": "Januvia 100mg",
}
NDC_LIST = list(NDC_DRUGS.keys())
NDC_NAMES = list(NDC_DRUGS.values())
RXNORM = [
    "860975",
    "861007",
    "617311",
    "40790",
    "329528",
    "36567",
    "41493",
    "435",
    "261242",
    "10582",
]
ATCODES = [
    "A10BA02",
    "C09AA02",
    "C10AA01",
    "A02BC01",
    "C08CA01",
    "H03AA01",
    "N06AB06",
    "C07AB02",
    "R03AC02",
    "A10BH01",
]

LOINC_LABS: dict[str, tuple[str, str, float, float]] = {
    "4548-4": ("HbA1c", "%", 4.5, 13.0),
    "2160-0": ("Creatinine", "mg/dL", 0.5, 4.0),
    "2345-7": ("Glucose", "mg/dL", 60.0, 400.0),
    "2089-1": ("LDL", "mg/dL", 40.0, 220.0),
    "718-7": ("Hemoglobin", "g/dL", 7.0, 18.0),
    "6690-2": ("WBC", "10*3/uL", 1.5, 18.0),
    "2823-3": ("Potassium", "mEq/L", 2.5, 6.5),
}
LOINC_LAB_CODES = list(LOINC_LABS.keys())

LOINC_VITALS: dict[str, tuple[str, str, float, float]] = {
    "8480-6": ("Systolic BP", "mmHg", 90.0, 180.0),
    "8462-4": ("Diastolic BP", "mmHg", 50.0, 120.0),
    "8867-4": ("Heart Rate", "bpm", 50.0, 120.0),
    "39156-5": ("BMI", "kg/m2", 18.0, 50.0),
    "3141-9": ("Body Weight", "kg", 45.0, 160.0),
}
LOINC_VITAL_CODES = list(LOINC_VITALS.keys())

CVX_VACCINES: dict[str, str] = {
    "08": "Hep B, adolescent or pediatric",
    "20": "DTaP",
    "43": "Hep B, adult",
    "49": "Hib (PRP-OMP)",
    "83": "Hep A, pediatric/adolescent",
    "94": "MMRV",
    "110": "DTaP-Hep B-IPV",
    "120": "DTaP-Hib-IPV",
    "133": "PCV 13",
    "140": "Influenza, seasonal, injectable, preservative free",
    "141": "Influenza, seasonal, injectable",
    "150": "Influenza, injectable, quadrivalent, preservative free",
    "160": "Influenza A (H1N1) 2009, monovalent, preservative free",
    "207": "COVID-19, mRNA, LNP-S, PF, 100 mcg/0.5 mL dose",
    "208": "COVID-19, mRNA, LNP-S, PF, 30 mcg/0.3 mL dose",
}
CVX_LIST = list(CVX_VACCINES.keys())
CVX_NAMES = list(CVX_VACCINES.values())

ENCOUNTER_TYPES = [
    "outpatient",
    "inpatient",
    "emergency",
    "office visit",
    "telehealth",
    "observation",
]
CONDITION_STATUSES = ["active"] * 6 + ["resolved"] * 3 + ["historical"]
CONDITION_TYPES = ["encounter-diagnosis", "problem-list-item", "health-concern"]
APPT_STATUSES = (
    ["completed"] * 14 + ["canceled"] * 3 + ["no-show"] * 2 + ["scheduled"] * 1
)
APPT_TYPES = [
    "Follow-up",
    "New Patient",
    "Annual Wellness",
    "Sick Visit",
    "Procedure",
    "Telehealth",
    "Consultation",
]
ROUTES = [
    "oral",
    "intravenous",
    "intramuscular",
    "subcutaneous",
    "inhaled",
    "topical",
    "sublingual",
]
BODY_SITES = [
    "left arm",
    "right arm",
    "left thigh",
    "right thigh",
    "deltoid",
    "abdomen",
    None,
]
ADMIT_SOURCE = ["1", "2", "4", "5", "7", "8", "9"]
ADMIT_TYPE = ["1", "2", "3", "4", "9"]
DISCH_DISP = ["01", "02", "03", "04", "05", "07", "20", "30", "43", "51"]
DRG_CODES = [
    "291",
    "292",
    "293",
    "194",
    "195",
    "196",
    "470",
    "871",
    "872",
    "378",
    "379",
    "380",
    "247",
    "248",
    "249",
]
BILL_TYPES = ["111", "112", "121", "122", "131", "132", "211", "212"]
POS_CODES = ["11", "21", "22", "23", "24", "31", "32", "99"]
REVENUE_CODES = [
    "0100",
    "0110",
    "0120",
    "0200",
    "0210",
    "0250",
    "0300",
    "0370",
    "0450",
    "0636",
]
MOD_CODES = ["25", "26", "59", "TC", "GT", "95", "GX", "GY", None, None, None, None]

FIRST_NAMES_F = [
    "Emma",
    "Olivia",
    "Ava",
    "Isabella",
    "Sophia",
    "Mia",
    "Charlotte",
    "Amelia",
    "Harper",
    "Evelyn",
    "Abigail",
    "Emily",
    "Elizabeth",
    "Sofia",
    "Avery",
    "Ella",
    "Scarlett",
    "Grace",
]
FIRST_NAMES_M = [
    "Liam",
    "Noah",
    "William",
    "James",
    "Oliver",
    "Benjamin",
    "Elijah",
    "Lucas",
    "Mason",
    "Logan",
    "Alexander",
    "Ethan",
    "Daniel",
    "Jacob",
    "Michael",
    "Henry",
    "Jackson",
    "Sebastian",
]
LAST_NAMES = [
    "Smith",
    "Johnson",
    "Williams",
    "Brown",
    "Jones",
    "Garcia",
    "Miller",
    "Davis",
    "Rodriguez",
    "Martinez",
    "Hernandez",
    "Lopez",
    "Gonzalez",
    "Wilson",
    "Anderson",
    "Thomas",
    "Taylor",
    "Moore",
    "Jackson",
    "Martin",
    "Lee",
    "Perez",
    "Thompson",
    "White",
    "Harris",
    "Sanchez",
    "Clark",
    "Ramirez",
    "Lewis",
    "Robinson",
    "Walker",
    "Young",
    "Allen",
    "King",
    "Wright",
    "Scott",
    "Torres",
    "Nguyen",
    "Hill",
    "Flores",
]
SPECIALTIES = [
    "Family Medicine",
    "Internal Medicine",
    "Pediatrics",
    "Obstetrics",
    "Cardiology",
    "Oncology",
    "Orthopedics",
    "Neurology",
    "Dermatology",
    "Psychiatry",
    "Urgent Care",
]
FAC_TYPES = ["clinic", "hospital", "urgent care", "imaging center", "lab", "pharmacy"]
STATES = [
    "CA",
    "TX",
    "FL",
    "NY",
    "PA",
    "IL",
    "OH",
    "GA",
    "NC",
    "MI",
    "NJ",
    "VA",
    "WA",
    "AZ",
    "MA",
]
CREDENTIALS = ["MD", "DO", "NP", "NP-C", "FNP-C", "PA-C", "APRN", "CNM", "RN"]
SEXES = ["male", "female"]
RACES = [
    "White",
    "Black or African American",
    "Asian",
    "American Indian or Alaska Native",
    "Other",
    "Unknown",
]


def fmt(dt: datetime | date | None, ts: bool = True) -> str:
    if dt is None:
        return ""
    if ts and isinstance(dt, datetime):
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    return dt.strftime("%Y-%m-%d")


# ── Generator functions ───────────────────────────────────────────────────────

AFFILIATIONS = [
    "Regional Health System",
    "Community Medical Center",
    "Solo Practice",
    "ValuMed Group",
    "StatCare Network",
]
SUB_SPECIALTIES = [
    "General",
    "Interventional",
    "Pediatric",
    "Geriatric",
    "Sports Medicine",
    None,
    None,
]


def make_practitioners() -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    r = np.random.default_rng(SEED + 1)
    for i in range(N_PRACTITIONERS):
        sex = r.choice(SEXES)
        first = r.choice(FIRST_NAMES_F if sex == "female" else FIRST_NAMES_M)
        last = r.choice(LAST_NAMES)
        rows.append(
            {
                "practitioner_id": PRAC_IDS[i],
                "npi": PRAC_NPIS[i],
                "first_name": first,
                "last_name": last,
                "practice_affiliation": r.choice(AFFILIATIONS),
                "specialty": r.choice(SPECIALTIES),
                "sub_specialty": r.choice(SUB_SPECIALTIES),
                "data_source": DATA_SOURCE,
                "META_data_source": f"META_{DATA_SOURCE}",
                "META_Load_DTTM": fmt(LOAD_DTTM),
            }
        )
    return pd.DataFrame(rows)


def make_locations() -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    r = np.random.default_rng(SEED + 2)
    for i in range(N_LOCATIONS):
        state = r.choice(STATES)
        rows.append(
            {
                "location_id": LOC_IDS[i],
                "npi": LOC_NPIS[i],
                "name": f"{state} Health {r.choice(FAC_TYPES).title()} {i + 1:03d}",
                "facility_type": r.choice(FAC_TYPES),
                "parent_organization": f"Health System {r.integers(1, 6)}",
                "address": f"{r.integers(100, 9999)} Healthcare Blvd",
                "city": f"{state} Metro",
                "state": state,
                "zip_code": f"{r.integers(10000, 99999):05d}",
                "latitude": round(float(r.uniform(25.0, 48.0)), 6),
                "longitude": round(float(r.uniform(-124.0, -67.0)), 6),
                "data_source": DATA_SOURCE,
                "META_data_source": f"META_{DATA_SOURCE}",
                "META_Load_DTTM": fmt(LOAD_DTTM),
            }
        )
    return pd.DataFrame(rows)


def make_encounters() -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    n = N_ENC
    person_idx = rng.integers(0, N_PERSONS, size=n)
    enc_type_idx = rng.integers(0, len(ENCOUNTER_TYPES), size=n)
    dur_days = rng.integers(0, 5, size=n)
    prac_idx = rng.integers(0, N_PRACTITIONERS, size=n)
    loc_idx = rng.integers(0, N_LOCATIONS, size=n)
    dx_idx = rng.integers(0, len(ICD10_CODES), size=n)
    drg_idx = rng.integers(0, len(DRG_CODES), size=n)
    charge_arr = np.exp(rng.normal(6.9, 0.80, size=n))  # PROD baseline distribution
    paid_arr = charge_arr * rng.uniform(0.5, 0.85, size=n)
    allowed_arr = charge_arr * rng.uniform(0.7, 0.95, size=n)
    date_jitter = rng.integers(-1, 2, size=n)  # ±1 day of load date

    for i in range(n):
        person_id = PERSON_IDS[person_idx[i]]
        patient_id = person_id.replace("PER-", "PAT-")
        enc_type = ENCOUNTER_TYPES[enc_type_idx[i]]
        is_inpatient = enc_type in ("inpatient", "emergency", "observation")

        enc_start = LOAD_DATE + timedelta(days=int(date_jitter[i]))
        enc_end = enc_start + timedelta(days=int(dur_days[i]))
        enc_id = f"ENC-{DATE_TAG}-{person_id}-{i:05d}"

        rows.append(
            {
                "encounter_id": enc_id,
                "person_id": person_id,
                "patient_id": patient_id,
                "encounter_type": enc_type,
                "encounter_start_date": fmt(enc_start, ts=False),
                "encounter_end_date": fmt(enc_end, ts=False),
                "admit_source_code": rng.choice(ADMIT_SOURCE) if is_inpatient else "",
                "admit_type_code": rng.choice(ADMIT_TYPE) if is_inpatient else "",
                "discharge_disposition_code": rng.choice(DISCH_DISP)
                if is_inpatient
                else "",
                "attending_provider_id": PRAC_IDS[prac_idx[i]],
                "attending_provider_name": "",
                "facility_npi": LOC_NPIS[loc_idx[i]],
                "facility_name": f"Location Facility {loc_idx[i] + 1:03d}",
                "primary_diagnosis_code_type": "ICD-10-CM",
                "primary_diagnosis_code": ICD10_CODES[dx_idx[i]],
                "drg_code_type": "MS-DRG" if is_inpatient else "",
                "drg_code": DRG_CODES[drg_idx[i]] if is_inpatient else "",
                "paid_amount": round(float(paid_arr[i]), 2),
                "allowed_amount": round(float(allowed_arr[i]), 2),
                "charge_amount": round(float(charge_arr[i]), 2),
                "ingest_datetime": fmt(LOAD_DTTM),
                "data_source": DATA_SOURCE,
                "META_data_source": f"META_{DATA_SOURCE}",
                "META_Load_DTTM": fmt(LOAD_DTTM),
            }
        )
    return pd.DataFrame(rows)


def make_conditions(enc_df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    n_enc = len(enc_df)
    cond_per_enc = rng.integers(2, 5, size=n_enc)
    for i, enc in enumerate(enc_df.to_dict("records")):
        n_cond = int(cond_per_enc[i])
        dx_idx = rng.integers(0, len(ICD10_CODES), size=n_cond)
        enc_date = date.fromisoformat(enc["encounter_start_date"])
        for j in range(n_cond):
            status = rng.choice(CONDITION_STATUSES)
            onset_date = enc_date - timedelta(days=int(rng.integers(1, 180)))
            resolved_date = (
                enc_date + timedelta(days=int(rng.integers(7, 90)))
                if status == "resolved"
                else None
            )
            icd_code = ICD10_CODES[dx_idx[j]]
            rows.append(
                {
                    "condition_id": f"{enc['encounter_id']}-C{j:02d}",
                    "person_id": enc["person_id"],
                    "patient_id": enc["patient_id"],
                    "encounter_id": enc["encounter_id"],
                    "recorded_date": fmt(enc_date, ts=False),
                    "onset_date": fmt(onset_date, ts=False),
                    "resolved_date": fmt(resolved_date, ts=False)
                    if resolved_date
                    else "",
                    "status": status,
                    "condition_type": rng.choice(CONDITION_TYPES),
                    "source_code_type": "ICD-10-CM",
                    "source_code": icd_code,
                    "source_description": f"Diagnosis {icd_code}",
                    "condition_rank": j + 1,
                    "present_on_admit_code": rng.choice(["Y", "N", "U", "W", ""])
                    if j == 0
                    else "",
                    "ingest_datetime": fmt(LOAD_DTTM),
                    "data_source": DATA_SOURCE,
                    "META_data_source": f"META_{DATA_SOURCE}",
                    "META_Load_DTTM": fmt(LOAD_DTTM),
                }
            )
    return pd.DataFrame(rows)


def make_procedures(enc_df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    n_enc = len(enc_df)
    procs_per_enc = rng.integers(1, 3, size=n_enc)
    for i, enc in enumerate(enc_df.to_dict("records")):
        n_proc = int(procs_per_enc[i])
        cpt_idx = rng.integers(0, len(CPT_CODES), size=n_proc)
        prac_idx = rng.integers(0, N_PRACTITIONERS, size=n_proc)
        enc_date = date.fromisoformat(enc["encounter_start_date"])
        for j in range(n_proc):
            cpt_code = CPT_CODES[cpt_idx[j]]
            mod_draws = rng.integers(0, len(MOD_CODES), size=5)
            mods = [MOD_CODES[int(m)] or "" for m in mod_draws]
            rows.append(
                {
                    "procedure_id": f"{enc['encounter_id']}-P{j:02d}",
                    "person_id": enc["person_id"],
                    "patient_id": enc["patient_id"],
                    "encounter_id": enc["encounter_id"],
                    "procedure_date": fmt(enc_date, ts=False),
                    "source_code_type": "CPT",
                    "source_code": cpt_code,
                    "source_description": f"Procedure {cpt_code}",
                    "modifier_1": mods[0],
                    "modifier_2": mods[1],
                    "modifier_3": mods[2],
                    "modifier_4": mods[3],
                    "modifier_5": mods[4],
                    "practitioner_id": PRAC_IDS[prac_idx[j]],
                    "ingest_datetime": fmt(LOAD_DTTM),
                    "data_source": DATA_SOURCE,
                    "META_data_source": f"META_{DATA_SOURCE}",
                    "META_Load_DTTM": fmt(LOAD_DTTM),
                }
            )
    return pd.DataFrame(rows)


def make_lab_results(enc_df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    n_enc = len(enc_df)
    labs_per_enc = rng.integers(1, 4, size=n_enc)
    prac_idx = rng.integers(0, N_PRACTITIONERS, size=n_enc)
    for i, enc in enumerate(enc_df.to_dict("records")):
        n_labs = int(labs_per_enc[i])
        lab_codes = rng.choice(LOINC_LAB_CODES, size=n_labs, replace=True)
        enc_date = date.fromisoformat(enc["encounter_start_date"])
        for j in range(n_labs):
            loinc_code = lab_codes[j]
            desc, units, lo, hi = LOINC_LABS[loinc_code]
            if loinc_code == "4548-4":
                val = float(
                    np.clip(rng.normal(7.2, 1.5), 4.5, 13.0)
                )  # PROD baseline HbA1c
            else:
                val = float(rng.uniform(lo, hi))
            result_str = f"{val:.2f}"
            abnormal = "Y" if (val < lo or val > hi) else "N"
            collect_dt = datetime(
                enc_date.year, enc_date.month, enc_date.day, int(rng.integers(6, 18)), 0
            )
            result_dt = collect_dt + timedelta(hours=int(rng.integers(0, 3)))
            rows.append(
                {
                    "lab_result_id": f"{enc['encounter_id']}-L{j:02d}",
                    "person_id": enc["person_id"],
                    "patient_id": enc["patient_id"],
                    "encounter_id": enc["encounter_id"],
                    "accession_number": f"ACC{rng.integers(100000, 999999)}",
                    "source_order_type": rng.choice(
                        ["laboratory", "point-of-care", "external"]
                    ),
                    "source_order_code": loinc_code,
                    "source_order_description": desc,
                    "source_component_type": "LOINC",
                    "source_component_code": loinc_code,
                    "source_component_description": desc,
                    "status": "final",
                    "result": result_str,
                    "result_datetime": fmt(result_dt),
                    "collection_datetime": fmt(collect_dt),
                    "source_units": units,
                    "normalized_units": units,
                    "source_reference_range_low": str(lo),
                    "source_reference_range_high": str(hi),
                    "normalized_reference_range_low": str(lo),
                    "normalized_reference_range_high": str(hi),
                    "source_abnormal_flag": abnormal,
                    "normalized_abnormal_flag": abnormal,
                    "specimen": rng.choice(["blood", "serum", "plasma", "urine", ""]),
                    "ordering_practitioner_id": PRAC_IDS[prac_idx[i]],
                    "ingest_datetime": fmt(LOAD_DTTM),
                    "data_source": DATA_SOURCE,
                    "META_data_source": f"META_{DATA_SOURCE}",
                    "META_Load_DTTM": fmt(LOAD_DTTM),
                }
            )
    return pd.DataFrame(rows)


def make_observations(enc_df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    n_enc = len(enc_df)
    obs_per_enc = rng.integers(2, 5, size=n_enc)
    for i, enc in enumerate(enc_df.to_dict("records")):
        n_obs = int(obs_per_enc[i])
        vital_codes = rng.choice(LOINC_VITAL_CODES, size=n_obs, replace=True)
        enc_date = date.fromisoformat(enc["encounter_start_date"])
        obs_dt = datetime(
            enc_date.year, enc_date.month, enc_date.day, int(rng.integers(7, 17)), 0
        )
        panel_id = f"PANEL-{enc['encounter_id']}"
        for j in range(n_obs):
            loinc_code = vital_codes[j]
            desc, units, lo, hi = LOINC_VITALS[loinc_code]
            if loinc_code == "39156-5":
                val = float(
                    np.clip(rng.normal(27.5, 5.0), 15.0, 55.0)
                )  # PROD baseline BMI
            else:
                val = float(rng.uniform(lo, hi))
            rows.append(
                {
                    "observation_id": f"{enc['encounter_id']}-O{j:02d}",
                    "person_id": enc["person_id"],
                    "patient_id": enc["patient_id"],
                    "encounter_id": enc["encounter_id"],
                    "panel_id": panel_id,
                    "observation_date": fmt(enc_date, ts=False),
                    "observation_type": "vital-signs",
                    "source_code_type": "LOINC",
                    "source_code": loinc_code,
                    "source_description": desc,
                    "result": f"{val:.1f}",
                    "source_units": units,
                    "normalized_units": units,
                    "source_reference_range_low": str(lo),
                    "source_reference_range_high": str(hi),
                    "normalized_reference_range_low": str(lo),
                    "normalized_reference_range_high": str(hi),
                    "ingest_datetime": fmt(LOAD_DTTM),
                    "data_source": DATA_SOURCE,
                    "META_data_source": f"META_{DATA_SOURCE}",
                    "META_Load_DTTM": fmt(LOAD_DTTM),
                }
            )
    return pd.DataFrame(rows)


def make_medications(enc_df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    n_enc = len(enc_df)
    meds_per_enc = rng.integers(0, 2, size=n_enc)
    for i, enc in enumerate(enc_df.to_dict("records")):
        n_meds = int(meds_per_enc[i])
        enc_date = date.fromisoformat(enc["encounter_start_date"])
        for j in range(n_meds):
            ndc_i = int(rng.integers(0, len(NDC_LIST)))
            prac_i = int(rng.integers(0, N_PRACTITIONERS))
            disp_dt = enc_date + timedelta(days=int(rng.integers(0, 3)))
            presc_dt = enc_date - timedelta(days=int(rng.integers(0, 3)))
            rows.append(
                {
                    "medication_id": f"{enc['encounter_id']}-MED{j:02d}",
                    "person_id": enc["person_id"],
                    "patient_id": enc["patient_id"],
                    "encounter_id": enc["encounter_id"],
                    "dispensing_date": fmt(disp_dt, ts=False),
                    "prescribing_date": fmt(presc_dt, ts=False),
                    "source_code_type": "NDC",
                    "source_code": NDC_LIST[ndc_i],
                    "source_description": NDC_NAMES[ndc_i],
                    "ndc_code": NDC_LIST[ndc_i],
                    "rxnorm_code": RXNORM[ndc_i % len(RXNORM)],
                    "atc_code": ATCODES[ndc_i % len(ATCODES)],
                    "route": rng.choice(ROUTES),
                    "strength": rng.choice(
                        ["10mg", "25mg", "50mg", "100mg", "500mg", "1g", "5mcg", "20mg"]
                    ),
                    "quantity": float(rng.integers(30, 91)),
                    "quantity_unit": rng.choice(
                        ["tablet", "capsule", "mL", "unit", "inhaler"]
                    ),
                    "days_supply": float(rng.integers(30, 91)),
                    "practitioner_id": PRAC_IDS[prac_i],
                    "ingest_datetime": fmt(LOAD_DTTM),
                    "data_source": DATA_SOURCE,
                    "META_data_source": f"META_{DATA_SOURCE}",
                    "META_Load_DTTM": fmt(LOAD_DTTM),
                }
            )
    return pd.DataFrame(rows)


def make_immunizations(enc_df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    n_enc = len(enc_df)
    # ~35 % of encounters have an immunization
    imm_mask = rng.random(size=n_enc) < 0.35
    prac_idx = rng.integers(0, N_PRACTITIONERS, size=n_enc)
    loc_idx = rng.integers(0, N_LOCATIONS, size=n_enc)
    dose_arr = rng.integers(1, 4, size=n_enc)
    for i, enc in enumerate(enc_df.to_dict("records")):
        if not imm_mask[i]:
            continue
        enc_date = date.fromisoformat(enc["encounter_start_date"])
        cvx_i = int(rng.integers(0, len(CVX_LIST)))
        status = rng.choice(
            ["completed", "not-done", "entered-in-error"], p=[0.92, 0.06, 0.02]
        )
        status_reason = (
            "patient refusal"
            if status == "not-done"
            else ("data entry error" if status == "entered-in-error" else "")
        )
        rows.append(
            {
                "immunization_id": f"{enc['encounter_id']}-IMM00",
                "person_id": enc["person_id"],
                "patient_id": enc["patient_id"],
                "encounter_id": enc["encounter_id"],
                "source_code_type": "CVX",
                "source_code": CVX_LIST[cvx_i],
                "source_description": CVX_NAMES[cvx_i],
                "status": status,
                "status_reason": status_reason,
                "occurrence_date": fmt(enc_date, ts=False),
                "source_dose": str(int(dose_arr[i])),
                "lot_number": f"LOT{rng.integers(10000, 99999)}",
                "body_site": rng.choice(BODY_SITES) or "",
                "route": rng.choice(
                    ["intramuscular", "subcutaneous", "intranasal", "oral"]
                ),
                "location_id": LOC_IDS[loc_idx[i]],
                "practitioner_id": PRAC_IDS[prac_idx[i]],
                "ingest_datetime": fmt(LOAD_DTTM),
                "data_source": DATA_SOURCE,
                "META_data_source": f"META_{DATA_SOURCE}",
                "META_Load_DTTM": fmt(LOAD_DTTM),
            }
        )
    return pd.DataFrame(rows)


def make_appointments(enc_df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    n_enc = len(enc_df)
    prac_idx = rng.integers(0, N_PRACTITIONERS, size=n_enc)
    loc_idx = rng.integers(0, N_LOCATIONS, size=n_enc)
    type_idx = rng.integers(0, len(APPT_TYPES), size=n_enc)
    status_idx = rng.integers(0, len(APPT_STATUSES), size=n_enc)
    dur_arr = rng.integers(15, 61, size=n_enc)
    for i, enc in enumerate(enc_df.to_dict("records")):
        enc_date = date.fromisoformat(enc["encounter_start_date"])
        start_hour = int(rng.integers(8, 17))
        appt_start = datetime(
            enc_date.year, enc_date.month, enc_date.day, start_hour, 0
        )
        dur_min = int(dur_arr[i])
        appt_end = appt_start + timedelta(minutes=dur_min)
        status = APPT_STATUSES[status_idx[i]]
        cancel_rsn = (
            rng.choice(["patient request", "provider unavailable", "weather", "other"])
            if status in ("canceled", "no-show")
            else ""
        )
        rows.append(
            {
                "appointment_id": f"{enc['encounter_id']}-A",
                "person_id": enc["person_id"],
                "patient_id": enc["patient_id"],
                "encounter_id": enc["encounter_id"],
                "start_datetime": fmt(appt_start),
                "end_datetime": fmt(appt_end),
                "duration": dur_min,
                "location_id": LOC_IDS[loc_idx[i]],
                "practitioner_id": PRAC_IDS[prac_idx[i]],
                "type_code": f"APPT-{APPT_TYPES[type_idx[i]].replace(' ', '-').upper()[:12]}",
                "type_description": APPT_TYPES[type_idx[i]],
                "status_code": status.upper().replace("-", "_"),
                "status_description": status,
                "reason": rng.choice(
                    [
                        "routine",
                        "follow-up",
                        "sick",
                        "preventive",
                        "chronic-management",
                        "",
                    ]
                ),
                "cancellation_reason": cancel_rsn,
                "data_source": DATA_SOURCE,
                "META_data_source": f"META_{DATA_SOURCE}",
                "META_Load_DTTM": fmt(LOAD_DTTM),
            }
        )
    return pd.DataFrame(rows)


def write_psv(df: pd.DataFrame, table_name: str) -> None:
    path = os.path.join(OUT_DIR, f"{table_name}_{DATE_TAG}.csv")
    df.to_csv(path, sep=",", index=False, quoting=csv.QUOTE_MINIMAL)
    print(f"  {table_name:<20s}  {len(df):>6,} rows  ->  {path}")


# ── Main ──────────────────────────────────────────────────────────────────────
print(
    f"\nGenerating prod_main_clinical nightly load — {LOAD_DATE}  ({N_ENC} encounters, seed={SEED})"
)
print(f"Output: {os.path.abspath(OUT_DIR)}\n")

prac_df = make_practitioners()
loc_df = make_locations()
enc_df = make_encounters()
cond_df = make_conditions(enc_df)
proc_df = make_procedures(enc_df)
lab_df = make_lab_results(enc_df)
obs_df = make_observations(enc_df)
med_df = make_medications(enc_df)
imm_df = make_immunizations(enc_df)
appt_df = make_appointments(enc_df)

write_psv(prac_df, "practitioner")
write_psv(loc_df, "location")
write_psv(enc_df, "encounter")
write_psv(cond_df, "condition")
write_psv(proc_df, "procedure")
write_psv(lab_df, "lab_result")
write_psv(obs_df, "observation")
write_psv(med_df, "medication")
write_psv(imm_df, "immunization")
write_psv(appt_df, "appointment")

total = sum(
    len(d)
    for d in [
        prac_df,
        loc_df,
        enc_df,
        cond_df,
        proc_df,
        lab_df,
        obs_df,
        med_df,
        imm_df,
        appt_df,
    ]
)
print(f"\nDone — {total:,} total rows across 10 tables.")
