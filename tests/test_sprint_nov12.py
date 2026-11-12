import unittest,copy,math
from jev_screen.adjudication import adjudication_queue
class Adjudication(unittest.TestCase):
 def test_conflict_keeps_unknown_consensus(self):
  x=adjudication_queue({'a':{'x':True},'b':{'x':False}})['rows'][0];self.assertTrue(x['needs_adjudication']);self.assertIsNone(x['consensus'])
 def test_single_vote_not_two_reviewer_consensus(self):
  x=adjudication_queue({'a':{'x':True},'b':{'x':None}})['rows'][0];self.assertTrue(x['needs_more_reviews']);self.assertIsNone(x['consensus'])
 def test_boolean_contract(self):
  with self.assertRaises(ValueError):adjudication_queue({'a':{'x':'false'}})
