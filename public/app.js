import {defaultGlossary, parseGlossary, correctText} from '/glossary.js';

const $ = id => document.getElementById(id);
const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
const SESSION_KEY = 'meetingCaptionRoom';
const MAX_RETRIES = 5;
let mode = 'personal', room = null, socket = null, roomState = 'none', hostOnline = false;
let entries = [], following = true, unread = 0, busy = false, terminal = false;
let generation = 0, retryCount = 0, reconnectTimer = null, handshakeTimer = null;
let recognition = null, wantsAudio = false, speechGeneration = 0, restartTimer = null, shortEnds = 0;
let micState = 'idle', wakeLock = null, wakePending = false;

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
  $('start').disabled = busy || wantsAudio || !SpeechRecognition || (mode === 'host' && roomState !== 'ready');
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
    active: ['收音中', 'active'], restarting: ['正在恢復收音', 'warning'], error: ['收音已停止', 'error']
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
function beginRecognition(run) {
  if (!wantsAudio || run !== speechGeneration) return;
  if (mode === 'host' && roomState !== 'ready') { stopAudio({discard: true}); return; }
  const rec = new SpeechRecognition(); recognition = rec;
  rec.lang = $('language').value; rec.continuous = true; rec.interimResults = true;
  const startedAt = Date.now();
  const completedResults = new Set();
  const current = () => run === speechGeneration && recognition === rec;
  rec.onstart = () => { if (current() && wantsAudio) { micState = 'active'; updateUI(); } };
  rec.onresult = event => {
    if (!current()) return;
    let interim = '';
    const glossary = parseGlossary($('glossary').value);
    for (let i = event.resultIndex; i < event.results.length; i++) {
      const result = event.results[i], text = correctText(result[0].transcript, glossary);
      if (result.isFinal) {
        if (!completedResults.has(i)) { completedResults.add(i); sendCaption(text, true); }
      } else if (wantsAudio) interim += text;
    }
    sendCaption(interim, false);
  };
  rec.onerror = event => {
    if (!current() || !wantsAudio || event.error === 'no-speech') return;
    stopAudio({discard: true, error: true});
    message(speechErrors[event.error] || '語音辨識已停止，請確認麥克風與網路，再按開始收音。');
  };
  rec.onend = () => {
    if (!current()) return;
    recognition = null;
    if (!wantsAudio) return;
    shortEnds = Date.now() - startedAt < 1000 ? shortEnds + 1 : 0;
    if (shortEnds >= 5) {
      stopAudio({discard: true, error: true});
      message('語音服務連續中斷，已停止自動重試。請檢查網路與瀏覽器後重新開始收音。');
      return;
    }
    micState = 'restarting'; updateUI();
    restartTimer = setTimeout(() => beginRecognition(run), 500);
  };
  try { rec.start(); } catch {
    stopAudio({discard: true, error: true}); message('無法啟動語音辨識，請確認麥克風權限後再試。');
  }
}
function startAudio() {
  if (wantsAudio || busy) return;
  if (!SpeechRecognition) return message('此瀏覽器不支援收音辨識，請使用桌面版 Chrome；仍可加入房間看字幕。');
  if (!window.isSecureContext) return message('麥克風需要 HTTPS，請使用安全的網站網址。');
  if (mode === 'host' && roomState !== 'ready') return message('房間尚未連線，請等待連線完成。');
  message(); wantsAudio = true; shortEnds = 0; micState = 'starting';
  const run = ++speechGeneration;
  updateUI(); beginRecognition(run);
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
$('stop').onclick = () => stopAudio();
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
$('resetGlossary').onclick = () => { $('glossary').value = defaultGlossary.map(pair => pair.join('=')).join('\n'); message('已恢復預設詞彙，按「儲存詞彙表」後保留設定。', 'info'); };
$('export').onclick = () => {
  const blob = new Blob([entries.map(entry => new Date(entry.time).toLocaleTimeString('zh-TW') + ' ' + entry.text).join('\n')], {type: 'text/plain;charset=utf-8'});
  const link = document.createElement('a'); link.href = URL.createObjectURL(blob); link.download = '聚會字幕.txt'; link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
};
let savedGlossary;
try { savedGlossary = localStorage.getItem('churchGlossary'); applyFontSize(localStorage.getItem('captionFontSize')); } catch {}
$('glossary').value = savedGlossary ?? defaultGlossary.map(pair => pair.join('=')).join('\n');

async function initialize() {
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
  if (!SpeechRecognition && mode !== 'viewer') message('此瀏覽器不支援收音辨識，請使用桌面版 Chrome；仍可加入房間看字幕。', 'info');
}
void initialize();
