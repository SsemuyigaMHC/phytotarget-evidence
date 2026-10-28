#!/usr/bin/env python3
"""Stage 02 QC — audit automated provisional literature classification."""
from __future__ import annotations
import argparse, sys
from pathlib import Path
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from config.settings import SETTINGS

from config.taxonomy import SIGNAL_TERMS, SUBSECTION_HINTS
EXPECTED_MECHANISMS=list(SIGNAL_TERMS)
EXPECTED_SUBS=list(SUBSECTION_HINTS)

def clean(x): return "" if pd.isna(x) else str(x).strip()

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--input',type=Path,default=SETTINGS.metadata_dir/'Literature_Classified.xlsx'); ap.add_argument('--output-dir',type=Path,default=SETTINGS.metadata_dir/'QC_Classification'); args=ap.parse_args()
    df=pd.read_excel(args.input,dtype=object).fillna(''); out=args.output_dir; out.mkdir(parents=True,exist_ok=True)
    req=['Primary Literature Category','Evidence Tier','Mechanism Flags','Subsection Hints','Scientific Role Flags','Classification Status','Final Literature Category']
    missing=[c for c in req if c not in df.columns]
    flags=[]
    if missing: flags.append(('FAIL','Missing required classification columns: '+', '.join(missing)))
    else:
        for c in req[:-2]:
            n=int(df[c].map(clean).eq('').sum());
            if n: flags.append(('WARN',f'{n:,} records have blank {c}.'))
        if not df['Classification Status'].astype(str).eq('AUTOMATED_PROVISIONAL').all(): flags.append(('WARN','Some records do not retain AUTOMATED_PROVISIONAL status.'))
        if df['Final Literature Category'].map(clean).ne('').any(): flags.append(('INFO','Final Literature Category contains manually populated values; inspect whether this is intentional.'))
    dist=df['Primary Literature Category'].value_counts(dropna=False).rename_axis('Category').reset_index(name='Records') if 'Primary Literature Category' in df else pd.DataFrame()
    tier=df['Evidence Tier'].value_counts(dropna=False).rename_axis('Evidence_Tier').reset_index(name='Records') if 'Evidence Tier' in df else pd.DataFrame()
    mech=[]
    if 'Mechanism Flags' in df:
        for m in EXPECTED_MECHANISMS:
            n=df['Mechanism Flags'].astype(str).str.contains(m,regex=False).sum(); mech.append({'Mechanism':m,'Records':int(n),'Percent':round(100*n/max(len(df),1),2)})
    mechdf=pd.DataFrame(mech)
    sub=[]
    if 'Subsection Hints' in df:
        for s in EXPECTED_SUBS:
            n=df['Subsection Hints'].astype(str).str.contains(s,regex=False).sum(); sub.append({'Subsection':s,'Records':int(n),'Percent':round(100*n/max(len(df),1),2)})
    subdf=pd.DataFrame(sub)
    no_mech=df[df.get('Mechanism Flags','').astype(str).str.strip().eq('')] if 'Mechanism Flags' in df else pd.DataFrame()
    no_sub=df[df.get('Subsection Hints','').astype(str).str.strip().eq('')] if 'Subsection Hints' in df else pd.DataFrame()
    # Potential review-type mismatch; never a final inclusion judgment.
    text_cols=[c for c in ['Title','Abstract','Publication Type'] if c in df.columns]
    txt=df[text_cols].astype(str).agg(' '.join,axis=1).str.lower() if text_cols else pd.Series(['']*len(df))
    contradiction=pd.DataFrame({'Title':df['Title'] if 'Title' in df else '', 'Category':df['Primary Literature Category'] if 'Primary Literature Category' in df else '', 'Text':txt})
    contradiction=contradiction[txt.str.contains(r'\breview\b',regex=True) & ~contradiction['Category'].eq('B_MAJOR_REVIEW')]
    contradiction.to_excel(out/'02E_Potential_Classification_Contradictions.xlsx',index=False)
    # Stratified review sample
    parts=[]
    for cat in dist['Category'].tolist() if not dist.empty else []:
        sub=df[df['Primary Literature Category'].eq(cat)]
        if not sub.empty: parts.append(sub.sample(min(10,len(sub)),random_state=40))
    sample=pd.concat(parts,ignore_index=True).drop_duplicates(subset=[c for c in ['PMID','DOI','Title'] if c in df]).head(100) if parts else pd.DataFrame()
    sample.to_excel(out/'02F_Stratifed_Classification_QC_Sample.xlsx',index=False)
    no_mech.to_excel(out/'02G_No_Evidence_Task_Flag.xlsx',index=False); no_sub.to_excel(out/'02H_No_Subsection_Hint.xlsx',index=False)
    dist.to_excel(out/'02A_Category_Distribution.xlsx',index=False); tier.to_excel(out/'02B_Evidence_Tier_Distribution.xlsx',index=False); mechdf.to_excel(out/'02C_Evidence_Task_Coverage.xlsx',index=False); subdf.to_excel(out/'02D_Subsection_Hint_Coverage.xlsx',index=False)
    if not flags: flags.append(('INFO','No automated classification QC warnings triggered; human review of the stratified sample remains required.'))
    pd.DataFrame(flags,columns=['Level','Finding']).to_excel(out/'02I_QC_Flags.xlsx',index=False)
    print(f'Classification QC written to: {out}')
if __name__=='__main__': main()
