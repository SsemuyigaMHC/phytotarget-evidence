"""Offline structural regression tests; cannot substitute for live PubMed testing."""
import tempfile,unittest,sys
from pathlib import Path
from importlib.util import spec_from_file_location,module_from_spec
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
spec=spec_from_file_location('probe',ROOT/'scripts'/'01_QC_Live_Query_Recovery.py')
probe=module_from_spec(spec);spec.loader.exec_module(probe)
class RecoveryTest(unittest.TestCase):
 def test_catalog_and_query_structure(self):
  indexed,publisher=probe.seeds()
  self.assertGreaterEqual(len(indexed),12)
  self.assertTrue(any('DrugBAN' in x['Study'] for x in publisher))
  s=probe.scoped_queries('all','2026-10-21')
  self.assertTrue(all('[Date - Publication]' in q for qs in s.values() for q in qs))
  self.assertTrue(all(q.count('(')==q.count(')') for qs in s.values() for q in qs))
 def test_core_chapter_names_are_present_in_queries(self):
  text=' '.join(q for qs in probe.scoped_queries('all','').values() for q in qs).lower()
  for term in ['starfish','drugban','ai-bind','deeptarget','dti-voodoo','ceteam','nimbolide','acevaltrate','eupalinolide','gaudichaudione','ginsenoside','scopedti','li-dti','5-methoxysalicylic acid']:
   with self.subTest(term=term):self.assertIn(term,text)
 def test_recovery_counts_are_from_matching_ids(self):
  indexed,_=probe.seeds()
  sought=indexed[0]['PMID']
  streams={'TEST_STREAM':('STarFish[Title/Abstract]','random[Title/Abstract]')}
  def fake_search(q,n):
   return [sought] if 'STarFish[Title/Abstract]' in q else []
  rows,found,errors=probe.test_queries(streams,indexed,fake_search)
  self.assertEqual(len(rows),2)
  self.assertEqual(len(found),1)
  self.assertEqual(found[sought],['TEST_STREAM#1'])
  self.assertEqual(errors,[])
  with tempfile.TemporaryDirectory() as t:
   meta=probe.write_report(Path(t),indexed,[],rows,found,errors,'all','2026-10-21')
   self.assertFalse(meta['pass'])
   self.assertEqual(meta['known_pubmed_indexed_matched'],1)
   self.assertTrue((Path(t)/'Query_Coverage_Report.md').is_file())
 def test_failure_cannot_be_counted_as_zero_recovery_without_notice(self):
  indexed,_=probe.seeds()
  def bad(q,n):raise OSError('intentional offline test failure')
  rows,found,err=probe.test_queries({'S':('abc',)},indexed,bad)
  self.assertEqual(rows[0]['Result'],'ERROR')
  self.assertEqual(len(err),1)
if __name__=='__main__':unittest.main()
