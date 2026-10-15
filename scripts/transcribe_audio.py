"""Local-only Whisper baseline; never pass reference text as a model prompt."""
import argparse
import hashlib
import importlib.metadata
import json
import platform
import time
from pathlib import Path


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def run(args):
    audio = Path(args.audio).resolve(strict=True)
    model_dir = Path(args.model_dir).resolve(strict=True)
    if not audio.is_file() or not model_dir.is_dir():
        raise ValueError('Expected local audio file and existing local model directory')
    # Hash model assets for reproducibility, without downloading or trusting a model name.
    model_files = {str(p.relative_to(model_dir)): sha256_file(p)
                   for p in sorted(model_dir.rglob('*')) if p.is_file()}
    if 'model.bin' not in model_files:
        raise ValueError('Local CTranslate2 model.bin missing')
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir()  # Refuse to replace previous transcripts and human annotations.
    from faster_whisper import WhisperModel
    started = time.monotonic()
    settings = dict(language='zh', task='transcribe', beam_size=5,
                    temperature=0, vad_filter=False, condition_on_previous_text=True,
                    initial_prompt=None, hotwords=None)
    model = WhisperModel(str(model_dir), device='cpu', compute_type='int8',
                         cpu_threads=args.threads, num_workers=1, local_files_only=True)
    segments, info = model.transcribe(str(audio), **settings)
    rows = []
    for segment in segments:
        rows.append(dict(id=segment.id, start=segment.start, end=segment.end,
                         text=segment.text, avg_logprob=segment.avg_logprob,
                         no_speech_prob=segment.no_speech_prob))
        print(json.dumps({'segments_completed': len(rows), 'audio_seconds': segment.end}), flush=True)
    elapsed = time.monotonic() - started
    report = dict(status='machine_generated', human_verified=False,
                  audio_sha256=sha256_file(audio), model_file_sha256=model_files,
                  settings=settings, runtime=dict(device='cpu', compute_type='int8',
                  threads=args.threads, python=platform.python_version(), platform=platform.platform(),
                  packages={name: importlib.metadata.version(name) for name in
                            ['faster-whisper', 'ctranslate2', 'av', 'tokenizers']}),
                  duration_seconds=info.duration, elapsed_seconds=elapsed,
                  load_and_transcription_rtf=elapsed/info.duration if info.duration else None,
                  language=info.language, segments=rows,
                  reference_used_as_prompt=False, glossary_applied=False,
                  training_run=False, gold_evaluation_run=False)
    (output/'raw-asr.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    (output/'raw-asr.txt').write_text(''.join(row['text'] for row in rows)+'\n')
    print(json.dumps({'output': str(output), 'segments': len(rows),
                      'elapsed_seconds': elapsed, 'human_verified': False}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audio', required=True)
    parser.add_argument('--model-dir', required=True)
    parser.add_argument('--output', required=True, help='New private artifact directory')
    parser.add_argument('--threads', type=int, default=4)
    args = parser.parse_args()
    if not 1 <= args.threads <= 16:
        parser.error('threads must be between 1 and 16')
    run(args)


if __name__ == '__main__':
    main()
