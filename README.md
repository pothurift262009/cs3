# AstraPay — Payment Profitability, Data Trust & Executive Decision

Five-day diagnostic answering:

> Why is payment contribution profit per successful transaction falling even though
> payment volume is increasing, and what should AstraPay change in the next 60 days?

## Repository layout

| Path | Deliverable | Contains |
|---|---|---|
| `00_data_generation/` | — | Synthetic data generator (deterministic, seed 42) |
| `01_problem_framing/` | 01 | SMART framing, MECE hypothesis tree, KPI definitions |
| `02_data_contract/` | 02 | Source-to-metric contract: grain, keys, cardinality, DQ rules |
| `03_dq_report/` | 03 | Profiling results, defect counts, severity, remediation |
| `04_sql/` | 04 | Reusable SQL — profiling, staging, model, analysis, validation |
| `05_profitability_model/` | 05 | Star schema, grain statements, metric definitions |
| `06_powerbi/` | 06 | Executive dashboard + design/metric notes |
| `07_executive_recommendation/` | 07 | Max 5 slides: diagnosis, evidence, recommendation, plan, risks |
| `08_ai_usage_log/` | 08 | The two permitted AI validation activities |
| `09_gitlab_mr/` | 09 | MR description, peer review evidence |
| `data_samples/` | — | First 500 rows of each table, for reviewers |
| `data/` | — | **Gitignored.** Regenerate locally (see below) |

## Reproducing the data

```bash
pip install numpy pandas
python 00_data_generation/generate_astrapay_data.py --out ./data
python 00_data_generation/make_samples.py
```

Deterministic on `--seed 42`. Expected row counts are in `00_data_generation/README.md`.

## Loading into Snowflake

Warehouse: Snowsight web UI. See `04_sql/00_setup/03_load_checklist.md` for the
click-level steps. In short: run `01_create_schema.sql`, then `02_create_tables.sql`,
then load each CSV into its pre-created table, then run `04_post_load_validation.sql`
and confirm every row count matches.

## Conventions

- Every analytical table carries a written **grain statement** as a header comment.
- Every KPI states **numerator, denominator, date basis, exclusion rules**.
- Every one-to-many source is **pre-aggregated to transaction grain before joining**.
- Money is handled in **minor units (integers)** wherever it is accumulated.
- No credentials, connection strings or secrets in this repository.
