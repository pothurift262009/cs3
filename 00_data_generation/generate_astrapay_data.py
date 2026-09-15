#!/usr/bin/env python3
"""
AstraPay capstone — synthetic data generator.

Two strictly separated passes:

    generate_clean(rng)      -> internally consistent, defect-free data
    corrupt(clean, rng)      -> injects the planted DQ defects, logs every touched row

The defect log is the answer key for Task 3.
truth_manifest.md is the answer key for Tasks 5 and 6.

Usage:
    python generate_astrapay_data.py --out ./data
    python generate_astrapay_data.py --out ./data --validate     # print KPIs + decomposition
"""
from __future__ import annotations

import argparse
import json
from enum import Enum
from pathlib import Path

import numpy as np
import pandas as pd

# ----------------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------------

SEED = 42
START = pd.Timestamp("2025-01-01")
END = pd.Timestamp("2025-12-31")
MONTHS = pd.date_range(START, "2025-12-01", freq="MS")
DAYS = pd.date_range(START, END, freq="D")

N_CUSTOMERS = 15_000
N_MERCHANTS = 600

# Attempts grow ~70% over the period (16.4k -> 27.9k per month)
ATTEMPTS_START = 16_400
ATTEMPTS_GROWTH = 1.0495

# Driver 1: the small-ticket cohort's share of attempts, 8% -> 34%
DIGITAL_SHARE_START = 0.08
DIGITAL_SHARE_END = 0.34

# Driver 3: latency incident window
INCIDENT_START = pd.Timestamp("2025-08-01")
INCIDENT_END = pd.Timestamp("2025-09-24")
INCIDENT_PROVIDER = "PROV_MERIDIAN"

# Driver 4: fraud model version cutover
MODEL_CUTOVER = pd.Timestamp("2025-09-01")


class Country(str, Enum):
    IN = "IN"
    SG = "SG"
    AE = "AE"


class Segment(str, Enum):
    RETAIL = "RETAIL"
    SME = "SME"


class Category(str, Enum):
    GROCERY = "GROCERY"
    TRAVEL = "TRAVEL"
    DIGITAL_GOODS = "DIGITAL_GOODS"
    ELECTRONICS = "ELECTRONICS"
    SERVICES = "SERVICES"
    GAMING = "GAMING"


class PricingPlan(str, Enum):
    FLAT_2_0 = "FLAT_2_0"
    TIERED = "TIERED"
    INTERCHANGE_PLUS = "INTERCHANGE_PLUS"
    ENTERPRISE_NEGOTIATED = "ENTERPRISE_NEGOTIATED"


class RiskTier(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class Channel(str, Enum):
    CARD = "CARD"
    UPI = "UPI"
    WALLET = "WALLET"
    BANK_TRANSFER = "BANK_TRANSFER"


class TxnStatus(str, Enum):
    CAPTURED = "CAPTURED"
    DECLINED = "DECLINED"
    FAILED = "FAILED"
    REVERSED = "REVERSED"
    PENDING = "PENDING"


class KycStatus(str, Enum):
    VERIFIED = "VERIFIED"
    PENDING = "PENDING"
    REJECTED = "REJECTED"


CURRENCY_OF = {"IN": "INR", "SG": "SGD", "AE": "AED"}

# Merchant revenue: rate on gross + a fixed per-transaction fee (USD)
TAKE_RATE = {
    PricingPlan.FLAT_2_0: (0.0200, 0.20),
    PricingPlan.TIERED: (0.0160, 0.12),
    PricingPlan.INTERCHANGE_PLUS: (0.0140, 0.15),
    PricingPlan.ENTERPRISE_NEGOTIATED: (0.0110, 0.08),
}

# Driver 2: route economics. High fixed fee is only worth it on large tickets.
PROVIDERS = {
    "PROV_NORTH": dict(fixed_fee=0.05, variable_fee_pct=0.0060),
    "PROV_MERIDIAN": dict(fixed_fee=0.15, variable_fee_pct=0.0045),
    "PROV_ORBIT": dict(fixed_fee=0.35, variable_fee_pct=0.0028),
}

# Driver 2: share of the small-ticket SG/AE cohort parked on PROV_ORBIT over time
DIGITAL_ORBIT_START = 0.20
DIGITAL_ORBIT_END = 0.95

# Driver 2b: PROV_ORBIT repriced its per-transaction fixed fee on 2025-07-01.
ORBIT_REPRICE_DATE = pd.Timestamp("2025-07-01")
ORBIT_FIXED_AFTER = 0.52

ROUTES = [
    # route_id, provider, region
    ("RT_IN_01", "PROV_NORTH", "IN"),
    ("RT_IN_02", "PROV_MERIDIAN", "IN"),
    ("RT_IN_03", "PROV_ORBIT", "IN"),
    ("RT_SG_01", "PROV_ORBIT", "SG"),
    ("RT_SG_02", "PROV_MERIDIAN", "SG"),
    ("RT_SG_03", "PROV_NORTH", "SG"),
    ("RT_AE_01", "PROV_ORBIT", "AE"),
    ("RT_AE_02", "PROV_MERIDIAN", "AE"),
    ("RT_AE_03", "PROV_NORTH", "AE"),
]

# The routing table keys on MERCHANT COUNTRY, not ticket size. That is the bug.
ROUTE_WEIGHTS = {
    "IN": {"RT_IN_01": 0.60, "RT_IN_02": 0.30, "RT_IN_03": 0.10},
    "SG": {"RT_SG_01": 0.70, "RT_SG_02": 0.22, "RT_SG_03": 0.08},
    "AE": {"RT_AE_01": 0.62, "RT_AE_02": 0.28, "RT_AE_03": 0.10},
}

# Median ticket in USD at period start
TICKET_MEDIAN_USD = {
    Category.GROCERY: 95.0,
    Category.SERVICES: 95.0,
    Category.TRAVEL: 480.0,
    Category.ELECTRONICS: 480.0,
    Category.GAMING: 35.0,
    Category.DIGITAL_GOODS: 40.0,
}
DIGITAL_COHORT_MEDIAN_USD = 14.0  # the SG/AE small-ticket cohort
TICKET_SIGMA = 0.75

CHANNEL_WEIGHTS = {
    "IN": {"UPI": 0.46, "CARD": 0.30, "WALLET": 0.16, "BANK_TRANSFER": 0.08},
    "SG": {"CARD": 0.58, "BANK_TRANSFER": 0.22, "WALLET": 0.16, "UPI": 0.04},
    "AE": {"CARD": 0.62, "BANK_TRANSFER": 0.20, "WALLET": 0.15, "UPI": 0.03},
}

BASE_SUCCESS_RATE = 0.914
CHARGEBACK_FEE_USD = 15.0

# FX: rate_to_usd is a MULTIPLIER -> amount_usd = amount_local * rate_to_usd
FX_START = {"INR": 1 / 83.0, "SGD": 1 / 1.345, "AED": 1 / 3.6725, "USD": 1.0}
FX_END = {"INR": 1 / 88.0, "SGD": 1 / 1.372, "AED": 1 / 3.6725, "USD": 1.0}
FX_SPREAD_BASE = 0.0035
FX_SPREAD_Q4 = 0.0060


# ----------------------------------------------------------------------------
# Small helpers
# ----------------------------------------------------------------------------

def weighted_choice(rng, keys_by_group, group_values, n):
    """Vectorised per-group weighted sampling. keys_by_group: {group: {key: w}}."""
    out = np.empty(n, dtype=object)
    for group, weights in keys_by_group.items():
        mask = group_values == group
        k = int(mask.sum())
        if k == 0:
            continue
        keys = list(weights.keys())
        probs = np.array(list(weights.values()), dtype=float)
        probs = probs / probs.sum()
        out[mask] = rng.choice(keys, size=k, p=probs)
    return out


def to_minor(usd_array):
    """Money as integers in minor units. Never float-accumulate currency."""
    return np.rint(np.asarray(usd_array, dtype=float) * 100).astype(np.int64)


def random_times_in_month(rng, month_starts):
    """Uniform timestamp within each row's calendar month."""
    ms = pd.DatetimeIndex(month_starts)
    month_end = ms + pd.offsets.MonthEnd(1)
    span_s = (month_end - ms).total_seconds() + 86399
    offs = rng.random(len(ms)) * span_s
    return ms + pd.to_timedelta(offs, unit="s")


# ----------------------------------------------------------------------------
# Clean generation
# ----------------------------------------------------------------------------

def gen_fx(rng):
    n = len(DAYS)
    t = np.linspace(0, 1, n)
    rows = []
    for cur in ["INR", "SGD", "AED", "USD"]:
        drift = FX_START[cur] + (FX_END[cur] - FX_START[cur]) * t
        noise = 1 + rng.normal(0, 0.0012, n) if cur != "USD" else np.ones(n)
        mid = drift * noise
        spread = np.where(DAYS >= pd.Timestamp("2025-10-01"), FX_SPREAD_Q4, FX_SPREAD_BASE)
        if cur == "USD":
            spread = np.zeros(n)
        rows.append(pd.DataFrame({
            "rate_date": DAYS, "currency": cur,
            "rate_to_usd": np.round(mid, 8), "rate_type": "MID",
        }))
        rows.append(pd.DataFrame({
            "rate_date": DAYS, "currency": cur,
            "rate_to_usd": np.round(mid * (1 - spread), 8), "rate_type": "SETTLEMENT",
        }))
    return pd.concat(rows, ignore_index=True).sort_values(
        ["rate_date", "currency", "rate_type"]).reset_index(drop=True)


def gen_route_cost(rng):
    rows = []
    for route_id, provider, region in ROUTES:
        p = PROVIDERS[provider]
        n = len(DAYS)
        drift = 1 + np.linspace(0, 0.015, n)  # mild cost creep
        fixed = p["fixed_fee"] * drift
        if provider == "PROV_ORBIT":
            fixed = np.where(DAYS >= ORBIT_REPRICE_DATE, ORBIT_FIXED_AFTER * drift, fixed)
        rows.append(pd.DataFrame({
            "route_id": route_id,
            "provider": provider,
            "region": region,
            "rate_date": DAYS,
            "fixed_fee": np.round(fixed, 4),
            "variable_fee_pct": np.round(p["variable_fee_pct"] * drift, 6),
        }))
    df = pd.concat(rows, ignore_index=True)
    return df[["route_id", "provider", "region", "rate_date", "fixed_fee", "variable_fee_pct"]]


def gen_customers(rng):
    n = N_CUSTOMERS
    country = rng.choice(["IN", "SG", "AE"], size=n, p=[0.62, 0.21, 0.17])
    segment = rng.choice(["RETAIL", "SME"], size=n, p=[0.78, 0.22])
    onboard = START - pd.to_timedelta(rng.integers(0, 1400, n), unit="D")
    kyc = rng.choice(["VERIFIED", "PENDING", "REJECTED"], size=n, p=[0.93, 0.055, 0.015])
    return pd.DataFrame({
        "customer_id": [f"CUS{str(i).zfill(6)}" for i in range(1, n + 1)],
        "segment": segment,
        "country": country,
        "onboarding_date": onboard.normalize(),
        "kyc_status": kyc,
    })


def gen_merchants(rng):
    n = N_MERCHANTS
    country = rng.choice(["IN", "SG", "AE"], size=n, p=[0.55, 0.24, 0.21])
    cats = [c.value for c in Category]
    category = rng.choice(cats, size=n, p=[0.19, 0.13, 0.22, 0.13, 0.22, 0.11])

    # Plan follows category economics: small-ticket digital merchants sit on FLAT_2_0
    plan = np.empty(n, dtype=object)
    for i in range(n):
        c = category[i]
        if c in (Category.DIGITAL_GOODS.value, Category.GAMING.value):
            plan[i] = rng.choice(["FLAT_2_0", "TIERED"], p=[0.82, 0.18])
        elif c in (Category.TRAVEL.value, Category.ELECTRONICS.value):
            plan[i] = rng.choice(
                ["ENTERPRISE_NEGOTIATED", "INTERCHANGE_PLUS", "TIERED"], p=[0.45, 0.35, 0.20])
        else:
            plan[i] = rng.choice(
                ["TIERED", "INTERCHANGE_PLUS", "FLAT_2_0"], p=[0.50, 0.30, 0.20])

    risk = np.where(category == Category.GAMING.value,
                    rng.choice(["MEDIUM", "HIGH"], size=n, p=[0.45, 0.55]),
                    rng.choice(["LOW", "MEDIUM", "HIGH"], size=n, p=[0.55, 0.35, 0.10]))

    df = pd.DataFrame({
        "merchant_id": [f"MER{str(i).zfill(5)}" for i in range(1, n + 1)],
        "category": category,
        "country": country,
        "pricing_plan": plan,
        "risk_tier": risk,
    })
    # Driver 1 cohort membership
    df["is_digital_cohort"] = (
        (df["category"] == Category.DIGITAL_GOODS.value) & (df["country"].isin(["SG", "AE"]))
    )
    # Per-merchant activity weight (Zipf-ish: a few big merchants)
    df["weight"] = rng.pareto(1.6, n) + 0.15
    return df


def gen_risk_snapshots(rng, merchants):
    base = merchants["risk_tier"].map({"LOW": 0.18, "MEDIUM": 0.42, "HIGH": 0.68}).to_numpy()
    rows = []
    for k, m in enumerate(MONTHS):
        score = np.clip(base + rng.normal(0, 0.06, len(merchants)) + k * 0.002, 0.01, 0.99)
        band = np.select(
            [score < 0.30, score < 0.55], ["LOW", "MEDIUM"], default="HIGH")
        rows.append(pd.DataFrame({
            "merchant_id": merchants["merchant_id"].to_numpy(),
            "snapshot_month": m.strftime("%Y-%m"),
            "risk_score": np.round(score, 4),
            "risk_band": band,
        }))
    return pd.concat(rows, ignore_index=True)


def gen_transactions(rng, customers, merchants, fx):
    mid = fx[fx["rate_type"] == "MID"].set_index(["rate_date", "currency"])["rate_to_usd"]

    dig_idx = merchants.index[merchants["is_digital_cohort"]].to_numpy()
    base_idx = merchants.index[~merchants["is_digital_cohort"]].to_numpy()
    dig_w = merchants.loc[dig_idx, "weight"].to_numpy()
    base_w = merchants.loc[base_idx, "weight"].to_numpy()
    dig_w = dig_w / dig_w.sum()
    base_w = base_w / base_w.sum()

    sme_cust = customers.index[customers["segment"] == "SME"].to_numpy()
    all_cust = customers.index.to_numpy()

    parts = []
    for k, month in enumerate(MONTHS):
        n_att = int(round(ATTEMPTS_START * (ATTEMPTS_GROWTH ** k)))
        share = DIGITAL_SHARE_START + (DIGITAL_SHARE_END - DIGITAL_SHARE_START) * (k / 11) ** 1.25
        n_dig = int(round(n_att * share))
        n_base = n_att - n_dig

        m_rows = np.concatenate([
            rng.choice(dig_idx, size=n_dig, p=dig_w),
            rng.choice(base_idx, size=n_base, p=base_w),
        ])
        is_dig = np.concatenate([np.ones(n_dig, bool), np.zeros(n_base, bool)])

        # Digital-cohort traffic skews SME
        c_rows = np.empty(n_att, dtype=np.int64)
        pick_sme = is_dig & (rng.random(n_att) < 0.80)
        c_rows[pick_sme] = rng.choice(sme_cust, size=int(pick_sme.sum()))
        c_rows[~pick_sme] = rng.choice(all_cust, size=int((~pick_sme).sum()))

        parts.append(pd.DataFrame({
            "m_idx": m_rows, "c_idx": c_rows, "is_dig": is_dig,
            "month_start": month,
        }))

    tx = pd.concat(parts, ignore_index=True)
    n = len(tx)
    tx["created_at"] = random_times_in_month(rng, tx["month_start"])
    tx = tx.sort_values("created_at").reset_index(drop=True)

    m = merchants.loc[tx["m_idx"].to_numpy()].reset_index(drop=True)
    c = customers.loc[tx["c_idx"].to_numpy()].reset_index(drop=True)

    tx["merchant_id"] = m["merchant_id"].to_numpy()
    tx["customer_id"] = c["customer_id"].to_numpy()
    tx["m_country"] = m["country"].to_numpy()
    tx["category"] = m["category"].to_numpy()
    tx["pricing_plan"] = m["pricing_plan"].to_numpy()
    tx["risk_tier"] = m["risk_tier"].to_numpy()
    tx["cust_segment"] = c["segment"].to_numpy()
    tx["currency"] = pd.Series(tx["m_country"]).map(CURRENCY_OF).to_numpy()

    # --- amount: lognormal, priced in LOCAL currency at period-start FX --------
    med_usd = np.where(
        tx["is_dig"].to_numpy(),
        DIGITAL_COHORT_MEDIAN_USD,
        pd.Series(tx["category"]).map({k.value: v for k, v in TICKET_MEDIAN_USD.items()}).to_numpy(),
    )
    start_rate = pd.Series(tx["currency"]).map(FX_START).to_numpy()
    med_local = med_usd / start_rate
    amount_local = med_local * np.exp(rng.normal(0, TICKET_SIGMA, n))
    tx["amount"] = np.round(amount_local, 2)

    # USD value at the MID rate on the transaction date (ground truth only)
    key = pd.MultiIndex.from_arrays(
        [tx["created_at"].dt.normalize(), tx["currency"]])
    tx["fx_mid"] = mid.reindex(key).to_numpy()
    tx["amount_usd"] = tx["amount"] * tx["fx_mid"]

    # --- channel & route ------------------------------------------------------
    tx["channel"] = weighted_choice(rng, CHANNEL_WEIGHTS, tx["m_country"].to_numpy(), n)
    tx["route_id"] = weighted_choice(rng, ROUTE_WEIGHTS, tx["m_country"].to_numpy(), n)

    # Driver 2: the routing table keys on country, and over the period an ever larger
    # share of the small-ticket SG/AE cohort is parked on the high-fixed-fee provider.
    k = (tx["created_at"].dt.month - 1).to_numpy()
    orbit_p = DIGITAL_ORBIT_START + (DIGITAL_ORBIT_END - DIGITAL_ORBIT_START) * (k / 11)
    dig = tx["is_dig"].to_numpy()
    to_orbit = rng.random(n) < orbit_p
    ctry = tx["m_country"].to_numpy()
    orbit_route = np.where(ctry == "SG", "RT_SG_01", "RT_AE_01")   # PROV_ORBIT
    alt_route = np.where(ctry == "SG", "RT_SG_03", "RT_AE_03")     # PROV_NORTH
    tx["route_id"] = np.where(dig, np.where(to_orbit, orbit_route, alt_route),
                              tx["route_id"].to_numpy())

    route_prov = {r[0]: r[1] for r in ROUTES}
    tx["provider"] = pd.Series(tx["route_id"]).map(route_prov).to_numpy()

    # --- latency (Driver 3) ---------------------------------------------------
    in_incident = (
        (tx["created_at"] >= INCIDENT_START)
        & (tx["created_at"] <= INCIDENT_END)
        & (tx["provider"] == INCIDENT_PROVIDER)
    ).to_numpy()
    mu = np.where(in_incident, np.log(1180), np.log(340))
    sig = np.where(in_incident, 0.95, 0.55)
    tx["processing_ms"] = np.rint(np.exp(rng.normal(mu, sig))).astype(int)
    tx["in_incident"] = in_incident

    # --- status ---------------------------------------------------------------
    p_success = np.full(n, BASE_SUCCESS_RATE)
    p_success -= np.where(tx["risk_tier"].to_numpy() == "HIGH", 0.035, 0.0)
    p_success -= np.where(tx["channel"].to_numpy() == "WALLET", 0.015, 0.0)
    p_success -= np.where(in_incident, 0.075, 0.0)          # timeouts during the incident
    u = rng.random(n)
    success = u < p_success
    tail = rng.random(n)
    status = np.where(
        success,
        np.where(tail < 0.008, TxnStatus.REVERSED.value, TxnStatus.CAPTURED.value),
        np.where(tail < 0.62, TxnStatus.DECLINED.value,
                 np.where(tail < 0.97, TxnStatus.FAILED.value, TxnStatus.PENDING.value)),
    )
    tx["status"] = status
    tx["transaction_id"] = [f"TXN{str(i).zfill(8)}" for i in range(1, n + 1)]

    # Reversals carry a negative amount and point at the original attempt
    rev = tx["status"].to_numpy() == TxnStatus.REVERSED.value
    tx.loc[rev, "amount"] = -tx.loc[rev, "amount"]
    tx.loc[rev, "amount_usd"] = -tx.loc[rev, "amount_usd"]

    return tx


def gen_payment_events(rng, tx):
    seq = {
        TxnStatus.CAPTURED.value: ["CREATED", "AUTHORIZED", "CAPTURED", "SETTLED"],
        TxnStatus.REVERSED.value: ["CREATED", "AUTHORIZED", "CAPTURED", "REVERSED"],
        TxnStatus.DECLINED.value: ["CREATED", "DECLINED"],
        TxnStatus.FAILED.value: ["CREATED", "AUTHORIZED", "FAILED"],
        TxnStatus.PENDING.value: ["CREATED", "AUTHORIZED"],
    }
    frames = []
    for st, evs in seq.items():
        sub = tx[tx["status"] == st]
        if sub.empty:
            continue
        k = len(evs)
        rep = np.repeat(sub["transaction_id"].to_numpy(), k)
        base = np.repeat(sub["created_at"].to_numpy(), k)
        pms = np.repeat(sub["processing_ms"].to_numpy(), k)
        step = np.tile(np.arange(k), len(sub))
        # each step costs a slice of total processing time; SETTLED lands days later
        offset_s = pms / 1000.0 * (step / max(k - 1, 1))
        settle_lag = np.where(np.tile(np.array(evs), len(sub)) == "SETTLED",
                              rng.integers(1, 3, k * len(sub)) * 86400, 0)
        ev_time = pd.to_datetime(base) + pd.to_timedelta(offset_s + settle_lag, unit="s")
        frames.append(pd.DataFrame({
            "transaction_id": rep,
            "event_type": np.tile(np.array(evs), len(sub)),
            "event_time": ev_time,
            "processing_ms": np.rint(pms / k).astype(int),
            "ingestion_time": ev_time + pd.to_timedelta(
                rng.integers(20, 900, k * len(sub)), unit="s"),
        }))
    ev = pd.concat(frames, ignore_index=True)
    return ev.sort_values(["transaction_id", "event_time"]).reset_index(drop=True)


def gen_fraud_decisions(rng, tx):
    n = len(tx)
    n_rules = np.clip(1 + rng.poisson(0.8, n), 1, 4)
    rep_id = np.repeat(tx["transaction_id"].to_numpy(), n_rules)
    rep_created = np.repeat(tx["created_at"].to_numpy(), n_rules)
    rep_tier = np.repeat(tx["risk_tier"].to_numpy(), n_rules)
    rep_status = np.repeat(tx["status"].to_numpy(), n_rules)
    total = len(rep_id)

    base = pd.Series(rep_tier).map({"LOW": 0.16, "MEDIUM": 0.38, "HIGH": 0.63}).to_numpy()
    score = np.clip(base + rng.normal(0, 0.12, total), 0.001, 0.999)

    declined = rep_status == TxnStatus.DECLINED.value
    score = np.where(declined & (rng.random(total) < 0.7),
                     np.clip(score + 0.28, 0, 0.999), score)
    decision = np.select(
        [score > 0.80, score > 0.55], ["DECLINE", "REVIEW"], default="APPROVE")

    model_version = np.where(pd.to_datetime(rep_created) >= MODEL_CUTOVER, "v3.0", "v2.1")
    rule_id = rng.choice(
        ["FR_VELOCITY", "FR_GEO", "FR_DEVICE", "FR_AMOUNT", "FR_BIN", "FR_MLSCORE"], total)

    return pd.DataFrame({
        "transaction_id": rep_id,
        "rule_id": rule_id,
        "decision": decision,
        "risk_score": np.round(score, 4),
        "model_version": model_version,
    })


def route_fees_for(route_cost, route_ids, dates):
    """Look up (fixed_fee, variable_fee_pct) for each transaction's route and date."""
    rc = route_cost.set_index(["route_id", "rate_date"])
    key = pd.MultiIndex.from_arrays([np.asarray(route_ids), pd.DatetimeIndex(dates)])
    return (rc["fixed_fee"].reindex(key).to_numpy(),
            rc["variable_fee_pct"].reindex(key).to_numpy())


def gen_settlements(rng, tx, fx, route_cost):
    """One settlement row per captured transaction.

    fee_amount is the fee AstraPay charges the MERCHANT (AstraPay revenue).
    The cost AstraPay pays the provider lives in route_cost and is not in here.
    settlement_amount is what the merchant actually receives.
    """
    st = fx[fx["rate_type"] == "SETTLEMENT"].set_index(["rate_date", "currency"])["rate_to_usd"]
    cap = tx[tx["status"] == TxnStatus.CAPTURED.value].copy()

    plan_rate = cap["pricing_plan"].map({k.value: v[0] for k, v in TAKE_RATE.items()}).to_numpy()
    plan_fixed = cap["pricing_plan"].map({k.value: v[1] for k, v in TAKE_RATE.items()}).to_numpy()

    key = pd.MultiIndex.from_arrays([cap["created_at"].dt.normalize(), cap["currency"]])
    rate_settle = st.reindex(key).to_numpy()
    amt_usd = cap["amount"].to_numpy() * rate_settle

    fee_usd = amt_usd * plan_rate + plan_fixed
    lag = rng.integers(1, 4, len(cap))
    settle_date = (cap["created_at"].dt.normalize() + pd.to_timedelta(lag, unit="D"))

    return pd.DataFrame({
        "transaction_id": cap["transaction_id"].to_numpy(),
        "settlement_amount": np.round(amt_usd - fee_usd, 2),
        "settlement_currency": "USD",
        "fee_amount": np.round(fee_usd, 4),
        "settlement_status": np.where(rng.random(len(cap)) < 0.985, "SETTLED", "IN_TRANSIT"),
        "settlement_date": settle_date.dt.date,
    })


def gen_chargebacks(rng, tx):
    cap = tx[tx["status"] == TxnStatus.CAPTURED.value].copy()
    n = len(cap)
    rate = np.full(n, 0.0022)
    gaming_ae = (cap["category"].to_numpy() == Category.GAMING.value) & \
                (cap["m_country"].to_numpy() == "AE")
    month_idx = cap["created_at"].dt.month.to_numpy() - 1
    rate = np.where(gaming_ae, 0.019 + 0.0009 * month_idx, rate)   # 1.9% -> 2.9%
    rate = np.where(cap["risk_tier"].to_numpy() == "HIGH", rate * 1.5, rate)
    # card-not-present fraud lands on small tickets; big-ticket flows carry 3DS
    size = np.abs(cap["amount_usd"].to_numpy())
    rate = rate * np.clip(60.0 / np.maximum(size, 1.0), 0.06, 2.5)

    hit = rng.random(n) < rate
    sub = cap[hit]
    k = len(sub)
    opened = sub["created_at"] + pd.to_timedelta(rng.integers(15, 75, k), unit="D")
    resolved = opened + pd.to_timedelta(rng.integers(10, 60, k), unit="D")
    resolved = resolved.where(rng.random(k) < 0.78)  # some still open

    return pd.DataFrame({
        "chargeback_id": [f"CB{str(i).zfill(6)}" for i in range(1, k + 1)],
        "transaction_id": sub["transaction_id"].to_numpy(),
        "reason": rng.choice(
            ["FRAUD", "PRODUCT_NOT_RECEIVED", "DUPLICATE", "SUBSCRIPTION_CANCELLED",
             "AUTHORISATION"], k, p=[0.44, 0.22, 0.11, 0.15, 0.08]),
        "amount": np.round(np.abs(sub["amount"].to_numpy()), 2),
        "opened_at": opened.to_numpy(),
        "resolved_at": resolved.to_numpy(),
    })


def gen_pricing_plan(rng):
    """Rate card. One row per pricing plan. The contracted merchant fee."""
    return pd.DataFrame([
        {"pricing_plan": k.value,
         "rate_pct": round(v[0] * 100, 4),
         "fixed_fee_usd": v[1],
         "effective_from": START.date(),
         "billing_basis": "per successful transaction"}
        for k, v in TAKE_RATE.items()
    ])


def generate_clean(rng):
    fx = gen_fx(rng)
    route_cost = gen_route_cost(rng)
    customers = gen_customers(rng)
    merchants = gen_merchants(rng)
    snapshots = gen_risk_snapshots(rng, merchants)
    tx = gen_transactions(rng, customers, merchants, fx)
    events = gen_payment_events(rng, tx)
    fraud = gen_fraud_decisions(rng, tx)
    settlement = gen_settlements(rng, tx, fx, route_cost)
    chargeback = gen_chargebacks(rng, tx)
    return dict(fx_rate=fx, route_cost=route_cost, pricing_plan=gen_pricing_plan(rng),
                customer=customers, merchant=merchants,
                merchant_risk_snapshot=snapshots, transaction=tx, payment_event=events,
                fraud_decision=fraud, settlement=settlement, chargeback=chargeback)


# ----------------------------------------------------------------------------
# Corruption pass — every defect logged
# ----------------------------------------------------------------------------

def corrupt(clean, rng):
    d = {k: v.copy() for k, v in clean.items()}
    log = []

    def note(defect, table, ids, severity, detail):
        log.append(dict(defect=defect, table=table, severity=severity,
                        n_rows=len(ids), detail=detail,
                        sample_ids=list(map(str, ids[:20]))))

    tx = d["transaction"]

    # 1. Missing merchant_id, concentrated in WALLET (2.1%) vs elsewhere (0.4%)
    p = np.where(tx["channel"].to_numpy() == "WALLET", 0.021, 0.004)
    hit = rng.random(len(tx)) < p
    tx.loc[hit, "merchant_id"] = None
    note("missing_merchant_id", "transaction", tx.loc[hit, "transaction_id"].to_numpy(),
         "WARNING", "Concentrated in WALLET channel; not uniform noise.")

    # 2b. Orphaned negative amounts: negative value on a CAPTURED row, no parent
    cap_idx = tx.index[tx["status"] == TxnStatus.CAPTURED.value].to_numpy()
    orph = rng.choice(cap_idx, size=int(0.0015 * len(tx)), replace=False)
    tx.loc[orph, "amount"] = -tx.loc[orph, "amount"].abs()
    note("orphan_negative_amount", "transaction", tx.loc[orph, "transaction_id"].to_numpy(),
         "BLOCKING", "Negative amount on CAPTURED status with no reversal parent. Quarantine.")

    # 2a. Legitimate reversals already exist (status REVERSED, negative amount)
    rev_ids = tx.loc[tx["status"] == TxnStatus.REVERSED.value, "transaction_id"].to_numpy()
    note("legitimate_reversal", "transaction", rev_ids, "INFORMATIONAL",
         "Negative amount with status REVERSED. Legitimate — net, do not drop.")

    # 3. risk_score out of 0-1 range: v3.0 emits a 0-100 scale
    fr = d["fraud_decision"]
    v3 = fr["model_version"].to_numpy() == "v3.0"
    fr.loc[v3, "risk_score"] = np.round(fr.loc[v3, "risk_score"] * 100, 2)
    note("risk_score_out_of_range", "fraud_decision",
         fr.loc[v3, "transaction_id"].to_numpy(), "WARNING",
         "model_version v3.0 emits 0-100 instead of 0-1. Normalise before comparing thresholds.")

    # 5. Late-arriving events: SETTLED from PROV_ORBIT arrive 2-9 days late
    ev = d["payment_event"]
    prov = tx.set_index("transaction_id")["provider"]
    ev_prov = prov.reindex(ev["transaction_id"]).to_numpy()
    late = (ev["event_type"].to_numpy() == "SETTLED") & (ev_prov == "PROV_ORBIT") & \
           (rng.random(len(ev)) < 0.62)
    ev.loc[late, "ingestion_time"] = ev.loc[late, "event_time"] + pd.to_timedelta(
        rng.integers(2, 10, int(late.sum())), unit="D")
    note("late_arriving_events", "payment_event",
         ev.loc[late, "transaction_id"].to_numpy(), "WARNING",
         "ingestion_time - event_time of 2-9 days. Use event_time for KPIs, ingestion_time for lag.")

    # 6a. Missing settlement rows, weighted toward December
    se = d["settlement"]
    sd = pd.to_datetime(se["settlement_date"])
    p_drop = np.where(sd.dt.month >= 12, 0.22, 0.026)
    drop = rng.random(len(se)) < p_drop
    dropped_ids = se.loc[drop, "transaction_id"].to_numpy()
    se = se[~drop].reset_index(drop=True)
    note("settlement_missing", "settlement", dropped_ids, "BLOCKING",
         "Captured transactions with no settlement row; weighted to December (in transit at cutoff).")

    # 6b. Duplicate settlement rows: a partial plus a correction
    dup_n = int(0.006 * len(se))
    dup_idx = rng.choice(se.index.to_numpy(), size=dup_n, replace=False)
    part = se.loc[dup_idx].copy()
    frac = rng.uniform(0.35, 0.65, dup_n)
    se.loc[dup_idx, "settlement_amount"] = np.round(
        se.loc[dup_idx, "settlement_amount"].to_numpy() * frac, 2)
    se.loc[dup_idx, "fee_amount"] = np.round(
        se.loc[dup_idx, "fee_amount"].to_numpy() * frac, 4)
    part["settlement_amount"] = np.round(part["settlement_amount"].to_numpy() * (1 - frac), 2)
    part["fee_amount"] = np.round(part["fee_amount"].to_numpy() * (1 - frac), 4)
    part["settlement_status"] = "CORRECTION"
    se = pd.concat([se, part], ignore_index=True)
    note("settlement_duplicate", "settlement", part["transaction_id"].to_numpy(), "BLOCKING",
         "Two rows per transaction (partial + correction). Sum at transaction grain before joining.")

    # 6c. Orphan settlement rows with no matching transaction
    orphan_n = int(0.002 * len(se))
    orphan = se.sample(orphan_n, random_state=7).copy()
    orphan["transaction_id"] = [f"TXN9{str(i).zfill(7)}" for i in range(orphan_n)]
    se = pd.concat([se, orphan], ignore_index=True)
    se = se.sample(frac=1.0, random_state=11).reset_index(drop=True)
    note("settlement_orphan", "settlement", orphan["transaction_id"].to_numpy(), "BLOCKING",
         "settlement_id refers to a transaction_id not present in transaction.csv.")
    d["settlement"] = se

    # 8/9. Fan-out risks are structural, not injected — log them so the key is complete
    note("fanout_merchant_risk_snapshot", "merchant_risk_snapshot",
         np.array(["(all merchants)"]), "BLOCKING",
         "12 rows per merchant. A plain join multiplies transaction amount by 12. Use an as-of join.")
    note("fanout_fraud_decision", "fraud_decision", np.array(["(1-4 rows per txn)"]), "BLOCKING",
         "Multiple rules fire per transaction. Pre-aggregate to transaction grain before joining.")
    note("fanout_payment_event", "payment_event", np.array(["(2-4 rows per txn)"]), "BLOCKING",
         "Lifecycle events. Pivot or pre-aggregate before joining to transaction.")
    note("fx_rate_types", "fx_rate", np.array(["MID", "SETTLEMENT"]), "WARNING",
         "Two rate types. SETTLEMENT is the realised rate; spread widens in Q4.")

    d["transaction"] = tx
    return d, pd.DataFrame(log)


# ----------------------------------------------------------------------------
# Output
# ----------------------------------------------------------------------------

PUBLIC_COLUMNS = {
    "customer": ["customer_id", "segment", "country", "onboarding_date", "kyc_status"],
    "merchant": ["merchant_id", "category", "country", "pricing_plan", "risk_tier"],
    "transaction": ["transaction_id", "customer_id", "merchant_id", "amount", "currency",
                    "channel", "status", "created_at", "route_id"],
    "payment_event": ["transaction_id", "event_type", "event_time", "processing_ms",
                      "ingestion_time"],
    "fraud_decision": ["transaction_id", "rule_id", "decision", "risk_score", "model_version"],
    "settlement": ["transaction_id", "settlement_amount", "settlement_currency", "fee_amount",
                   "settlement_status", "settlement_date"],
    "fx_rate": ["rate_date", "currency", "rate_to_usd", "rate_type"],
    "route_cost": ["route_id", "provider", "region", "rate_date", "fixed_fee",
                   "variable_fee_pct"],
    "pricing_plan": ["pricing_plan", "rate_pct", "fixed_fee_usd", "effective_from",
                     "billing_basis"],
    "chargeback": ["chargeback_id", "transaction_id", "reason", "amount", "opened_at",
                   "resolved_at"],
    "merchant_risk_snapshot": ["merchant_id", "snapshot_month", "risk_score", "risk_band"],
}


def write_csvs(data, outdir: Path):
    outdir.mkdir(parents=True, exist_ok=True)
    for name, cols in PUBLIC_COLUMNS.items():
        df = data[name][cols]
        df.to_csv(outdir / f"{name}.csv", index=False)
        print(f"  {name}.csv  {len(df):>8,} rows")


# ----------------------------------------------------------------------------
# Validation — this is the grader, not part of the deliverable
# ----------------------------------------------------------------------------

def validate(clean):
    tx = clean["transaction"]
    cb = clean["chargeback"].set_index("transaction_id")["amount"]

    cap = tx[tx["status"] == TxnStatus.CAPTURED.value].copy()
    rates = cap["pricing_plan"].map({k.value: v[0] for k, v in TAKE_RATE.items()}).to_numpy()
    fixed_rev = cap["pricing_plan"].map({k.value: v[1] for k, v in TAKE_RATE.items()}).to_numpy()
    rfix, rvar = route_fees_for(
        clean["route_cost"], cap["route_id"].to_numpy(), cap["created_at"].dt.normalize())

    gross = cap["amount_usd"].to_numpy()
    revenue = gross * rates + fixed_rev
    cost = rfix + gross * rvar
    cb_amt = cb.reindex(cap["transaction_id"]).fillna(0).to_numpy()
    cb_cost = np.where(cb_amt > 0, cb_amt * cap["fx_mid"].to_numpy() + CHARGEBACK_FEE_USD, 0)
    cap["contribution"] = revenue - cost - cb_cost
    cap["month"] = cap["created_at"].dt.to_period("M")

    g = cap.groupby("month").agg(
        successful=("transaction_id", "count"),
        total_contribution=("contribution", "sum"),
        gpv_usd=("amount_usd", "sum"),
    )
    g["contrib_per_txn"] = g["total_contribution"] / g["successful"]
    att = tx.groupby(tx["created_at"].dt.to_period("M")).size().rename("attempted")
    g = g.join(att)
    g["success_rate"] = g["successful"] / g["attempted"]

    print("\n=== Monthly KPIs ===")
    print(g[["attempted", "successful", "success_rate", "gpv_usd",
             "total_contribution", "contrib_per_txn"]].round(3).to_string())

    first, last = g.iloc[0], g.iloc[-1]
    print(f"\nattempts        {first.attempted:>10,.0f} -> {last.attempted:>10,.0f}"
          f"   {last.attempted / first.attempted - 1:+.1%}")
    print(f"total contrib   {first.total_contribution:>10,.0f} -> "
          f"{last.total_contribution:>10,.0f}   "
          f"{last.total_contribution / first.total_contribution - 1:+.1%}")
    print(f"contrib / txn   {first.contrib_per_txn:>10.3f} -> {last.contrib_per_txn:>10.3f}"
          f"   {last.contrib_per_txn / first.contrib_per_txn - 1:+.1%}")

    # Mix vs within-segment decomposition over cohort x category
    cap["cohort"] = np.where(cap["is_dig"], "DIGITAL_SME_SGAE", cap["category"])
    a = cap[cap["month"] == g.index[0]]
    b = cap[cap["month"] == g.index[-1]]
    wa = a.groupby("cohort").size() / len(a)
    wb = b.groupby("cohort").size() / len(b)
    ca = a.groupby("cohort")["contribution"].mean()
    cb_ = b.groupby("cohort")["contribution"].mean()
    idx = wa.index.union(wb.index)
    wa, wb = wa.reindex(idx, fill_value=0), wb.reindex(idx, fill_value=0)
    ca, cb_ = ca.reindex(idx).fillna(0), cb_.reindex(idx).fillna(0)

    mix = ((wb - wa) * ca).sum()
    within = (wb * (cb_ - ca)).sum()
    print(f"\n=== Decomposition (Jan -> Dec, contribution per successful txn) ===")
    print(f"  mix effect     {mix:+.4f}")
    print(f"  within-segment {within:+.4f}")
    print(f"  total          {mix + within:+.4f}   "
          f"(actual {last.contrib_per_txn - first.contrib_per_txn:+.4f})")
    print(f"  mix share      {mix / (mix + within):.1%}")

    print("\n=== Cohort detail ===")
    det = pd.DataFrame({"w_jan": wa, "w_dec": wb, "contrib_jan": ca, "contrib_dec": cb_})
    print(det.round(4).to_string())

    inc = clean["transaction"]
    mer = inc[inc["provider"] == INCIDENT_PROVIDER].copy()
    mer["m"] = mer["created_at"].dt.to_period("M")
    sr = mer.groupby("m").apply(
        lambda x: (x["status"] == "CAPTURED").mean(), include_groups=False)
    print(f"\n=== {INCIDENT_PROVIDER} success rate by month ===")
    print(sr.round(4).to_string())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="./data")
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--validate", action="store_true")
    args = ap.parse_args()

    rng = np.random.default_rng(args.seed)
    print("Generating clean data...")
    clean = generate_clean(rng)

    if args.validate:
        validate(clean)

    print("\nInjecting defects...")
    dirty, defect_log = corrupt(clean, np.random.default_rng(args.seed + 1))

    out = Path(args.out)
    print(f"\nWriting to {out.resolve()}")
    write_csvs(dirty, out)

    keydir = out / "_answer_key"
    keydir.mkdir(exist_ok=True)
    defect_log.to_csv(keydir / "defect_log.csv", index=False)
    (keydir / "params.json").write_text(json.dumps({
        "seed": args.seed,
        "period": [str(START.date()), str(END.date())],
        "incident": {"provider": INCIDENT_PROVIDER,
                     "window": [str(INCIDENT_START.date()), str(INCIDENT_END.date())]},
        "model_cutover": str(MODEL_CUTOVER.date()),
        "digital_share": [DIGITAL_SHARE_START, DIGITAL_SHARE_END],
        "providers": PROVIDERS,
        "take_rate": {k.value: v for k, v in TAKE_RATE.items()},
    }, indent=2))
    print(f"  _answer_key/defect_log.csv  ({len(defect_log)} defect classes)")
    print("  _answer_key/params.json")
    print("\nDo not open _answer_key/ until Tasks 3-6 are done.")


if __name__ == "__main__":
    main()
