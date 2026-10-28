# PhytoTarget Evidence

**Reproducible literature discovery and evidence curation for Chapter 13: AI for Target Prediction and Mechanistic Elucidation.**

This project helps researchers find and screen relevant publications, acquire accessible full texts, and prepare **blank, claim-level evidence templates**. It supports a **purposive narrative review**, not a systematic review. Automated screening is **provisional**; scientific verification remains manual.

## Get started (Python 3.10+)

From the extracted repository folder:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
export NCBI_EMAIL='you@institution.edu'  # your real contact email
```

On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1` and set `$env:NCBI_EMAIL='you@institution.edu'`.

## Run in order

| Step | Command | Expected result |
|---|---|---|
| 1. Offline tests | `python run.py test` | Unit tests pass and 38 queries preview; **no internet used** |
| 2. Search recovery | `python run.py probe` | Live PubMed test of known-paper search coverage; inspect missing studies |
| 3. Literature search | `python run.py discover` | `data/metadata/Literature_Discovery_all.xlsx` + QC reports |
| 4. Screen | `python run.py screen` | `data/metadata/Chapter13_Metadata_Screened/Chapter13_Metadata_Screened_FINAL.xlsx` |
| 5. Download pilot | `python run.py download` | Up to 5 article attempts + acquisition QC |
| 6. Download rest | `python run.py download --all` | Remaining eligible PMID articles attempted; failures logged |
| 7. Evidence template | `python run.py template` | `data/claims/Chapter13_Evidence_Matrix_Template.xlsx` (blank claims) |

Check what exists anytime with `python run.py status`. See additional options: `python run.py --help` and `python run.py <step> --help`.

**Stop and inspect the QC reports between steps 2–4.** A successful command is not proof of complete retrieval. After the download pilot, inspect actual PDF/HTML/XML content before continuing. The template generator intentionally does **not** extract or invent experimental findings.

## Important details

- The default search publication cutoff is **21 October 2026**; override with `--end-date YYYY-MM-DD`. This filters **publication dates**, not search execution dates. Only describe literature actually examined in the manuscript.
- If a PubMed query exceeds the ESearch 10,000-ID retrieval limit, it is flagged as an **incomplete search**; refine/split it before treating results as complete.
- To include exported licensed database references, place `.ris`, `.csv`, `.tsv` or `.txt` exports in `data/external_records/`, then run `python run.py discover --include-external` (no database scraping).
- The app prevents accidental overwriting of discovery, screening and the blank template. Use `--force` **only after protecting any manually reviewed files**.
- Missing papers, publisher-only studies and unacquired articles are not negative experimental evidence.
- `data/` generated results, full-text files and `.env` are ignored by Git. Keep any proprietary exports and downloaded papers out of public commits.

## Research interpretation

Separate **natural-product studies** from general drug–target comparator methods. Distinguish computational target nomination, biochemical activity, molecular binding, intact-cell engagement, functional contribution and causation. Keep endpoint, compound identity, protein organism/isoform, model evaluation, source locator, controls and negative/inconclusive/untested evidence explicit. Recovery of known annotations is not new experimental validation.

See [`docs/SCIENTIFIC_NOTES.md`](docs/SCIENTIFIC_NOTES.md) for scope, validation status and manuscript reporting cautions. The underlying stage implementations are in `scripts/`; **normal use requires only `run.py`**.

## GitHub release

Suggested repository: **`phytotarget-evidence`**. Upload these extracted repository contents, not runtime search results or downloaded articles. Automated GitHub Actions run **offline** tests only. No live PubMed or scientific recall has been claimed for this release. The repository has **no license yet**; select one before sharing if you want to grant reuse permissions.
