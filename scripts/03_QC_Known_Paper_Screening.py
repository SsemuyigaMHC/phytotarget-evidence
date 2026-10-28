#!/usr/bin/env python3
"""Audit provisional screening decisions for known Chapter 13 publications.

Missing records and provisionally excluded records are distinct warnings.
Does not modify any screening decisions or silently inject known papers.
"""
from __future__ import annotations
import argparse,csv,re,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import pandas as pd

def norm_doi(x):
    return re.sub(r'^https?://(?:dx\.)?doi\.org/|^doi:\s*','',str(x or '').strip().lower()).rstrip(' ,.;')
def norm_pmid(x):
    return str(x or '').strip().removesuffix('.0')
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',type=Path,default=ROOT/'data'/'metadata'/'Chapter13_Metadata_Screened'/'Chapter13_Metadata_Screened_FINAL.csv')
    p.add_argument('--outdir',type=Path,default=ROOT/'data'/'logs'/'screened_sentinels')
    p.add_argument('--strict',action='store_true',help='Fail if known PubMed papers missing or provisionally EXCLUDE')
    a=p.parse_args()
    if not a.input.is_file():p.error('Run classification and metadata screening first; provide real --input CSV/XLSX')
    df=pd.read_csv(a.input,dtype=str,keep_default_na=False) if a.input.suffix.lower()=='.csv' else pd.read_excel(a.input,dtype=str).fillna('')
    needed={'PMID','DOI','Metadata Decision'}
    if not needed.issubset(df.columns):p.error(f'Missing columns: {needed-set(df.columns)}')
    with (ROOT/'config'/'known_papers_sentinel.csv').open(newline='',encoding='utf-8-sig') as f:
        papers=list(csv.DictReader(f))
    df['_pmid']=df['PMID'].map(norm_pmid);df['_doi']=df['DOI'].map(norm_doi)
    rows=[]
    for paper in papers:
        pid=norm_pmid(paper['PMID']);doi=norm_doi(paper['DOI'])
        candidates=df[(df['_pmid']==pid)&(df['_pmid']!='')] if pid else df.iloc[:0]
        if doi:candidates=pd.concat([candidates,df[(df['_doi']==doi)&(df['_doi']!='')]]).drop_duplicates()
        if candidates.empty:stage='NOT_IN_SCREENED_CORPUS';status=''
        else:
            statuses=sorted(set(candidates['Metadata Decision'].astype(str)))
            status=';'.join(statuses)
            stage='PROVISIONAL_EXCLUDE_REVIEW_NEEDED' if 'EXCLUDE' in statuses else 'PRESENT_FOR_MANUAL_REVIEW'
        rows.append({'Study':paper['Study'],'PMID':pid,'DOI':doi,'Screening QC':stage,
            'Provisional decisions':status,'Registry status':paper['Registry status']})
    a.outdir.mkdir(parents=True,exist_ok=True)
    with (a.outdir/'Known_Paper_Screening_QC.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    misses=[r for r in rows if r['Screening QC']=='NOT_IN_SCREENED_CORPUS']
    exclusions=[r for r in rows if r['Screening QC']=='PROVISIONAL_EXCLUDE_REVIEW_NEEDED']
    msg=[ '# Known paper — provisional screening QC','',f'Present: {len(rows)-len(misses)}/{len(rows)}; missing: {len(misses)}; provisional EXCLUDE: {len(exclusions)}.',
          'This is a known-paper screening safety check, not a substitute for screening all records.', '',
          '## Warnings'] + [f'- {r["Screening QC"]}: {r["Study"]}' for r in misses+exclusions]
    if not misses and not exclusions:msg.append('- No known-paper screening warnings.')
    (a.outdir/'Known_Paper_Screening_QC.md').write_text('\n'.join(msg)+'\n',encoding='utf-8')
    print(f'Known-paper screening: {len(rows)-len(misses)}/{len(rows)} present; {len(exclusions)} provisionally excluded')
    important = [r for r in misses+exclusions if 'confirmed' in r['Registry status'].lower()]
    if a.strict and important: sys.exit(2)
if __name__=='__main__':main()
