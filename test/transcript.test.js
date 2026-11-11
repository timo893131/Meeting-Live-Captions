import test from 'node:test';
import assert from 'node:assert/strict';
import {cleanTranscript} from '../cloudflare/transcript.js';

test('Whisper text is converted to Traditional Chinese without changing church wording', () => {
  assert.equal(cleanTranscript({text: '我们来读以弗所书，神的经纶，信息'}, 'zh'), '我們來讀以弗所書，神的經綸，信息');
});

test('silence hallucinations and silent segments are dropped; sermon text is kept', () => {
  assert.equal(cleanTranscript({text: '優優獨播劇場——YoYo Television Series Exclusive'}, 'zh'), '');
  assert.equal(cleanTranscript({text: '请不吝点赞 订阅 转发 打赏支持明镜与点点栏目'}, 'zh'), '');
  assert.equal(cleanTranscript({text: '字幕志愿者 杨茜茜'}, 'zh'), '');  // seen on production with a beeping test microphone
  assert.equal(cleanTranscript({text: 'x', segments: [{text: '那', no_speech_prob: 0.7, avg_logprob: -1.3}, {text: '神的經綸', no_speech_prob: 0.7, avg_logprob: -0.3}]}, 'zh'), '神的經綸');
  assert.equal(cleanTranscript({text: 'x', segments: [{text: '弟兄姊妹', no_speech_prob: 0.1}, {text: '字幕由Amara.org社区提供', no_speech_prob: 0.2},
    {text: '嗯', no_speech_prob: 0.95}]}, 'zh'), '弟兄姊妹');
  assert.equal(cleanTranscript({text: ' Amen, brothers ', segments: []}, 'en'), 'Amen, brothers');
});
