// Live speech chunks for server-side Whisper (Cloudflare Workers AI).
// The microphone is cut at pauses into chunks of a few seconds, like the "停頓切段 ≤10 秒" condition that
// was evaluated on the MEET test set; each chunk is recognized on its own.

export const RATE = 16000;
const FRAME = 320;  // 20 ms

/** Energy-based pause detector that groups speech into chunks of at most maxSeconds.
 *  push(samples16k) returns the chunks (Float32Array) completed by these samples; flush() returns the rest. */
export function createSegmenter({maxSeconds = 9, targetSeconds = 5, pauseSeconds = 0.3, endSeconds = 1.5,
  minSpeechSeconds = 0.4, preRollSeconds = 0.2} = {}) {
  const maxFrames = Math.round(maxSeconds * RATE / FRAME), targetFrames = Math.round(targetSeconds * RATE / FRAME);
  const pauseFrames = Math.round(pauseSeconds * RATE / FRAME), endFrames = Math.round(endSeconds * RATE / FRAME);
  const minSpeech = Math.round(minSpeechSeconds * RATE / FRAME), preRoll = Math.round(preRollSeconds * RATE / FRAME);
  let recent = [], pending = new Float32Array(0), frames = [], energies = [], speechFrames = 0, silence = 0, ring = [];

  const join = list => {
    const out = new Float32Array(list.reduce((n, f) => n + f.length, 0));
    let at = 0; for (const f of list) { out.set(f, at); at += f.length; }
    return out;
  };
  const reset = () => { frames = []; energies = []; speechFrames = 0; silence = 0; };
  function cut(end, done) {  // emit frames[0, end), keep the rest as the start of the next chunk
    const head = frames.slice(0, end), speech = energies.slice(0, end).filter(e => e.speech).length;
    const tail = frames.slice(end), tailEnergies = energies.slice(end);
    reset();
    frames = tail; energies = tailEnergies; speechFrames = tailEnergies.filter(e => e.speech).length;
    if (speech >= minSpeech) done.push(join(head));
  }
  function frame(samples, done) {
    let sum = 0; for (const s of samples) sum += s * s;
    const rms = Math.sqrt(sum / samples.length);
    // Background level = the quietest frame of the last 5 seconds (speech always has gaps between syllables).
    recent.push(rms); if (recent.length > 250) recent.shift();
    const speech = rms > Math.max(0.008, Math.min(...recent) * 3);
    if (!frames.length) {
      if (!speech) { ring.push(samples); if (ring.length > preRoll) ring.shift(); return; }
      frames = [...ring]; energies = ring.map(() => ({rms: 0, speech: false})); ring = [];
    }
    frames.push(samples); energies.push({rms, speech});
    if (speech) { speechFrames++; silence = 0; } else silence++;
    const length = frames.length;
    if (silence >= endFrames) {  // end of a sentence, or only noise since the last cut
      cut(length - silence + Math.min(silence, 8), done); frames = []; energies = []; speechFrames = 0; silence = 0;
    } else if (silence >= pauseFrames && length >= targetFrames) {
      cut(length - silence + Math.min(silence, 8), done);
    } else if (length >= maxFrames) {  // no pause long enough: cut at the quietest point of the last 3 seconds
      const from = Math.max(1, length - 150); let best = length - 1;
      for (let i = from; i < length; i++) if (energies[i].rms <= energies[best].rms) best = i;
      cut(best + 1, done);
    }
  }
  return {
    push(samples) {
      const done = [], all = pending.length ? join([pending, samples]) : samples;
      let at = 0;
      for (; at + FRAME <= all.length; at += FRAME) frame(all.slice(at, at + FRAME), done);
      pending = all.slice(at);
      return done;
    },
    flush() {
      const done = [];
      if (frames.length && speechFrames >= minSpeech) done.push(join(frames));
      reset(); pending = new Float32Array(0); ring = []; recent = [];
      return done;
    }
  };
}

/** Averaging resampler to 16 kHz (input rates are 44.1/48 kHz microphones). */
export function createResampler(inputRate) {
  const step = inputRate / RATE; let position = 0, carry = new Float32Array(0);
  return samples => {
    const all = carry.length ? new Float32Array([...carry, ...samples]) : samples;
    const out = [];
    while (position + step <= all.length) {
      const start = Math.floor(position), end = Math.floor(position + step);
      let sum = 0; for (let i = start; i < end; i++) sum += all[i];
      out.push(end > start ? sum / (end - start) : all[start]);
      position += step;
    }
    const keep = Math.floor(position);
    carry = all.slice(keep); position -= keep;
    return Float32Array.from(out);
  };
}

export function encodeWav(samples) {
  const buffer = new ArrayBuffer(44 + samples.length * 2), view = new DataView(buffer);
  const text = (at, value) => { for (let i = 0; i < value.length; i++) view.setUint8(at + i, value.charCodeAt(i)); };
  text(0, 'RIFF'); view.setUint32(4, 36 + samples.length * 2, true); text(8, 'WAVE'); text(12, 'fmt ');
  view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
  view.setUint32(24, RATE, true); view.setUint32(28, RATE * 2, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true);
  text(36, 'data'); view.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) view.setInt16(44 + i * 2, Math.max(-1, Math.min(1, samples[i])) * 32767, true);
  return buffer;
}

/** Delivers results in chunk order even when requests finish out of order. */
export function createOrderedQueue(deliver) {
  let next = 0, issued = 0; const ready = new Map();
  return {
    reserve: () => issued++,
    settle(seq, value) {
      ready.set(seq, value);
      while (ready.has(next)) { const item = ready.get(next); ready.delete(next); next++; deliver(item); }
    },
    get waiting() { return issued - next; }
  };
}

const WORKLET = `registerProcessor('caption-tap', class extends AudioWorkletProcessor {
  constructor() { super(); this.buffer = new Float32Array(4096); this.used = 0; }
  process(inputs) {
    const input = inputs[0] && inputs[0][0];
    if (input) {
      if (this.used + input.length > this.buffer.length) { this.port.postMessage(this.buffer.slice(0, this.used)); this.used = 0; }
      this.buffer.set(input, this.used); this.used += input.length;
    }
    return true;
  }
});`;

/** Microphone → 16 kHz chunks. onChunk(Float32Array) is called for every finished chunk. */
export async function startMicrophoneChunks(onChunk, options = {}) {
  const stream = await navigator.mediaDevices.getUserMedia({audio: {channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true}});
  const context = new AudioContext();
  const url = URL.createObjectURL(new Blob([WORKLET], {type: 'text/javascript'}));
  try { await context.audioWorklet.addModule(url); } finally { URL.revokeObjectURL(url); }
  const source = context.createMediaStreamSource(stream), tap = new AudioWorkletNode(context, 'caption-tap');
  const resample = createResampler(context.sampleRate), segmenter = createSegmenter(options);
  let stopped = false;
  tap.port.onmessage = event => { if (!stopped) for (const chunk of segmenter.push(resample(event.data))) onChunk(chunk); };
  source.connect(tap);  // not connected to the speakers
  await context.resume();
  return {
    stream,
    stop() {
      if (stopped) return; stopped = true;
      for (const chunk of segmenter.flush()) onChunk(chunk);
      tap.port.onmessage = null; source.disconnect(); stream.getTracks().forEach(track => track.stop()); context.close().catch(() => {});
    }
  };
}
