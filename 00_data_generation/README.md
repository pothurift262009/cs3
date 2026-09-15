# Data generation

```bash
pip install numpy pandas
python generate_astrapay_data.py --out ../data
python make_samples.py
```

Deterministic on `--seed 42`. `--validate` prints monthly KPIs and the mix/within
decomposition — **do not run it before Tasks 3–6 are written**; it gives away the answer.

## Expected row counts (seed 42)

| File | Rows | Size |
|---|---|---|
| customer.csv | 15,000 | 0.6 MB |
| merchant.csv | 600 | 0.03 MB |
| transaction.csv | 260,287 | 24 MB |
| payment_event.csv | 1,000,316 | 80 MB |
| fraud_decision.csv | 466,451 | 18 MB |
| settlement.csv | 224,242 | 10 MB |
| fx_rate.csv | 2,920 | 0.1 MB |
| route_cost.csv | 3,285 | 0.2 MB |
| chargeback.csv | 721 | 0.1 MB |
| merchant_risk_snapshot.csv | 7,200 | 0.2 MB |

Total ~135 MB. Not committed — the generator is the source of truth.

## Notes on the data

- `fx_rate.rate_to_usd` is a **multiplier**: `amount_usd = amount_local * rate_to_usd`.
- `route_cost` is a **dated** table — fees are not constant across the period.
- `settlement.fee_amount` is the processing fee charged on that settlement record.
- `_answer_key/` is written alongside the data and is gitignored. Do not open it
  until Tasks 3–6 are complete, and never commit it.
