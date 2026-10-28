#!/usr/bin/env python3
"""Post-retrieval known-paper recovery QC for Chapter 13.

This checks *observed retrieval outputs*, not query quality in the abstract.
Missing papers are coverage warnings, NOT scientific exclusion decisions.
Known-paper coverage is a sentinel check, NOT a completeness estimate.
"""
from __future__ import annotations
import argparse, csv, re, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SENTINELS=ROOT/'config'/'known_papers_sentinel.csv'
DEFAULT_INPUTS=[ROOT/'data'/'metadata'/'Literature_Discovery_all.csv',ROOT/'data'/'metadata'/'Literature_Discovery_broad.csv',ROOT/'data'/'metadata'/'Literature_Discovery_targeted.csv']

def norm_doi(s):
    return re.sub(r'^https?://(?:dx\.)?doi\.org/|^doi:\s*','',str(s or '').strip().lower()).rstrip(' .,;')
def norm_pmid(s):
    s=str(s or '').strip()
    if re.fullmatch(r'\d+(?:\.0)?',s): return s.removesuffix('.0')
    return ''
def load_rows(p):
    with p.open(newline='',encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))
def read_many(paths):
    entries=[]
    for p in paths:
        for row in load_rows(p):
            row['_input_file']=p.name
            entries.append(row)
    return entries

def audit(inputs):
    corpus=read_many(inputs)
    reg=load_rows(SENTINELS)
    rows=[]
    for paper in reg:
        pid=norm_pmid(paper.get('PMID')); doi=norm_doi(paper.get('DOI'))
        matches=[r for r in corpus if (pid and pid == norm_pmid(r.get('PMID'))) or (doi and doi == norm_doi(r.get('DOI')))]
        streams=set(); sources=set(); inputs_found=set()
        for m in matches:
            streams.update(v.strip() for v in str(m.get('Originating Search Streams','')).split(';') if v.strip())
            sources.update(v.strip() for v in str(m.get('Source Databases','')).split(';') if v.strip())
            inputs_found.add(m['_input_file'])
        found=bool(matches)
        indexed='confirmed' in paper['Registry status'].lower()
        pubmed=any(s.lower()=='pubmed' for s in sources)
        if found and pubmed: outcome='FOUND_PUBMED'
        elif found: outcome='FOUND_EXTERNAL_ONLY'
        elif indexed: outcome='MISSING_PUBMED_CONFIRMED'
        else: outcome='MISSING_PUBLISHER_RECORD'
        rows.append({'Study':paper['Study'],'PMID':pid,'DOI':doi,'Scope':paper['Scope'],'Registry status':paper['Registry status'],'Outcome':outcome,'Retrieved via':'; '.join(sorted(sources)),'Search streams':'; '.join(sorted(streams)),'Input files':'; '.join(sorted(inputs_found))})
    return corpus,rows

def output(corpus,results,outdir):
    outdir.mkdir(parents=True,exist_ok=True)
    with (outdir/'Known_Paper_Recovery.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=list(results[0]));w.writeheader();w.writerows(results)
    eligible=[r for r in results if 'confirmed' in r['Registry status'].lower()]
    recovered=sum(r['Outcome']=='FOUND_PUBMED' for r in eligible)
    any_recovered=sum(r['Outcome'].startswith('FOUND_') for r in eligible)
    issues=[r for r in results if not r['Outcome'].startswith('FOUND_')]
    review_external=[r for r in results if r['Outcome']=='FOUND_EXTERNAL_ONLY']
    lines=[
      '# Chapter 13 known-paper recovery QC',
      '',f'Unique/duplicated input records inspected: {len(corpus)}',
      f'Known PubMed-indexed sentinels recovered by PubMed search: {recovered}/{len(eligible)}',
      f'Known PubMed-indexed sentinels found by any source: {any_recovered}/{len(eligible)}',
      f'Missing reference papers: {len(issues)}; external-only recoveries: {len(review_external)}.',
      '', '**Interpretation:** sentinel recovery tests the configured search against known relevant literature. It does not establish completeness, sensitivity against all eligible research, or correctness of scientific inclusion.',
      'External-only means the supplied output does not document PubMed retrieval even if the study is indexed there. It may also reflect missing provenance.',
      '', '## Records needing attention',
    ]
    if issues or review_external:
        lines.extend(f'- {r["Outcome"]}: {r["Study"]} ({r["DOI"]})' for r in issues+review_external)
    else:lines.append('- None among this sentinel set.')
    lines.extend(['','## Individual studies']+[f'- **{r["Study"]}**: {r["Outcome"]}; streams: {r["Search streams"] or "not documented"}' for r in results])
    lines.extend(['','## Actions when a key study is missing',
        '1. Inspect failed-query and run-manifest outputs before interpreting a miss as query failure.',
        '2. Search by verified PMID/DOI in PubMed and check index status; publisher-only articles require external database capture.',
        '3. Test alternative text synonyms in a newly versioned targeted search and rerun retrieval; do not silently append a known paper and count it as originally retrieved.',
        '4. Track manual additions as a distinct source with an audit trail; rerun classification and screening for them.',
        '5. Do not assert full coverage from a perfect sentinel score.' ])
    (outdir/'Known_Paper_Recovery_Report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return recovered,len(eligible),issues

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',action='append',type=Path,default=[],help='CSV from search discovery. Can pass twice for broad and targeted.')
    p.add_argument('--outdir',type=Path,default=ROOT/'data'/'logs'/'known_paper_recovery')
    p.add_argument('--strict',action='store_true',help='Exit 2 if any known PubMed-indexed sentinel missing from PubMed retrieval.')
    args=p.parse_args()
    if args.input: paths=args.input
    elif DEFAULT_INPUTS[0].exists(): paths=DEFAULT_INPUTS[:1]
    else: paths=[x for x in DEFAULT_INPUTS[1:] if x.exists()]
    if not paths or any(not x.is_file() for x in paths):
        p.error('No real discovery CSV available: run broad/targeted (or all) PubMed search first, or provide --input CSV.')
    corpus,results=audit(paths)
    recovered,denom,missing=output(corpus,results,args.outdir)
    print(f'PubMed-indexed sentinel studies recovered via PubMed: {recovered}/{denom}')
    print(f'Report: {args.outdir / "Known_Paper_Recovery_Report.md"}')
    if args.strict and any(r['Outcome']!='FOUND_PUBMED' for r in results if 'confirmed' in r['Registry status'].lower()):
        sys.exit(2)
if __name__=='__main__':main()
