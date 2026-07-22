"""
Generate two months of synthetic Aetna bronze-layer claims data.

Tables:
  med_claims  (176 cols month-1 / 177 cols month-2)  — uat_bronze.aetna_ingested
  rx_claims   (74 cols, both months)                  — uat_bronze.aetna_ingested

Schema-drift signal:
  Month-2 med_claims gains one new column — `telehealth_indicator` ("Y"/"N") —
  inserted before `org_cd`.  Month-1 does NOT have this column, making the
  two files a clean A/B pair for the platform's schema-diff demo.

Output: data/synthetic/aetna_ingested/
  med_claims_<YYYYMMDD>.csv   (pipe-delimited)
  rx_claims_<YYYYMMDD>.csv    (pipe-delimited)

Usage:
  python scripts/generate_aetna_claims_data.py
  python scripts/generate_aetna_claims_data.py --months 20260601 20260701 --med-rows 1000 --rx-rows 500
"""

from __future__ import annotations

import argparse
import os
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

# ── CLI ──────────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser()
parser.add_argument(
    "--months",
    nargs="+",
    default=["20260601", "20260701"],
    help="File date tags YYYYMMDD — generates one file per tag",
)
parser.add_argument(
    "--med-rows", default=1000, type=int, help="Med claim lines per month"
)
parser.add_argument("--rx-rows", default=500, type=int, help="Rx claim lines per month")
parser.add_argument("--seed", default=42, type=int, help="Base random seed")
parser.add_argument("--out", default="data/synthetic/aetna_ingested")
args = parser.parse_args()

SEED = args.seed
OUT_DIR = args.out
os.makedirs(OUT_DIR, exist_ok=True)

# ── Plan constants ────────────────────────────────────────────────────────────
ORG_CD = "AETNA"
CUSTOMER_NBR = "1234567"
GROUP_NBR = "0987654"
SUBGROUP_NBR = "001"
ACCOUNT_NBR = "AC123456"
PLAN_ID = "PPO001"
BNFT_PKG_ID = "PKG0042"
NSA_ID = "NY0001"

# ── Reference data ────────────────────────────────────────────────────────────
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
    "Victoria",
    "Riley",
    "Aria",
    "Nora",
    "Chloe",
    "Zoey",
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
    "Aiden",
    "Matthew",
    "Samuel",
    "David",
    "Joseph",
    "Carter",
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
]
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
    "CO",
]

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
    "Z79.899",
    "E66.9",
    "G47.33",
    "J30.9",
    "K57.30",
]

CPT_PROF = [
    "99213",
    "99214",
    "99203",
    "99204",
    "99205",
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
    "99396",
    "90834",
    "90847",
    "99291",
]
CPT_INST = [
    "99232",
    "99233",
    "99291",
    "31500",
    "36556",
    "43753",
    "99284",
    "99285",
    "99281",
]

MOD_CODES = ["25", "26", "59", "TC", "GT", "95", "50", "51", "AT", "", "", "", ""]
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
    "392",
    "683",
]
REVENUE_CDS = [
    "0100",
    "0110",
    "0200",
    "0250",
    "0300",
    "0370",
    "0450",
    "0636",
    "0730",
    "0900",
]
MDC_CDS = [
    "01",
    "02",
    "03",
    "04",
    "05",
    "06",
    "07",
    "08",
    "09",
    "10",
    "11",
    "12",
    "13",
    "14",
    "15",
]
BILL_TYPES = ["111", "112", "121", "122", "131", "132", "211", "212"]
POS_CODES = ["11", "21", "22", "23", "24", "31", "32", "99", "12", "13"]
SPEC_CDS = [
    "01",
    "02",
    "03",
    "04",
    "05",
    "06",
    "07",
    "08",
    "09",
    "10",
    "11",
    "12",
    "38",
    "40",
    "50",
]
TYPE_SRV = ["1", "2", "4", "A", "B", "F", "M", "N", "S"]
MED_COST_SUB = ["01", "02", "03", "04", "05", "06", "07", "08"]

NDC_DRUGS: dict[str, tuple[str, str, str, float, float]] = {
    # ndc: (label, formulary_tier, generic_cd, ingredient_cost, awp)
    "00071015223": ("Lisinopril 10mg", "1", "Y", 8.50, 12.00),
    "00093721956": ("Metformin 500mg", "1", "Y", 6.25, 9.00),
    "00054418925": ("Atorvastatin 20mg", "2", "Y", 12.00, 18.00),
    "65862001705": ("Omeprazole 20mg", "1", "Y", 7.50, 11.00),
    "00781107905": ("Amlodipine 5mg", "1", "Y", 9.00, 13.50),
    "00378395305": ("Levothyroxine 50mcg", "1", "Y", 11.00, 16.00),
    "00093310505": ("Sertraline 50mg", "1", "Y", 10.50, 15.00),
    "63304082805": ("Metoprolol 25mg", "1", "Y", 8.00, 12.00),
    "00247100552": ("Albuterol HFA Inhaler", "2", "N", 35.00, 55.00),
    "00006098154": ("Januvia 100mg", "3", "N", 285.00, 420.00),
    "00169750111": ("Ozempic 0.5mg pen", "3", "N", 720.00, 1100.00),
    "00310015615": ("Humira 40mg/0.4mL", "3", "N", 4800.00, 6800.00),
    "51479087501": ("Jardiance 10mg", "3", "N", 480.00, 700.00),
    "00002774601": ("Trulicity 0.75mg", "3", "N", 750.00, 1050.00),
    "00310015620": ("Eliquis 5mg", "2", "N", 290.00, 420.00),
}
NDC_LIST = list(NDC_DRUGS.keys())
GPI_LOOKUP = {
    "00071015223": "3600001000",
    "00093721956": "2720002000",
    "00054418925": "3900001000",
    "65862001705": "4920001000",
    "00781107905": "3600002000",
    "00378395305": "5400001000",
    "00093310505": "5800002000",
    "63304082805": "3700002000",
    "00247100552": "4400001000",
    "00006098154": "2720003000",
    "00169750111": "2720004000",
    "00310015615": "8000001000",
    "51479087501": "2720005000",
    "00002774601": "2720006000",
    "00310015620": "3300001000",
}

# ── Member / Subscriber pool ──────────────────────────────────────────────────
_rp = np.random.default_rng(SEED + 99)


def _rand_date(yr_lo: int, yr_hi: int) -> date:
    return date(
        int(_rp.integers(yr_lo, yr_hi)),
        int(_rp.integers(1, 13)),
        int(_rp.integers(1, 29)),
    )


N_SUBS = 400

# Subscriber (employee) records
_SUBS: list[dict[str, Any]] = []
for _i in range(N_SUBS):
    _sex = _rp.choice(["M", "F"])
    _fn = _rp.choice(FIRST_NAMES_F if _sex == "F" else FIRST_NAMES_M)
    _ln = _rp.choice(LAST_NAMES)
    _st = _rp.choice(STATES)
    _zip = f"{_rp.integers(10000, 99999):05d}"
    _bd = _rand_date(1960, 1995)
    _ssn = f"{_rp.integers(100, 999):03d}{_rp.integers(10, 99):02d}{_rp.integers(1000, 9999):04d}"
    _SUBS.append(
        {
            "sub_id": f"W{_i + 1:09d}",
            "ln": _ln,
            "fn": _fn,
            "sex": _sex,
            "bd": _bd,
            "ssn": _ssn,
            "st": _st,
            "zip": _zip,
            "cov_type": _rp.choice(["EE", "EF", "ES", "EC"]),
        }
    )

# Full member pool: employees + dependents
MEMBER_POOL: list[dict[str, Any]] = []
for _s in _SUBS:
    MEMBER_POOL.append(
        {
            "member_id": _s["sub_id"],
            "sub_id": _s["sub_id"],
            "mbr_type": "EE",
            "mem_last_nm": _s["ln"],
            "mem_first_nm": _s["fn"],
            "mem_gender": _s["sex"],
            "birth_dt": _s["bd"],
            "emp_last_nm": _s["ln"],
            "emp_first_nm": _s["fn"],
            "emp_gender": _s["sex"],
            "sub_birth_dt": _s["bd"],
            "ssn_nbr": _s["ssn"],
            "subs_zip_cd": _s["zip"],
            "subs_st_postal_cd": _s["st"],
            "coverage_type_cd": _s["cov_type"],
        }
    )

for _j in range(300):
    _sub = _SUBS[int(_rp.integers(0, N_SUBS))]
    _dtype = _rp.choice(["SP", "CH", "CH"])
    _sex2 = _rp.choice(["M", "F"])
    _fn2 = _rp.choice(FIRST_NAMES_F if _sex2 == "F" else FIRST_NAMES_M)
    _bd2 = _rand_date(2000, 2022) if _dtype == "CH" else _rand_date(1965, 1998)
    MEMBER_POOL.append(
        {
            "member_id": f"W{N_SUBS + _j + 1:09d}",
            "sub_id": _sub["sub_id"],
            "mbr_type": _dtype,
            "mem_last_nm": _sub["ln"],
            "mem_first_nm": _fn2,
            "mem_gender": _sex2,
            "birth_dt": _bd2,
            "emp_last_nm": _sub["ln"],
            "emp_first_nm": _sub["fn"],
            "emp_gender": _sub["sex"],
            "sub_birth_dt": _sub["bd"],
            "ssn_nbr": "",
            "subs_zip_cd": _sub["zip"],
            "subs_st_postal_cd": _sub["st"],
            "coverage_type_cd": _sub["cov_type"],
        }
    )

N_MEMBERS = len(MEMBER_POOL)

# Provider pool
N_PROV = 300
PROV_NPIS = [f"{2000000000 + _i}" for _i in range(1, N_PROV + 1)]
PROV_TINS = [f"{100000000 + _i:09d}" for _i in range(1, N_PROV + 1)]
PROV_IDS = [f"PV{_i:06d}" for _i in range(1, N_PROV + 1)]
PROV_SPEC = [SPEC_CDS[_i % len(SPEC_CDS)] for _i in range(N_PROV)]

# Prescriber pool
N_PRESC = 150
PRESC_NPIS = [f"{3000000000 + _i}" for _i in range(1, N_PRESC + 1)]
PRESC_IDS = [f"DR{_i:06d}" for _i in range(1, N_PRESC + 1)]

# Pharmacy pool
N_PHARM = 80
NABP_NBRS = [f"{7000000 + _i}" for _i in range(1, N_PHARM + 1)]
_rph = np.random.default_rng(SEED + 200)
PHARM_ZIPS = [f"{_rph.integers(10000, 99999):05d}" for _ in range(N_PHARM)]

# ── Helpers ───────────────────────────────────────────────────────────────────


def _dt(d: date | None) -> str:
    return d.strftime("%Y%m%d") if d else ""


def _amt(v: float) -> str:
    return f"{v:.2f}"


# ── Med claims generator ──────────────────────────────────────────────────────


def gen_med_claims(
    file_dt_str: str, n: int, seed: int, add_telehealth: bool
) -> pd.DataFrame:
    """
    Generate n medical claim lines for the given file date tag (YYYYMMDD).
    add_telehealth=True appends the `telehealth_indicator` column (schema drift signal).
    """
    r = np.random.default_rng(seed)
    file_dt = date(int(file_dt_str[:4]), int(file_dt_str[4:6]), int(file_dt_str[6:]))

    mbr_idx = r.integers(0, N_MEMBERS, size=n)
    prov_idx = r.integers(0, N_PROV, size=n)
    is_inst = r.random(size=n) < 0.30  # 30% institutional
    denied = r.random(size=n) < 0.10  # 10% denied
    reversal = r.random(size=n) < 0.03  # 3% reversals

    svc_off = r.integers(5, 90, size=n)  # days before file_dt
    los = r.integers(0, 5, size=n)  # inpatient LOS
    adjn_off = r.integers(1, 20, size=n)
    recv_off = r.integers(5, 30, size=n)

    billed_arr = np.exp(r.normal(6.5, 0.85, size=n))
    allowed_rt = r.uniform(0.25, 0.75, size=n)
    ded_rt = r.uniform(0.00, 0.30, size=n)
    coins_rt = r.uniform(0.10, 0.25, size=n)
    copay_arr = r.choice([0, 20, 30, 40, 50, 75], size=n).astype(float)

    cpt_idx = r.integers(0, len(CPT_PROF), size=n)
    rev_idx = r.integers(0, len(REVENUE_CDS), size=n)
    drg_idx = r.integers(0, len(DRG_CODES), size=n)
    mdc_idx = r.integers(0, len(MDC_CDS), size=n)
    dx_idx = r.integers(0, len(ICD10_CODES), size=(n, 5))
    mod_idx = r.integers(0, len(MOD_CODES), size=(n, 3))
    pos_idx = r.integers(0, len(POS_CODES), size=n)
    bill_idx = r.integers(0, len(BILL_TYPES), size=n)
    poa_arr = r.choice(["Y", "N", "", ""], size=(n, 10))
    tele_arr = r.choice(["Y", "N", "N", "N", "N"], size=n)  # ~20% telehealth

    seq_base = int(file_dt_str) * 100_000_000
    rows: list[dict[str, Any]] = []

    for i in range(n):
        mbr = MEMBER_POOL[int(mbr_idx[i])]
        pi = int(prov_idx[i])
        inst = bool(is_inst[i])

        srv_start = file_dt - timedelta(days=int(svc_off[i]))
        srv_stop = srv_start + timedelta(days=int(los[i]) if inst else 0)
        adjn_dt = file_dt - timedelta(days=int(adjn_off[i]))
        recv_dt = adjn_dt - timedelta(days=int(recv_off[i]))
        paid_dt = adjn_dt + timedelta(days=int(r.integers(1, 5)))

        is_denied = bool(denied[i])
        rev_cd = "1" if reversal[i] else "0"
        status_cd = "D" if is_denied else "P"

        billed = round(float(billed_arr[i]), 2)
        allowed = round(billed * float(allowed_rt[i]), 2) if not is_denied else 0.0
        ded = round(allowed * float(ded_rt[i]), 2)
        copay = float(copay_arr[i])
        coins = round(max(0.0, allowed - ded - copay) * float(coins_rt[i]), 2)
        paid = (
            round(max(0.0, allowed - ded - copay - coins), 2) if not is_denied else 0.0
        )
        not_cov = round(billed - allowed, 2) if allowed > 0 else billed
        covered = round(billed - not_cov, 2)
        negot = round(billed - allowed, 2) if allowed > 0 else 0.0
        bnft_py = round(max(0.0, allowed - ded - copay - coins), 2)

        prcdr = CPT_PROF[int(cpt_idx[i])]
        mods = [MOD_CODES[int(mod_idx[i][j])] for j in range(3)]
        spec_cd = PROV_SPEC[pi]
        ben_tier = r.choice(["1", "2", "3", "N"])
        par_cd = "N" if ben_tier == "N" else "P"

        prov_npi = PROV_NPIS[pi]
        prov_tin = PROV_TINS[pi]
        prov_id = PROV_IDS[pi]
        prov_nm = f"DR {LAST_NAMES[pi % len(LAST_NAMES)]} MD"
        prov_st = r.choice(STATES)
        prov_zip = f"{r.integers(10000, 99999):05d}"
        prov_city = f"{prov_st} MEDICAL CTR"

        drg = DRG_CODES[int(drg_idx[i])] if inst else ""
        mdc = MDC_CDS[int(mdc_idx[i])] if inst else ""
        rev = REVENUE_CDS[int(rev_idx[i])] if inst else ""
        bill_type = BILL_TYPES[int(bill_idx[i])] if inst else ""
        dschrg_st = r.choice(["01", "02", "03", "04", "05", "07", "20"]) if inst else ""
        admit_src = r.choice(["1", "2", "4", "5", "7", ""]) if inst else ""
        admit_typ = r.choice(["1", "2", "3", "4", "9", ""]) if inst else ""
        admit_dt = _dt(srv_start) if inst else ""
        disc_dt = _dt(srv_stop) if inst else ""
        plc_srv = POS_CODES[int(pos_idx[i])]
        clm_type = "I" if inst else "P"
        seq_id = seq_base + i + 1

        dx = [ICD10_CODES[int(dx_idx[i][k])] for k in range(5)]
        dx_present = [
            True,
            r.random() > 0.35,
            r.random() > 0.55,
            r.random() > 0.75,
            r.random() > 0.88,
        ]
        diag = [dx[k] if dx_present[k] else "" for k in range(5)]

        row: dict[str, Any] = {
            "ps_unique_id": f"{seq_id:018d}",
            "customer_nbr": CUSTOMER_NBR,
            "group_nbr": GROUP_NBR,
            "idn_indicator": "N",
            "subgroup_nbr": SUBGROUP_NBR,
            "account_nbr": ACCOUNT_NBR,
            "file_id": "01" if inst else "03",
            "clm_ln_type_cd": clm_type,
            "non_prfrrd_srv_cd": "Y" if par_cd == "N" else "N",
            "plsp_prod_cd": "",
            "product_ln_cd": "PPO",
            "classification_cd": r.choice(["01", "02", "03"]),
            "bnft_pkg_id": BNFT_PKG_ID,
            "plan_id": PLAN_ID,
            "benefit_tier_cd": ben_tier,
            "fund_ctg_cd": "F",
            "src_subscriber_id": mbr["sub_id"],
            "emp_last_nm": mbr["emp_last_nm"],
            "emp_first_nm": mbr["emp_first_nm"],
            "emp_gender": mbr["emp_gender"],
            "subscriber_brth_dt": _dt(mbr["sub_birth_dt"]),
            "subs_zip_cd": mbr["subs_zip_cd"],
            "subs_st_postal_cd": mbr["subs_st_postal_cd"],
            "coverage_type_cd": mbr["coverage_type_cd"],
            "ssn_nbr": mbr["ssn_nbr"],
            "member_id": mbr["member_id"],
            "src_clm_mbr_id": mbr["member_id"],
            "mem_last_nm": mbr["mem_last_nm"],
            "mem_first_nm": mbr["mem_first_nm"],
            "mem_gender": mbr["mem_gender"],
            "mbr_rtp_type_cd": mbr["mbr_type"],
            "birth_dt": _dt(mbr["birth_dt"]),
            "src_clm_id": f"{file_dt_str}{i + 1:07d}",
            "acas_src_claim_line_id": f"ACAS{seq_id:015d}",
            "acas_prev_clm_seg_id": "",
            "derived_tcn_nbr": f"TCN{seq_id:015d}",
            "src_claim_line_id": f"SRC{seq_id:015d}",
            "claim_line_id": f"{seq_id:018d}",
            "ntwk_srv_area_id": NSA_ID,
            "paid_prvdr_nsa_id": NSA_ID,
            "srv_capacity_cd": "",
            "pcp_tax_id_format_cd": "2",
            "pcp_tax_id_nbr": prov_tin,
            "pcp_print_nm": prov_nm,
            "svc_pvdr_tax_id_format_cd": "2",
            "svc_pvdr_tax_id_nbr": prov_tin,
            "srv_prvdr_id": prov_id,
            "srv_prvdr_print_nm": prov_nm,
            "srv_prvdr_address_line_1_txt": f"{r.integers(100, 9999)} MEDICAL PLAZA",
            "srv_prvdr_address_line_2_txt": "",
            "srv_prvdr_city_nm": prov_city,
            "srv_prvdr_state_postal_cd": prov_st,
            "srv_prvdr_zip_cd": prov_zip,
            "srv_prvdr_provider_type_cd": "4" if inst else "1",
            "srv_prvdr_specialty_cd": spec_cd,
            "payee_cd": "P",
            "paid_prvdr_par_cd": par_cd,
            "received_dt": _dt(recv_dt),
            "adjn_dt": _dt(adjn_dt),
            "srv_start_dt": _dt(srv_start),
            "srv_stop_dt": _dt(srv_stop),
            "paid_dt_for_file_id_03_else_adjn_dt_for_other_file_id": _dt(paid_dt),
            "filler1": "",
            "filler2": "",
            "filler3": "",
            "mdc_cd": mdc,
            "drg_cd": drg,
            "prcdr_cd": prcdr,
            "prcdr_modifier_cd_1": mods[0],
            "prcdr_type_cd": clm_type,
            "icd10_indicator": "Y",
            "med_cost_subctg_cd": r.choice(MED_COST_SUB),
            "prcdr_group_nbr": "",
            "type_srv_cd": r.choice(TYPE_SRV),
            "srv_benefit_cd": "",
            "tooth_1_nbr": "",
            "plc_srv_cd": plc_srv,
            "dschrg_status_cd": dschrg_st,
            "revenue_cd": rev,
            "hcfa_bill_type_cd": bill_type,
            "unit_cnt": str(int(r.integers(1, 4))),
            "src_unit_cnt": str(int(r.integers(1, 4))),
            "src_billed_amt": _amt(billed),
            "billed_amt": _amt(billed),
            "not_covered_amt_1": _amt(not_cov),
            "not_covered_amt_2": "0.00",
            "not_covered_amt_3": "0.00",
            "clm_ln_msg_cd_1": "PR1" if ded > 0 else "",
            "clm_ln_msg_cd_2": "CO45" if not_cov > 0 else "",
            "clm_ln_msg_cd_3": "",
            "covered_amt": _amt(covered),
            "allowed_amt": _amt(allowed),
            "filler_space": "",
            "srv_copay_amt": _amt(copay),
            "src_srv_copay_amt": _amt(copay),
            "deductible_amt": _amt(ded),
            "coinsurance_amt": _amt(coins),
            "src_coins_amt": _amt(coins),
            "bnft_payable_amt": _amt(bnft_py),
            "paid_amt": _amt(paid),
            "cob_paid_amt": "0.00",
            "ahf_bfd_amt": "0.00",
            "ahf_paid_amt": "0.00",
            "negot_savings_amt": _amt(negot),
            "r_c_savings_amt": "0.00",
            "cob_savings_amt": "0.00",
            "src_cob_svngs_amt": "0.00",
            "pri_payer_cvg_cd": "",
            "cob_type_cd": "N",
            "cob_cd": "",
            "prcdr_cd_ndc": "",
            "acas_member_cumb_id": mbr["member_id"],
            "clm_ln_status_cd": status_cd,
            "src_member_id": mbr["member_id"],
            "reversal_cd": rev_cd,
            "admit_cnt": "1" if inst else "0",
            "admin_savings_amt": "0.00",
            "adj_prvdr_dsgnn_cd": "",
            "aex_plan_dsgntn_cd": "",
            "aex_benefit_tier_cd": ben_tier,
            "aex_prvdr_spctg_cd": spec_cd,
            "prod_distnctn_cd": "",
            "billed_eligible_amt": _amt(billed),
            "spclty_ctg_cls_cd": "",
            "poa_cd_1": str(poa_arr[i][0]),
            "poa_cd_2": str(poa_arr[i][1]) if diag[1] else "",
            "poa_cd_3": str(poa_arr[i][2]) if diag[2] else "",
            "filler4": "",
            "filler5": "",
            "filler6": "",
            "pricing_mthd_cd": "1",
            "type_class_cd": "",
            "specialty_ctg_cd": spec_cd,
            "srv_prvdr_npi": prov_npi,
            "ttl_ded_met_ind": "N",
            "ttl_interest_amt": "0.00",
            "ttl_surcharge_amt": "0.00",
            "srv_spclty_ctg_cd": spec_cd,
            "hcfa_plc_srv_cd": plc_srv,
            "hcfa_admit_src_cd": admit_src,
            "hcfa_admit_type_cd": admit_typ,
            "src_admit_dt": admit_dt,
            "src_discharge_dt": disc_dt,
            "prcdr_modifier_cd_2": mods[1],
            "prcdr_modifier_cd_3": mods[2],
            "poa_cd_4": str(poa_arr[i][3]) if diag[3] else "",
            "poa_cd_5": str(poa_arr[i][4]) if diag[4] else "",
            "poa_cd_6": "",
            "poa_cd_7": "",
            "poa_cd_8": "",
            "poa_cd_9": "",
            "poa_cd_10": "",
            "pri_icd9_dx_cd": diag[0],
            "icd9_dx_cd_2": diag[1],
            "icd9_dx_cd_3": diag[2],
            "icd9_dx_cd_4": diag[3],
            "icd9_dx_cd_5": diag[4],
            "icd9_dx_cd_6": "",
            "icd9_dx_cd_7": "",
            "icd9_dx_cd_8": "",
            "icd9_dx_cd_9": "",
            "icd9_dx_cd_10": "",
            "icd9_prcdr_cd_1": prcdr,
            "icd9_prcdr_cd_2": "",
            "icd9_prcdr_cd_3": "",
            "icd9_prcdr_cd_4": "",
            "icd9_prcdr_cd_5": "",
            "icd9_prcdr_cd_6": "",
            "ahf_det_order_cd": "",
            "ahf_mbr_coins_amt": _amt(coins),
            "ahf_mbr_copay_amt": _amt(copay),
            "ahf_mbr_ded_amt": _amt(ded),
            "sensitivity_indicator": "N",
            "ub92_admission_type": admit_typ,
            "filler7": "",
        }

        # Schema drift: only month-2 gets this column
        if add_telehealth:
            row["telehealth_indicator"] = str(tele_arr[i])

        row["org_cd"] = ORG_CD
        rows.append(row)

    return pd.DataFrame(rows)


# ── Rx claims generator ───────────────────────────────────────────────────────


def gen_rx_claims(file_dt_str: str, n: int, seed: int) -> pd.DataFrame:
    """Generate n pharmacy claim lines for the given file date tag (YYYYMMDD)."""
    r = np.random.default_rng(seed)
    file_dt = date(int(file_dt_str[:4]), int(file_dt_str[4:6]), int(file_dt_str[6:]))

    mbr_idx = r.integers(0, N_MEMBERS, size=n)
    presc_idx = r.integers(0, N_PRESC, size=n)
    pharm_idx = r.integers(0, N_PHARM, size=n)
    ndc_idx = r.integers(0, len(NDC_LIST), size=n)
    disp_off = r.integers(1, 60, size=n)
    proc_off = r.integers(0, 3, size=n)
    qty_arr = r.choice([30, 60, 90], size=n)
    days_arr = r.choice([30, 60, 90], size=n)
    refill_arr = r.integers(0, 6, size=n)
    daw_arr = r.choice(["0", "0", "0", "0", "1", "2", "3"], size=n)
    denied = r.random(size=n) < 0.05
    maint_arr = r.choice(["Y", "N", "N"], size=n)

    rows: list[dict[str, Any]] = []
    seq_base = int(file_dt_str) * 100_000_000

    for i in range(n):
        mbr = MEMBER_POOL[int(mbr_idx[i])]
        pi = int(presc_idx[i])
        ph = int(pharm_idx[i])
        ndc = NDC_LIST[int(ndc_idx[i])]
        name, tier, gnrc, ing_cost, awp = NDC_DRUGS[ndc]

        disp_dt = file_dt - timedelta(days=int(disp_off[i]))
        proc_dt = disp_dt + timedelta(days=int(proc_off[i]))
        qty = int(qty_arr[i])
        days = int(days_arr[i])
        is_denied = bool(denied[i])

        # Scale cost by qty (30-day base → qty factor)
        qty_factor = qty / 30.0
        ing = round(ing_cost * qty_factor, 2)
        awp_ = round(awp * qty_factor, 2)
        fee = round(float(r.uniform(2.0, 10.0)), 2)
        tax = 0.00
        calc = round(ing * float(r.uniform(0.95, 1.0)), 2)

        if tier == "1":
            copay = float(r.choice([5, 10, 15]))
        elif tier == "2":
            copay = float(r.choice([30, 35, 40]))
        else:
            copay = float(r.choice([60, 80, 100, 120]))

        ded = round(float(r.uniform(0, 0.15)) * ing, 2) if r.random() > 0.70 else 0.0
        paid = round(max(0.0, ing + fee - copay - ded), 2) if not is_denied else 0.0
        clm_status = "D" if is_denied else "P"

        seq_id = seq_base + i + 1

        rows.append(
            {
                "ps_unique_id": f"{seq_id:018d}",
                "customer_nbr": CUSTOMER_NBR,
                "group_nbr": GROUP_NBR,
                "source_derived": "N",
                "subgroup_nbr": SUBGROUP_NBR,
                "account_nbr": ACCOUNT_NBR,
                "product_ln_cd": "PPO",
                "rx_product_cd": "RX",
                "plan_id": PLAN_ID,
                "fund_ctg_cd": "F",
                "option_cd": "01",
                "rx_intgrtn_opt_cd": "I",
                "ee_id": mbr["sub_id"],
                "ee_last_name": mbr["emp_last_nm"],
                "ee_first_name": mbr["emp_first_nm"],
                "subs_zip_cd": mbr["subs_zip_cd"],
                "ssn_nbr": mbr["ssn_nbr"],
                "member_id": mbr["member_id"],
                "src_rx_member_id": mbr["member_id"],
                "last_name": mbr["mem_last_nm"],
                "first_name": mbr["mem_first_nm"],
                "src_mbr_gender_cd": mbr["mem_gender"],
                "mbr_rtp_type_cd": mbr["mbr_type"],
                "src_mbr_birth_dt": _dt(mbr["birth_dt"]),
                "filler1": "",
                "filler2": "",
                "clm_status": clm_status,
                "dir_mbr_reim_ind": "N",
                "ee_ntwk_srv_area_id": NSA_ID,
                "office_id": f"OFF{ph + 1:04d}",
                "sort_name": f"{mbr['mem_last_nm']} {mbr['mem_first_nm']}",
                "prescriber_id": PRESC_IDS[pi],
                "spclty_ctg_cd": r.choice(SPEC_CDS),
                "address_line_1": f"{r.integers(100, 9999)} PHARMACY ST",
                "address_line_2": "",
                "nabp_nbr": NABP_NBRS[ph],
                "phm_zip_cd": PHARM_ZIPS[ph],
                "process_dt": _dt(proc_dt),
                "disp_dt": _dt(disp_dt),
                "ndc_cd": ndc,
                "label_nm": name,
                "formulary_cd": tier,
                "generic_cd": gnrc,
                "source_type_cd": r.choice(["R", "R", "R", "M"]),
                "retail_mod_cd": r.choice(["R", "R", "R", "M"]),
                "new_refill_cnt": str(int(refill_arr[i])),
                "daw_cd": str(daw_arr[i]),
                "unts_dispensed_qty": str(qty),
                "days_supply_cnt": str(days),
                "sub_ing_cost_amt": _amt(ing),
                "prof_fee_amt": _amt(fee),
                "awp_amt": _amt(awp_),
                "sales_tax_amt": _amt(tax),
                "app_to_per_ded_amt": _amt(ded),
                "srv_copay_amt": _amt(copay),
                "paid_amt": _amt(paid),
                "ahf_paid_amt": "0.00",
                "ahf_bfd_amt": "0.00",
                "gpi_1st_10_bytes": GPI_LOOKUP.get(ndc, "0000000000"),
                "phi_acas_bypass_cd": "N",
                "price_type_cd": "AWP",
                "calc_ing_cost_amt": _amt(calc),
                "prescbr_id_qlfy_cd": "01",
                "prod_distnctn_cd": "",
                "rx_claim_id": f"RX{seq_id:015d}",
                "compound_cd": "0",
                "maint_drug_cd": str(maint_arr[i]),
                "prescription_nbr": f"{r.integers(1000000, 9999999)}",
                "spaces1": "",
                "spaces2": "",
                "derived1": "",
                "derived2": "",
                "filler3": "",
                "org_cd": ORG_CD,
            }
        )

    return pd.DataFrame(rows)


# ── Write pipe-delimited CSV ──────────────────────────────────────────────────


def write_pipe_csv(df: pd.DataFrame, table: str, file_dt_str: str) -> None:
    path = os.path.join(OUT_DIR, f"{table}_{file_dt_str}.csv")
    df.to_csv(path, sep="|", index=False)
    print(
        f"  {table}_{file_dt_str}.csv  {len(df):>6,} rows  {len(df.columns):>3} cols  ->  {path}"
    )


# ── Main ─────────────────────────────────────────────────────────────────────
months = args.months
if len(months) < 2:
    months = months + months  # duplicate if only one supplied

print(f"\nGenerating Aetna bronze claims — {len(months)} months")
print(f"Med rows/month: {args.med_rows}   Rx rows/month: {args.rx_rows}")
print("Schema drift: med_claims month-2 gains `telehealth_indicator` column\n")

for idx, tag in enumerate(months):
    is_month2 = idx > 0
    med_seed = SEED + idx * 10
    rx_seed = SEED + idx * 10 + 5

    med_df = gen_med_claims(tag, args.med_rows, seed=med_seed, add_telehealth=is_month2)
    rx_df = gen_rx_claims(tag, args.rx_rows, seed=rx_seed)

    write_pipe_csv(med_df, "med_claims", tag)
    write_pipe_csv(rx_df, "rx_claims", tag)

print(f"\nDone — output: {os.path.abspath(OUT_DIR)}")
print("Schema drift summary:")
print(f"  med_claims_{months[0]}.csv  — {args.med_rows} rows, 176 cols  (baseline)")
print(
    f"  med_claims_{months[1]}.csv  — {args.med_rows} rows, 177 cols  (+telehealth_indicator)"
)
print(f"  rx_claims_{months[0]}.csv   — {args.rx_rows} rows,  74 cols  (no drift)")
print(f"  rx_claims_{months[1]}.csv   — {args.rx_rows} rows,  74 cols  (no drift)")
