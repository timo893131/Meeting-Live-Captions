import {defaultGlossary, startingGlossary, parseGlossary, correctText} from '/glossary.js';
import {DEFAULT_TERMS, NEAR_SKIP, loadPinyin, parseTerms, phoneticCorrect, pinyinReady} from '/phonetic.js';
import {parseOutline, correctionOptions, splitMessages} from '/outline.js';
import {preparePassages, alignCaption} from '/verse-align.js';
import {BIBLE_BOOKS, CORE_TERMS, LIFE_STUDY_TERMS, BIBLE_NAMES} from '/church-terms.js';
import {ALWAYS_CORRECTED} from '/always-corrected.js';
import {RATE, createSegmenter, startMicrophoneChunks, encodeWav, createOrderedQueue} from '/speech-chunker.js';

const $ = id => document.getElementById(id);
const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
const SESSION_KEY = 'meetingCaptionRoom';
const MAX_RETRIES = 5;
let mode = 'personal', room = null, socket = null, roomState = 'none', hostOnline = false;
let entries = [], following = true, unread = 0, busy = false, terminal = false;
let generation = 0, retryCount = 0, reconnectTimer = null, handshakeTimer = null;
let recognition = null, wantsAudio = false, speechGeneration = 0, restartTimer = null, shortEnds = 0;
let micState = 'idle', wakeLock = null, wakePending = false;
// Whisper on Cloudflare Workers AI (server-side): microphone chunks cut at pauses. When Chrome's recognizer is
// available it runs alongside as an instant grey preview; it also takes over if Whisper is unavailable.
let serverSpeech = false, serverVerses = false, whisper = null;
const usingWhisper = () => serverSpeech && $('engine').value === 'whisper' && !fileSource;
// Audio-file test: the file plays into a Web Audio stream (not the speakers) whose track is recognized.
let fileSource = null;
const FILE_RETRIES = 8;
// Chrome sometimes stops answering mid-phrase on an audio track. If no result arrives for STALL_SECONDS of
// audio (or SILENT_SESSION_SECONDS when a session has produced nothing, which may be real silence or music),
// the session is restarted; after a mid-phrase stall the audio is rewound to the last answered position.
const STALL_SECONDS = 5, SILENT_SESSION_SECONDS = 8;
function checkFileStall() {
  const source = fileSource;
  if (!source || !recognition || micState !== 'active' || source.audio.paused || source.audio.ended || source.stopping) return;
  const answered = source.lastResultAt != null, since = answered ? source.lastResultAt : source.sessionStartAt;
  if (source.audio.currentTime - since < (answered ? STALL_SECONDS : SILENT_SESSION_SECONDS)) return;
  // Rewind only forward of the previous rewind target, so real silence cannot loop forever.
  const target = answered ? Math.max(source.sessionStartAt, source.lastResultAt - 0.5) : null;
  source.rewindTo = target != null && target > (source.lastRewindTo ?? -1) + 0.5 ? target : null;
  if (source.rewindTo != null) source.lastRewindTo = source.rewindTo;
  fileStats.stalls++; diag('stall', {since: +since.toFixed(1), rewindTo: source.rewindTo});
  source.stopping = true;
  try { recognition.stop(); } catch {}
}
// Diagnostics for the audio-file test (kept after it stops, downloadable as JSON lines).
let fileLog = null, fileStats = null;
function diag(type, data = {}) {
  if (!fileLog || !fileSource) return;
  fileLog.push({t: +((performance.now() - fileStats.began) / 1000).toFixed(1), at: +fileSource.audio.currentTime.toFixed(1), type, ...data});
}

function message(text = '', kind = 'error') {
  $('message').textContent = text;
  $('message').dataset.kind = kind;
  $('message').hidden = !text;
}
function setInterim(text = '') {
  $('interim').textContent = text;
  $('interimLabel').hidden = !text;
}
function badge(id, text, tone = 'neutral') {
  $(id).textContent = text;
  $(id).dataset.tone = tone;
}
function updateUI() {
  for (const id of ['personal', 'host', 'viewer']) {
    $(id).classList.toggle('selected', id === mode);
    $(id).setAttribute('aria-pressed', String(id === mode));
    $(id).disabled = busy;
  }
  $('settings').hidden = mode === 'viewer';
  $('start').hidden = $('stop').hidden = mode === 'viewer';
  $('micStatus').hidden = mode === 'viewer';
  $('fileTest').hidden = mode !== 'personal';
  $('start').disabled = busy || wantsAudio || (!SpeechRecognition && !serverSpeech) || (mode === 'host' && roomState !== 'ready');
  $('engine').disabled = wantsAudio || !serverSpeech;
  $('stop').disabled = !wantsAudio;
  $('language').disabled = wantsAudio;
  $('joinButton').disabled = busy || roomState === 'connecting';
  $('closeRoom').disabled = busy;
  $('export').disabled = !entries.length;
  $('reconnect').hidden = !room || terminal || !['retrying', 'failed'].includes(roomState);
  const states = {
    none: [mode === 'viewer' ? '尚未加入房間' : mode === 'host' ? '正在建立房間' : '個人模式', 'neutral'], connecting: ['房間連線中', 'warning'],
    ready: [mode === 'viewer' && !hostOnline ? '房主暫時離線' : '房間已連線', mode === 'viewer' && !hostOnline ? 'warning' : 'active'],
    retrying: [navigator.onLine ? '連線中斷・正在重連' : '網路離線', 'warning'],
    failed: ['房間未連線', 'error'], closed: ['房間已結束', 'neutral']
  };
  badge('status', ...(states[roomState] || states.none));
  const micStates = {
    idle: ['尚未收音', 'neutral'], starting: ['正在啟動麥克風', 'warning'],
    active: [whisper ? '收音中・Whisper' : wantsAudio && serverSpeech ? '收音中・Chrome' : '收音中', 'active'], restarting: ['正在恢復收音', 'warning'], error: ['收音已停止', 'error']
  };
  badge('micStatus', ...micStates[micState]);
  void syncWakeLock();
}

function saveSession() {
  if (!room) return;
  try { sessionStorage.setItem(SESSION_KEY, JSON.stringify({mode, room})); } catch {}
}
function clearSession() {
  try { sessionStorage.removeItem(SESSION_KEY); } catch {}
}
function readSession() {
  try {
    const saved = JSON.parse(sessionStorage.getItem(SESSION_KEY));
    const item = saved?.room;
    if (!item || !/^[a-f0-9]{10}$/.test(item.id) || !Number.isFinite(item.savedAt) || Date.now() - item.savedAt > 12 * 3600000) return null;
    if (saved.mode === 'host' && /^[a-f0-9]{64}$/.test(item.hostToken) && /^[a-f0-9]{48}$/.test(item.viewerToken) && typeof item.password === 'string') return saved;
    if (saved.mode === 'viewer' && ((typeof item.password === 'string' && item.password.length <= 128) || /^[a-f0-9]{48}$/.test(item.invite))) return saved;
  } catch {}
  return null;
}
async function request(path, options = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 10000);
  try {
    const response = await fetch(path, {...options, signal: controller.signal});
    if (!response.ok) {
      const body = await response.json().catch(() => null);
      const error = new Error(body?.error || '服務暫時無法回應，請稍後再試。');
      error.status = response.status;
      throw error;
    }
    return response;
  } catch (error) {
    if (error.name === 'AbortError') throw new Error('連線逾時，請確認網路後再試。');
    throw error;
  } finally { clearTimeout(timer); }
}

function showLatest() {
  following = true; unread = 0;
  $('captions').scrollTop = $('captions').scrollHeight;
  $('latest').hidden = true;
}
function updateLatest() {
  $('latest').hidden = following || !entries.length;
  $('latest').textContent = unread ? `回到最新字幕（${unread}）↓` : '回到最新字幕 ↓';
}
function placeholder() {
  const p = document.createElement('p'); p.className = 'placeholder';
  p.textContent = mode === 'viewer' ? '加入房間後，字幕會在這裡顯示。' : '準備好了，按下「開始收音」。';
  $('captions').replaceChildren(p);
}
function addEntry(entry) {
  if (!entry || typeof entry.text !== 'string' || (entry.id && entries.some(old => old.id === entry.id))) return;
  const root = $('captions'), follow = following;
  root.querySelector('.placeholder')?.remove();
  entries.push(entry);
  const p = document.createElement('p'); p.textContent = entry.text; p.dataset.id = entry.id || '';
  root.append(p);
  if (entries.length > 200) {
    entries.shift();
    const first = root.firstElementChild;
    const removedHeight = first.getBoundingClientRect().height + parseFloat(getComputedStyle(first).marginBottom);
    first.remove();
    if (!follow) root.scrollTop = Math.max(0, root.scrollTop - removedHeight);
  }
  if (follow) showLatest(); else { unread++; updateLatest(); }
  $('export').disabled = false;
}
function setHistory(history = []) {
  const root = $('captions'), oldTop = root.scrollTop, follow = following;
  const firstVisible = [...root.children].find(p => p.getBoundingClientRect().bottom > root.getBoundingClientRect().top);
  const anchor = firstVisible?.dataset.id;
  const offset = firstVisible ? firstVisible.getBoundingClientRect().top - root.getBoundingClientRect().top : 0;
  const oldNodes = new Map([...root.children].map(p => [p.dataset.id, p]));
  entries = history.filter(entry => entry && typeof entry.text === 'string').slice(-200);
  root.setAttribute('aria-live', 'off');
  const nodes = entries.map(entry => {
    const p = oldNodes.get(entry.id) || document.createElement('p');
    p.textContent = entry.text; p.dataset.id = entry.id || ''; return p;
  });
  root.replaceChildren(...nodes);
  if (!entries.length) placeholder();
  if (follow) showLatest(); else {
    const restored = nodes.find(p => p.dataset.id === anchor);
    root.scrollTop = restored ? restored.offsetTop - root.offsetTop - offset : oldTop;
    updateLatest();
  }
  queueMicrotask(() => root.setAttribute('aria-live', 'polite'));
  $('export').disabled = !entries.length;
}
$('captions').addEventListener('scroll', () => {
  const root = $('captions');
  following = root.scrollHeight - root.scrollTop - root.clientHeight < 64;
  if (following) unread = 0;
  updateLatest();
});
$('latest').onclick = showLatest;

function sendCaption(text, final) {
  if (mode === 'host') {
    if (roomState !== 'ready' || socket?.readyState !== WebSocket.OPEN) return;
    socket.send(JSON.stringify({type: 'caption', text, final}));
  } else if (final) addEntry({id: crypto.randomUUID(), text, time: Date.now()});
  setInterim(final ? '' : text);
}
function stopAudio({discard = false, error = false} = {}) {
  wantsAudio = false;
  if (whisper) {  // the last chunk is still recognized and shown, unless the captions are being discarded
    const state = whisper; whisper = null;
    if (discard) state.discarded = true;
    state.capture?.stop();
  }
  if (fileSource) {
    const source = fileSource; fileSource = null;
    clearInterval(source.watchdog);
    source.audio.pause(); source.context.close().catch(() => {}); URL.revokeObjectURL(source.audio.src);
    $('fileProgress').hidden = true; $('testAudio').value = '';
  }
  clearTimeout(restartTimer);
  const old = recognition;
  if (discard) { speechGeneration++; recognition = null; }
  try { discard ? old?.abort() : old?.stop(); } catch {}
  micState = error ? 'error' : 'idle';
  setInterim();
  if (mode === 'host' && roomState === 'ready' && socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({type: 'caption', text: '', final: false}));
  updateUI();
}
const speechErrors = {
  'not-allowed': '麥克風未獲允許。請在瀏覽器的網站權限中允許麥克風，再按開始收音。',
  'service-not-allowed': '語音辨識服務無法使用。請確認瀏覽器支援與網站權限。',
  'audio-capture': '找不到可用的麥克風。請檢查裝置連接與系統收音設定。',
  network: '語音服務連線中斷。請確認網路，再按開始收音。',
  'language-not-supported': '語音服務不支援目前語言，請切換語言後再試。'
};
// Same-sound church-term correction: the pinyin data is loaded once, only when someone starts captioning.
let pinyinLoading = null, commonWords = null;
function loadPinyinData() {
  pinyinLoading ||= import('/pinyin-zh.js').then(data => { loadPinyin(data); commonWords = new Set(data.COMMON.split('|')); })
    .catch(() => { pinyinLoading = null; });
  return pinyinLoading;
}
function ensurePinyin() {
  if (!$('phonetic').checked || pinyinReady()) return Promise.resolve();
  return loadPinyinData();
}
// This meeting's outline (host's browser only): parsed once per text, see outline.js.
function currentOutline() {
  const text = $('outline').value;
  return text.trim() && commonWords ? parseOutline(text, {common: commonWords, known: DEFAULT_TERMS}) : null;
}
function captionCorrection() {
  const value = $('glossary').value, outline = correctionOptions(currentOutline(), {nearSkip: NEAR_SKIP});
  return {glossary: parseGlossary(value), terms: [...DEFAULT_TERMS, ...outline.terms, ...parseTerms(value)],
    options: outline.nearTerms ? {nearTerms: outline.nearTerms} : {}};
}
// Verse alignment (M2): the host of a broadcast room fetches the outline's Recovery Version verses from the private
// store; a final caption that reads one of them shows the verse text and its reference (verse-align.js).
let verseState = {key: '', passages: [], count: 0, error: ''};
function verseQuery() {
  const outline = currentOutline();
  if (mode !== 'host' || !room?.hostToken || !serverVerses || !outline?.refs.length) return null;
  const refs = [], seen = new Set();
  let total = 0;
  for (const r of outline.refs) {
    const to = Math.min(r.to, r.verse + 59), ref = `${r.book}${r.chapter}:${r.verse}${to > r.verse ? '-' + to : ''}`;
    if (seen.has(ref) || total + to - r.verse + 1 > 300) continue;
    seen.add(ref); refs.push(ref); total += to - r.verse + 1;
  }
  return {key: `${room.id}|${refs.join(',')}`, refs};
}
async function ensureVerses() {
  const query = verseQuery();
  if (!query) { verseState = {key: '', passages: [], count: 0, error: ''}; return; }
  if (verseState.key === query.key) return verseState.loading;
  const state = verseState = {key: query.key, passages: [], count: 0, error: ''};
  state.loading = (async () => {
    try {
      await loadPinyinData();
      const verses = [];
      for (let i = 0; i < query.refs.length; i += 80) {
        const params = new URLSearchParams({room: room.id, refs: query.refs.slice(i, i + 80).join(',')});
        const response = await fetch('/api/verses?' + params, {headers: {Authorization: 'Bearer ' + room.hostToken}});
        if (!response.ok) throw new Error(String(response.status));
        verses.push(...(await response.json()).verses);
      }
      if (verseState === state) { state.passages = preparePassages(verses); state.count = verses.length; }
    } catch { if (verseState === state) state.error = '經文暫時無法取得，字幕照常顯示。'; }
    if (verseState === state) showOutlineSummary();
  })();
  return state.loading;
}
function alignVerses(text) {
  if (!$('verseAlign').checked || !verseState.passages.length) return text;
  const aligned = alignCaption(text, verseState.passages);
  return aligned ? `${aligned.text}（${aligned.label}）` : text;
}
function correctCaption(text, {glossary, terms, options}) {
  const exact = correctText(text, glossary);
  return $('phonetic').checked ? phoneticCorrect(exact, terms, options).text : exact;
}

function beginRecognition(run) {
  if (!wantsAudio || run !== speechGeneration) return;
  if (mode === 'host' && roomState !== 'ready') { stopAudio({discard: true}); return; }
  const rec = new SpeechRecognition(); recognition = rec;
  rec.lang = $('language').value; rec.continuous = true; rec.interimResults = true;
  const startedAt = Date.now();
  const completedResults = new Set();
  const current = () => run === speechGeneration && recognition === rec;
  rec.onstart = () => {
    if (!current() || !wantsAudio) return;
    micState = 'active'; updateUI();
    // Audio-file test: the file only plays while a recognition session is running, so nothing is skipped
    // while Chrome reconnects between sessions.
    if (fileSource && !fileSource.audio.ended) fileSource.audio.play().catch(() => {});
    if (fileSource) {
      Object.assign(fileSource, {sessionStartAt: fileSource.audio.currentTime, lastResultAt: null, stopping: false});
      fileStats.sessions++; diag('start');
    }
  };
  rec.onresult = event => {
    if (!current()) return;
    let interim = '';
    const correction = captionCorrection();
    for (let i = event.resultIndex; i < event.results.length; i++) {
      const result = event.results[i], text = correctCaption(result[0].transcript, correction);
      if (result.isFinal) {
        if (completedResults.has(i)) continue;
        completedResults.add(i);
        if (whisper) whisper.preview += text; else sendCaption(alignVerses(text), true);
      } else if (wantsAudio) interim += text;
    }
    if (whisper) interim = whisper.preview + interim;
    if (fileSource) {
      const finals = [];
      for (let i = event.resultIndex; i < event.results.length; i++) if (event.results[i].isFinal) finals.push(event.results[i][0].transcript.length);
      fileStats.finals += finals.length;
      // An unfinished phrase that shrinks without any final result was thrown away by the recognizer.
      const dropped = !finals.length && fileSource.pending.length >= 8 && interim.length < fileSource.pending.length / 2;
      if (dropped) fileStats.drops++;
      diag(dropped ? 'interim-dropped' : 'result', {index: event.resultIndex, total: event.results.length, finals,
        interim: interim.length, before: fileSource.pending.length});
      fileSource.pending = interim; fileSource.failures = 0; fileSource.lastResultAt = fileSource.audio.currentTime;
      // Diagnostics showed Chrome goes deaf for ~30 s after each final result on an audio track, while a fresh
      // session responds within 1–3 s: so end the session after every final and restart (audio waits meanwhile).
      if (finals.length && !fileSource.restartAfterFinal) {
        fileSource.restartAfterFinal = true; fileSource.stopping = true; diag('restart-after-final');
        try { rec.stop(); } catch {}
      }
    }
    sendCaption(interim, false);
  };
  rec.onerror = event => {
    if (fileSource && current()) { fileStats.errors++; diag('error', {error: event.error}); }
    if (!current() || !wantsAudio || event.error === 'no-speech') return;
    if (whisper) {  // only the preview is affected; Whisper keeps captioning
      if (['not-allowed', 'service-not-allowed', 'language-not-supported', 'audio-capture'].includes(event.error)) whisper.noPreview = true;
      return;
    }
    // Audio-file test: transient service errors are retried (with back-off in onend) instead of stopping.
    if (fileSource && ['network', 'aborted'].includes(event.error)) { fileSource.failures++; return; }
    stopAudio({discard: true, error: true});
    message(speechErrors[event.error] || '語音辨識已停止，請確認麥克風與網路，再按開始收音。');
  };
  rec.onend = () => {
    if (!current()) return;
    recognition = null;
    if (!wantsAudio) return;
    if (fileSource) {
      const source = fileSource, audio = source.audio;
      diag('end', {pending: source.pending.length});
      if (source.pending) { sendCaption(source.pending, true); source.pending = ''; }  // keep the unfinished phrase
      sendCaption('', false);
      // Rewind a little so a phrase cut by the restart is heard again; less after a planned restart.
      if (!audio.ended) {
        audio.pause();
        audio.currentTime = source.rewindTo ?? Math.max(0, audio.currentTime - (source.restartAfterFinal ? 0.3 : 1));
      }
      source.restartAfterFinal = false; source.rewindTo = null;
      if (source.failures >= FILE_RETRIES) {
        stopAudio({discard: true, error: true});
        message('語音服務連續中斷，音檔測試已停止。請確認網路後重新選擇音檔。');
        return;
      }
      micState = 'restarting'; updateUI();
      restartTimer = setTimeout(() => beginRecognition(run), source.failures ? Math.min(8000, 500 * 2 ** source.failures) : 100);
      return;
    }
    if (whisper?.noPreview) return;
    shortEnds = Date.now() - startedAt < 1000 ? shortEnds + 1 : 0;
    if (shortEnds >= 5 && whisper) { whisper.noPreview = true; return; }
    if (shortEnds >= 5) {
      stopAudio({discard: true, error: true});
      message('語音服務連續中斷，已停止自動重試。請檢查網路與瀏覽器後重新開始收音。');
      return;
    }
    micState = 'restarting'; updateUI();
    restartTimer = setTimeout(() => beginRecognition(run), 500);
  };
  const usingFile = Boolean(fileSource);
  try { usingFile ? rec.start(fileSource.track) : rec.start(); } catch {
    if (whisper) { whisper.noPreview = true; recognition = null; return; }
    stopAudio({discard: true, error: true});
    message(usingFile ? '此 Chrome 版本無法辨識音檔，請更新到桌面版 Chrome 133 以上。' : '無法啟動語音辨識，請確認麥克風權限後再試。');
  }
}
function deliverWhisper(state, item) {
  if (state.discarded) return;
  if (item.text !== undefined) {
    state.failures = 0;
    // Whisper may repeat itself on noise or music: the same longer line twice in a row is shown once.
    if (item.text && !(item.text.length >= 6 && item.text === state.lastText)) {
      state.lastText = item.text;
      sendCaption(alignVerses(correctCaption(item.text, captionCorrection())), true);
    }
    state.preview = '';  // the preview of this stretch is replaced by the recognized caption
    return;
  }
  if (state.preview) { sendCaption(state.preview, true); state.preview = ''; }  // keep what the preview heard
  if (item.fatal || ++state.failures >= 3) fallbackToChrome(state, item.fatal);
}
function fallbackToChrome(state, code) {
  if (whisper !== state) return;
  whisper = null; state.capture?.stop();
  const reason = {quota: '今天的 Whisper 免費額度已用完', limit: '這個網路今天的 Whisper 用量已達上限', unavailable: '此網站沒有 Whisper 辨識'}[code] || 'Whisper 辨識連續失敗';
  if (state.file) { stopAudio({error: true}); return message(`${reason}，音檔辨識已停止；已完成的字幕仍保留，可以下載。`); }
  if (SpeechRecognition && wantsAudio && !state.noPreview) {
    message(`${reason}，已改用 Chrome 即時辨識繼續字幕。`, 'info'); updateUI();
  } else {
    stopAudio({error: true});
    message(`${reason}，字幕已停止。請改用桌面版 Chrome（設定選「Chrome 即時辨識」），或稍後再試。`);
  }
}
async function sendChunk(state, samples) {
  const seq = state.queue.reserve(), language = $('language').value.startsWith('en') ? 'en' : 'zh';
  for (let attempt = 0; attempt < 2; attempt++) {
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 30000);
    try {
      const response = await fetch('/api/transcribe?lang=' + language, {method: 'POST', headers: {'Content-Type': 'audio/wav'},
        body: encodeWav(samples), signal: controller.signal});
      const body = await response.json().catch(() => ({}));
      if (response.ok) return state.queue.settle(seq, {text: typeof body.text === 'string' ? body.text : ''});
      if (['quota', 'limit', 'unavailable'].includes(body.code)) return state.queue.settle(seq, {fatal: body.code});
    } catch {} finally { clearTimeout(timer); }
    if (attempt === 0) await new Promise(resolve => setTimeout(resolve, 1000));
  }
  state.queue.settle(seq, {failed: true});
}
async function startWhisper(run) {
  const state = {failures: 0, preview: '', capture: null, discarded: false, noPreview: !SpeechRecognition};
  state.queue = createOrderedQueue(item => deliverWhisper(state, item));
  whisper = state;
  let capture;
  try { capture = await startMicrophoneChunks(chunk => { void sendChunk(state, chunk); }); }
  catch (error) {
    if (whisper !== state) return;
    whisper = null; stopAudio({discard: true, error: true});
    return message(error?.name === 'NotAllowedError' ? speechErrors['not-allowed'] : speechErrors['audio-capture']);
  }
  state.capture = capture;
  if (whisper !== state || run !== speechGeneration) { capture.stop(); return; }  // stopped while starting
  micState = 'active'; updateUI();
  if (!state.noPreview) beginRecognition(run);
}
function startAudio() {
  if (wantsAudio || busy) return;
  if (!SpeechRecognition && !usingWhisper()) return message('此瀏覽器不支援收音辨識，請使用桌面版 Chrome；仍可加入房間看字幕。');
  if (!window.isSecureContext) return message('麥克風需要 HTTPS，請使用安全的網站網址。');
  if (mode === 'host' && roomState !== 'ready') return message('房間尚未連線，請等待連線完成。');
  message(); wantsAudio = true; shortEnds = 0; micState = 'starting';
  const run = ++speechGeneration;
  ensurePinyin(); updateUI();
  if (usingWhisper()) void startWhisper(run); else beginRecognition(run);
}

function disconnect() {
  generation++;
  clearTimeout(reconnectTimer); clearTimeout(handshakeTimer);
  const old = socket; socket = null; old?.close();
}
function resetRoom({closed = false} = {}) {
  stopAudio({discard: true}); disconnect(); clearSession();
  room = null; retryCount = 0; terminal = false; hostOnline = false;
  roomState = closed ? 'closed' : 'none';
  $('sharePanel').hidden = true;
  const qr = $('qr').src;
  if (qr.startsWith('blob:')) URL.revokeObjectURL(qr);
  $('qr').removeAttribute('src'); updateUI();
}
function retryConnection() {
  if (!room || terminal) return;
  roomState = 'retrying';
  if (!navigator.onLine) {
    updateUI(); message('網路已離線。連線恢復後會重新加入房間；房主需重新開始收音。', 'info'); return;
  }
  if (retryCount >= MAX_RETRIES) {
    roomState = 'failed';
    if (mode === 'viewer') $('joinPanel').hidden = false;
    updateUI();
    message('暫時無法連上房間。請確認網路或房間是否仍開啟，再按「重新連線」。'); return;
  }
  const delay = Math.min(500 * 2 ** retryCount, 8000); retryCount++;
  updateUI();
  message(mode === 'host' ? '房間連線中斷，已停止收音。重連完成後請重新開始收音。' : '連線中斷，正在重新加入房間，字幕歷史會保留。', 'info');
  reconnectTimer = setTimeout(connectRoom, delay);
}
function connectRoom() {
  if (!room || terminal) return;
  clearTimeout(reconnectTimer); clearTimeout(handshakeTimer);
  const currentGeneration = generation, membership = {...room}, role = mode === 'host' ? 'host' : 'viewer';
  const old = socket; socket = null; old?.close();
  roomState = 'connecting'; updateUI();
  const ws = new WebSocket((location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/ws?room=' + encodeURIComponent(membership.id));
  socket = ws;
  const current = () => currentGeneration === generation && socket === ws;
  let timedOut = false;
  handshakeTimer = setTimeout(() => { if (current() && roomState !== 'ready') { timedOut = true; ws.close(); } }, 10000);
  ws.onopen = () => {
    if (current()) ws.send(JSON.stringify({type: 'join', room: membership.id, role, token: role === 'host' ? membership.hostToken : undefined, password: role === 'viewer' ? membership.password : undefined, invite: role === 'viewer' ? membership.invite : undefined}));
  };
  ws.onmessage = event => {
    if (!current()) return;
    let msg; try { msg = JSON.parse(event.data); } catch { return; }
    if (!msg || typeof msg !== 'object') return;
    if (msg.type === 'ready') {
      clearTimeout(handshakeTimer); roomState = 'ready'; hostOnline = !!msg.hostOnline;
      const wasRetry = retryCount > 0; retryCount = 0;
      setHistory(Array.isArray(msg.history) ? msg.history : []); setInterim(msg.interim || '');
      saveSession(); updateUI();
      if (role === 'host') ensureVerses();
      message(wasRetry && role === 'host' ? '房間已重新連線，請按「開始收音」繼續廣播。' : '', 'info');
      if (mode === 'viewer') $('joinPanel').hidden = true;
    }
    if (msg.type === 'final') { addEntry(msg.entry); setInterim(); }
    if (msg.type === 'interim' && typeof msg.text === 'string') setInterim(msg.text);
    if (msg.type === 'presence') {
      hostOnline = !!msg.hostOnline;
      if (!hostOnline) setInterim();
      updateUI();
    }
    if (msg.type === 'closed') {
      resetRoom({closed: true}); message('房主已結束此房間。你仍可下載目前保留的字幕。', 'info');
      if (mode === 'viewer') $('joinPanel').hidden = false;
    }
  };
  ws.onclose = event => {
    if (!current()) return;
    clearTimeout(handshakeTimer); stopAudio({discard: true});
    if (!timedOut && (event.code === 1008 || event.code === 1000)) {
      terminal = true; roomState = 'failed'; clearSession();
      if (mode === 'viewer') $('joinPanel').hidden = false;
      updateUI(); message(event.reason || '房間已結束或無法加入。請向房主確認房間代碼與密碼。'); return;
    }
    retryConnection();
  };
  ws.onerror = () => {}; // onclose handles retry and the visible state.
}
async function loadQR() {
  const currentRoom = room;
  $('shareId').textContent = currentRoom.id; $('sharePassword').textContent = currentRoom.password;
  $('sharePanel').hidden = false;
  const response = await request('/api/qr?room=' + currentRoom.id, {headers: {Authorization: 'Bearer ' + currentRoom.hostToken}});
  const blob = await response.blob();
  if (room !== currentRoom) return;
  const previous = $('qr').src;
  if (previous.startsWith('blob:')) URL.revokeObjectURL(previous);
  $('qr').src = URL.createObjectURL(blob);
  $('shareId').textContent = currentRoom.id; $('sharePassword').textContent = currentRoom.password;
  $('sharePanel').hidden = false;
}
async function selectMode(next) {
  if (next === mode || busy) return;
  if (room?.hostToken) return message('請先按「結束房間」，再切換模式。', 'info');
  resetRoom(); mode = next; following = true; unread = 0; setHistory([]); setInterim(); message();
  $('joinPanel').hidden = mode !== 'viewer'; updateUI();
  if (mode !== 'host') return;
  busy = true; updateUI();
  try {
    room = {...await (await request('/api/rooms', {method: 'POST'})).json(), savedAt: Date.now()};
    saveSession();
    await loadQR(); connectRoom();
  } catch (error) {
    if (room?.hostToken) await fetch('/api/rooms/' + room.id, {method: 'DELETE', headers: {Authorization: 'Bearer ' + room.hostToken}}).catch(() => {});
    resetRoom(); mode = 'personal'; placeholder(); message(error.message || '無法建立房間，請確認網路後再試。');
  } finally { busy = false; updateUI(); }
}

async function syncWakeLock() {
  const wanted = $('keepAwake').checked && document.visibilityState === 'visible' && (wantsAudio || (mode === 'viewer' && roomState === 'ready'));
  if (!wanted) { const lock = wakeLock; wakeLock = null; await lock?.release().catch(() => {}); return; }
  if (!navigator.wakeLock || wakeLock || wakePending) return;
  wakePending = true;
  try {
    const lock = await navigator.wakeLock.request('screen');
    wakeLock = lock;
    lock.addEventListener('release', () => { if (wakeLock === lock) wakeLock = null; });
    $('wakeNote').hidden = true;
    if (!$('keepAwake').checked || document.visibilityState !== 'visible' || (!wantsAudio && !(mode === 'viewer' && roomState === 'ready'))) { wakeLock = null; await lock.release(); }
  } catch {
    $('wakeNote').textContent = '目前無法保持螢幕亮起，請留意裝置的自動鎖屏設定。'; $('wakeNote').hidden = false;
  } finally { wakePending = false; }
}

for (const id of ['personal', 'host', 'viewer']) $(id).onclick = () => selectMode(id);
$('start').onclick = startAudio;

const clock = seconds => Number.isFinite(seconds) ? `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, '0')}` : '--:--';
// Audio-file test with Whisper: decode the whole file at 16 kHz, cut it at pauses like the live microphone, and
// send the chunks a few at a time (much faster than playing it in real time).
async function whisperFileTest(file) {
  $('testAudio').value = ''; message('正在讀取音檔…', 'info');
  let samples;
  try {
    const decoded = await new OfflineAudioContext(1, 1, RATE).decodeAudioData(await file.arrayBuffer());
    samples = decoded.getChannelData(0).slice();
    for (let c = 1; c < decoded.numberOfChannels; c++) {
      const channel = decoded.getChannelData(c);
      for (let i = 0; i < samples.length; i++) samples[i] += channel[i];
    }
    if (decoded.numberOfChannels > 1) for (let i = 0; i < samples.length; i++) samples[i] /= decoded.numberOfChannels;
  } catch { return message('無法讀取這個音檔，請改用 mp3、m4a 或 wav。'); }
  const segmenter = createSegmenter(), chunks = [...segmenter.push(samples), ...segmenter.flush()];
  samples = null;
  if (!chunks.length) return message('音檔裡沒有偵測到說話聲。');
  const total = chunks.reduce((n, c) => n + c.length, 0) / RATE;
  await ensurePinyin();  // the first answers arrive within seconds: correct them too
  message(); wantsAudio = true; micState = 'active';
  const state = {failures: 0, preview: '', capture: null, discarded: false, noPreview: true, file: true};
  state.queue = createOrderedQueue(item => deliverWhisper(state, item));
  whisper = state; updateUI();
  let next = 0, finished = 0;
  const progress = () => { $('fileProgress').textContent = `Whisper 音檔辨識中：${finished} / ${chunks.length} 段（說話約 ${clock(total)}）`; };
  $('fileProgress').hidden = false; progress();
  const worker = async () => {
    while (next < chunks.length && whisper === state) { const chunk = chunks[next++]; await sendChunk(state, chunk); finished++; progress(); }
  };
  await Promise.all([worker(), worker(), worker()]);
  $('fileProgress').hidden = true;
  if (whisper === state) { stopAudio(); message(`音檔辨識完成（Whisper，${chunks.length} 段），可以按「下載字幕」。`, 'success'); }
}
$('testAudio').onchange = async () => {
  const file = $('testAudio').files[0];
  if (!file) return;
  if (mode !== 'personal') { $('testAudio').value = ''; return message('音檔測試只能在個人模式使用。'); }
  if (wantsAudio || busy) { $('testAudio').value = ''; return message('請先停止收音，再選擇音檔。'); }
  if (serverSpeech && $('engine').value === 'whisper') return whisperFileTest(file);
  if (!SpeechRecognition) { $('testAudio').value = ''; return message('此瀏覽器不支援語音辨識，請使用桌面版 Chrome 133 以上。'); }
  const audio = new Audio(URL.createObjectURL(file)), context = new AudioContext();
  const output = context.createMediaStreamDestination();
  context.createMediaElementSource(audio).connect(output);  // not connected to the speakers
  audio.ontimeupdate = () => {
    if (fileSource?.audio !== audio) return;  // also skips the playback check before the test starts
    $('fileProgress').textContent = `音檔辨識中：${clock(audio.currentTime)} / ${clock(audio.duration)}｜辨識階段 ${fileStats.sessions} 次｜`
      + `確定字幕 ${fileStats.finals} 句｜錯誤 ${fileStats.errors} 次｜卡住重啟 ${fileStats.stalls} 次`;
  };
  audio.onended = () => {
    diag('audio-ended');
    // Give the recognizer a moment to return the last final result.
    setTimeout(() => { if (fileSource?.audio === audio) { stopAudio(); message('音檔辨識完成，可以按「下載字幕」。', 'success'); } }, 4000);
  };
  // Check the file plays (and unlock playback while the file choice still counts as a user action), then wait:
  // playback starts when the recognition session starts.
  try { await context.resume(); await audio.play(); audio.pause(); audio.currentTime = 0; }
  catch { context.close().catch(() => {}); $('testAudio').value = ''; return message('無法讀取這個音檔，請改用 mp3、m4a 或 wav。'); }
  fileSource = {audio, context, track: output.stream.getAudioTracks()[0], pending: '', failures: 0};
  fileStats = {began: performance.now(), sessions: 0, finals: 0, errors: 0, drops: 0, stalls: 0};
  fileSource.watchdog = setInterval(checkFileStall, 500);
  fileLog = [{type: 'file', name: file.name, duration: +audio.duration.toFixed(1), browser: navigator.userAgent,
    language: $('language').value, phonetic: $('phonetic').checked, sampleRate: context.sampleRate}];
  $('fileProgress').hidden = false; $('diagnostics').hidden = false;
  startAudio();
};
$('stop').onclick = () => stopAudio();
$('diagnostics').onclick = () => {
  if (!fileLog) return;
  const blob = new Blob([fileLog.map(entry => JSON.stringify(entry)).join('\n') + '\n'], {type: 'application/json'});
  const link = document.createElement('a'); link.href = URL.createObjectURL(blob); link.download = '音檔測試診斷紀錄.jsonl'; link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
};
$('reconnect').onclick = () => { retryCount = 0; terminal = false; connectRoom(); };
$('joinForm').onsubmit = event => {
  event.preventDefault(); stopAudio({discard: true}); disconnect(); clearSession();
  terminal = false; retryCount = 0; following = true; unread = 0; setHistory([]); message();
  room = {id: $('roomId').value.trim().toLowerCase(), password: $('password').value.trim(), savedAt: Date.now()};
  connectRoom();
};
$('closeRoom').onclick = async () => {
  if (!room?.hostToken || busy) return;
  busy = true; updateUI();
  try {
    await request('/api/rooms/' + room.id, {method: 'DELETE', headers: {Authorization: 'Bearer ' + room.hostToken}});
    resetRoom({closed: true}); mode = 'personal'; updateUI(); message('房間已結束，仍可下載目前保留的字幕。', 'info');
  } catch (error) {
    if (error.status === 404) { resetRoom({closed: true}); mode = 'personal'; updateUI(); message('房間已到期或結束。', 'info'); }
    else if (error.status === 403) { resetRoom(); mode = 'personal'; updateUI(); message('無法恢復房主權限，已離開此房間，請重新建立房間。', 'info'); }
    else message(error.message);
  } finally { busy = false; updateUI(); }
};
$('copyLink').onclick = async () => {
  if (!room?.viewerToken) return;
  try { await navigator.clipboard.writeText(location.origin + '/?room=' + room.id + '#invite=' + room.viewerToken); message('邀請連結已複製，請只分享給聚會參與者。', 'success'); }
  catch { message('無法複製，請使用房間代碼或 QR Code 分享。'); }
};
$('focusView').onclick = () => {
  const active = document.body.classList.toggle('focus-view');
  $('focusView').setAttribute('aria-pressed', String(active)); $('focusView').textContent = active ? '退出專注' : '專注閱讀';
  if (following) showLatest();
};
document.addEventListener('keydown', event => { if (event.key === 'Escape' && document.body.classList.contains('focus-view')) $('focusView').click(); });
$('keepAwake').onchange = () => { $('wakeNote').hidden = true; void syncWakeLock(); };
$('wakeControl').hidden = !navigator.wakeLock;
document.addEventListener('visibilitychange', () => {
  void syncWakeLock();
  if (document.visibilityState === 'visible' && room && !terminal && roomState !== 'ready' && roomState !== 'connecting') { retryCount = 0; connectRoom(); }
});
window.addEventListener('offline', () => {
  stopAudio({discard: true});
  if (room) { disconnect(); roomState = 'retrying'; updateUI(); }
  message('網路已離線。請確認連線後再開始收音。', 'info');
});
window.addEventListener('online', () => {
  if (room && !terminal) { retryCount = 0; connectRoom(); }
  else message('網路已恢復，可重新開始收音。', 'info');
});

function applyFontSize(value) {
  const size = Number(value);
  if (!Number.isFinite(size) || size < 20 || size > 56) return;
  $('fontSize').value = String(size); $('fontValue').textContent = String(size);
  document.documentElement.style.setProperty('--caption-size', size + 'px');
}
$('fontSize').oninput = () => { applyFontSize($('fontSize').value); try { localStorage.setItem('captionFontSize', $('fontSize').value); } catch {} };
$('saveGlossary').onclick = () => {
  try { localStorage.setItem('churchGlossary', $('glossary').value); message('詞彙表已儲存。', 'success'); }
  catch { message('此瀏覽器無法儲存，詞彙表仍在本次使用期間生效。', 'info'); }
};
$('resetGlossary').onclick = () => { $('glossary').value = startingGlossary.map(pair => pair.join('=')).join('\n'); message('已清空詞彙表（預設為空），按「儲存詞彙表」後保留設定。', 'info'); };
$('export').onclick = () => {
  const blob = new Blob([entries.map(entry => new Date(entry.time).toLocaleTimeString('zh-TW') + ' ' + entry.text).join('\n')], {type: 'text/plain;charset=utf-8'});
  const link = document.createElement('a'); link.href = URL.createObjectURL(blob); link.download = '聚會字幕.txt'; link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
};
// Read-only list of the built-in same-sound terms (the glossary box holds only the host's own additions).
$('builtinTerms').ontoggle = () => {
  if (!$('builtinTerms').open || $('builtinList').childElementCount) return;
  const groups = [
    ['聖經書卷', BIBLE_BOOKS], ['教會專名', CORE_TERMS], ['生命讀經常用專名', LIFE_STUDY_TERMS],
    ['一般詞一律校正', Object.entries(ALWAYS_CORRECTED).map(([heard, term]) => `${heard}→${term}`)],
    ['聖經人名地名', BIBLE_NAMES]
  ];
  for (const [title, list] of groups) {
    const heading = document.createElement('p'), body = document.createElement('p');
    heading.className = 'termGroup'; heading.textContent = `${title}（${list.length}）`;
    body.className = 'hint'; body.textContent = list.join('、');
    $('builtinList').append(heading, body);
  }
};
$('engine').onchange = () => { try { localStorage.setItem('speechEngine', $('engine').value); } catch {} updateUI(); };
$('phonetic').onchange = () => {
  try { localStorage.setItem('phoneticCorrection', $('phonetic').checked ? 'on' : 'off'); } catch {}
  if (wantsAudio) ensurePinyin();
};
let savedGlossary;
try {
  savedGlossary = localStorage.getItem('churchGlossary'); applyFontSize(localStorage.getItem('captionFontSize'));
  $('phonetic').checked = localStorage.getItem('phoneticCorrection') !== 'off';
  if (localStorage.getItem('speechEngine') === 'chrome') $('engine').value = 'chrome';
} catch {}
// A box saved unchanged with the earlier default pairs counts as never edited: it starts empty like everyone's.
const oldDefault = defaultGlossary.map(pair => pair.join('=')).join('\n');
$('glossary').value = savedGlossary == null || savedGlossary.trim() === oldDefault ? startingGlossary.map(pair => pair.join('=')).join('\n') : savedGlossary;

function verseStatus() {
  if (!serverVerses) return '此網站沒有經文資料，讀經時不換成經文';
  if (mode !== 'host') return '讀經時換成恢復本經文：需在廣播房間（房主）使用';
  if (verseState.error) return verseState.error;
  if (verseState.count) return `已載入綱要的經文 ${verseState.count} 節，讀經時換成恢復本原文`;
  return '正在載入綱要的經文…';
}
$('verseAlign').onchange = () => {
  try { localStorage.setItem('verseAlign', $('verseAlign').checked ? 'on' : 'off'); } catch {}
  showOutlineSummary();
};
try { $('verseAlign').checked = localStorage.getItem('verseAlign') !== 'off'; } catch {}
// 本場綱要: saved in this browser only (never sent anywhere); the summary shows what the captions will use.
function showOutlineSummary() {
  const text = $('outline').value;
  if (!text.trim()) { $('outlineSummary').textContent = '未輸入綱要。'; return; }
  if (!commonWords) {
    $('outlineSummary').textContent = '正在讀取綱要…';
    loadPinyinData().then(() => { if (commonWords) showOutlineSummary(); else $('outlineSummary').textContent = '無法載入讀音資料，綱要暫時不會用於校正。'; });
    return;
  }
  const outline = currentOutline();
  const list = (items, limit = 30) => items.slice(0, limit).join('、') + (items.length > limit ? `…等 ${items.length} 個` : '');
  $('outlineSummary').textContent = [
    outline.title ? `篇題：${outline.title}` : '沒有找到篇題（第一行或「第X篇」後面的文字）',
    `經節 ${outline.refs.length} 處`,
    outline.known.length ? `綱要裏的專名 ${outline.known.length} 個（讀音相近也會改正）：${list(outline.known)}` : '綱要裏沒有內建專名',
    outline.terms.length ? `本場新詞 ${outline.terms.length} 個：${list(outline.terms)}` : '沒有新詞',
    ...(outline.refs.length && $('verseAlign').checked ? [verseStatus()] : [])
  ].join('；') + '。';
  ensureVerses();
}
let outlineTimer;
$('outline').oninput = () => {
  clearTimeout(outlineTimer);
  outlineTimer = setTimeout(() => {
    try { localStorage.setItem('meetingOutline', $('outline').value); } catch {}
    showOutlineSummary();
  }, 400);
};
function setOutline(text) {
  $('outline').value = text;
  try { localStorage.setItem('meetingOutline', text); } catch {}
  showOutlineSummary();
}
// A file with several messages (the whole training) lists them; picking one loads only that message.
let outlineParts = [];
function showOutlineParts(parts, selected = 0) {
  outlineParts = parts;
  $('outlinePartLabel').hidden = parts.length < 2;
  $('outlinePart').replaceChildren(...parts.map((part, index) => new Option(part.label, String(index), false, index === selected)));
}
$('outlinePart').onchange = () => {
  const index = Number($('outlinePart').value);
  setOutline(outlineParts[index]?.text || '');
  try { localStorage.setItem('meetingOutlinePart', String(index)); } catch {}
};
$('outlineFile').onchange = async () => {
  const file = $('outlineFile').files[0];
  $('outlineFile').value = '';
  if (!file) return;
  let text, note = '';
  if (/\.pdf$/i.test(file.name) || file.type === 'application/pdf') {
    if (file.size > 150_000_000) { message('PDF 太大（超過 150 MB）。', 'info'); return; }
    message(`正在讀取「${file.name}」…（檔案只在這台電腦處理，不會上傳）`, 'info');
    let stop = false, started = 0;
    $('outlineFile').disabled = true;
    $('stopOutlineOcr').onclick = () => { stop = true; $('stopOutlineOcr').disabled = true; };
    try {
      const {pdfToText} = await import('/outline-pdf.js');
      const pdf = await pdfToText(file, {ocr: true, shouldStop: () => stop, onProgress: (stage, n, total) => {
        if (stage === 'text') { $('outlineSummary').textContent = `正在讀取 PDF：第 ${n}／${total} 頁…`; return; }
        if (n === 1) {
          started = Date.now(); $('stopOutlineOcr').hidden = false; $('stopOutlineOcr').disabled = false;
          message('這是掃描的 PDF，正在這台電腦上辨識文字（第一次使用需下載約 6 MB）。可以先做別的事，請保持此分頁開啟。', 'info');
        }
        const left = n > 1 ? Math.round((Date.now() - started) / (n - 1) * (total - n + 1) / 60000) : null;
        $('outlineSummary').textContent = `正在辨識掃描頁：第 ${n}／${total} 頁${left !== null ? `，約剩 ${Math.max(1, left)} 分鐘` : ''}…`;
      }});
      if (!pdf.ocrPages && pdf.emptyPages > pdf.pages / 2) throw new Error('no text');
      text = pdf.text;
      if (pdf.ocrPages) {
        note = `${pdf.stopped ? `已停止辨識，只載入已辨識的 ${pdf.ocrPages} 頁` : `已辨識 ${pdf.ocrPages} 頁掃描檔`}；瀏覽器辨識可能有錯字，請看一下篇題、專名和經節（要更準確可用 Colab 筆記本 outline_ocr）。`;
      }
    } catch (error) {
      showOutlineSummary();
      message('無法讀取這份 PDF（檔案可能損壞或有密碼）。可改用 Colab 筆記本 outline_ocr 轉成 Markdown。', 'info');
      return;
    } finally {
      $('outlineFile').disabled = false; $('stopOutlineOcr').hidden = true;
    }
  } else {
    if (file.size > 2_000_000) { message('檔案太大（超過 2 MB），請選單篇或整份訓練的綱要 Markdown。', 'info'); return; }
    text = await file.text();
    if (text.includes('\uFFFD')) { message('這個檔案不是 UTF-8 文字，請另存成 UTF-8 的 .txt 或 .md。', 'info'); return; }
  }
  const parts = splitMessages(text);
  try { localStorage.setItem('meetingOutlineFile', parts.length > 1 ? text : ''); localStorage.setItem('meetingOutlinePart', '0'); } catch {}
  showOutlineParts(parts);
  setOutline(parts[0].text);
  message((parts.length > 1 ? `已載入「${file.name}」，共 ${parts.length} 篇；請在下方選當堂這一篇。` : `已載入「${file.name}」。`) + note, 'success');
};
$('clearOutline').onclick = () => {
  setOutline('');
  showOutlineParts([]);
  try { localStorage.removeItem('meetingOutline'); localStorage.removeItem('meetingOutlineFile'); } catch {}
  message('已清除本場綱要。', 'info');
};
try {
  $('outline').value = localStorage.getItem('meetingOutline') || '';
  const file = localStorage.getItem('meetingOutlineFile');
  if (file) showOutlineParts(splitMessages(file), Number(localStorage.getItem('meetingOutlinePart')) || 0);
} catch {}
if ($('outline').value.trim()) showOutlineSummary(); else $('outlineSummary').textContent = '未輸入綱要。';

async function checkServerSpeech() {
  try {
    const health = await (await request('/api/health')).json();
    serverSpeech = health.transcribe === true; serverVerses = health.verses === true;
  } catch { serverSpeech = false; serverVerses = false; }
  $('engine').querySelector('[value=whisper]').disabled = !serverSpeech;
  if (!serverSpeech) { $('engine').value = 'chrome'; $('engineHint').textContent = '此網站目前只提供 Chrome 即時辨識。'; }
}
async function initialize() {
  await checkServerSpeech();
  const queryRoom = new URLSearchParams(location.search).get('room');
  const invite = new URLSearchParams(location.hash.slice(1)).get('invite');
  const saved = readSession();
  if (queryRoom) {
    mode = 'viewer'; $('roomId').value = queryRoom; $('joinPanel').hidden = false;
    if (invite) {
      history.replaceState(null, '', '/?room=' + encodeURIComponent(queryRoom));
      clearSession(); room = {id: queryRoom, invite, savedAt: Date.now()}; connectRoom();
    } else if (saved?.mode === 'viewer' && saved.room.id === queryRoom) { room = saved.room; connectRoom(); }
  } else if (saved) {
    mode = saved.mode; room = saved.room;
    if (mode === 'host') {
      busy = true; roomState = 'connecting'; updateUI();
      try { await loadQR(); connectRoom(); }
      catch (error) {
        if ([403, 404].includes(error.status)) { resetRoom(); mode = 'personal'; message('先前房間已到期或無法恢復，請建立新房間。', 'info'); }
        else { roomState = 'failed'; message('暫時無法恢復房間，請確認網路後按「重新連線」。'); }
      } finally { busy = false; updateUI(); }
    } else { $('roomId').value = room.id; connectRoom(); }
  } else { clearSession(); }
  if (!entries.length) placeholder();
  updateUI();
  if (!SpeechRecognition && !serverSpeech && mode !== 'viewer') message('此瀏覽器不支援收音辨識，請使用桌面版 Chrome；仍可加入房間看字幕。', 'info');
}
void initialize();
