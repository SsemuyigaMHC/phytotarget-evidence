#!/usr/bin/env python3
"""Chapter 13 Stage 01 — broad and targeted literature discovery.

This stage maximizes recall and preserves search provenance. It does not make
final scientific inclusion decisions. Use --phase broad for Day 4 discovery,
--phase targeted for Day 5 targeted retrieval, or --phase all for both.
"""
from __future__ import annotations
import argparse, sys, json
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config.settings import SEARCH_PHASES, SETTINGS
from utilities.logging_utils import configure_logging
from utilities.pubmed import ingest_external_exports, build_literature_index, retrieve_metadata, search_all_queries, write_literature_outputs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--phase', choices=sorted(SEARCH_PHASES), default='broad')
    parser.add_argument('--end-date', default='', help='Optional PubMed publication-date cutoff YYYY-MM-DD; preview shows its exact query filter')
    parser.add_argument('--output-tag', default='', help='Optional suffix for a distinct search run, e.g. RUN02')
    parser.add_argument('--preview-queries', action='store_true', help='Print exact queries without network access or outputs')
    parser.add_argument('--no-external', action='store_true', help='Do not ingest external database exports for this run')
    args = parser.parse_args()

    streams = SEARCH_PHASES[args.phase]
    if args.end_date:
        try:
            cutoff = date.fromisoformat(args.end_date)
        except ValueError as exc:
            parser.error(f'--end-date must be YYYY-MM-DD: {exc}')
        end = cutoff.strftime('%Y/%m/%d')
        # Date - Publication, not indexing date: no implicit limit on age of founding studies.
        streams = {key: tuple(f'({q}) AND ("1800/01/01"[Date - Publication] : "{end}"[Date - Publication])' for q in queries) for key, queries in streams.items()}
    if args.preview_queries:
        for stream, queries in streams.items():
            for index, query in enumerate(queries, 1):
                print(f'{stream} [{index}]: {query}')
        return

    SETTINGS.metadata_dir.mkdir(parents=True, exist_ok=True)
    SETTINGS.logs_dir.mkdir(parents=True, exist_ok=True)
    logger = configure_logging(SETTINGS.logs_dir / f'01_Search_PubMed_{args.phase}.log')
    logger.info('Chapter 13 literature discovery | phase=%s | streams=%d', args.phase, len(streams))

    query_to_pmids, failed = search_all_queries(streams)
    pubmed_index = build_literature_index(query_to_pmids, source_database='PubMed')
    if args.no_external:
        external_records, external_failures = [], []
        logger.info('External database exports disabled for this run.')
    else:
        external_records, external_failures = ingest_external_exports(SETTINGS.external_records_dir)
        failed.extend(external_failures)
    combined = build_literature_index({}, source_database='PubMed', base_records=pubmed_index, external_records=external_records)
    metadata = retrieve_metadata(combined)
    # PubMed initially supplies PMIDs only; DOI/title are learned later. Reconcile
    # PubMed and imported records again after enrichment without losing provenance.
    metadata = build_literature_index({}, base_records=metadata)

    tag = f'_{args.output_tag.strip()}' if args.output_tag.strip() else ''
    out = SETTINGS.metadata_dir / f'Literature_Discovery_{args.phase}{tag}.xlsx'
    metadata.to_excel(out, index=False)
    metadata.to_csv(out.with_suffix('.csv'), index=False)
    run_dir = SETTINGS.metadata_dir / f'discovery_{args.phase}{tag}'
    write_literature_outputs(metadata, query_to_pmids, failed, run_dir)
    (run_dir / 'Search_Run_Manifest.json').write_text(json.dumps({
        'chapter': 13, 'run_utc': datetime.now(timezone.utc).isoformat(), 'phase': args.phase,
        'publication_end_date': args.end_date or None, 'output_tag': args.output_tag or None,
        'query_count': sum(len(v) for v in streams.values()), 'canonical_record_count': len(metadata),
        'failed_queries': len(failed), 'external_exports_included': not args.no_external,
        'description': 'Purposive search; automated classification not final scientific inclusion.'
    }, indent=2),encoding='utf-8')
    logger.info('Canonical records: %d', len(metadata))
    logger.info('Output: %s', out)

if __name__ == '__main__':
    main()
