#!/usr/bin/env python3
"""Chapter 13 classifier-aware, conservative metadata screening. No automatic paper exclusion is final."""
from pathlib import Path
import argparse,re,sys
import pandas as pd
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from config.settings import SETTINGS
from config.taxonomy import SIGNAL_TERMS
DEFAULT_OUTPUT_DIR=SETTINGS.metadata_dir/'Chapter13_Metadata_Screened'
REQUIRED_CLASSIFIER=['Primary Literature Category','Evidence Tier','Mechanism Flags','Subsection Hints','Scientific Role Flags']
REQUIRED_SOURCE=['PMID','Title','Abstract','Publication Type','Originating Search Streams']

PATTERNS={
 'natural_product':r'\b(?:natural product|phytochemical|plant-derived|ginsenoside|celastrol|nimbolide|acevaltrate|eupalinolide|phenolic)\b',
 'target_task':r'\b(?:target prediction|target identification|target fishing|drug.target interaction|compound.protein|protein.ligand|target deconvolution)\b',
 'experimental':r'\b(?:target engagement|binding assay|covalent|chemoproteomic|enzyme inhibition|knockdown|knockout|rescue|binding affinity|thermal shift|cetsa|dart[s]?)\b',
 'context_inference':r'\b(?:perturbation|l1000|connectivity map|phenotypic screening|transcriptomic|multi.omics|latent factor)\b',
 'method_evaluation':r'\b(?:benchmark|cold.start|domain adaptation|explainab|generalizab|external validation|assay interference|false positive)\b',
}
PATTERNS={k:re.compile(v,re.I) for k,v in PATTERNS.items()}
NONPRIMARY=re.compile(r'\b(?:editorial|letter|comment|news|meeting abstract)\b',re.I)

def load(path):return pd.read_csv(path,dtype=object).fillna('') if path.suffix.lower()=='.csv' else pd.read_excel(path,dtype=object).fillna('')
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--input',type=Path,default=SETTINGS.metadata_dir/'Literature_Classified.xlsx');ap.add_argument('--output-dir',type=Path,default=DEFAULT_OUTPUT_DIR);args=ap.parse_args()
 df=load(args.input)
 missing=[x for x in REQUIRED_CLASSIFIER+REQUIRED_SOURCE if x not in df.columns]
 if missing:raise RuntimeError(f'Classifier-aware screening requires: {missing}; run Stage 02 first.')
 content=df[[c for c in ['Title','Abstract','Keywords','MeSH Terms'] if c in df.columns]].astype(str).agg(' '.join,axis=1).str.lower()
 signals={k:content.str.contains(p,na=False) for k,p in PATTERNS.items()}
 n=len(df);score=np.zeros(n,dtype=int);reasons=[[] for _ in range(n)]
 def add(mask,weight,label):
  nonlocal score
  arr=mask.to_numpy(dtype=bool);score+=arr.astype(int)*weight
  for i in np.flatnonzero(arr):reasons[i].append(label)
 cats=df['Primary Literature Category'].astype(str)
 for cat,weight in [('A_FOUNDATIONAL',2),('B_MAJOR_REVIEW',2),('C_AI_TARGET_PREDICTION',3),('D_EXPERIMENTAL_MECHANISM',3),('E_PERTURBATION_CONTEXT',3),('F_GENERAL_METHOD_OR_PERSPECTIVE',1)]:add(cats.eq(cat),weight,f'CATEGORY:{cat}')
 for name,weight in [('natural_product',2),('target_task',3),('experimental',3),('context_inference',2),('method_evaluation',1)]:add(signals[name],weight,f'CONTENT:{name}')
 explicit=signals['natural_product']&(signals['target_task']|signals['experimental']|signals['context_inference'])
 add(explicit,3,'NP_WITH_RELEVANT_EVIDENCE')
 task_flags=df['Mechanism Flags'].astype(str).str.contains(r'T\d+_',regex=True,na=False)
 add(task_flags,1,'EVIDENCE_TASK_FLAG')
 add(df['Subsection Hints'].astype(str).str.strip().ne(''),1,'SECTION_HINT')
 nonprimary=df['Publication Type'].astype(str).str.contains(NONPRIMARY,na=False)
 add(nonprimary,-2,'NONPRIMARY_FORMAT')
 # No global cancer requirement; general-method comparators are preserved for review.
 decision=np.where(score>=8,'RETAIN',np.where(score>=4,'REVIEW','EXCLUDE'))
 # Never silently discard a clearly chapter-relevant paper because one metadata field is missing.
 safety=(signals['target_task']|signals['experimental']|signals['context_inference'])&~nonprimary
 decision=np.where(safety&(decision=='EXCLUDE'),'REVIEW',decision)
 priority=np.where(decision=='RETAIN','P2_SUPPORTING',np.where(decision=='REVIEW','P3_MANUAL_REVIEW','P4_REFERENCE_ONLY')).astype(object)
 core=(explicit)&cats.isin(['C_AI_TARGET_PREDICTION','D_EXPERIMENTAL_MECHANISM','E_PERTURBATION_CONTEXT'])
 priority=np.where(core,'P1_CORE_CLAIMS',priority)
 route=np.where(decision=='RETAIN','CH13_RELEVANT_METADATA',np.where(decision=='REVIEW','MANUAL_METADATA_REVIEW','LOW_RELEVANCE_REFERENCE')).astype(object)
 route=np.where(core,'CORE_PREDICTION_OR_MECHANISM',route)
 route=np.where((decision=='RETAIN')&cats.eq('B_MAJOR_REVIEW'),'REVIEW_FRAMEWORK',route)
 route=np.where((decision=='RETAIN')&cats.eq('F_GENERAL_METHOD_OR_PERSPECTIVE'),'GENERAL_METHOD_COMPARATOR',route)
 out=df.copy();out['Metadata Relevance Score']=score;out['Metadata Decision']=decision;out['Acquisition Priority']=priority;out['Screening Route']=route
 out['Screening Reason']=['; '.join(dict.fromkeys(r)) for r in reasons]
 for k,v in signals.items():out['Signal '+k]=v
 out['Classifier Evidence Task Signal']=task_flags
 out['NonPrimary Publication Form']=nonprimary
 args.output_dir.mkdir(parents=True,exist_ok=True)
 stem='Chapter13_Metadata_Screened_FINAL'
 out.to_excel(args.output_dir/(stem+'.xlsx'),index=False);out.to_csv(args.output_dir/(stem+'.csv'),index=False)
 summary=args.output_dir/(stem+'_Summary.txt')
 summary.write_text(f'Chapter 13 metadata screening (automated provisional)\nInput records: {len(df)}\nOutput records: {len(out)}\nDecisions:\n{out["Metadata Decision"].value_counts()}\n\nAutomated EXCLUDE means manual reconsideration required, not final rejection.\n',encoding='utf-8')
 print(f'Screened {len(out)} records; provisional decisions: {out["Metadata Decision"].value_counts().to_dict()}')
 print(f'Wrote: {args.output_dir/(stem+".xlsx")}')
if __name__=='__main__':main()
