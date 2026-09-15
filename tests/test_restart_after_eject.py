import importlib.util
from pathlib import Path
import tempfile
import unittest

B=Path(__file__).resolve().parent
s=importlib.util.spec_from_file_location('restart',B.parent/'code/reference-system/opt/gpd-egpu/auto/restart-clean-cycle.py')
r=importlib.util.module_from_spec(s);s.loader.exec_module(r)

class Tests(unittest.TestCase):
    def test_only_clean_same_boot_restart(self):
        eject={'boot':'one','stage':'all-nvidia-modules-unloaded'}
        done={'boot_id':'one','stage':'completed'}
        r.validate_records('one',eject,done,done,False)
        for args in [('two',eject,done,done,False),('one',eject,done,done,True),
                     ('one',dict(eject,stage='failed-do-not-unplug'),done,done,False),
                     ('one',eject,dict(done,stage='failed'),done,False),
                     ('one',eject,done,dict(done,stage='before-nvidia-drm.ko'),False)]:
            with self.assertRaises(RuntimeError):r.validate_records(*args)

    def test_archives_preserve_and_never_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            b=Path(d);src=b/'before';src.mkdir();(src/'state').write_text('evidence')
            dest=b/'saved';r.archive(src,dest)
            self.assertFalse(src.exists());self.assertEqual((dest/'state').read_text(),'evidence')
            src.mkdir();(src/'state').write_text('different')
            with self.assertRaises(RuntimeError):r.archive(src,dest)
            self.assertEqual((src/'state').read_text(),'different')

    def test_no_recovery_or_trial_load(self):
        text=(B.parent/'code/reference-system/opt/gpd-egpu/auto/restart-clean-cycle.py').read_text();compile(text,'restart','exec')
        for forbidden in ("['insmod'","['rmmod'","['modprobe'",'setpci','/rescan','/reset','/unbind','mkinitcpio','depmod'):
            self.assertNotIn(forbidden,text)
        self.assertIn("t.run(['/usr/local/sbin/gpd-egpu-start']",text)
        self.assertLess(text.index("validate_records(boot"),text.index("archive(p,base"))
        self.assertLess(text.index("checkpoint('before-working-loader')"),text.index("t.run(['/usr/local/sbin/gpd-egpu-start']"))
        self.assertLess(text.index("l.nvml(t,m)"),text.index("archive(eject,base"))

if __name__=='__main__':unittest.main()
