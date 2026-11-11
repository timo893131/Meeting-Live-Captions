import {Converter} from 'opencc-js/cn2t';

const toTraditional = Converter({from: 'cn', to: 'tw'});
// Whisper "hears" video-site credits and channel names in silence or noise; such a line is never sermon text.
// Checked after the Traditional conversion, so one pattern covers both scripts.
const HALLUCINATIONS = /(字幕|字幕組).{0,12}(提供|製作|志願者|校對|翻譯)|^(作詞|作曲|編曲)[：:]|感謝觀看|請不吝|點贊|訂閱|轉發|打賞|Amara|明鏡|謝謝(觀看|收看|大家收看)|優優獨播|獨播劇場|YoYo|Television Series|Exclusive|字幕by|中文字幕/i;

/** Whisper result → caption text: drops silent and hallucinated segments, Simplified → Traditional (Taiwan). */
export function cleanTranscript(result, language) {
  const parts = Array.isArray(result?.segments) && result.segments.length
    // Whisper's own rule (no speech + low confidence), plus near-certain silence on its own.
    ? result.segments.filter(s => !(s.no_speech_prob > 0.8 || (s.no_speech_prob > 0.6 && s.avg_logprob < -1))).map(s => s.text || '')
    : [result?.text || ''];
  return parts.map(part => (language === 'zh' ? toTraditional(part) : part).trim())
    .filter(part => part && !HALLUCINATIONS.test(part))
    .join(language === 'zh' ? '' : ' ').trim();
}
