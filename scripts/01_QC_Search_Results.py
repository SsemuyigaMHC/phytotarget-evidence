#!/usr/bin/env python3
"""Stage 01 QC — analyze completed Chapter 13 literature discovery.

This is a QC gate, not a second search. It audits retrieval yield, deduplication,
search-stream/query contribution, terminology coverage, metadata completeness,
year/publication-type balance, and produces a stratified manual-review sample.
"""
from __future__ import annotations
import argparse, re, sys
from pathlib import Path
from collections import Counter
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from config.settings import SETTINGS

from config.taxonomy import SIGNAL_TERMS as MECH_TERMS


def clean(x):
    return "" if pd.isna(x) else str(x).strip()


def load(path):
    if not path.exists():
        raise FileNotFoundError(path)
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path, dtype=object).fillna("")
    return pd.read_excel(path, dtype=object).fillna("")


def parse_search_log(path):
    rows = []
    if not path.exists():
        return pd.DataFrame(columns=["Database", "Stream", "Hit Count", "Query"])
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split("\t", 3)
        if len(parts) == 4:
            db, stream, count, query = parts
            try: count = int(count)
            except ValueError: count = 0
            rows.append({"Database": db, "Stream": stream, "Hit Count": count, "Query": query})
    return pd.DataFrame(rows)


def provenance_rows(path):
    if not path.exists():
        return pd.DataFrame(columns=["PMID", "Search Stream", "Search Query"])
    return pd.read_csv(path, dtype=object).fillna("")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=Path, default=None, help="Literature_Discovery_*.xlsx/csv")
    ap.add_argument("--output-dir", type=Path, default=None)
    args = ap.parse_args()

    metadata_dir = SETTINGS.metadata_dir
    if args.input:
        inp = args.input
    else:
        candidates = sorted(metadata_dir.glob("Literature_Discovery_*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not candidates:
            raise FileNotFoundError("No Literature_Discovery_*.xlsx found in data/metadata")
        inp = candidates[0]
    outdir = args.output_dir or (metadata_dir / "QC_Search")
    outdir.mkdir(parents=True, exist_ok=True)

    df = load(inp)
    stem = inp.stem.replace("Literature_Discovery_", "")
    log = parse_search_log(metadata_dir / f"discovery_{stem}" / "Search_Log.txt")
    prov = provenance_rows(metadata_dir / f"discovery_{stem}" / "PubMed_Search_Provenance.csv")

    report = []
    report.append(["INPUT", str(inp)])
    report.append(["CANONICAL_RECORDS", len(df)])
    report.append(["SEARCH_LOG_ROWS", len(log)])
    report.append(["PROVENANCE_ROWS", len(prov)])

    # Record-level metadata completeness
    important = [c for c in ["PMID", "DOI", "Title", "Abstract", "Year", "Publication Type", "Source Databases", "Originating Search Streams", "Originating Search Queries"] if c in df.columns]
    completeness = []
    for c in important:
        nonempty = df[c].map(clean).ne("").sum()
        completeness.append({"Field": c, "Records": len(df), "Non-empty": int(nonempty), "Completeness_%": round(100*nonempty/max(len(df),1),2)})

    # Search stream/query yield
    stream = log.groupby("Stream", dropna=False).agg(Queries=("Query", "nunique"), Raw_Hits=("Hit Count", "sum")).reset_index() if not log.empty else pd.DataFrame()
    query = log.sort_values(["Hit Count", "Stream"], ascending=[False, True]).copy() if not log.empty else pd.DataFrame()

    # Unique record contribution by originating stream
    stream_contrib = []
    if "Originating Search Streams" in df.columns:
        for _, r in df.iterrows():
            streams = [x.strip() for x in clean(r["Originating Search Streams"]).split(";") if x.strip()]
            for s in streams:
                stream_contrib.append(s)
    contrib = pd.DataFrame(Counter(stream_contrib).items(), columns=["Stream", "Unique_Canonical_Records"]).sort_values("Unique_Canonical_Records", ascending=False) if stream_contrib else pd.DataFrame(columns=["Stream","Unique_Canonical_Records"])

    # Search task/claim-evidence term coverage from title+abstract+keywords/MeSH.
    text_cols = [c for c in ["Title", "Abstract", "Keywords", "MeSH Terms", "Publication Type"] if c in df.columns]
    combined = df[text_cols].astype(str).agg(" ".join, axis=1).str.lower() if text_cols else pd.Series([""]*len(df))
    mech_rows=[]
    for mech, terms in MECH_TERMS.items():
        mask = combined.map(lambda t: any(term.lower() in t for term in terms))
        mech_rows.append({"Mechanism_or_Process": mech, "Records_Matching_Terms": int(mask.sum()), "Percent_of_Records": round(100*mask.mean(),2) if len(mask) else 0})
    mech_df=pd.DataFrame(mech_rows)

    # Year distribution
    year_df=pd.DataFrame()
    if "Year" in df.columns:
        years=pd.to_numeric(df["Year"].astype(str).str.extract(r"((?:19|20)\d{2})")[0], errors="coerce")
        year_df=years.value_counts(dropna=False).sort_index().rename_axis("Year").reset_index(name="Records")

    # Publication type distribution
    ptype_df=pd.DataFrame()
    if "Publication Type" in df.columns:
        ptype_df=(df["Publication Type"].astype(str).str.split(";").explode().str.strip().replace("", pd.NA).dropna().value_counts().rename_axis("Publication_Type").reset_index(name="Records"))

    # Cross-database duplicate report if present
    dupfile=metadata_dir / f"discovery_{stem}" / "Cross_Database_Duplicates.csv"
    dup_df=pd.read_csv(dupfile,dtype=object).fillna("") if dupfile.exists() else pd.DataFrame()

    # Manual-review sample: top/bottom stream contribution plus evidence-task strata.
    sample_parts=[]
    if not df.empty:
        sample_n=min(30,len(df))
        sample_parts.append(df.head(min(10,len(df))))
        sample_parts.append(df.tail(min(10,len(df))))
        if "Originating Search Streams" in df.columns:
            for s in contrib.head(10)["Stream"].tolist():
                sub=df[df["Originating Search Streams"].astype(str).str.contains(re.escape(s),case=False,regex=True)]
                if not sub.empty: sample_parts.append(sub.sample(min(3,len(sub)),random_state=40))
        sample=pd.concat(sample_parts,ignore_index=True).drop_duplicates(subset=[c for c in ["PMID","DOI","Title"] if c in df.columns]).head(100)
    else: sample=pd.DataFrame()

    # QC flags intentionally use warnings rather than pretending arbitrary thresholds are scientific truth.
    flags=[]
    failed_path=metadata_dir / f"discovery_{stem}" / "Failed_Searches.txt"
    if failed_path.exists() and failed_path.read_text(encoding="utf-8",errors="replace").strip():
        failed_n=len([x for x in failed_path.read_text(encoding="utf-8",errors="replace").splitlines() if x.strip()])
        flags.append(("FAIL",f"{failed_n} search/import failures in Failed_Searches.txt; do not declare search complete."))
    if len(df)==0: flags.append(("FAIL","No canonical records retrieved."))
    if not log.empty and len(log[log["Hit Count"]==0])>0: flags.append(("WARN",f"{int((log['Hit Count']==0).sum())} query rows returned zero hits."))
    if "Title" in df.columns and df["Title"].map(clean).eq("").mean()>0.01: flags.append(("WARN","More than 1% of canonical records lack titles."))
    if "Abstract" in df.columns and df["Abstract"].map(clean).eq("").mean()>0.25: flags.append(("WARN","More than 25% of records lack abstracts; classification will be less reliable."))
    for m in MECH_TERMS:
        row=mech_df.loc[mech_df.Mechanism_or_Process.eq(m)]
        if not row.empty and int(row.iloc[0].Records_Matching_Terms)==0:
            flags.append(('WARN', f'No metadata term matches for {m}; review source coverage, synonyms, and query yields.'))
    if len(dup_df): flags.append(("INFO",f"{len(dup_df)} records were flagged as potential cross-database duplicates/provenance overlaps."))
    if not flags: flags.append(("INFO","No automated QC warnings triggered; manual inspection is still required."))

    pd.DataFrame(report,columns=["Metric","Value"]).to_excel(outdir/"01_Search_QC_Summary.xlsx",index=False)
    pd.DataFrame(completeness).to_excel(outdir/"01A_Metadata_Completeness.xlsx",index=False)
    stream.to_excel(outdir/"01B_Stream_Yield.xlsx",index=False)
    query.to_excel(outdir/"01C_Query_Yield.xlsx",index=False)
    contrib.to_excel(outdir/"01D_Unique_Record_Contribution.xlsx",index=False)
    mech_df.to_excel(outdir/"01E_Mechanism_Term_Coverage.xlsx",index=False)
    year_df.to_excel(outdir/"01F_Year_Distribution.xlsx",index=False)
    ptype_df.to_excel(outdir/"01G_Publication_Type_Distribution.xlsx",index=False)
    dup_df.to_excel(outdir/"01H_Cross_Database_Duplicates.xlsx",index=False)
    sample.to_excel(outdir/"01I_Manual_QC_Sample.xlsx",index=False)
    pd.DataFrame(flags,columns=["Level","Finding"]).to_excel(outdir/"01J_QC_Flags.xlsx",index=False)

    with (outdir/"01_Search_QC_Report.md").open("w",encoding="utf-8") as f:
        f.write(f"# Chapter 13 Search QC\n\nInput: `{inp}`\n\nCanonical records: **{len(df):,}**\n\n")
        f.write("## Gate findings\n")
        for level,msg in flags: f.write(f"- **{level}** — {msg}\n")
        f.write("\n## Interpretation\n")
        f.write("This report does not declare retrieval complete merely because the script finished. Review stream/query yield, task/claim-evidence term coverage, metadata completeness, duplicate/provenance behavior, and the manual sample before proceeding to classification.\n")
    print(f"Search QC written to: {outdir}")

if __name__ == "__main__": main()
