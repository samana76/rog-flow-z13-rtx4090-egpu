import ast
import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import patch

B=Path(__file__).resolve().parent
from importlib.machinery import SourceFileLoader
path=B.parent/'code/reference-system/usr/local/libexec/gpd-egpu-eject'
spec=importlib.util.spec_from_loader('eject',SourceFileLoader('eject',str(path)))
e=importlib.util.module_from_spec(spec);spec.loader.exec_module(e)

class Tests(unittest.TestCase):
    def test_invalid_pci(self):
        good=bytearray(64);good[:4]=bytes.fromhex('de108426');e.valid_config(good)
        for data in [b'',b'\xff'*64,b'\0'*64,bytes(good[:14])+b'\x7f'+bytes(good[15:])]:
            with self.assertRaises(RuntimeError):e.valid_config(data)

    def test_applications_block_release(self):
        e.classify_clients([],False)
        e.classify_clients([{'pid':3579,'name':'kwin_wayland','exe':'/usr/bin/kwin_wayland','uid':1000}],True)
        for found,allowed in [([{'pid':1,'name':'python'}],True),([{'pid':2,'name':'kwin_wayland'}],False)]:
            with self.assertRaises(RuntimeError):e.classify_clients(found,allowed)

    def test_client_detection_uses_saved_device_numbers(self):
        class Proc:
            def iterdir(self):return [Path('/proc')/str(os.getpid())]
        with open('/dev/null') as f,patch.object(e,'Path',return_value=Proc()):
            ids={os.fstat(f.fileno()).st_rdev}
            self.assertTrue(any(x['pid']==os.getpid() for x in e.clients(ids)))

    def test_no_force_or_pci_recovery(self):
        source=(B.parent/'code/reference-system/usr/local/libexec/gpd-egpu-eject').read_text()
        tree=ast.parse(source)
        calls=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='run']
        unloads=[c for c in calls if ast.literal_eval(c.args[0].elts[0])=='/usr/bin/rmmod']
        self.assertEqual(len(unloads),1)
        for c in calls:
            self.assertIn(ast.literal_eval(c.args[0].elts[0]),('/usr/bin/rmmod','/usr/bin/systemctl'))
        self.assertNotIn("'-f'",source)
        for text in ["/'remove'","/'reset'","/'rescan'",'setpci','/unbind',"['modprobe'"]:
            self.assertNotIn(text,source)
        self.assertIn("p/'uevent'",source)
        self.assertLess(source.index("checkpoint('all-gpu-clients-released')"),source.index("run(['/usr/bin/rmmod'"))
        self.assertLess(source.index("(p/'refcnt').read_text().strip()=='0'"),source.index("run(['/usr/bin/rmmod'"))

    def test_syntax(self):
        for p in (path,B.parent/'code/maintenance/install-eject.py'):
            compile(p.read_text(),str(p),'exec')

    def test_session_holders_only_before_release(self):
        processes=[{'pid':1,'name':'systemd','exe':'/usr/lib/systemd/systemd','uid':0},
                   {'pid':2626,'name':'systemd-logind','exe':'/usr/lib/systemd/systemd-logind','uid':0},
                   {'pid':4333,'name':'Xwayland','exe':'/usr/bin/Xwayland','uid':1000}]
        e.classify_clients(processes,True)
        with self.assertRaises(RuntimeError):e.classify_clients(processes,False)
        for p in processes:
            with self.assertRaises(RuntimeError):e.classify_clients([{**p,'exe':'/tmp/pretend-session'}],True)
        with self.assertRaises(RuntimeError):e.classify_clients([{'pid':5907,'name':'lact','uid':0,'exe':'/usr/bin/lact'}],True)

if __name__=='__main__':unittest.main()
