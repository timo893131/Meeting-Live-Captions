import test, {before, after} from 'node:test';
import assert from 'node:assert/strict';
import {chromium, expect} from '@playwright/test';
import {createApp} from '../server.js';

let browser, server, wss, base;
before(async () => {
  const app = createApp(); server = app.server; wss = app.wss;
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  base = 'http://127.0.0.1:' + server.address().port;
  browser = await chromium.launch({headless: true, ...(process.env.CHROMIUM_PATH ? {executablePath: process.env.CHROMIUM_PATH} : {})});
});
after(async () => {
  await browser?.close();
  for (const client of wss?.clients || []) client.terminate();
  if (server) await new Promise(resolve => server.close(resolve));
  wss?.close();
});
async function fixture(t) {
  const context = await browser.newContext();
  const errors = [];
  context.on('page', page => page.on('pageerror', error => errors.push(error.message)));
  await context.addInitScript(() => {
    window.__speechCount = 0;
    window.__wakeRequests = 0; window.__wakeReleases = 0;
    Object.defineProperty(navigator, 'wakeLock', {configurable: true, value: {request: async () => {
      window.__wakeRequests++; const lock = new EventTarget();
      lock.release = async () => { window.__wakeReleases++; lock.dispatchEvent(new Event('release')); };
      return lock;
    }}});
    window.SpeechRecognition = class {
      constructor() { window.__speech = this; window.__speechCount++; this.results = []; }
      start() {}
      stop() { setTimeout(() => this.onend?.(), 0); }
      abort() { setTimeout(() => this.onend?.(), 0); }
      confirmStart() { this.onstart?.(); }
      emit(text, final = true) {
        const result = Object.assign([{transcript: text}], {isFinal: final});
        const index = this.results.length; this.results.push(result);
        this.onresult?.({resultIndex: index, results: this.results});
      }
      repeatFinal() { this.onresult?.({resultIndex: this.results.length - 1, results: this.results}); }
      end() { this.onend?.(); }
      fail(error) { this.onerror?.({error}); }
    };
    const NativeSocket = window.WebSocket;
    window.WebSocket = class extends NativeSocket {
      constructor(...args) { super(...args); window.__socket = this; }
    };
    Object.defineProperty(navigator, 'clipboard', {value: {writeText: async text => { window.__copied = text; }}});
  });
  t.after(async () => {
    for (const page of context.pages()) {
      const saved = await page.evaluate(() => JSON.parse(sessionStorage.getItem('meetingCaptionRoom'))).catch(() => null);
      if (saved?.mode === 'host') await fetch(base + '/api/rooms/' + saved.room.id, {method: 'DELETE', headers: {Authorization: 'Bearer ' + saved.room.hostToken}}).catch(() => {});
    }
    await context.close(); assert.deepEqual(errors, []);
  });
  const page = await context.newPage(); await page.goto(base); return {context, page};
}
async function start(page) {
  await page.locator('#start').click(); await page.evaluate(() => window.__speech.confirmStart());
  await expect(page.locator('#micStatus')).toHaveText('收音中');
}
async function hostRoom(page) {
  await page.locator('#host').click(); await expect(page.locator('#status')).toHaveText('房間已連線');
  await expect(page.locator('#start')).toBeEnabled();
}

test('microphone state waits for actual startup, deduplicates final results, and rejects stale callbacks', async t => {
  const {page} = await fixture(t);
  await page.locator('#start').click();
  await expect(page.locator('#micStatus')).toHaveText('正在啟動麥克風');
  await page.evaluate(() => { window.__speech.confirmStart(); window.__speech.emit('耶蘇說阿門'); window.__speech.repeatFinal(); });
  await expect(page.locator('#captions p')).toHaveCount(1);
  await expect(page.locator('#captions')).toContainText('耶穌說阿們');
  await page.evaluate(() => { window.__oldSpeech = window.__speech; window.__speech.fail('not-allowed'); window.__oldSpeech.end(); });
  await expect(page.locator('#message')).toContainText('麥克風未獲允許');
  await expect(page.locator('#start')).toBeEnabled();
  await page.locator('#start').click();
  await page.evaluate(() => { window.__oldSpeech.confirmStart(); window.__oldSpeech.emit('過期事件'); });
  await expect(page.locator('#micStatus')).toHaveText('正在啟動麥克風');
  await expect(page.locator('#captions p')).toHaveCount(1);
  await page.evaluate(() => window.__speech.confirmStart());
  await page.locator('#stop').click();
  await expect(page.locator('#stop')).toBeDisabled();
});

test('reading history keeps scroll and focus; latest, font persistence and focus mode work', async t => {
  const {page} = await fixture(t); await start(page);
  await page.evaluate(() => {
    for (let i = 0; i < 50; i++) window.__speech.emit('平安與恩典，第 ' + i + ' 段聚會字幕。');
    const captions = document.getElementById('captions'); captions.scrollTop = 20; captions.focus();
  });
  await expect(page.locator('#latest')).toBeVisible();
  const top = await page.locator('#captions').evaluate(element => element.scrollTop);
  await page.evaluate(() => window.__speech.emit('新的字幕不應搶走閱讀位置。'));
  assert.equal(await page.locator('#captions').evaluate(element => element.scrollTop), top);
  assert.equal(await page.evaluate(() => document.activeElement.id), 'captions');
  await page.locator('#latest').click(); await expect(page.locator('#latest')).toBeHidden();
  assert.ok(await page.locator('#captions').evaluate(element => element.scrollHeight - element.scrollTop - element.clientHeight < 2));
  await page.locator('#fontSize').fill('40');
  await expect(page.locator('#fontValue')).toHaveText('40');
  await page.locator('#focusView').click(); await expect(page.locator('.intro')).toBeHidden();
  await page.keyboard.press('Escape'); await expect(page.locator('.intro')).toBeVisible();
  await page.reload(); await expect(page.locator('#fontSize')).toHaveValue('40');
});

test('invite/password joins, reload recovery, transient disconnect and closure preserve correct state', async t => {
  const {context, page: host} = await fixture(t); await hostRoom(host);
  await expect(host.locator('#qr')).toBeVisible();
  assert.ok(await host.locator('#qr').evaluate(image => image.complete && image.naturalWidth > 0));
  const id = await host.locator('#shareId').textContent();
  const password = await host.locator('#sharePassword').textContent();
  const viewer = await context.newPage(); await viewer.goto(base + '/?room=' + id);
  await viewer.locator('#password').fill('incorrect'); await viewer.locator('#joinButton').click();
  await expect(viewer.locator('#message')).toContainText('房間或密碼錯誤');
  await viewer.locator('#password').fill(password); await viewer.locator('#joinButton').click();
  await expect(viewer.locator('#status')).toHaveText('房間已連線');
  await start(host); await host.evaluate(() => window.__speech.emit('創世紀與耶蘇'));
  await expect(viewer.locator('#captions')).toContainText('創世記與耶穌');
  await viewer.reload(); await expect(viewer.locator('#status')).toHaveText('房間已連線');
  await expect(viewer.locator('#captions')).toContainText('創世記與耶穌');
  await host.locator('#copyLink').click();
  const invite = await host.evaluate(() => window.__copied);
  const invited = await context.newPage(); await invited.goto(invite);
  await expect(invited.locator('#status')).toHaveText('房間已連線');
  assert.equal(new URL(invited.url()).hash, '');
  await host.evaluate(() => window.__socket.close(4000, 'test-disconnect'));
  await expect(host.locator('#status')).toHaveText('房間已連線');
  await expect(host.locator('#start')).toBeEnabled(); await expect(host.locator('#stop')).toBeDisabled();
  await expect(host.locator('#message')).toContainText('重新連線');
  await host.reload(); await expect(host.locator('#status')).toHaveText('房間已連線');
  assert.equal(await host.locator('#shareId').textContent(), id);
  await expect(host.locator('#start')).toBeEnabled();
  await start(host); await host.evaluate(() => window.__speech.emit('恢復後的字幕'));
  await expect(viewer.locator('#captions')).toContainText('恢復後的字幕');
  await host.locator('#closeRoom').click();
  await expect(viewer.locator('#status')).toHaveText('房間已結束');
  await expect(viewer.locator('#export')).toBeEnabled();
  await expect(host.locator('#status')).toHaveText('房間已結束');
  assert.equal(await host.evaluate(() => sessionStorage.getItem('meetingCaptionRoom') === null), true);
});

test('silence does not raise an error; repeated short recognition failures stop retrying', async t => {
  const {page} = await fixture(t); await start(page);
  await page.evaluate(() => window.__speech.fail('no-speech')); await expect(page.locator('#message')).toBeHidden();
  for (let i = 1; i <= 5; i++) {
    await page.evaluate(() => window.__speech.end());
    if (i < 5) await page.waitForFunction(count => window.__speechCount === count, i + 1);
  }
  await expect(page.locator('#message')).toContainText('停止自動重試');
  await expect(page.locator('#start')).toBeEnabled();
  assert.equal(await page.evaluate(() => window.__speechCount), 5);
});

test('failed room creation restores personal controls and leaves no saved room', async t => {
  const {page} = await fixture(t);
  await page.route('**/api/rooms', route => route.fulfill({status: 503, contentType: 'application/json', body: JSON.stringify({error: '暫時無法建立房間'})}));
  await page.locator('#host').click(); await expect(page.locator('#message')).toContainText('暫時無法建立');
  await expect(page.locator('#personal')).toHaveAttribute('aria-pressed', 'true');
  await expect(page.locator('#start')).toBeEnabled(); await expect(page.locator('#sharePanel')).toBeHidden();
  assert.equal(await page.evaluate(() => sessionStorage.getItem('meetingCaptionRoom') === null), true);
});


test('connection retries stop at the limit and offer a manual recovery action', async t => {
  const {page} = await fixture(t);
  await page.clock.install();
  await page.evaluate(() => {
    window.__socketAttempts = 0;
    window.WebSocket = class {
      static OPEN = 1;
      constructor() {
        window.__socketAttempts++; this.readyState = 0;
        setTimeout(() => { this.readyState = 1; this.onopen?.(); }, 0);
      }
      send() { setTimeout(() => { this.readyState = 3; this.onclose?.({code: 1006}); }, 1); }
      close() { this.readyState = 3; }
    };
  });
  await page.locator('#host').click();
  await expect(page.locator('#sharePanel')).toBeVisible();
  await page.clock.runFor(20000);
  await expect(page.locator('#status')).toHaveText('房間未連線');
  await expect(page.locator('#reconnect')).toBeVisible();
  await expect(page.locator('#start')).toBeDisabled();
  assert.equal(await page.evaluate(() => window.__socketAttempts), 6);
  await page.clock.runFor(30000);
  assert.equal(await page.evaluate(() => window.__socketAttempts), 6);
});

test('desktop/mobile long subtitles stay within viewport and keyboard controls remain usable', async t => {
  const {page} = await fixture(t);
  for (const width of [1280, 390, 320]) {
    await page.setViewportSize({width, height: 844});
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  }
  await start(page);
  await page.locator('#fontSize').fill('56');
  await page.evaluate(() => window.__speech.emit('1234567890'.repeat(50)));
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await page.locator('#focusView').focus(); await page.keyboard.press('Enter');
  await expect(page.locator('#focusView')).toHaveAttribute('aria-pressed', 'true');
  assert.ok(await page.locator('.toolbar').evaluate(element => element.getBoundingClientRect().bottom <= innerHeight));
  await page.keyboard.press('Escape');
  await expect(page.locator('#focusView')).toHaveAttribute('aria-pressed', 'false');
  if (process.env.UI_SCREENSHOT_DIR) {
    await page.reload(); await start(page);
    await page.evaluate(() => {
      window.__speech.emit('願主的平安與你們同在。');
      window.__speech.emit('我們一同禱告，領受恩典。');
      window.__speech.emit('讓我們一起聆聽今天的信息。', false);
    });
    await page.setViewportSize({width: 1280, height: 900});
    await page.locator('#fontSize').fill('30');
    await page.screenshot({path: process.env.UI_SCREENSHOT_DIR + '/desktop.png', fullPage: true});
    await page.setViewportSize({width: 390, height: 844});
    await page.screenshot({path: process.env.UI_SCREENSHOT_DIR + '/mobile.png', fullPage: true});
    await page.locator('#focusView').click();
    await page.screenshot({path: process.env.UI_SCREENSHOT_DIR + '/mobile-focus.png', fullPage: true});
  }
});


test('screen wake lock follows the user control and is released when audio stops', async t => {
  const {page} = await fixture(t);
  await page.locator('#keepAwake').uncheck(); await start(page);
  assert.equal(await page.evaluate(() => window.__wakeRequests), 0);
  await page.locator('#keepAwake').check();
  await page.waitForFunction(() => window.__wakeRequests === 1);
  await page.locator('#stop').click();
  await page.waitForFunction(() => window.__wakeReleases === 1);
});

test('expired host session falls back to a usable personal mode', async t => {
  const {page} = await fixture(t); await hostRoom(page);
  await page.evaluate(() => { window.__savedRoom = sessionStorage.getItem('meetingCaptionRoom'); });
  await page.locator('#closeRoom').click(); await expect(page.locator('#status')).toHaveText('房間已結束');
  await page.evaluate(() => sessionStorage.setItem('meetingCaptionRoom', window.__savedRoom));
  await page.reload();
  await expect(page.locator('#message')).toContainText('先前房間已到期');
  await expect(page.locator('#personal')).toHaveAttribute('aria-pressed', 'true');
  await expect(page.locator('#start')).toBeEnabled();
  assert.equal(await page.evaluate(() => sessionStorage.getItem('meetingCaptionRoom') === null), true);
});
