#!/usr/bin/env node
// Context-correction experiment driver (evaluation only; the website is unchanged).
//
// Input: a folder from `context_experiment.py prepare` (NN.chunks.json + NN.chunks.s16: the website's live chunks,
// "pause cut, ≤10 s", as 16 kHz mono s16le, back to back). For every pair it produces up to four conditions:
//   base        Workers AI Whisper per chunk (as the website), then the website's corrections
//   prompt      the same, with initial_prompt = recent church terms + previous caption (A)
//   llm         base + language-model fixes (B), per model
//   prompt_llm  prompt + language-model fixes (A+B), per model
// "Website corrections" = cleanTranscript (Worker: silence/hallucination filter, Simplified → Traditional) +
// glossary (empty starting box) + same-sound church terms, i.e. exactly what a caption shows today.
//
// Every request is saved at once (NN.<stream>.partial.json); a run stops at --neuron-cap (estimated neurons of this
// run) or when Cloudflare reports the daily allocation is used up (exit 3), and continues with --reuse <run>.
// Scoring: scripts/context_experiment.py score.
//
// node scripts/context-experiment.mjs --prepared <dir> --output <new run> [--reuse <run>]... [--base-raw <evaluate_meet run>]
//   [--conditions base,prompt,llm,prompt_llm] [--models @cf/a,@cf/b] [--prices prices.json] [--neuron-cap 6000] [--only 01,05]
// env: CF_ACCOUNT_ID, CF_API_TOKEN (CF_API_BASE only for tests)
import {existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync} from 'node:fs';
import {join} from 'node:path';
import {parseArgs} from 'node:util';
import {cleanTranscript} from '../cloudflare/transcript.js';
import {correctText, parseGlossary, startingGlossary} from '../glossary.js';
import * as pinyinData from '../public/pinyin-zh.js';
import {DEFAULT_TERMS, loadPinyin, phoneticCorrect} from '../public/phonetic.js';
import {applyEdits, correctionMessages, findCandidates, parseEdits, soundIndex, whisperPrompt} from '../public/context-correct.js';

export const WHISPER = '@cf/openai/whisper-large-v3-turbo';
export const WHISPER_NEURONS_PER_MINUTE = 46.63;   // same figure as evaluate_meet.py
const RATE = 16000;
const CONTEXT_CAPTIONS = 2;

export class Paused extends Error {}

export const slug = model => model.replace(/^@cf\//, '').replace(/[^A-Za-z0-9]+/g, '-');

export function siteCaption(whisperResult, pairs = parseGlossary(startingGlossary.map(p => p.join('=')).join('\n'))) {
  const cleaned = cleanTranscript(whisperResult, 'zh');
  return {cleaned, site: phoneticCorrect(correctText(cleaned, pairs), DEFAULT_TERMS).text};
}

function wav(samples) {
  const out = Buffer.alloc(44 + samples.length);
  out.write('RIFF', 0); out.writeUInt32LE(36 + samples.length, 4); out.write('WAVE', 8); out.write('fmt ', 12);
  out.writeUInt32LE(16, 16); out.writeUInt16LE(1, 20); out.writeUInt16LE(1, 22); out.writeUInt32LE(RATE, 24);
  out.writeUInt32LE(RATE * 2, 28); out.writeUInt16LE(2, 32); out.writeUInt16LE(16, 34); out.write('data', 36);
  out.writeUInt32LE(samples.length, 40); samples.copy(out, 44);
  return out;
}

/** POST to Workers AI with retries. Quota → Paused; auth/bad request → Error (stop). */
export async function runModel(model, body, {account, token, base = 'https://api.cloudflare.com/client/v4', attempts = 6, fetchImpl = fetch, sleep = ms => new Promise(r => setTimeout(r, ms))}) {
  let last = '';
  for (let attempt = 0; attempt < attempts; attempt++) {
    try {
      const response = await fetchImpl(`${base}/accounts/${account}/ai/run/${model}`, {
        method: 'POST', headers: {Authorization: `Bearer ${token}`, 'Content-Type': 'application/json'},
        body: JSON.stringify(body), signal: AbortSignal.timeout(120_000)});
      const data = await response.json().catch(() => ({}));
      if (response.ok && data.success !== false) return data.result ?? {};
      const errors = data.errors || [], codes = new Set(errors.map(e => e.code));
      const detail = errors.map(e => `${e.code} ${e.message}`).join('; ') || `HTTP ${response.status}`;
      if (codes.has(3036)) throw new Paused(`Cloudflare：今天的免費額度已用完（${detail}）`);
      if (response.status === 401 || response.status === 403) throw new Error(`Workers AI 拒絕請求（${detail}）：請確認 CF_ACCOUNT_ID／CF_API_TOKEN`);
      if (response.status !== 429 && response.status < 500) throw new Error(`Workers AI 錯誤（${model}：${detail}）`);
      last = detail;
    } catch (error) {
      if (error instanceof Paused || /Workers AI (拒絕|錯誤)/.test(error.message)) throw error;
      last = error.message;
    }
    await sleep(Math.min(60_000, 1000 * 2 ** attempt));
  }
  throw new Error(`Workers AI 重試 ${attempts} 次仍失敗：${last}`);
}

/** Reply text and token usage from either Workers AI response shape (response/usage or OpenAI-style choices). */
export function replyOf(result) {
  const reply = result?.response ?? result?.choices?.[0]?.message?.content ?? '';
  const usage = result?.usage || {};
  return {reply: typeof reply === 'string' ? reply : JSON.stringify(reply),
    tokensIn: usage.prompt_tokens ?? null, tokensOut: usage.completion_tokens ?? null};
}

export async function runExperiment(options) {
  const {prepared, output, reuse = [], baseRaw = null, conditions = ['base', 'prompt', 'llm', 'prompt_llm'], models = [],
    prices = {}, neuronCap = 6000, only = null, account, token, base, fetchImpl, sleep, log = console.log} = options;
  const pairs = readdirSync(prepared).filter(f => f.endsWith('.chunks.json')).map(f => f.replace('.chunks.json', ''))
    .filter(p => !only || only.includes(p)).sort();
  if (!pairs.length) throw new Error(`${prepared} 沒有 NN.chunks.json`);
  const needLlm = conditions.some(c => c.endsWith('llm'));
  if (needLlm && !models.length) throw new Error('llm 條件需要 --models');
  for (const model of needLlm ? models : []) {
    const p = prices[model];
    if (!p || !(p.input_neurons_per_m >= 0) || !(p.output_neurons_per_m >= 0)) throw new Error(`沒有 ${model} 的價格（--prices），無法控制 neurons 用量`);
  }
  mkdirSync(output, {recursive: true});
  loadPinyin(pinyinData);
  const index = soundIndex(pinyinData), terms = DEFAULT_TERMS;
  const usage = {neurons: 0, whisperMinutes: 0, llmTokensIn: 0, llmTokensOut: 0, requests: 0};
  const api = {account, token, base, fetchImpl, sleep};
  const charge = neurons => { usage.neurons += neurons; };
  const guardCap = () => { if (usage.neurons >= neuronCap) throw new Paused(`已達本次上限約 ${neuronCap} neurons（--neuron-cap）`); };

  const load = name => {
    for (const folder of [output, ...reuse]) {
      const path = join(folder, name);
      if (existsSync(path)) return JSON.parse(readFileSync(path, 'utf8'));
    }
    return null;
  };
  const save = (name, value) => writeFileSync(join(output, name), JSON.stringify(value, null, 1));

  async function whisperStream(pair, meta, audio, withPrompt) {
    const name = `${pair}.whisper_${withPrompt ? 'prompt' : 'base'}`;
    const done = load(`${name}.json`);
    if (done?.complete) { save(`${name}.json`, done); return done.records; }
    const records = load(`${name}.partial.json`) || [];
    if (!withPrompt && baseRaw && records.length === 0) {
      const cached = JSON.parse(readFileSync(join(baseRaw, `${pair}.workers_ai_live_vad_10s.json`), 'utf8')).raw;
      if (cached.length !== meta.total_chunks) throw new Error(`${pair}：--base-raw 有 ${cached.length} 段，切段結果是 ${meta.total_chunks} 段，不能沿用`);
      for (const chunk of meta.chunks) {
        const raw = cached[chunk.full_index];
        records.push({i: records.length, raw, ...siteCaption({text: raw}), seconds: chunk.seconds, latency: null, reused: true});
      }
    }
    let offset = meta.chunks.slice(0, records.length).reduce((sum, c) => sum + c.samples, 0) * 2;
    for (const chunk of meta.chunks.slice(records.length)) {
      guardCap();
      const prompt = withPrompt ? whisperPrompt(records.map(r => r.site), terms) : '';
      const body = {audio: wav(audio.subarray(offset, offset + chunk.samples * 2)).toString('base64'), task: 'transcribe',
        language: 'zh', vad_filter: false, condition_on_previous_text: false, beam_size: 5, ...(prompt ? {initial_prompt: prompt} : {})};
      const began = performance.now();
      const result = await runModel(WHISPER, body, api);
      const latency = (performance.now() - began) / 1000;
      const neurons = chunk.seconds / 60 * WHISPER_NEURONS_PER_MINUTE;
      charge(neurons); usage.whisperMinutes += chunk.seconds / 60; usage.requests++;
      records.push({i: records.length, raw: (result.text || '').trim(), ...siteCaption(result), prompt: prompt || null,
        seconds: chunk.seconds, latency: Math.round(latency * 1000) / 1000, neurons: Math.round(neurons * 100) / 100});
      offset += chunk.samples * 2;
      save(`${name}.partial.json`, records);
    }
    save(`${name}.json`, {complete: true, model: WHISPER, records});
    return records;
  }

  async function llmStream(pair, source, sourceName, model) {
    const name = `${pair}.llm_${sourceName}__${slug(model)}`;
    const done = load(`${name}.json`);
    if (done?.complete) { save(`${name}.json`, done); return; }
    const records = load(`${name}.partial.json`) || [];
    const price = prices[model];
    for (const segment of source.slice(records.length)) {
      const candidates = findCandidates(segment.site, terms, index);
      const record = {i: records.length, site: segment.site, candidates, called: false, final: segment.site, final_unguarded: segment.site};
      if (candidates.length) {
        guardCap();
        const context = records.slice(-CONTEXT_CAPTIONS).map(r => r.final);
        const messages = correctionMessages({context, text: segment.site, candidates, suffix: /qwen3/i.test(model) ? '/no_think' : ''});
        const began = performance.now();
        const result = await runModel(model, {messages, temperature: 0, max_tokens: 256}, api);
        const latency = (performance.now() - began) / 1000;
        const {reply, tokensIn, tokensOut} = replyOf(result);
        // Without reported usage, count characters as tokens (an over-estimate for Chinese) and mark it.
        const estimated = tokensIn == null || tokensOut == null;
        const tin = tokensIn ?? messages.reduce((n, m) => n + m.content.length, 0), tout = tokensOut ?? reply.length;
        const neurons = (tin * price.input_neurons_per_m + tout * price.output_neurons_per_m) / 1e6;
        charge(neurons); usage.llmTokensIn += tin; usage.llmTokensOut += tout; usage.requests++;
        const edits = parseEdits(reply);
        const guarded = applyEdits(segment.site, edits || [], {terms, index, guarded: true});
        const loose = applyEdits(segment.site, edits || [], {terms, index, guarded: false});
        Object.assign(record, {called: true, reply, parse_error: edits === null, edits: edits || [], accepted: guarded.accepted,
          rejected: guarded.rejected, final: guarded.text, final_unguarded: loose.text, tokens_in: tin, tokens_out: tout,
          tokens_estimated: estimated, latency: Math.round(latency * 1000) / 1000, neurons: Math.round(neurons * 100) / 100});
      }
      records.push(record);
      save(`${name}.partial.json`, records);
    }
    save(`${name}.json`, {complete: true, model, source: sourceName, price, records});
  }

  try {
    for (const pair of pairs) {
      const meta = JSON.parse(readFileSync(join(prepared, `${pair}.chunks.json`), 'utf8'));
      const audio = readFileSync(join(prepared, `${pair}.chunks.s16`));
      log(`[${pair}] ${meta.chunks.length} 段、${(meta.duration_seconds / 60).toFixed(1)} 分鐘`);
      const sources = {};
      if (conditions.includes('base') || conditions.includes('llm')) sources.base = await whisperStream(pair, meta, audio, false);
      if (conditions.includes('prompt') || conditions.includes('prompt_llm')) sources.prompt = await whisperStream(pair, meta, audio, true);
      for (const model of models) {
        if (conditions.includes('llm')) await llmStream(pair, sources.base, 'base', model);
        if (conditions.includes('prompt_llm')) await llmStream(pair, sources.prompt, 'prompt', model);
      }
      log(`  完成；本次累計約 ${Math.round(usage.neurons)} neurons`);
    }
  } catch (error) {
    if (!(error instanceof Paused)) throw error;
    writeFileSync(join(output, 'usage.json'), JSON.stringify({...usage, paused: error.message, neuron_cap: neuronCap}, null, 1));
    log(`\n已暫停：${error.message}\n本次約 ${Math.round(usage.neurons)} neurons。已完成的部分存在 ${output}；額度重置後（台灣早上 8 點）用 --reuse 這個資料夾再執行即可接續。`);
    return {paused: true, usage};
  }
  writeFileSync(join(output, 'usage.json'), JSON.stringify({...usage, paused: null, neuron_cap: neuronCap}, null, 1));
  log(`\n全部完成；本次約 ${Math.round(usage.neurons)} neurons（Whisper ${usage.whisperMinutes.toFixed(1)} 分鐘、語言模型 ${usage.llmTokensIn}+${usage.llmTokensOut} tokens）`);
  return {paused: false, usage};
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const {values} = parseArgs({options: {
    prepared: {type: 'string'}, output: {type: 'string'}, reuse: {type: 'string', multiple: true, default: []},
    'base-raw': {type: 'string'}, conditions: {type: 'string', default: 'base,prompt,llm,prompt_llm'},
    models: {type: 'string', default: ''}, prices: {type: 'string'}, 'neuron-cap': {type: 'string', default: '6000'}, only: {type: 'string'}}});
  if (!values.prepared || !values.output) { console.error('需要 --prepared 與 --output'); process.exit(2); }
  if (existsSync(values.output)) { console.error(`${values.output} 已存在；請用新的資料夾並以 --reuse 接續`); process.exit(2); }
  const account = process.env.CF_ACCOUNT_ID, token = process.env.CF_API_TOKEN;
  if (!account || !token) { console.error('缺少 CF_ACCOUNT_ID／CF_API_TOKEN 環境變數'); process.exit(2); }
  const result = await runExperiment({prepared: values.prepared, output: values.output, reuse: values.reuse, baseRaw: values['base-raw'] || null,
    conditions: values.conditions.split(',').map(s => s.trim()).filter(Boolean), models: values.models.split(',').map(s => s.trim()).filter(Boolean),
    prices: values.prices ? JSON.parse(readFileSync(values.prices, 'utf8')) : {}, neuronCap: Number(values['neuron-cap']),
    only: values.only ? values.only.split(',') : null, account, token, base: process.env.CF_API_BASE || undefined});
  process.exit(result.paused ? 3 : 0);
}
