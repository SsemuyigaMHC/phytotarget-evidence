#!/usr/bin/env python3
"""Stage 03 full-text QC using screened queue and actual validated files/log; no invented summary."""
from __future__ import annotations
import argparse,re,sys,importlib.util
from pathlib import Path
import pandas as pd
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from config.settings import SETTINGS
# Share exact PDF/HTML/XML validation with the downloader; do not equate
# nonzero file size to a valid article.
_spec = importlib.util.spec_from_file_location('phyto_acquisition', ROOT/'scripts'/'03_Full_Text_Acquisition.py')
_acquisition = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _acquisition
_spec.loader.exec_module(_acquisition)

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--screened',type=Path,default=SETTINGS.metadata_dir/'Chapter13_Metadata_Screened'/'Chapter13_Metadata_Screened_FINAL.xlsx');ap.add_argument('--output-dir',type=Path,default=SETTINGS.metadata_dir/'QC_Full_Text');args=ap.parse_args()
 df=pd.read_excel(args.screened,dtype=object).fillna('');out=args.output_dir;out.mkdir(parents=True,exist_ok=True)
 queue=df[df['Metadata Decision'].isin(['RETAIN','REVIEW'])].copy()
 base=SETTINGS.full_text_dir;results=[]
 for _,r in queue.iterrows():
  pmid=str(r['PMID']).strip();priority=str(r.get('Acquisition Priority','')).strip();route=str(r.get('Screening Route','')).strip()
  candidates=[]
  for ext in ('pdf','html','xml'):
   path=base/priority/route/ext/(pmid+'.'+ext)
   if _acquisition.validate_saved_file(path): candidates.append(str(path.relative_to(ROOT)))
  results.append({'PMID':pmid,'Acquisition Priority':priority,'Screening Route':route,'Found_Article_Artifacts':'; '.join(candidates),'Has_Article_File':bool(candidates)})
 rd=pd.DataFrame(results);rd.to_excel(out/'03A_Article_File_Inventory.xlsx',index=False)
 missing=rd[~rd['Has_Article_File']] if not rd.empty else rd
 missing.to_excel(out/'03B_Acquisition_Missing.xlsx',index=False)
 flags=[('INFO',f'{len(queue)} eligible records, {len(rd)-len(missing)} with article artifacts, {len(missing)} missing.')]
 flags.append(('WARN','File format/content validation is not proof of scientific completeness; inspect actual papers and downloader log.'))
 pd.DataFrame(flags,columns=['Level','Finding']).to_excel(out/'03C_Acquisition_QC_Flags.xlsx',index=False)
 print(f'Acquisition QC: {len(rd)-len(missing)}/{len(rd)} eligible PMIDs have an article file; see {out}')
if __name__=='__main__':main()
