import ast
import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).parents[1]


class ColabNotebookTests(unittest.TestCase):
    def notebook(self):
        return json.loads((ROOT/'notebooks/cloud_whisper_lora.ipynb').read_text())

    def helper(self):
        source=''.join(next(c for c in self.notebook()['cells'] if c.get('id')=='cloud-whisper-01')['source'])
        definition=next(node for node in ast.parse(source).body if isinstance(node,ast.FunctionDef) and node.name=='run_step')
        namespace={'subprocess':subprocess}
        exec(compile(ast.Module(body=[definition],type_ignores=[]),'<trusted-notebook-helper>','exec'),namespace)
        return namespace['run_step']

    def test_all_code_cells_parse_and_are_unexecuted_in_repository(self):
        for cell in self.notebook()['cells']:
            if cell['cell_type']=='code':
                ast.parse(''.join(cell['source']))
                self.assertIsNone(cell['execution_count'])
                self.assertEqual(cell['outputs'],[])

    def test_expected_failure_keeps_real_diagnostic_output(self):
        output=io.StringIO()
        with contextlib.redirect_stdout(output):
            result=self.helper()([sys.executable,'-c',"import sys; print('structured diagnostic'); print('stderr detail',file=sys.stderr); sys.exit(1)"],require_success=False)
        self.assertEqual(result.returncode,1)
        self.assertIn('structured diagnostic',result.stdout)
        self.assertIn('stderr detail',result.stdout)
        self.assertIn('structured diagnostic',output.getvalue())
        with contextlib.redirect_stdout(io.StringIO()),self.assertRaisesRegex(RuntimeError,'exit 1'):
            self.helper()([sys.executable,'-c','raise SystemExit(1)'])

    def test_missing_manifest_cli_lists_inputs_without_starting_training(self):
        with tempfile.TemporaryDirectory() as folder:
            result=subprocess.run([sys.executable,str(ROOT/'scripts/cloud_training_data.py'),'--root',folder],cwd=ROOT,capture_output=True,text=True)
            self.assertEqual(result.returncode,1)
            report=json.loads(result.stdout)
            self.assertEqual(report['reason'],'missing_manifests')
            self.assertEqual(report['missing_files'],['manifests/train.jsonl','manifests/validation.jsonl','manifests/test.jsonl'])
            self.assertFalse(report['training_started'])


if __name__=='__main__':unittest.main()
