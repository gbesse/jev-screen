import tempfile,unittest
from pathlib import Path
from jev_screen.cache import ResultCache
from jev_screen.client import JevResult
class CacheSnapshotTests(unittest.TestCase):
 def test_put_detaches_provider_result(self):
  with tempfile.TemporaryDirectory() as tmp:
   c=ResultCache(Path(tmp)/'c.json');r=JevResult(model='jev-1.13.0',answers={'q':{'choice':'include'}},usage={'input_tokens':1},estimated_cost_usd=0);c.put('key',r);r.answers['q']['choice']='exclude';r.usage['input_tokens']=99
   self.assertEqual(c.get('key').answers['q']['choice'],'include');self.assertEqual(c.get('key').usage['input_tokens'],1)
 def test_get_detaches_nested_answers_and_persisted_cache(self):
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'c.json';c=ResultCache(path);c.put('key',JevResult(model='jev-1.13.0',answers={'q':{'choice':'include'}},usage={'input_tokens':1},estimated_cost_usd=0));r=c.get('key');r.answers['q']['choice']='exclude';c.save()
   self.assertEqual(c.get('key').answers['q']['choice'],'include');self.assertEqual(ResultCache(path).get('key').answers['q']['choice'],'include')
