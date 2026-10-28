"""Regression tests for simplified entrypoint and safe data handling (offline)."""
import importlib.util
import tempfile
import unittest
from pathlib import Path
import sys
from unittest.mock import patch
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from utilities.pubmed import build_literature_index
from utilities.ncbi import _validate_search_count


class PipelineSafetyTest(unittest.TestCase):
    def test_pubmed_external_same_doi_merge_after_enrichment(self):
        data=pd.DataFrame([
            {'PMID':'12345678','DOI':'10.1234/abc','Title':'Test paper','Authors':'A B','Year':'2024','Source Databases':'PubMed','Originating Search Streams':'A'},
            {'PMID':'','DOI':'https://doi.org/10.1234/abc','Title':'Test paper','Authors':'A B','Year':'2024','Source Databases':'Scopus','Originating Search Streams':'B'},
        ])
        result=build_literature_index({},base_records=data)
        self.assertEqual(len(result),1)
        self.assertEqual(result.iloc[0]['PMID'],'12345678')
        self.assertIn('PubMed',result.iloc[0]['Source Databases'])
        self.assertIn('Scopus',result.iloc[0]['Source Databases'])

    def test_pubmed_hard_limit_fails_instead_of_truncating(self):
        with self.assertRaisesRegex(RuntimeError,'incomplete'):
            _validate_search_count(12000,[str(i) for i in range(10000)],10000,'sample')
        with self.assertRaisesRegex(RuntimeError,'incomplete'):
            _validate_search_count(4,['1','2'],10000,'sample')
        _validate_search_count(2,['1','2'],10000,'sample')

    def test_downloader_validator_rejects_fake_pdf(self):
        path=ROOT/'scripts'/'03_Full_Text_Acquisition.py'
        spec=importlib.util.spec_from_file_location('phyto_downloader_test',path)
        module=importlib.util.module_from_spec(spec)
        sys.modules[spec.name]=module
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            pdf=Path(tmp)/'fake.pdf'
            pdf.write_bytes(b'this is not a pdf file')
            self.assertFalse(module.validate_saved_file(pdf))
            pdf.write_bytes(b'%PDF-1.4\nminimal\n%%EOF')
            self.assertTrue(module.validate_saved_file(pdf))

    def test_single_entrypoint_is_importable(self):
        import run
        self.assertTrue(hasattr(run, 'make_parser'))
        self.assertEqual(run.make_parser().parse_args(['status']).step,'status')

if __name__ == '__main__':unittest.main()
