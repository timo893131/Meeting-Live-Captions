import test from 'node:test';
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {mkdtempSync, mkdirSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';

test('term miner proposes a same-sound term that fixes recognizer output and leaves correct text alone', () => {
  const root = mkdtempSync(join(tmpdir(), 'mine-')), corpus = join(root, 'corpus'), run = join(root, 'run'), refs = join(root, 'refs');
  for (const dir of [corpus, run, refs]) mkdirSync(dir);
  writeFileSync(join(corpus, 'a.txt'), '基督在第三層天上登寶座，為全宇宙的元首。\n'.repeat(50) + '燈台是見證。\n'.repeat(50));
  writeFileSync(join(refs, '01.txt'), '基督登寶座。基督登寶座。');
  writeFileSync(join(run, '01.whisper_live_vad_10s.json'), JSON.stringify({raw: ['基督燈寶座', '他的燈寶座以後']}));
  const out = execFileSync(process.execPath, ['scripts/mine-same-sound-terms.mjs', '--run', run, '--refs', refs, '--corpus', corpus], {encoding: 'utf8'});
  const row = out.split('\n').find(line => line.startsWith('| 登寶座 |'));
  assert.ok(row, out);
  const cells = row.split('|').map(c => c.trim());
  assert.equal(cells[3], '2');            // fixes
  assert.equal(cells[6], '0');            // no false edits on the correct text (燈台 stays)
  assert.match(row, /燈寶座×2/);
  assert.match(row, /加入/);
});
