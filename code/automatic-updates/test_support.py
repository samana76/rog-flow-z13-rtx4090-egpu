#!/usr/bin/python3
import ast
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE/'payload'))
import registry
import update
BASELINE=json.loads((HERE/'payload/registry.json').read_text())

class Checks(unittest.TestCase):
    def test_baseline(self):
        self.assertEqual(set(registry.validate(BASELINE)),{'7.2.4-arch1-2','7.2.5-1-cachyos'})
    def test_incomplete(self):
        d=copy.deepcopy(BASELINE);del d['kernels']['7.2.4-arch1-2']['modules']['nvidia-drm.ko']
        with self.assertRaises(RuntimeError):registry.validate(d)
    def test_wrong_kernel(self):
        d=copy.deepcopy(BASELINE);d['kernels']['7.2.4-arch1-2']['modules']['nvidia.ko']['vermagic']='different SMP'
        with self.assertRaises(RuntimeError):registry.validate(d)
    def test_wrong_source(self):
        d=copy.deepcopy(BASELINE);d['kernels']['7.2.4-arch1-2']['modules']['nvidia.ko']['srcversion']='new-source'
        with self.assertRaises(RuntimeError):registry.validate(d)
    def test_path_escape(self):
        d=copy.deepcopy(BASELINE);d['kernels']['7.2.4-arch1-2']['payload']='/tmp/untrusted'
        with self.assertRaises(RuntimeError):registry.validate(d)
    def test_same_version_new_build(self):
        d=copy.deepcopy(BASELINE);r=d['kernels'].pop('7.2.4-arch1-2');k='7.2.6-arch2-1';r['payload']=r['display_payload']='/opt/gpd-egpu/615.71.09/'+k
        r['package_version']='7.2.6.arch2-1'
        for m in r['modules'].values():m['vermagic']=k+' SMP preempt mod_unload'
        d['kernels'][k]=r;self.assertIn(k,registry.validate(d))
    def test_untrusted_registry(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'registry.json';p.write_text(json.dumps(BASELINE))
            with self.assertRaises(RuntimeError):registry.read(p)
    def test_supported_invocations(self):
        for argv in [['pacman','-Syu'],['pacman','--color','always','-Syu','--noconfirm'],['pacman','--sync','--sysupgrade','--refresh']]:update.check_invocation(argv)
    def test_unsupported_invocations(self):
        for args in [['-U','a.pkg'],['-S','linux'],['-Syu','--config','alternate'],['-Syu','--ignore','linux'],['-R','linux'],['-Syu','core/linux']]:
            with self.assertRaises(RuntimeError):update.check_invocation(['pacman',*args])
    def test_plan(self):
        self.assertEqual(update.parse_plan('linux|7.2.6.arch2-1|https://example/pkg\n')['linux']['version'],'7.2.6.arch2-1')
        with self.assertRaises(RuntimeError):update.parse_plan('warning: package database missing')
    def test_duplicate_plan(self):
        with self.assertRaises(RuntimeError):update.parse_plan('linux|1|https://x\nlinux|2|https://y')
    def test_duplicate_boot_entry(self):
        with self.assertRaises(RuntimeError):update.entries('//linux\n//linux\n')
    def test_both_working_kernels_blocked(self):
        versions={'nvidia-utils':'615.71.09-1','linux':'7.2.4.arch1-2','linux-cachyos':'7.2.5-1'}
        with patch.object(update,'installed',side_effect=versions.__getitem__):
            with self.assertRaises(RuntimeError):update.policy_check({'linux':{},'linux-cachyos':{}},BASELINE['kernels'])
    def test_unknown_driver_blocked(self):
        with patch.object(update,'installed',return_value='615.71.09-1'):
            with self.assertRaises(RuntimeError):update.policy_check({'nvidia-utils':{'version':'616.0-1'}},BASELINE['kernels'])
    def test_no_forced_module_loads(self):
        tree=ast.parse((HERE/'payload/update.py').read_text())
        strings=[n.value for n in ast.walk(tree) if isinstance(n,ast.Constant) and isinstance(n.value,str)]
        self.assertFalse(set(strings)&{'insmod','modprobe','rmmod','reboot','setpci','/usr/bin/insmod'})
    def test_precise_driver_module_detection(self):
        import re
        pattern=r'(?:^|/)(?:nvidia(?:[-_](?:drm|modeset|uvm|peermem))?|nouveau)\.ko(?:\.|\s|$)'
        for x in ['usr/lib/firmware/nvidia/gsp.bin','usr/lib/modules/kernel/nvidia-wmi-ec-backlight.ko.zst','etc/udev/rules.d/99-usb4-tunnel-ports-awake.rules']:
            self.assertIsNone(re.search(pattern,x,re.M))
        for x in ['usr/lib/modules/nvidia.ko.zst','usr/lib/modules/nvidia_drm.ko','usr/lib/modules/nouveau.ko.xz']:
            self.assertIsNotNone(re.search(pattern,x,re.M))
    def test_generated_helpers_preserve_safety(self):
        changes=json.loads((HERE/'payload/changes.json').read_text())
        for r in changes:ast.parse((HERE/'payload'/r['source']).read_text())
        loader=(HERE/'payload/loader.py').read_text()
        for fragment in ['NVreg_DynamicPowerManagement=0','NVreg_EnableGpuFirmware=0','m.validate_gate','boot_check(t,m)','t.check_errors()','no recovery']:
            self.assertIn(fragment,loader)
        self.assertIn('restore_lact',(HERE/'payload/restart-clean-cycle.py').read_text())
    def test_hooks_precedes_package_changes(self):
        s=(HERE/'payload/00-gpd-egpu-update-pre.hook').read_text()
        self.assertIn('When = PreTransaction',s);self.assertIn('AbortOnFail',s);self.assertIn('NeedsTargets',s)

    def test_dynamic_required_package(self):
        tree=ast.parse((HERE/'payload/loader.py').read_text())
        fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='required_packages')
        ns={'REGISTRY':{'7.2.6-arch2-1':{'package':'linux','package_version':'7.2.6.arch2-1'}}}
        exec(compile(ast.Module(body=[fn],type_ignores=[]),'fixture','exec'),ns)
        self.assertEqual(ns['required_packages']('7.2.6-arch2-1'),[('nvidia-utils','615.71.09-1'),('linux','7.2.6.arch2-1')])
        with self.assertRaises(RuntimeError):ns['required_packages']('unknown')
    def test_startup_failure_still_blocks_retry(self):
        tree=ast.parse((HERE/'payload/loader.py').read_text())
        fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='startup_action')
        ns={};exec(compile(ast.Module(body=[fn],type_ignores=[]),'fixture','exec'),ns)
        with self.assertRaises(RuntimeError):ns['startup_action']({'stage':'failed'},False,False)
    def test_boot_failure_prevents_post_registry_commit(self):
        with tempfile.TemporaryDirectory() as t:
            state=Path(t)
            (state/'pending.json').write_text(json.dumps({'pacman_pid':123,'stage':'prepared','plan':{}}))
            with patch.object(update,'STATE',state),patch.object(update,'pacman_parent',return_value=123),patch.object(update,'baseline_integrity'),patch.object(update,'boot_check',side_effect=RuntimeError('bad checksum')),patch.object(update,'atomic') as write:
                with self.assertRaises(RuntimeError):update.post()
                write.assert_not_called()
                self.assertTrue((state/'pending.json').exists())
    def test_package_mismatch_prevents_post_registry_commit(self):
        with tempfile.TemporaryDirectory() as t:
            state=Path(t)
            (state/'pending.json').write_text(json.dumps({'pacman_pid':123,'stage':'prepared','plan':{'linux':{'version':'new'}}}))
            with patch.object(update,'STATE',state),patch.object(update,'pacman_parent',return_value=123),patch.object(update,'baseline_integrity'),patch.object(update,'installed',return_value='different'),patch.object(update,'atomic') as write:
                with self.assertRaises(RuntimeError):update.post()
                write.assert_not_called()
    def test_header_descriptor(self):
        d=update.parse_desc('%NAME%\nlinux-headers\n\n%VERSION%\n7.2.6.arch2-1\n\n%PGPSIG%\nYWJj\n')
        self.assertEqual(d['NAME'],'linux-headers');self.assertEqual(d['PGPSIG'],'YWJj')
    def test_network_only_pre_hook(self):
        self.assertIn('NetworkAccess = allowed',(HERE/'payload/00-gpd-egpu-update-pre.hook').read_text())
        self.assertNotIn('NetworkAccess = allowed',(HERE/'payload/zz-gpd-egpu-update-post.hook').read_text())

    def test_blocked_driver_payload_is_accepted(self):
        update.validate_dependency_report('install /usr/bin/false\n')
    def test_harmless_dependencies_are_accepted(self):
        update.validate_dependency_report('insmod /lib/modules/test/kernel/drm_gpuvm.ko.zst\ninstall /usr/bin/false\n')
    def test_actual_driver_insertion_is_blocked(self):
        with self.assertRaises(RuntimeError):
            update.validate_dependency_report('insmod /lib/modules/test/nvidia.ko.zst\ninstall /usr/bin/false\n')
    def test_missing_install_block_is_blocked(self):
        with self.assertRaises(RuntimeError):update.validate_dependency_report('')
    def test_overridden_install_block_is_blocked(self):
        with self.assertRaises(RuntimeError):update.validate_dependency_report('install /usr/bin/true\n')
    def test_config_priority(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            for relative,text in [('etc/modprobe.d/same.conf','install nvidia /usr/bin/false'),('usr/lib/modprobe.d/same.conf','install nvidia /usr/bin/true')]:
                p=root/relative;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
            self.assertEqual(update.image_config_files(root)['same.conf'],'install nvidia /usr/bin/false')
    def test_forced_load_blocked(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);(root/'config').write_text('MODULES=(nvidia_drm)\n')
            with self.assertRaises(RuntimeError):update.check_embedded_forced_loads(root)
    def test_empty_modules_accepted(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);(root/'config').write_text('MODULES=()\n')
            update.check_embedded_forced_loads(root)
    def test_config_escape_blocked(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);p=root/'etc/modprobe.d';p.mkdir(parents=True);(p/'bad.conf').symlink_to('/etc/passwd')
            with self.assertRaises(RuntimeError):update.image_config_files(root)
    def test_real_kmod_query_is_nonexecuting(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);c=root/'conf';c.mkdir()
            (c/'zzz-block.conf').write_text('blacklist nvidia\ninstall nvidia /usr/bin/false\n')
            r=subprocess.run(['/usr/bin/modprobe','--config',str(c),'--dirname',str(root),'--set-version','fixture','--show-depends','nvidia'],capture_output=True,text=True)
            self.assertEqual(r.returncode,0,r.stderr)
            update.validate_dependency_report(r.stdout)

if __name__=='__main__':unittest.main()
