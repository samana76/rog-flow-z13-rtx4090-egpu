"""Exercise only the package-query function; no GPU/system writes."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SOURCE=Path(__file__).resolve().parents[1]/'code/reference-system/opt/gpd-egpu/615.71.09/loader.py'
class PackageQueryTests(unittest.TestCase):
    def setUp(self):
        tree=ast.parse(SOURCE.read_text())
        function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='query_package')
        ns={};exec(compile(ast.Module(body=[function],type_ignores=[]),str(SOURCE),'exec'),ns)
        self.query=ns['query_package'];self.logs=[];self.trial=SimpleNamespace(log=self.logs.append)
    def run_query(self,out,err='',code=0):
        with patch('subprocess.run',return_value=SimpleNamespace(stdout=out,stderr=err,returncode=code)) as run:
            result=self.query(self.trial,'nvidia-utils')
            self.assertEqual(run.call_args.args[0],['pacman','-Q','nvidia-utils'])
            self.assertTrue(run.call_args.kwargs['capture_output'])
            self.assertEqual(run.call_args.kwargs['timeout'],30)
            return result
    def test_clean_version(self):
        self.assertEqual(self.run_query('nvidia-utils 615.71.09-1\n'),'nvidia-utils 615.71.09-1')
    def test_warning_does_not_contaminate_version(self):
        warning="warning: database file for 'openai-chatgpt' does not exist"
        self.assertEqual(self.run_query('nvidia-utils 615.71.09-1\n',warning),'nvidia-utils 615.71.09-1')
        self.assertTrue(any(warning in s for s in self.logs))
    def test_command_failure_even_with_expected_stdout(self):
        with self.assertRaises(RuntimeError):self.run_query('nvidia-utils 615.71.09-1','error',1)
    def test_wrong_empty_extra_and_other_package_rejected_by_exact_comparison(self):
        for out in ['nvidia-utils 999-1','','nvidia-utils 615.71.09-1\nextra','other 615.71.09-1']:
            with self.subTest(out=out):self.assertNotEqual(self.run_query(out),'nvidia-utils 615.71.09-1')
    def test_identity_retains_exact_version_guard(self):
        tree=ast.parse(SOURCE.read_text());identity=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='identity')
        comparisons=[n for n in ast.walk(identity) if isinstance(n,ast.Compare) and isinstance(n.left,ast.Call) and isinstance(n.left.func,ast.Name) and n.left.func.id=='query_package']
        self.assertEqual(len(comparisons),1)
        self.assertIsInstance(comparisons[0].ops[0],ast.Eq)
        self.assertEqual(ast.unparse(comparisons[0].comparators[0]),"name + ' ' + version")
if __name__=='__main__':unittest.main()
