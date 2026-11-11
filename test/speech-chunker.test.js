import test from 'node:test';
import assert from 'node:assert/strict';
import {RATE, createSegmenter, createResampler, encodeWav, createOrderedQueue} from '../public/speech-chunker.js';

// Speech-like signal: 0.2 s syllables with short quiet gaps between them.
const tone = seconds => Float32Array.from({length: Math.round(seconds * RATE)}, (_, i) => (i % 4000 < 3200 ? 0.2 : 0.004) * Math.sin(i / 5));
const quiet = seconds => new Float32Array(Math.round(seconds * RATE)).fill(0.0005);
const join = (...parts) => { const out = new Float32Array(parts.reduce((n, p) => n + p.length, 0)); let at = 0; for (const p of parts) { out.set(p, at); at += p.length; } return out; };
const run = (audio, options) => { const s = createSegmenter(options), out = []; for (let i = 0; i < audio.length; i += 2048) out.push(...s.push(audio.slice(i, i + 2048))); return [out, s]; };

test('short pauses inside a phrase do not cut before the target length; a pause after it does', () => {
  const [chunks] = run(join(quiet(1), tone(2), quiet(0.35), tone(2), quiet(0.35), tone(2), quiet(2)));
  assert.equal(chunks.length, 1);
  const seconds = chunks[0].length / RATE;
  assert.ok(seconds > 6 && seconds < 7.2, `one chunk with all three phrases, got ${seconds}`);
});

test('continuous speech is cut at the maximum length; nothing is lost', () => {
  const speech = tone(20);
  const [chunks, segmenter] = run(join(quiet(0.5), speech, quiet(0.1)));
  chunks.push(...segmenter.flush());
  assert.ok(chunks.every(c => c.length / RATE <= 9.01));
  assert.ok(Math.abs(chunks.reduce((n, c) => n + c.length, 0) / RATE - 20.1) < 0.4);
});

test('a long silence ends the chunk early and noise alone is never sent', () => {
  const [chunks] = run(join(tone(1.5), quiet(2), quiet(5)));
  assert.equal(chunks.length, 1);
  assert.ok(chunks[0].length / RATE < 2);
  const [none] = run(quiet(10));
  assert.equal(none.length, 0);
});

test('resampler and WAV encoder produce 16 kHz mono PCM', () => {
  const resample = createResampler(48000);
  const out = [resample(new Float32Array(48000).fill(0.5)), resample(new Float32Array(48000).fill(0.5))];
  assert.equal(out[0].length + out[1].length, 32000);
  const wav = new DataView(encodeWav(new Float32Array([0, 1, -1])));
  assert.equal(wav.getUint32(24, true), 16000);
  assert.equal(wav.byteLength, 44 + 6);
  assert.deepEqual([wav.getInt16(44, true), wav.getInt16(46, true), wav.getInt16(48, true)], [0, 32767, -32767]);
});

test('results are delivered in chunk order', () => {
  const seen = [], queue = createOrderedQueue(value => seen.push(value));
  const [a, b, c] = [queue.reserve(), queue.reserve(), queue.reserve()];
  queue.settle(c, 'c'); queue.settle(a, 'a');
  assert.deepEqual(seen, ['a']); assert.equal(queue.waiting, 2);
  queue.settle(b, 'b');
  assert.deepEqual(seen, ['a', 'b', 'c']);
});
