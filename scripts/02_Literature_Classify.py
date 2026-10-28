#!/usr/bin/env python3
"""Chapter 13 provisional literature role classification; title/abstract only.
Scientific inclusion and claim validation remain human decisions.
"""
from __future__ import annotations
import argparse,sys,re
from pathlib import Path
import pandas as pd
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from config.settings import SETTINGS
from config.taxonomy import CATEGORIES, SIGNAL_TERMS, SUBSECTION_HINTS

def clean(x): return '' if pd.isna(x) else str(x).strip().lower()
def contains(txt,terms): return any(t in txt for t in terms)
def classify(row,seeds):
    pmid=clean(row.get('PMID','')); doi=clean(row.get('DOI','')).replace('https://doi.org/','')
    text=' '.join(clean(row.get(c,'')) for c in ['Title','Abstract','Keywords','MeSH Terms'])
    ptype=clean(row.get('Publication Type',''))
    if (pmid and pmid in seeds) or (doi and doi in seeds): return 'A_FOUNDATIONAL'
    if 'review' in ptype or 'meta-analysis' in ptype: return 'B_MAJOR_REVIEW'
    if any(w in ptype for w in ['editorial','comment','letter']): return 'F_GENERAL_METHOD_OR_PERSPECTIVE'
    experimental=contains(text, ['measured binding','binding assay','target engagement','chemoproteomic','covalent modification','rescue experiment','knockdown','knockout','microscale thermophoresis','surface plasmon resonance','mass spectrometry','inhibition assay'])
    predictive=contains(text,['target prediction','target fishing','drug-target interaction','compound-protein','protein-ligand','binding affinity prediction','machine learning','deep learning'])
    context=contains(text,['perturbation','l1000','transcriptomic','multi-omics','connectivity map','viability profile','latent factor'])
    if experimental: return 'D_EXPERIMENTAL_MECHANISM'
    if predictive: return 'C_AI_TARGET_PREDICTION'
    if context: return 'E_PERTURBATION_CONTEXT'
    return 'F_GENERAL_METHOD_OR_PERSPECTIVE'

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--input',type=Path,default=SETTINGS.metadata_dir/'Literature_Discovery_broad.xlsx');args=ap.parse_args()
    df=pd.read_csv(args.input,dtype=object).fillna('') if args.input.suffix.lower()=='.csv' else pd.read_excel(args.input,dtype=object).fillna('')
    seeds=set();seed=ROOT/'config'/'foundational_seed.csv'
    if seed.exists():
        sdf=pd.read_csv(seed,dtype=str).fillna('')
        for col in ['PMID','DOI']:
            if col in sdf:seeds.update(clean(v).replace('https://doi.org/','') for v in sdf[col] if clean(v))
    cats=[];tiers=[];flags=[];subs=[];roles=[]
    for _,row in df.iterrows():
        text=' '.join(clean(row.get(c,'')) for c in ['Title','Abstract','Keywords','MeSH Terms'])
        cat=classify(row,seeds);cats.append(cat)
        ptype=clean(row.get('Publication Type',''))
        tier=('Tier 2' if cat=='B_MAJOR_REVIEW' else 'Tier 4' if any(w in ptype for w in ['editorial','comment','letter']) else 'Tier 1' if cat in ['A_FOUNDATIONAL','C_AI_TARGET_PREDICTION','D_EXPERIMENTAL_MECHANISM','E_PERTURBATION_CONTEXT'] else 'Tier 5')
        tiers.append(tier)
        hit=[key for key,terms in SIGNAL_TERMS.items() if contains(text,terms)]
        flags.append('; '.join(hit))
        subs.append('; '.join(key for key,terms in SUBSECTION_HINTS.items() if contains(text,terms)))
        roles.append('; '.join(hit) if hit else 'UNDETERMINED_FROM_METADATA')
    df['Primary Literature Category']=cats
    df['Evidence Tier']=tiers
    df['Mechanism Flags']=flags # backward compatible field; these are Chapter 13 evidence TASK flags, not proven mechanisms
    df['Subsection Hints']=subs
    df['Scientific Role Flags']=roles
    df['Classification Status']='AUTOMATED_PROVISIONAL'
    df['Final Literature Category']=''
    df['Foundational Status']=['MANUALLY_CURATED' if cat=='A_FOUNDATIONAL' else 'NOT_MANUALLY_CURATED' for cat in cats]
    out=SETTINGS.metadata_dir/'Literature_Classified.xlsx';out.parent.mkdir(parents=True,exist_ok=True)
    df.to_excel(out,index=False);df.to_csv(out.with_suffix('.csv'),index=False)
    print(f'Wrote {len(df)} provisionally classified records to {out}')
    print(df['Primary Literature Category'].value_counts(dropna=False).to_string())
if __name__=='__main__':main()
