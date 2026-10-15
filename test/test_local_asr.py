import argparse
import importlib.util
import json
import sys
import tempfile
import types
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('local_asr', Path(__file__).parents[1]/'scripts/transcribe_audio.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class LocalASRTests(unittest.TestCase):
    def test_synthetic_engine_records_raw_results_without_reference_prompt(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            audio = root/'audio.bin'
            audio.write_bytes(b'synthetic audio placeholder, not real ASR')
            model_dir = root/'model'
            model_dir.mkdir()
            (model_dir/'model.bin').write_bytes(b'synthetic model placeholder')
            calls = {}

            class FakeModel:
                def __init__(self, model, **kwargs):
                    calls['model'] = kwargs

                def transcribe(self, file, **kwargs):
                    calls['decode'] = kwargs
                    segment = types.SimpleNamespace(id=0, start=0.0, end=1.0,
                                                    text='測試機器稿', avg_logprob=-0.2,
                                                    no_speech_prob=0.01)
                    return iter([segment]), types.SimpleNamespace(duration=1.0, language='zh')

            args = argparse.Namespace(audio=str(audio), model_dir=str(model_dir), output=str(root/'result'), threads=2)
            fake = types.SimpleNamespace(WhisperModel=FakeModel)
            with patch.dict(sys.modules, {'faster_whisper': fake}), patch.object(module.importlib.metadata, 'version', return_value='synthetic-test-version'):
                module.run(args)
            report = json.loads((root/'result/raw-asr.json').read_text())
            self.assertTrue(calls['model']['local_files_only'])
            self.assertIsNone(calls['decode']['initial_prompt'])
            self.assertIsNone(calls['decode']['hotwords'])
            self.assertFalse(report['human_verified'])
            self.assertFalse(report['gold_evaluation_run'])
            self.assertFalse(report['glossary_applied'])
            self.assertEqual(report['segments'][0]['text'], '測試機器稿')
            self.assertEqual(report['audio_sha256'], module.sha256_file(audio))
            with self.assertRaises(FileExistsError):
                module.run(args)

    def test_installed_decoder_accepts_audio_with_pinned_av(self):
        from faster_whisper.audio import decode_audio
        with tempfile.TemporaryDirectory() as root:
            file = Path(root)/'sample.wav'
            with wave.open(str(file), 'wb') as out:
                out.setnchannels(1)
                out.setsampwidth(2)
                out.setframerate(16000)
                out.writeframes(b'\x00\x00' * 16000)
            samples = decode_audio(str(file))
            self.assertEqual(len(samples), 16000)
            self.assertTrue((samples == 0).all())

    def test_missing_local_model_is_not_automatically_downloaded(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            (root/'audio.bin').write_bytes(b'test')
            (root/'model').mkdir()
            args = argparse.Namespace(audio=str(root/'audio.bin'), model_dir=str(root/'model'), output=str(root/'result'), threads=2)
            with self.assertRaisesRegex(ValueError, 'model.bin missing'):
                module.run(args)
            self.assertFalse((root/'result').exists())


if __name__ == '__main__':
    unittest.main()
