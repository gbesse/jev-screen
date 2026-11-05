import unittest
from jev_screen.stats import recall_by_group
class GroupRecallTests(unittest.TestCase):
 def test_global_can_hide_group_failure(self):
  x=recall_by_group([True,True,False],[True,True,True],['a','a','b'])['groups'];self.assertEqual([r['recall']for r in x],[1,0])
 def test_no_positives_unknown(self):self.assertIsNone(recall_by_group([False],[False],['a'])['groups'][0]['recall'])
 def test_length(self):
  with self.assertRaises(ValueError):recall_by_group([True],[],[])
