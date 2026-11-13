import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync, mkdirSync, readFileSync, writeFileSync, existsSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import * as pinyinData from '../public/pinyin-zh.js';
import {DEFAULT_TERMS} from '../public/phonetic.js';
import {applyEdits, correctionMessages, findCandidates, parseEdits, soundIndex, whisperPrompt} from '../public/context-correct.js';
import {Paused, replyOf, runExperiment, runModel, slug} from '../scripts/context-experiment.mjs';

const index = soundIndex(pinyinData);
const opts = {terms: DEFAULT_TERMS, index};

test('candidates: same-sound windows of terms, longest first, no exact or nested ones', () => {
  const found = findCandidates('我們讀以服所書和詔會生活', DEFAULT_TERMS, index);
  assert.deepEqual(found.map(c => [c.from, c.term]), [['以服所書', '以弗所書'], ['詔會生活', '召會生活']]);
  assert.deepEqual(findCandidates('我們今天要看生命讀經', DEFAULT_TERMS, index), []);
  assert.equal(findCandidates('以服所書', DEFAULT_TERMS, index, {limit: 0}).length, 0);
});

test('guard keeps same-sound fixes and rejects rewrites, length changes and correct terms', () => {
  const text = '我們讀以服所書和召會生活';
  const result = applyEdits(text, [
    {from: '以服', to: '以弗'},            // same sound
    {from: '讀', to: '看'},                // other sound, no term → rejected
    {from: '我們', to: '你們大家'},        // length change
    {from: '召會', to: '教會'},            // already a correct term
    {from: '不在', to: '不再'},            // not in the text
    {from: '讀', to: 'A'},                 // not CJK (and other sound)
  ], opts);
  assert.equal(result.text, '我們讀以弗所書和召會生活');
  assert.deepEqual(result.rejected.map(r => r.reason), ['sound', 'length', 'locked_term', 'not_found', 'not_cjk']);
  const loose = applyEdits(text, [{from: '我們', to: '你們大家'}, {from: '生活', to: '生命'}], {...opts, guarded: false});
  assert.equal(loose.text, '你們大家讀以服所書和召會生命');
});

test('guard allows one other syllable only when it completes a 3+ char term', () => {
  // 拿厄米 → 拿俄米 is a tone slip (same toneless syllable); 撒但 → 撒但 unchanged; a one-syllable change into a name passes
  assert.equal(applyEdits('路得和拿厄米', [{from: '拿厄米', to: '拿俄米'}], opts).text, '路得和拿俄米');
  const other = applyEdits('他讀以服所書', [{from: '以服所書', to: '以弗所書'}], opts);
  assert.equal(other.text, '他讀以弗所書');
  const one = applyEdits('他讀一本所書', [{from: '一本所書', to: '以弗所書'}], opts);   // 本→弗 differs, completes the term
  assert.equal(one.text, '他讀以弗所書');
  const two = applyEdits('他讀二本所書', [{from: '二本所書', to: '以弗所書'}], opts);   // two other syllables
  assert.deepEqual(two.rejected.map(r => r.reason), ['sound']);
});

test('overlapping or repeated edits apply once, right to left', () => {
  const result = applyEdits('詔會詔會', [{from: '詔會', to: '召會'}, {from: '詔會', to: '召會'}, {from: '會詔', to: '會召'}], opts);
  assert.equal(result.text, '召會召會');
  assert.equal(result.accepted.length, 2);
});

test('whisper prompt: recent exact terms newest first plus the previous caption tail', () => {
  assert.equal(whisperPrompt([], DEFAULT_TERMS), '');
  const prompt = whisperPrompt(['今天讀以弗所書', '召會是基督的身體'], DEFAULT_TERMS);
  assert.ok(prompt.startsWith('召會、基督的身體、以弗所書。'));
  assert.ok(prompt.endsWith('召會是基督的身體'));
  assert.ok(Array.from(whisperPrompt(['甲'.repeat(200)], DEFAULT_TERMS)).length <= 60);
});

test('messages and reply parsing', () => {
  const messages = correctionMessages({context: ['前一段'], text: '詔會', candidates: [{from: '詔會', term: '召會'}], suffix: '/no_think'});
  assert.equal(messages[0].role, 'system');
  assert.match(messages[1].content, /前一段/); assert.match(messages[1].content, /「詔會」可能是「召會」/); assert.match(messages[1].content, /\/no_think$/);
  assert.deepEqual(parseEdits('<think>\n</think>```json\n{"edits":[{"from":"a","to":"b"},{"from":1}]}\n```'), [{from: 'a', to: 'b'}]);
  assert.equal(parseEdits('沒有要改'), null);
  assert.equal(parseEdits('{"edit": []}'), null);
  assert.deepEqual(replyOf({choices: [{message: {content: '{"edits":[]}'}}], usage: {prompt_tokens: 5, completion_tokens: 2}}),
    {reply: '{"edits":[]}', tokensIn: 5, tokensOut: 2});
  assert.equal(slug('@cf/qwen/qwen3-30b-a3b-fp8'), 'qwen-qwen3-30b-a3b-fp8');
});

const response = (status, body) => ({ok: status < 400, status, json: async () => body});

test('runModel: quota pauses, auth stops, server errors retry', async () => {
  const api = {account: 'a', token: 't', sleep: async () => {}};
  await assert.rejects(runModel('m', {}, {...api, fetchImpl: async () => response(429, {success: false, errors: [{code: 3036, message: 'daily'}]})}), Paused);
  await assert.rejects(runModel('m', {}, {...api, fetchImpl: async () => response(401, {success: false, errors: []})}), /拒絕/);
  let calls = 0;
  const result = await runModel('m', {}, {...api, fetchImpl: async () => (++calls < 3 ? response(502, {}) : response(200, {success: true, result: {text: 'ok'}}))});
  assert.deepEqual([result.text, calls], ['ok', 3]);
});

function prepared() {
  const dir = mkdtempSync(join(tmpdir(), 'ctx-'));
  const chunk = {samples: 16000, seconds: 1};
  const meta = {pair: '01', total_chunks: 4, duration_seconds: 60, window: null,
    chunks: [0, 1, 2].map(k => ({full_index: k + 1, start: k, ...chunk}))};
  writeFileSync(join(dir, '01.chunks.json'), JSON.stringify(meta));
  const pcm = Buffer.alloc(3 * 16000 * 2);
  for (let k = 0; k < 3; k++) pcm.fill(k + 1, k * 32000, (k + 1) * 32000);   // chunk k is recognizable by its bytes
  writeFileSync(join(dir, '01.chunks.s16'), pcm);
  return dir;
}

function fakeCloudflare(log) {
  const heard = ['我們讀以服所书', '这是诏会生活', '他说戒严的话'];
  return async (url, init) => {
    const body = JSON.parse(init.body), model = decodeURIComponent(url.split('/ai/run/')[1]);
    log.push({model, prompt: body.initial_prompt ?? null});
    if (model.includes('whisper')) {
      const k = Buffer.from(body.audio, 'base64')[44] - 1;
      return response(200, {success: true, result: {text: heard[k]}});
    }
    const text = body.messages[1].content;
    const edits = text.includes('本段：他說戒嚴') ? [{from: '戒嚴', to: '介言'}, {from: '他說', to: '你們大家'}] : [];
    return response(200, {success: true, result: {response: JSON.stringify({edits}), usage: {prompt_tokens: 300, completion_tokens: 20}}});
  };
}

const prices = {'@cf/test/llm': {input_neurons_per_m: 10000, output_neurons_per_m: 100000}};

test('experiment: four conditions, site corrections, guard, usage and pause/resume', async () => {
  const dir = prepared(), out = mkdtempSync(join(tmpdir(), 'run-'));
  const log = [], base = {prepared: dir, models: ['@cf/test/llm'], prices, account: 'a', token: 't', sleep: async () => {}, log: () => {}};
  // ~0.78 neurons per 1 s whisper chunk: the cap stops the run part way.
  const first = await runExperiment({...base, output: join(out, 'r1'), neuronCap: 2, fetchImpl: fakeCloudflare(log)});
  assert.equal(first.paused, true);
  assert.ok(existsSync(join(out, 'r1', '01.whisper_base.partial.json')));
  const before = log.length;
  const second = await runExperiment({...base, output: join(out, 'r2'), reuse: [join(out, 'r1')], neuronCap: 100, fetchImpl: fakeCloudflare(log)});
  assert.equal(second.paused, false);
  const read = name => JSON.parse(readFileSync(join(out, 'r2', name), 'utf8'));
  const whisperBase = read('01.whisper_base.json');
  assert.equal(whisperBase.records.length, 3);
  assert.equal(log.filter(e => e.model.includes('whisper')).length, 6, 'no chunk is sent twice (3 base + 3 prompt)');
  assert.ok(log.length > before);
  // Website corrections: Traditional + same-sound terms.
  assert.equal(whisperBase.records[1].site, '這是召會生活');
  const prompts = read('01.whisper_prompt.json').records.map(r => r.prompt);
  assert.equal(prompts[0], null);
  assert.ok(prompts[1].includes('我們讀以弗所書'));
  const llm = read(`01.llm_base__${slug('@cf/test/llm')}.json`);
  assert.equal(llm.records[0].site, '我們讀以弗所書');            // the site already fixed it: no candidate, no call
  assert.equal(llm.records[0].called, false);
  const r = llm.records[2];
  assert.equal(r.site, '他說戒嚴的話');                               // a real word: the same-sound rule leaves it
  assert.deepEqual(r.candidates.map(c => c.term), ['介言']);
  assert.equal(r.final, '他說介言的話');
  assert.equal(r.final_unguarded, '你們大家介言的話');
  assert.deepEqual(r.rejected.map(x => x.reason), ['length']);
  assert.equal(r.neurons, 5);                                         // 300×10000/1e6 + 20×100000/1e6
  assert.ok(existsSync(join(out, 'r2', `01.llm_prompt__${slug('@cf/test/llm')}.json`)));
  const usage = JSON.parse(readFileSync(join(out, 'r2', 'usage.json'), 'utf8'));
  assert.equal(usage.paused, null);
});

test('experiment refuses models without a price and mismatched reused base captions', async () => {
  const dir = prepared(), out = mkdtempSync(join(tmpdir(), 'run-'));
  const base = {prepared: dir, account: 'a', token: 't', sleep: async () => {}, log: () => {}, fetchImpl: fakeCloudflare([])};
  await assert.rejects(runExperiment({...base, output: join(out, 'a'), models: ['@cf/x'], prices: {}}), /價格/);
  const raw = join(out, 'meet'); mkdirSync(raw);
  writeFileSync(join(raw, '01.workers_ai_live_vad_10s.json'), JSON.stringify({raw: ['一', '二']}));
  await assert.rejects(runExperiment({...base, output: join(out, 'b'), conditions: ['base'], baseRaw: raw}), /不能沿用/);
  writeFileSync(join(raw, '01.workers_ai_live_vad_10s.json'), JSON.stringify({raw: ['零', '詔會', '以服所書', '三']}));
  const log = [];
  await runExperiment({...base, output: join(out, 'c'), conditions: ['base'], baseRaw: raw, fetchImpl: fakeCloudflare(log)});
  const records = JSON.parse(readFileSync(join(out, 'c', '01.whisper_base.json'), 'utf8')).records;
  assert.deepEqual(records.map(r => r.site), ['召會', '以弗所書', '三']);
  assert.equal(log.length, 0, 'reused base captions cost nothing');
});
