#!/usr/bin/env python3
"""Live NCBI PubMed search-semantic recovery test BEFORE full discovery.

Each configured query is ANDed with a set of known PubMed PMIDs, and the
normal Entrez ESearch endpoint evaluates that restricted query. This uses
actual PubMed matching and indexing but does not acquire articles or sample
from the full search yield. It is a discovery-gate, not a comprehensive review.

"Known-paper" seeds must NOT be injected into ordinary discovery results or
reported as newly discovered. Non-PubMed publisher records are handled apart.
"""
from __future__ import annotations
import argparse, csv, json, os, sys
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from config.settings import SEARCH_PHASES, SETTINGS
from utilities.ncbi import EntrezClient

REGISTRY=ROOT/'config'/'known_papers_sentinel.csv'

def seeds():
    with REGISTRY.open(newline='',encoding='utf-8-sig') as fp:
        all_rows=list(csv.DictReader(fp))
    indexed=[r for r in all_rows if r.get('PMID','').strip().isdigit() and 'confirmed' in r['Registry status'].lower()]
    publisher=[r for r in all_rows if r not in indexed]
    return indexed,publisher

def scoped_queries(phase,end_date):
    streams=SEARCH_PHASES[phase]
    if not end_date:
        return streams
    parsed=date.fromisoformat(end_date)
    end=parsed.strftime('%Y/%m/%d')
    return {k:tuple(f'({q}) AND ("1800/01/01"[Date - Publication] : "{end}"[Date - Publication])' for q in v) for k,v in streams.items()}

def make_probe(query,ids):
    uid_filter=' OR '.join(f'{pid}[uid]' for pid in ids)
    return f'({query}) AND ({uid_filter})'

def test_queries(streams,indexed,search_func):
    ids=[s['PMID'] for s in indexed]
    qrows=[]; matches=defaultdict(list); failures=[]
    for stream,queries in streams.items():
        for qi,q in enumerate(queries,1):
            probe=make_probe(q,ids)
            try:
                found=set(str(x) for x in search_func(probe,len(ids)))
                unexpected=found.difference(ids)
                if unexpected:
                    raise ValueError(f'Unexpected NCBI IDs outside sentinels: {unexpected}')
                status='OK'
            except Exception as exc:
                found=set();status='ERROR';failures.append(f'{stream} Q{qi}: {type(exc).__name__}: {exc}')
            qrows.append({'Search stream':stream,'Query number':qi,'Result':status,'Sentinel matches':len(found),
                'Matched PMIDs':'; '.join(sorted(found)),'Configured query':q})
            for pid in found:
                matches[pid].append(f'{stream}#{qi}')
    return qrows,matches,failures

def write_report(outdir,indexed,publisher,qrows,matches,failures,phase,end_date):
    outdir.mkdir(parents=True,exist_ok=True)
    with (outdir/'Query_Probe_Results.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=list(qrows[0]));w.writeheader();w.writerows(qrows)
    rows=[]
    for paper in indexed:
        where=matches.get(paper['PMID'],[])
        rows.append({'Study':paper['Study'],'PMID':paper['PMID'],'DOI':paper['DOI'],
          'Search match status':'RECOVERED_IN_LIVE_PROBE' if where else 'NOT_MATCHED',
          'Matched search queries':'; '.join(where),'Scope':paper['Scope']})
    with (outdir/'Known_Paper_Query_Coverage.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    covered=sum(bool(matches.get(r['PMID'])) for r in indexed)
    complete=not failures
    meta={'method':'NCBI ESearch restricted to independently identified PMID sentinels',
      'test_type':'live_pubmed_query_probe','execution_utc':datetime.now(timezone.utc).isoformat(),
      'phase':phase,'publication_end_date':end_date or None,'configured_query_count':len(qrows),
      'query_failures':len(failures),'known_pubmed_indexed_total':len(indexed),
      'known_pubmed_indexed_matched':covered,'publisher_only_unscored':len(publisher),
      'pass':complete and covered==len(indexed)}
    (outdir/'Query_Probe_Manifest.json').write_text(json.dumps(meta,indent=2)+'\n',encoding='utf-8')
    lines=['# Chapter 13 — Live query recovery validation','',
      f'**Result:** {covered}/{len(indexed)} PubMed-indexed reference papers matched at least one configured {phase} query.',
      f'**Query failures:** {len(failures)}. **Pass:** {meta["pass"]}.',
      '**Important:** This tests search matching against known PMIDs; it is NOT full retrieval, screening, an unbiased recall estimate, or evidence that all literature was found. It does not imply the pipeline was run if only the preview was used.','',
      '## Individual paper recovery']
    for row in rows:lines.append(f'- {row["Search match status"]}: {row["Study"]} — {row["Matched search queries"] or "none"}')
    lines+=['','## Publisher-only reference papers (not part of PubMed denominator)']
    for r in publisher:lines.append(f'- {r["Study"]}: {r["DOI"]} ({r["Registry status"]})')
    if failures:lines+=['','## Failed probes']+[f'- {error}' for error in failures]
    lines+=['','## Recovery caveat','The sentinel set was selected from known chapter references. High matching is useful as a QC check but is not an independent measure of search sensitivity. Preserve the unmodified broad query streams and separately document any changes made after sentinel testing.','',
    'Next: run full Stage 01 PubMed discovery with the same query version and cutoff; run `01_QC_Search_Results.py` and `01_QC_Known_Paper_Recovery.py`; inspect classification and screening decisions before any full-text acquisition.']
    (outdir/'Query_Coverage_Report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return meta

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--phase',choices=('broad','targeted','all'),default='all')
    p.add_argument('--end-date',default='',help='YYYY-MM-DD, must match eventual discovery date cutoff')
    p.add_argument('--outdir',type=Path,default=ROOT/'data'/'logs'/'query_probe')
    p.add_argument('--preview',action='store_true',help='Show the exact real-PubMed sentinel-restricted queries without contacting NCBI')
    p.add_argument('--strict',action='store_true',help='Return nonzero if any PubMed sentinel missed or query errored')
    a=p.parse_args()
    try:streams=scoped_queries(a.phase,a.end_date)
    except ValueError:p.error('Invalid --end-date; use YYYY-MM-DD')
    indexed,publisher=seeds()
    if a.preview:
        for stream,queries in streams.items():
            for q in queries: print(stream, make_probe(q,[r['PMID'] for r in indexed]))
        print(f'PREVIEW ONLY. No PubMed queries run. Known indexed studies: {len(indexed)}; publisher-only: {len(publisher)}.')
        return
    if not os.environ.get('NCBI_EMAIL'):
        p.error('Set NCBI_EMAIL to your contact address before live PubMed requests.')
    client=EntrezClient()
    qrows,matches,failures=test_queries(streams,indexed,lambda query,n:client.search_pubmed(query,retmax=n))
    meta=write_report(a.outdir,indexed,publisher,qrows,matches,failures,a.phase,a.end_date)
    print(f'LIVE PubMed query recovery: {meta["known_pubmed_indexed_matched"]}/{meta["known_pubmed_indexed_total"]}; failed queries {len(failures)}; pass={meta["pass"]}.')
    print(f'Report: {a.outdir / "Query_Coverage_Report.md"}')
    if a.strict and not meta['pass']:sys.exit(2)

if __name__=='__main__': main()
