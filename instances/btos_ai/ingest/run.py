"""Normalize the BTOS AI use series (original wording, September 2023 to October 2025).

Reads data/raw/<date>/AI Core Questions.xlsx (written by ingest/audit/fetch.py) and writes data/normalized/:

  series.parquet   group, period, smpdt, date, ref_end, value, se   (value: share of firms answering "Yes" to "In the last
                   two weeks, did this business use AI in producing goods or services?"; one row per sector and
                   biweekly period; suppressed estimates are missing; group "_all" is the national estimate)
  groups.parquet   group, label, modelled, scored, periods_published
  summary.json     Overview facts and charts

Sectors are two-digit NAICS sectors whose estimate is published in at least 90% of periods; the national estimate is
the economy-wide adoption the sectors imitate (it is read as an input, not scored). The wording changed on 2025-11-17
with a level shift (Census started a new series), so only the original-wording periods are used. Nothing is fitted here.
"""
from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
from lxml import etree

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main", "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
QUESTION_ID, YES = "7", "1"
MIN_PUBLISHED = 0.9
NAICS = {"11": "Agriculture, Forestry, Fishing and Hunting", "21": "Mining, Quarrying, and Oil and Gas Extraction", "22": "Utilities", "23": "Construction",
         "31": "Manufacturing", "42": "Wholesale Trade", "44": "Retail Trade", "48": "Transportation and Warehousing", "51": "Information",
         "52": "Finance and Insurance", "53": "Real Estate and Rental and Leasing", "54": "Professional, Scientific, and Technical Services",
         "55": "Management of Companies and Enterprises", "56": "Administrative and Support and Waste Management", "61": "Educational Services",
         "62": "Health Care and Social Assistance", "71": "Arts, Entertainment, and Recreation", "72": "Accommodation and Food Services",
         "81": "Other Services (except Public Administration)"}


def log(msg: str) -> None:
    print(f"[btos_ai ingest] {msg}", flush=True)


def read_xlsx(path: Path) -> dict[str, list[list[str | None]]]:
    """Every sheet as rows of cell strings (shared strings resolved). Standard library and lxml only."""
    z = zipfile.ZipFile(path)
    ss = []
    if "xl/sharedStrings.xml" in z.namelist():
        ss = ["".join(si.itertext()) for si in etree.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", NS)]
    wb = etree.fromstring(z.read("xl/workbook.xml"))
    rmap = {r.get("Id"): r.get("Target") for r in etree.fromstring(z.read("xl/_rels/workbook.xml.rels"))}

    def col(ref: str) -> int:
        n = 0
        for ch in re.match(r"[A-Z]+", ref).group(0):
            n = n * 26 + ord(ch) - 64
        return n - 1

    out = {}
    for sh in wb.find("m:sheets", NS):
        tgt = rmap[sh.get("{%s}id" % NS["r"])].lstrip("/")
        root = etree.fromstring(z.read(tgt if tgt.startswith("xl/") else "xl/" + tgt))
        rows = []
        for row in root.iter("{%s}row" % NS["m"]):
            vals = {}
            for c in row.findall("m:c", NS):
                v = c.find("m:v", NS)
                t = c.get("t")
                vals[col(c.get("r"))] = ss[int(v.text)] if t == "s" and v is not None else ("".join(c.itertext()) if t == "inlineStr" else (v.text if v is not None else None))
            if vals:
                rows.append([vals.get(i) for i in range(max(vals) + 1)])
        out[sh.get("name")] = rows
    return out


def pct(x: str | None) -> float:
    if x is None or not str(x).strip().endswith("%"):
        return np.nan                                           # "S" (suppressed) or blank
    return float(str(x).strip().rstrip("%")) / 100


def long_table(rows: list[list[str | None]], key: str | None) -> pd.DataFrame:
    hdr = rows[0]
    first = hdr.index("Answer") + 1
    out = []
    for r in rows[1:]:
        r = r + [None] * (len(hdr) - len(r))
        qi = hdr.index("Question ID")
        if r[qi] != QUESTION_ID or r[hdr.index("Answer ID")] != YES:
            continue
        g = "_all" if key is None else str(r[hdr.index(key)])
        for j in range(first, len(hdr)):
            out.append({"group": g, "smpdt": str(hdr[j]), "v": pct(r[j])})
    return pd.DataFrame(out)


def main(ctx) -> None:
    raw = sorted(ctx.data_raw.glob("*/AI Core Questions.xlsx"))
    if not raw:
        raise FileNotFoundError(f"{ctx.data_raw}/<date>/AI Core Questions.xlsx missing; run instances/btos_ai/ingest/audit/fetch.py")
    wb = read_xlsx(raw[-1])
    log(f"read {raw[-1].relative_to(ctx.root)}: sheets {list(wb)}")
    est = pd.concat([long_table(wb["Sector Estimates"], "Sector"), long_table(wb["National Estimates"], None)])
    se = pd.concat([long_table(wb["Sector SE"], "Sector"), long_table(wb["National SE"], None)]).rename(columns={"v": "se"})
    dts = pd.DataFrame(wb["Collection and Reference Dates"][1:], columns=wb["Collection and Reference Dates"][0])
    dts = dts[dts.Smpdt.notna()].rename(columns={"Smpdt": "smpdt", "Col Start": "date", "Ref End": "ref_end"})[["smpdt", "date", "ref_end"]]
    dts["smpdt"] = dts.smpdt.astype(str)
    dts["date"] = pd.to_datetime(dts.date, format="%m/%d/%Y")
    dts["ref_end"] = pd.to_datetime(dts.ref_end, format="%m/%d/%Y")
    dts = dts[dts.smpdt.isin(set(est.smpdt))].sort_values("smpdt").reset_index(drop=True)
    dts["period"] = np.arange(len(dts))
    s = est.merge(se, on=["group", "smpdt"], how="left").merge(dts, on="smpdt").rename(columns={"v": "value"})
    s = s[["group", "period", "smpdt", "date", "ref_end", "value", "se"]].sort_values(["group", "period"]).reset_index(drop=True)
    pub = s.groupby("group").value.apply(lambda x: float(x.notna().mean()))
    keep = [g for g in pub.index if g in NAICS and pub[g] >= MIN_PUBLISHED]
    groups = pd.DataFrame({"group": keep + ["_all"], "label": [NAICS[g] for g in keep] + ["All U.S. employer businesses"],
                           "modelled": [True] * len(keep) + [False], "scored": [True] * len(keep) + [False],
                           "periods_published": [pub[g] for g in keep] + [pub["_all"]]})
    s = s[s.group.isin(groups.group)]
    out = ctx.data_normalized
    out.mkdir(parents=True, exist_ok=True)
    s.to_parquet(out / "series.parquet", index=False)
    groups.to_parquet(out / "groups.parquet", index=False)
    excluded = sorted(set(pub.index) - set(keep) - {"_all"})
    nat = s[s.group == "_all"].sort_values("period")
    last = s[s.period == s.period.max()].set_index("group").value
    first = s[s.period == 0].set_index("group").value
    summary = {
        "title": "Share of U.S. businesses using AI, by sector (Census BTOS)",
        "period": f"{dts.date.min().date()} .. {dts.ref_end.max().date()}",
        "facts": [{"label": "Biweekly survey periods (original AI question wording)", "value": int(len(dts)), "unit": ""},
                  {"label": "Sectors modelled (published in at least 90% of periods)", "value": len(keep), "unit": ""},
                  {"label": "Sectors left out (estimates mostly suppressed)", "value": len(excluded), "unit": ""},
                  {"label": "National AI use, first period", "value": round(float(nat.value.iloc[0]) * 100, 1), "unit": "%"},
                  {"label": "National AI use, last period", "value": round(float(nat.value.iloc[-1]) * 100, 1), "unit": "%"}],
        "org": {"units": [{"id": g, "label": NAICS[g]} for g in keep], "roles": [{"id": "firm", "label": "Employer business", "headcount": None, "onet_code": "11-1021.00"}], "systems": []},
        "charts": [{"id": "national", "type": "line", "title": "Businesses that used AI in the last two weeks, United States (%)", "x": [str(d.date()) for d in nat.date], "x_label": "", "y_label": "%",
                    "series": [{"name": "Actual outcome", "y": [round(float(x) * 100, 2) if pd.notna(x) else None for x in nat.value], "source": "actual"}], "note": "Original question wording."},
                   {"id": "sectors", "type": "hbar", "title": "AI use by sector, first and last period (%)", "x": [NAICS[g] for g in keep], "x_label": "", "y_label": "%",
                    "series": [{"name": str(dts.date.min().date()), "y": [round(float(first.get(g, np.nan)) * 100, 1) for g in keep]},
                               {"name": str(dts.date.max().date()), "y": [round(float(last.get(g, np.nan)) * 100, 1) for g in keep]}], "note": ""}],
        "excluded_sectors": {g: NAICS.get(g, g) for g in excluded},
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=1, default=str))
    log(f"{len(keep)} sectors x {len(dts)} periods ({dts.date.min().date()} .. {dts.date.max().date()}); left out: {excluded}")


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from orgsim.instances import get_instance
    main(get_instance("btos_ai"))
