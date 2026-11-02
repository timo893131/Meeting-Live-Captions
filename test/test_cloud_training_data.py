import array
import copy
import hashlib
import importlib.util
import json
import tempfile
import unittest
import wave
from pathlib import Path

ROOT=Path(__file__).parents[1]
spec=importlib.util.spec_from_file_location('cloud_training_data',ROOT/'scripts/cloud_training_data.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class CloudDataTests(unittest.TestCase):
    def fixture(self,root):
        config=json.loads((ROOT/'training/cloud-whisper-lora.json').read_text())
        config['data']['root']=str(root)
        (root/'manifests').mkdir()
        originals={}
        for index,split in enumerate(['train','validation','test']):
            file=root/f'{split}.wav'
            values=array.array('h',[index+1]*81600)
            with wave.open(str(file),'wb') as out:
                out.setnchannels(1);out.setsampwidth(2);out.setframerate(16000);out.writeframes(values.tobytes())
            row=dict(id=split,audio_filepath=file.name,text=f'synthetic contract reference {index}',duration=5.1,sha256=module.digest(file),split=split,recording_id=f'recording-{index}',speaker_id=f'speaker-{index}',license_status='approved',allowed_uses=['training'] if split=='train' else ['internal_evaluation'],rights_evidence_ref='synthetic fixture only',training_ready=split=='train',evaluation_ready=split!='train',transcript_status='human_verified',local_reference_verified=True,near_duplicate_review='passed')
            originals[split]=row
        return config,originals

    def write(self,root,rows):
        for split,row in rows.items():(root/f'manifests/{split}.jsonl').write_text(json.dumps(row)+'\n')

    def test_passing_contract_excludes_sealed_text_from_returned_training_data(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);config,rows=self.fixture(root);self.write(root,rows)
            report,training=module.inspect_manifests(config)
            self.assertEqual(report['status'],'passed');self.assertEqual(set(training),{'train','validation'})
            self.assertNotIn(rows['test']['text'],json.dumps(report))
            self.assertFalse(report['training_started'])
            # Evaluation-only permission suffices for test/validation, never for training.
            self.assertFalse(rows['test']['training_ready'])

    def test_pending_rights_labels_and_source_pilot_records_cannot_train(self):
        edits=[lambda r:r.update(training_ready=False),lambda r:r.update(transcript_status='machine_generated'),lambda r:r.update(near_duplicate_review='unrun'),lambda r:r.update(allowed_uses=['internal_evaluation']),lambda r:r.update(local_reference_verified=False),lambda r:r.update(rights_evidence_ref=None),lambda r:r.update(example_only=True)]
        for edit in edits:
            with tempfile.TemporaryDirectory() as folder:
                root=Path(folder);config,rows=self.fixture(root);edit(rows['train']);self.write(root,rows)
                report,_=module.inspect_manifests(config);self.assertEqual(report['status'],'failed')

    def test_cross_split_recordings_speakers_audio_and_text_are_blocked(self):
        for field in ['recording_id','speaker_id','text']:
            with tempfile.TemporaryDirectory() as folder:
                root=Path(folder);config,rows=self.fixture(root);rows['test'][field]=rows['train'][field];self.write(root,rows)
                report,_=module.inspect_manifests(config);self.assertEqual(report['status'],'failed')
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);config,rows=self.fixture(root);rows['test']['audio_filepath']=rows['train']['audio_filepath'];rows['test']['sha256']=rows['train']['sha256'];self.write(root,rows)
            report,_=module.inspect_manifests(config);self.assertEqual(report['status'],'failed')

    def test_hash_paths_unknown_speakers_and_wrong_format_fail(self):
        edits=[lambda r:r.update(sha256='f'*64),lambda r:r.update(audio_filepath='/etc/hosts'),lambda r:r.update(speaker_id=None),lambda r:r.update(duration=99),lambda r:r.update(text='[EN]hello[/EN]')]
        for edit in edits:
            with tempfile.TemporaryDirectory() as folder:
                root=Path(folder);config,rows=self.fixture(root);edit(rows['train']);self.write(root,rows)
                report,_=module.inspect_manifests(config);self.assertEqual(report['status'],'failed')


if __name__=='__main__':unittest.main()
