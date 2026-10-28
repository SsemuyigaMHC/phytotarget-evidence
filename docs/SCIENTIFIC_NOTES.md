# Scientific scope, provenance, and validation

## What the pipeline does and does not do

- Searches PubMed through broad and section-specific strategies, with optional imported external records.
- Preserves retrieval provenance, performs deterministic deduplication after metadata enrichment, categorises from metadata, and produces provisional RETAIN/REVIEW/EXCLUDE strata.
- Tests known-study search coverage and screening survival as **sentinel checks**, not unbiased recall estimates.
- Downloads legitimately accessible files when PMIDs are present; articles lacking PMIDs require manual/external acquisition and a documented provenance trail.
- Produces a blank claim-evidence workbook. It **does not** extract experimental conclusions or confirm molecular mechanisms automatically.

## Priority distinctions

1. Phytochemical-specific results versus general drug–target methodological comparators.
2. Predicted interactions versus biochemical inhibition, physical binding, intact-cell target engagement, functional contribution, and complete causal mechanisms.
3. Retrospective rediscovery, external annotation validation, selected experimental follow-up and independent replication.
4. Tested positive, controlled negative, untested, technically inconclusive and unreported outcomes.
5. Model task, candidate universe, chemical novelty, protein novelty, splits and whether negative/unlabelled labels are justified.
6. Claim-level evidence with exact compounds, targets, biological preparation, exposures, controls and source locations.

## Validation status (this release)

- Offline 4 bundled tests, code compilation and query preview: **tested locally**.
- Additional regression tests check record deduplication, truncated PubMed results and artifact integrity: **tested locally**.
- Live PubMed queries, full-retrieval coverage, download success, and actual full-text scientific verification: **not completed**.
- A QC pass or a successful download does not substantiate biological target claims.

## Search reproducibility record — complete after running

- Operator, date/time and Git commit/tag.
- Databases and exact executed query strings; publication cutoff and accession dates.
- Counts by search; unique canonical records; any failures/truncations and resolutions.
- Known-study query matching and actual corpus retrieval (including missing records and manually sourced citations).
- Screening decisions with reviewer annotations and full-text access limitations.
- Original figures/tables/supplements supporting each manuscript claim and explicit negative/uncertain outcomes.

## Draft methodology text — do not use as a factual account before executing

## 2. Materials and Methods

This chapter uses a purposive narrative literature-selection approach supported by staged PubMed searches combining broad and subsection-specific queries, supplemented by publisher records, accessible full texts, supplementary materials and citation tracing. The searches address AI-assisted phytochemical target prediction, related drug–target modelling, perturbation-informed inference, evidence integration, biochemical interaction, cellular target engagement, functional mechanisms and assay confounding. Search terms and provenance are documented, and retrieved records are deduplicated and subjected to query-coverage, metadata and relevance checks, including recovery of selected reference studies. Automated classification supports screening but does not determine inclusion or validate claims. Primary studies are prioritised according to their relevance to defined predictive or experimental questions; general drug–target studies serve as methodological comparators and are distinguished from phytochemical-specific evidence. Findings are appraised by task, evaluation setting, compound and target identity, measured endpoint, assay conditions and biological context, with negative, untested and inconclusive evidence treated separately. The approach supports critical synthesis rather than exhaustive or systematic-review coverage.


**Before manuscript submission:** Align this paragraph with the executed searches, documented external records, manual citation additions and source-level verification. Do not invent search yields or portray the method as an exhaustive systematic review.
