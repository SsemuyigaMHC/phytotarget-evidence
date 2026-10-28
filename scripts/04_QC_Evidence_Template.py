#!/usr/bin/env python3
"""Stage 04 QC — verify the evidence-matrix template before claim extraction."""
from __future__ import annotations
import argparse,sys
from pathlib import Path
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from config.settings import SETTINGS
EXPECTED_SHEETS=['Evidence_Matrix','Literature_Discovery_Master','Coding_Guide']
EXPECTED_COLUMNS=['Claim ID', 'Chapter section', 'Study PMID', 'DOI', 'Compound name / preparation', 'Compound identifier / structure', 'Protein / mediator', 'Protein isoform / organism', 'Proposed relationship', 'Prediction task', 'Computational evidence', 'Model and data provenance', 'Train / test separation', 'Predicted endpoint and score', 'Evidence origin', 'Experiment / assay', 'Measured endpoint (raw)', 'Protein source / biological system', 'Dose / exposure / timing', 'Controls and comparators', 'Observed result', 'Negative / discordant evidence', 'Claim supported', 'Unresolved alternatives', 'Status: tested positive / tested negative / untested / inconclusive', 'Source locator (figure/table/page)', 'Independent replication?', 'Reviewer decision', 'Scientific limitations', 'Figure or table mapping']

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--input',type=Path,default=SETTINGS.claims_dir/'Chapter13_Evidence_Matrix_Template.xlsx'); ap.add_argument('--output-dir',type=Path,default=SETTINGS.claims_dir/'QC_Template'); args=ap.parse_args()
    out=args.output_dir; out.mkdir(parents=True,exist_ok=True); flags=[]
    xl=pd.ExcelFile(args.input); sheets=xl.sheet_names
    pd.DataFrame({'Expected_Sheet':EXPECTED_SHEETS,'Present':[x in sheets for x in EXPECTED_SHEETS]}).to_excel(out/'04A_Sheet_Check.xlsx',index=False)
    if any(x not in sheets for x in EXPECTED_SHEETS): flags.append(('FAIL','One or more expected evidence-matrix sheets are missing.'))
    if 'Evidence_Matrix' in sheets:
        df=pd.read_excel(args.input,sheet_name='Evidence_Matrix',dtype=object).fillna('')
        missing=[c for c in EXPECTED_COLUMNS if c not in df.columns]
        pd.DataFrame({'Expected_Column':EXPECTED_COLUMNS,'Present':[x in df.columns for x in EXPECTED_COLUMNS]}).to_excel(out/'04B_Evidence_Column_Check.xlsx',index=False)
        if missing: flags.append(('FAIL','Missing Evidence_Matrix columns: '+', '.join(missing)))
        if 'Claim ID' in df:
            ids=df['Claim ID'].astype(str).str.strip()
            ids=ids[ids.ne('')]
            if ids.duplicated().any():flags.append(('FAIL','Duplicate nonblank Claim ID values detected.'))
    pd.DataFrame(flags or [('INFO','Evidence template structure passed automated QC; claim-level scientific QC begins during extraction.')],columns=['Level','Finding']).to_excel(out/'04C_QC_Flags.xlsx',index=False)
    print(f'Evidence template QC written to: {out}')
if __name__=='__main__': main()
