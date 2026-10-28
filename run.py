#!/usr/bin/env python3
"""Single user-facing command for the Chapter 13 evidence pipeline.

Stage implementations remain in scripts/ for scientific traceability.
No final scientific inclusion/validation decisions are automated.
"""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
SCRIPTS = ROOT / "scripts"
METADATA = ROOT / "data" / "metadata"
DISCOVERY = METADATA / "Literature_Discovery_all.xlsx"
DISCOVERY_CSV = DISCOVERY.with_suffix(".csv")
SCREENED = METADATA / "Chapter13_Metadata_Screened" / "Chapter13_Metadata_Screened_FINAL.xlsx"
CLAIMS = ROOT / "data" / "claims" / "Chapter13_Evidence_Matrix_Template.xlsx"


def call(script: str, *args: str) -> None:
    cmd = [sys.executable, str(SCRIPTS / script), *args]
    print("\n> " + " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=ROOT, check=True)


def need(path: Path, preceding: str) -> None:
    if not path.is_file():
        raise SystemExit(f"Missing {path.relative_to(ROOT)}. Run: python run.py {preceding}")


def protect(paths: list[Path], force: bool) -> None:
    existing = [p for p in paths if p.exists()]
    if existing and not force:
        paths_text = ", ".join(str(p.relative_to(ROOT)) for p in existing)
        raise SystemExit(f"Output already exists ({paths_text}). Save/review it first; use --force to replace.")


def email() -> None:
    if not os.getenv("NCBI_EMAIL") or os.getenv("NCBI_EMAIL").endswith("example.com"):
        raise SystemExit("Set a real NCBI contact email first: export NCBI_EMAIL='you@institution.edu'")


def status() -> None:
    checks = [
        ("Discovery metadata", DISCOVERY),
        ("Search QC", METADATA / "QC_Search" / "01_Search_QC_Report.md"),
        ("Known-paper discovery QC", ROOT / "data" / "logs" / "known_paper_recovery" / "Known_Paper_Recovery_Report.md"),
        ("Screened records", SCREENED),
        ("Known-paper screening QC", ROOT / "data" / "logs" / "screened_sentinels" / "Known_Paper_Screening_QC.md"),
        ("Acquisition QC", METADATA / "QC_Full_Text" / "03A_Article_File_Inventory.xlsx"),
        ("Evidence template", CLAIMS),
    ]
    for label, path in checks:
        print(f"{'READY' if path.exists() else 'NOT RUN':8} {label}: {path.relative_to(ROOT)}")
    print("\nThese are file-existence checks, not scientific validation or evidence verification.")


def make_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="PhytoTarget-Evidence: Chapter 13 literature-to-evidence workflow")
    sub = p.add_subparsers(dest="step", required=True)
    sub.add_parser("test", help="Offline unit tests, compilation and query preview")
    preview = sub.add_parser("preview", help="Show exact searches without internet access")
    preview.add_argument("--phase", choices=("broad", "targeted", "all"), default="all")
    preview.add_argument("--end-date", default="2026-10-21")
    probe = sub.add_parser("probe", help="Live PubMed query matching against known Chapter 13 articles")
    probe.add_argument("--end-date", default="2026-10-21")
    probe.add_argument("--strict", action="store_true")
    discover = sub.add_parser("discover", help="Run broad + targeted search and corpus/QC reports")
    discover.add_argument("--end-date", default="2026-10-21")
    discover.add_argument("--include-external", action="store_true", help="Include licensed/exported RIS/CSV files in data/external_records")
    discover.add_argument("--force", action="store_true", help="Replace prior discovery output")
    screen = sub.add_parser("screen", help="Classify, screen and generate classification/screening QC")
    screen.add_argument("--force", action="store_true", help="Replace existing screening/classification outputs")
    down = sub.add_parser("download", help="Acquire accessible article files (default: small pilot of 5 attempts)")
    limit = down.add_mutually_exclusive_group()
    limit.add_argument("--all", action="store_true", help="Run remaining eligible download queue")
    limit.add_argument("--limit", type=int, default=5, help="Maximum attempts this invocation (default: 5)")
    down.add_argument("--retry-failed", action="store_true")
    template = sub.add_parser("template", help="Create and QC blank source-verification evidence workbook")
    template.add_argument("--force", action="store_true", help="Replace existing template; manual entries could be lost")
    sub.add_parser("status", help="Show generated files/checkpoints")
    return p


def main() -> None:
    args = make_parser().parse_args()
    if args.step == "test":
        subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"], cwd=ROOT, check=True)
        subprocess.run([sys.executable, "-m", "compileall", "-q", "config", "scripts", "utilities", "tests", "run.py"], cwd=ROOT, check=True)
        preview = subprocess.run([sys.executable, str(SCRIPTS/"01_Search_PubMed.py"), "--phase", "all", "--end-date", "2026-10-21", "--preview-queries"], cwd=ROOT, capture_output=True, text=True, check=True)
        queries = [line for line in preview.stdout.splitlines() if ': ' in line]
        if len(queries) != 38:
            raise SystemExit(f"Query preview unexpectedly contains {len(queries)} queries; expected 38")
        probe_preview = subprocess.run([sys.executable, str(SCRIPTS/"01_QC_Live_Query_Recovery.py"), "--phase", "all", "--end-date", "2026-10-21", "--preview"], cwd=ROOT, capture_output=True, text=True, check=True)
        if "PREVIEW ONLY" not in probe_preview.stdout:
            raise SystemExit("Known-paper probe preview did not complete as expected")
        print("\nOffline checks passed: 38 queries and a known-paper probe preview. No internet used.")
    elif args.step == "preview":
        call("01_Search_PubMed.py", "--phase", args.phase, "--end-date", args.end_date, "--preview-queries")
    elif args.step == "probe":
        email()
        call("01_QC_Live_Query_Recovery.py", "--phase", "all", "--end-date", args.end_date, *(["--strict"] if args.strict else []))
        print("Read: data/logs/query_probe/Query_Coverage_Report.md")
    elif args.step == "discover":
        email()
        protect([DISCOVERY, DISCOVERY_CSV], args.force)
        call("01_Search_PubMed.py", "--phase", "all", "--end-date", args.end_date, *([] if args.include_external else ["--no-external"]))
        failed = METADATA / "discovery_all" / "Failed_Searches.txt"
        call("01_QC_Search_Results.py", "--input", str(DISCOVERY))
        call("01_QC_Known_Paper_Recovery.py", "--input", str(DISCOVERY_CSV))
        print("Review: data/metadata/QC_Search/01_Search_QC_Report.md and data/logs/known_paper_recovery/Known_Paper_Recovery_Report.md")
        if failed.is_file() and failed.read_text(encoding="utf-8").strip():
            raise SystemExit("STOP: one or more searches/imports failed. See data/metadata/discovery_all/Failed_Searches.txt")
    elif args.step == "screen":
        need(DISCOVERY, "discover")
        classified = METADATA / "Literature_Classified.xlsx"
        protect([classified, SCREENED], args.force)
        call("02_Literature_Classify.py", "--input", str(DISCOVERY))
        call("02_QC_Classification.py")
        call("03_Metadata_Screen_Chapter13_FINAL.py")
        call("03_QC_Known_Paper_Screening.py")
        call("06_Analyse_Metadata_Screen_Chapter13_FINAL.py")
        print("Review RETAIN, REVIEW and EXCLUDE before downloading. Screening is provisional.")
    elif args.step == "download":
        need(SCREENED, "screen")
        if not args.all and args.limit < 0:
            raise SystemExit("--limit must be zero or greater")
        print("WARNING: screen decisions are metadata-based and must be human-reviewed.", flush=True)
        call("03_Full_Text_Acquisition.py", *([] if args.all else ["--limit", str(args.limit)]), *(["--retry-failed"] if args.retry_failed else []))
        call("03_QC_Full_Text_Acquisition.py")
        print("Review QC and the actual downloaded documents; file-level validity is not scientific validation.")
    elif args.step == "template":
        need(SCREENED, "screen")
        protect([CLAIMS], args.force)
        call("04_Create_Evidence_Templates.py")
        call("04_QC_Evidence_Template.py")
        print("The claim-level workbook is BLANK; manually verify claims against source papers.")
    elif args.step == "status":
        status()


if __name__ == "__main__":
    main()
