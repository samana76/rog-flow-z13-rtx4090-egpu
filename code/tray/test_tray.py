import importlib.util
from pathlib import Path
import tempfile
import unittest
s=importlib.util.spec_from_file_location('tray',Path(__file__).with_name('egpu-tray.py'))
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
class Tests(unittest.TestCase):
    def test_dynamic_device(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            for name,v,d,c in [('0000:63:00.0','0x10de','0x2684','0x030000'),('0000:63:00.1','0x10de','0x22ba','0x040300'),('0000:c4:00.0','0x1002','0x150e','0x030000')]:
                p=root/name;p.mkdir()
                for key,val in [('vendor',v),('device',d),('class',c)]: (p/key).write_text(val+'\n')
            self.assertEqual(m.devices(root),('0000:63:00.0',))
    def test_success_requires_helper_marker_and_normal_exit(self):
        self.assertTrue(m.succeeded(0,True,'READY TO UNPLUG: all unloaded'))
        for c,n,o in [(1,True,'READY TO UNPLUG:'),(0,False,'READY TO UNPLUG:'),(0,True,'nothing')]:
            self.assertFalse(m.succeeded(c,n,o))
    def test_fixed_privilege_target(self):
        self.assertEqual(m.HELPER,'/usr/local/libexec/gpd-egpu-eject')
if __name__=='__main__': unittest.main()
