import tempfile
import unittest
from pathlib import Path
from jev_screen.screening import read_decisions

class DecisionCsvTests(unittest.TestCase):
 def read(self,text):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'decisions.csv';p.write_text(text);return read_decisions(p)
 def test_invalid_probability_cells_are_rejected(self):
  for value in ['nan','NaN','inf','-inf','1.01','-0.1','unknown']:
   with self.assertRaisesRegex(ValueError,'Invalid decisions CSV'):self.read('id,decision,reason,p_x,inclusion_score\na,include,reason,'+value+',0.5\n')
 def test_duplicate_ids_headers_and_partial_rows_rejected(self):
  cases=['id,decision,reason,p_x,p_x\na,include,r,0.5,0.9\n','id,decision,reason\na,include,r\na,exclude,r\n','id,decision,reason\na,include\n','id,decision,reason\na,include,r,extra\n','id,decision,reason\n,include,r\n','id,decision,reason\na,unknown,r\n']
  for text in cases:
   with self.assertRaises(ValueError):self.read(text)
 def test_blank_unjudged_probabilities_and_boundaries_survive(self):
  rows=self.read('id,decision,reason,p_x,inclusion_score\na,maybe,no-abstract,,\nb,include,ok,1,0\n')
  self.assertIsNone(rows[0]['p_x']);self.assertIsNone(rows[0]['inclusion_score']);self.assertEqual(rows[1]['p_x'],1);self.assertEqual(rows[1]['inclusion_score'],0)
