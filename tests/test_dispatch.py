import unittest,threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch
from jev_screen.screening import screen_records
from jev_screen.records import Record
class DispatchTests(unittest.TestCase):
 def test_one_worker_failure_does_not_enqueue_the_whole_review(self):
  calls=[]
  def worker(record,*a,**kw):
   calls.append(record.id)
   if record.id=='0':raise RuntimeError('synthetic failure')
   return SimpleNamespace(record=record)
  with patch('jev_screen.screening.ScreeningContext.build'),patch('jev_screen.screening.screen_one',side_effect=worker):
   with self.assertRaisesRegex(RuntimeError,'synthetic failure'):screen_records([Record(str(i))for i in range(1000)],None,None,concurrency=1)
  self.assertEqual(calls,['0'])
 def test_slow_prefix_bounds_dispatch_and_callbacks_still_follow_input(self):
  release=threading.Event();second=threading.Event();calls=[];emitted=[]
  def worker(record,*a,**kw):
   calls.append(record.id)
   if record.id=='0':self.assertTrue(release.wait(2))
   if record.id=='1':second.set()
   return SimpleNamespace(record=record)
  with patch('jev_screen.screening.ScreeningContext.build'),patch('jev_screen.screening.screen_one',side_effect=worker),ThreadPoolExecutor(max_workers=1)as outer:
   future=outer.submit(screen_records,[Record(str(i))for i in range(10)],None,None,concurrency=2,on_result=lambda r:emitted.append(r.record.id))
   try:self.assertTrue(second.wait(2));self.assertEqual(set(calls),{'0','1'});self.assertEqual(emitted,[])
   finally:release.set()
   result=future.result(3)
  self.assertEqual([r.record.id for r in result],[str(i)for i in range(10)]);self.assertEqual(emitted,[str(i)for i in range(10)])
 def test_invalid_concurrency_is_rejected_before_context_or_calls(self):
  with patch('jev_screen.screening.ScreeningContext.build')as context:
   for concurrency in [True,0,-1,1.5,65,float('nan')]:
    with self.assertRaises(ValueError):screen_records([],None,None,concurrency=concurrency)
   context.assert_not_called()
