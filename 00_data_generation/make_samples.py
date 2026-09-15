#!/usr/bin/env python3
"""Write the first 500 rows of each generated table to ../data_samples/.

Committed so a reviewer can inspect schemas without regenerating 135 MB.
These are SAMPLES, not analysis inputs.
"""
from pathlib import Path
import pandas as pd

SRC = Path(__file__).resolve().parents[1] / "data"
DST = Path(__file__).resolve().parents[1] / "data_samples"
N = 500

def main():
    DST.mkdir(exist_ok=True)
    files = sorted(p for p in SRC.glob("*.csv"))
    if not files:
        raise SystemExit(f"No CSVs in {SRC}. Run generate_astrapay_data.py first.")
    for src in files:
        df = pd.read_csv(src, nrows=N)
        out = DST / f"{src.stem}__sample.csv"
        df.to_csv(out, index=False)
        print(f"  {out.name:<44} {len(df):>4} rows")
    (DST / "README.md").write_text(
        "# Data samples\n\n"
        f"First {N} rows of each generated table, for schema inspection only.\n"
        "**Not** the analysis input — regenerate the full data with\n"
        "`00_data_generation/generate_astrapay_data.py`.\n")

if __name__ == "__main__":
    main()
