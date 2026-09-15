import importlib.util,unittest
from pathlib import Path
B=Path(__file__).resolve().parent
s=importlib.util.spec_from_file_location('r',B.parent/'code/pending-lact/restart-with-lact.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
class Tests(unittest.TestCase):
 def test_no_record_no_start(self):
  for r in ({},{'lact_paused':False},{'lact_paused':'true'}):
   self.assertEqual(m.restore_lact(r,lambda *a,**k:self.fail('Must not run service commands'),lambda _:None),'not-requested')
 def test_restore_once(self):
  calls=[];responses=iter(['inactive','','active'])
  def run(a,**k):calls.append(a);return next(responses)
  self.assertEqual(m.restore_lact({'lact_paused':True},run,lambda _:None),'restored')
  self.assertEqual(calls.count(['systemctl','start','lactd.service']),1)
 def test_active_service_untouched(self):
  calls=[]
  def run(a,**k):calls.append(a);return 'active'
  self.assertEqual(m.restore_lact({'lact_paused':True},run,lambda _:None),'already-active');self.assertEqual(len(calls),1)
 def test_failed_service_not_retried(self):
  self.assertEqual(m.restore_lact({'lact_paused':True},lambda *a,**k:'failed',lambda _:None),'not-restored:failed')
 def test_start_failure_does_not_fail_gpu(self):
  calls=[]
  def run(a,**k):
   calls.append(a)
   if 'start' in a:raise RuntimeError('failure')
   return 'inactive'
  self.assertEqual(m.restore_lact({'lact_paused':True},run,lambda _:None),'restore-failed');self.assertEqual(len(calls),2)
 def test_only_after_gpu_success(self):
  src=(B.parent/'code/pending-lact/restart-with-lact.py').read_text();call=src.index("record['lact_restore'] =")
  for required in ["l.nvml(t,m)","'New loader record incomplete'","archive(eject,base/'eject-before')"]:self.assertLess(src.index(required),call)
if __name__=='__main__':unittest.main()
