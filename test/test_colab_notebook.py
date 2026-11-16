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

    def run_collect_cell(self,pilot,enable_collection=False):
        calls=[]
        def fake_step(command,**kwargs):
            calls.append((command,kwargs))
            return subprocess.CompletedProcess(command,0,stdout='')
        namespace=dict(WORKFLOW_STAGE='collect',PILOT_ROOT=pilot,REPO=ROOT,sys=sys,run_step=fake_step)
        cell=next(c for c in self.notebook()['cells'] if c.get('id')=='cloud-whisper-06')
        source=''.join(cell['source'])
        if enable_collection:
            self.assertIn('RUN_COLLECTION = False',source)
            source=source.replace('RUN_COLLECTION = False','RUN_COLLECTION = True',1)
        output=io.StringIO()
        with contextlib.redirect_stdout(output):exec(source,namespace)
        return calls,namespace,output.getvalue()

    def test_collect_stage_skips_disabled_fleurs_download_and_points_to_crawler(self):
        # FLEURS cmn_hant_tw matched 0 records (docs/tasks/2026-11-02-taiwan-mandarin-pilot.md),
        # so the default notebook must not retry the download.
        with tempfile.TemporaryDirectory() as folder:
            calls,namespace,output=self.run_collect_cell(Path(folder)/'pilots/taiwan-mandarin-v1')
            self.assertEqual(calls,[])
            self.assertFalse(namespace['RUN_COLLECTION'])
            self.assertIn('crawl_church_sources.ipynb',output)

    def test_collect_stage_runs_bounded_download_to_separate_drive_pilot_root_when_enabled(self):
        with tempfile.TemporaryDirectory() as folder:
            pilot=Path(folder)/'pilots/taiwan-mandarin-v1'
            (pilot/'reports').mkdir(parents=True)
            (pilot/'reports/collection-report.json').write_text('{"status":"synthetic_test_only","audio_downloaded":0}')
            calls,namespace,_=self.run_collect_cell(pilot,enable_collection=True)
            self.assertEqual(len(calls),1)
            self.assertTrue(namespace['RUN_COLLECTION'])
            self.assertIn(str(pilot),calls[0][0])
            self.assertIn('--prepare',calls[0][0])
            self.assertFalse(calls[0][1]['require_success'])

    def test_collect_stage_skips_formal_preflight_and_training_even_if_training_toggle_true(self):
        def forbidden(*args,**kwargs):raise AssertionError('Training command must not execute in collect stage')
        namespace=dict(WORKFLOW_STAGE='collect',run_step=forbidden)
        cell=next(c for c in self.notebook()['cells'] if c.get('id')=='cloud-whisper-08')
        with contextlib.redirect_stdout(io.StringIO()):exec(''.join(cell['source']),namespace)
        self.assertFalse(namespace['DATA_READY'])
        cell=next(c for c in self.notebook()['cells'] if c.get('id')=='cloud-whisper-10')
        source=''.join(cell['source']).replace('RUN_TRAINING = False','RUN_TRAINING = True')
        with contextlib.redirect_stdout(io.StringIO()):exec(source,namespace)

    def test_missing_manifest_cli_lists_inputs_without_starting_training(self):
        with tempfile.TemporaryDirectory() as folder:
            result=subprocess.run([sys.executable,str(ROOT/'scripts/cloud_training_data.py'),'--root',folder],cwd=ROOT,capture_output=True,text=True)
            self.assertEqual(result.returncode,1)
            report=json.loads(result.stdout)
            self.assertEqual(report['reason'],'missing_manifests')
            self.assertEqual(report['missing_files'],['manifests/train.jsonl','manifests/validation.jsonl','manifests/test.jsonl'])
            self.assertFalse(report['training_started'])


if __name__=='__main__':unittest.main()
