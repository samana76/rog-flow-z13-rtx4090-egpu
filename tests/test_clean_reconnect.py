import importlib.util
from pathlib import Path
import tempfile
import unittest
import json
from unittest.mock import patch
from types import SimpleNamespace

B=Path(__file__).resolve().parent
def source_path(name):
    if name=='install-clean-reconnect.py':return B.parent/'code/maintenance'/name
    return B.parent/'code/reference-system/opt/gpd-egpu/auto'/('auto-start.py' if name=='auto-clean-cycle.py' else name)
def load(name):
    s=importlib.util.spec_from_file_location(name,source_path(name));m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
a=load('auto-clean-cycle.py');r=load('restart-clean-cycle.py')

class Tests(unittest.TestCase):
    def test_dispatch(self):
        self.assertEqual(a.action(False,False,None),'first')
        self.assertEqual(a.action(True,False,{'stage':'all-nvidia-modules-unloaded'}),'restart')
        for loaded,record in [(True,{'stage':'all-nvidia-modules-unloaded'}),(False,None),(False,{'stage':'failed-do-not-unplug'})]:
            self.assertEqual(a.action(True,loaded,record),'skip')

    def test_owned_checkpoint(self):
        marker={'boot':'b','cycle':'c','action':'clean-eject-restart'}
        r.validate_marker(True,marker,'b','c');r.validate_marker(False,None,'b','c')
        for automatic,value,boot,cycle in [(True,None,'b','c'),(False,marker,'b','c'),(True,marker,'other','c'),(True,marker,'b','old'),(True,dict(marker,action='first'),'b','c')]:
            with self.assertRaises(RuntimeError):r.validate_marker(automatic,value,boot,cycle)

    def test_cycle_id_preserves_multiple_same_boot_ejects(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'state.json').write_text('{"stage":"all-nvidia-modules-unloaded"}')
            (p/'operations.log').write_text('first timestamp')
            first=r.cycle_id(p);self.assertEqual(first,r.cycle_id(p))
            (p/'operations.log').write_text('second timestamp')
            self.assertNotEqual(first,r.cycle_id(p))

    def test_clean_eject_guard_retained(self):
        eject={'boot':'b','stage':'all-nvidia-modules-unloaded'};done={'boot_id':'b','stage':'completed'}
        r.validate_records('b',eject,done,done,False)
        for loaded,record in [(True,eject),(False,dict(eject,stage='failed-do-not-unplug'))]:
            with self.assertRaises(RuntimeError):r.validate_records('b',record,done,done,loaded)

    def test_syntax_and_no_recovery(self):
        for name in ('auto-clean-cycle.py','restart-clean-cycle.py','install-clean-reconnect.py'):
            text=(source_path(name)).read_text();compile(text,name,'exec')
            for forbidden in ('setpci',"['rmmod'","['modprobe'",'/rescan','/reset','/unbind','mkinitcpio'):
                self.assertNotIn(forbidden,text)
        installer=(source_path('install-clean-reconnect.py')).read_text()
        for token in ("['systemctl','start'","['systemctl','restart'","['systemctl','stop'"):
            self.assertNotIn(token,installer)
        auto=(source_path('auto-clean-cycle.py')).read_text()
        self.assertLess(auto.index("with marker.open('x')"),auto.index('subprocess.run(command'))
        self.assertLess(auto.index('subprocess.run(command'),auto.index('marker.unlink()'))

    def test_rollback_restores_only_owned_files_and_is_idempotent(self):
        i=load('install-clean-reconnect.py')
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);back=p/'backup';back.mkdir()
            auto=p/'auto';helper=p/'helper';owner=p/'owner'
            auto.write_text('new');helper.write_text('helper');owner.write_text('new owner')
            (back/'auto.before').write_text('original');(back/'owner.before').write_text('old owner')
            (back/'expected.json').write_text(json.dumps({'auto':i.sha(auto),'helper':i.sha(helper),'owner_before':i.sha(back/'owner.before'),'owner_after':i.sha(owner)}))
            unrelated=p/'unrelated';unrelated.write_text('keep')
            with patch.multiple(i,BACK=back,AUTO=auto,HELPER=helper,OWNER=owner,OLD=i.sha(back/'auto.before')),patch.object(i.os,'geteuid',return_value=0),patch.object(i.sys,'argv',['installer','--undo']),patch.object(i.subprocess,'run',return_value=SimpleNamespace(stdout='inactive\n')):
                i.main();i.main()
            self.assertEqual(auto.read_text(),'original');self.assertEqual(owner.read_text(),'old owner')
            self.assertFalse(helper.exists());self.assertEqual(unrelated.read_text(),'keep')

    def test_rollback_refuses_changed_file_before_mutation(self):
        i=load('install-clean-reconnect.py')
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);back=p/'backup';back.mkdir();auto=p/'auto';auto.write_text('externally changed')
            (back/'expected.json').write_text(json.dumps({'auto':'different','helper':'h','owner_before':'b','owner_after':'a'}))
            with patch.multiple(i,BACK=back,AUTO=auto,HELPER=p/'helper',OWNER=p/'owner'),patch.object(i.os,'geteuid',return_value=0),patch.object(i.sys,'argv',['installer','--undo']),patch.object(i.subprocess,'run',return_value=SimpleNamespace(stdout='inactive\n')):
                with self.assertRaises(RuntimeError):i.main()
            self.assertEqual(auto.read_text(),'externally changed')

if __name__=='__main__':unittest.main()
