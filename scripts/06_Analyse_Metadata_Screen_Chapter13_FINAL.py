#!/usr/bin/env python3
"""Chapter 13 post-screening descriptive QC; does not alter decisions."""
from pathlib import Path
import argparse,re
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--input',type=Path,default=ROOT/'data/metadata/Chapter13_Metadata_Screened/Chapter13_Metadata_Screened_FINAL.xlsx');ap.add_argument('--output-dir',type=Path,default=ROOT/'data/metadata/QC_Metadata_Screen');args=ap.parse_args()
 df=pd.read_excel(args.input,dtype=object).fillna('');o=args.output_dir;o.mkdir(parents=True,exist_ok=True)
 for col,label in [('Metadata Decision','Decisions'),('Primary Literature Category','Categories'),('Evidence Tier','EvidenceTiers'),('Screening Route','ScreeningRoutes')]:
  tab=df[col].value_counts(dropna=False).rename_axis(col).reset_index(name='Records')
  tab.to_excel(o/f'{label}.xlsx',index=False)
 for col,label in [('Mechanism Flags','EvidenceTasks'),('Subsection Hints','SectionHints'),('Originating Search Streams','SearchStreams')]:
  vals=df[col].astype(str).str.split(';').explode().str.strip();vals=vals[vals.ne('')]
  vals.value_counts().rename_axis(col).reset_index(name='Records').to_excel(o/f'{label}.xlsx',index=False)
 df.sample(min(len(df),75),random_state=13).to_excel(o/'Stratified_Manual_Check.xlsx',index=False) if len(df) else None
 report=(f'Chapter 13 metadata review | Records {len(df)}\nAutomated decisions are provisional; inspect false negatives and the stratified sample.\n')
 (o/'Report.txt').write_text(report,encoding='utf-8');print(report)
if __name__=='__main__':main()
