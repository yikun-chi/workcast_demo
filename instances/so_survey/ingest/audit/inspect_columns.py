"""Print, for each survey wave, the AI-use question's column, wording and answer counts, and the role and experience
columns used for groups. An audit of the raw files; nothing is written.

  python instances/so_survey/ingest/audit/inspect_columns.py
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
DATA = {2023: "results.csv", 2024: "results.csv", 2025: "results.csv", 2026: "survey_results_public.csv"}
SCHEMA = {2023: "schema.csv", 2024: "schema.csv", 2025: "schema.csv", 2026: "survey_results_schema.csv"}


def main() -> None:
    for y in DATA:
        sch = pd.read_csv(RAW / str(y) / SCHEMA[y])
        cols = pd.read_csv(RAW / str(y) / DATA[y], nrows=0).columns.tolist()
        print(f"===== {y}: {len(cols)} columns")
        txt = sch.fillna("").astype(str).apply(lambda r: " | ".join(map(str, r.tolist())), axis=1)
        for line in txt[txt.str.contains("AI tool|AI in your|artificial intelligence|AISelect|AI agent", case=False)].tolist()[:12]:
            print("  schema:", line[:260])
        ai = [c for c in cols if c.lower().startswith("ai")]
        print("  AI columns:", ai[:30])
        want = [c for c in cols if c in ("AISelect", "AIUse", "AIToolCurrently", "DevType", "YearsCodePro", "YearsCode", "WorkExp", "MainBranch", "Employment")]
        df = pd.read_csv(RAW / str(y) / DATA[y], usecols=want + [c for c in ai if c in ("AISelect",)], low_memory=False)
        print("  rows:", len(df), "grouping columns present:", want)
        for c in [c for c in ("AISelect", "AIUse") if c in df]:
            print("  ", c, df[c].value_counts(dropna=False).head(8).to_dict())
        if "DevType" in df:
            print("   DevType top:", df.DevType.value_counts().head(14).to_dict())
        for c in ("YearsCodePro", "WorkExp", "YearsCode"):
            if c in df:
                print("  ", c, df[c].astype(str).value_counts().head(6).to_dict())


if __name__ == "__main__":
    main()
