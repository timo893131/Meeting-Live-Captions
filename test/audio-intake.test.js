import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,writeFile,readFile,rm,symlink} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {inspectAudio,draftRecord} from '../scripts/prepare-audio-intake.mjs';
const template=JSON.parse(await readFile(new URL('../docs/templates/audio-segment.example.json',import.meta.url)));
const approved=JSON.parse(await readFile(new URL('../evaluation/glossary/approved-targets.json',import.meta.url)));
test('approved target scope does not enable replacements or training',()=>{
 assert.equal(approved.review.status,'target_scope_approved');assert.equal(approved.automatic_replacements,'not_reviewed');assert.equal(approved.training_ready,false);
 const terms=approved.targets.flatMap(r=>r.terms);assert.equal(terms.length,26);assert.equal(new Set(terms).size,terms.length);
 assert.deepEqual(approved.targets.find(r=>r.category==='local_names').terms,[]);
});
test('intake probes real bytes but leaves human metadata and rights incomplete',async()=>{
 const root=await mkdtemp(path.join(tmpdir(),'meeting-intake-'));
 try {
  const wav=Buffer.alloc(32044);wav.write('RIFF');wav.writeUInt32LE(32036,4);wav.write('WAVEfmt ',8);wav.writeUInt32LE(16,16);wav.writeUInt16LE(1,20);wav.writeUInt16LE(1,22);wav.writeUInt32LE(16000,24);wav.writeUInt32LE(32000,28);wav.writeUInt16LE(2,32);wav.writeUInt16LE(16,34);wav.write('data',36);wav.writeUInt32LE(32000,40);
  await writeFile(path.join(root,'sample.wav'),wav);
  const audio=await inspectAudio(root,'sample.wav');assert.equal(audio.raw_sha256,createHash('sha256').update(wav).digest('hex'));assert.equal(audio.duration_seconds,1);assert.equal(audio.sample_rate_hz,16000);
  const record=draftRecord(audio,0,template);assert.equal(record.example_only,false);assert.equal(record.reference.status,'pending');assert.equal(record.rights.status,'pending');assert.equal(record.session_id,null);assert.equal(record.split,'unassigned');assert.equal(template.example_only,true);
  await assert.rejects(inspectAudio(root,path.join(root,'sample.wav')),/relative/);
  await symlink('/etc/hosts',path.join(root,'escape'));await assert.rejects(inspectAudio(root,'escape'),/outside/);
  await writeFile(path.join(root,'broken.mp3'),'not audio');await assert.rejects(inspectAudio(root,'broken.mp3'));
  const script=fileURLToPath(new URL('../scripts/prepare-audio-intake.mjs',import.meta.url));
  const output=path.join(root,'output');const args=[script,'--root',root,'--audio','sample.wav','--output',output];
  const run=spawnSync(process.execPath,args,{encoding:'utf8'});assert.equal(run.status,0,run.stderr);
  const report=JSON.parse(await readFile(path.join(output,'intake-report.json'),'utf8'));assert.equal(report.asr_run,false);assert.equal(report.training_run,false);assert.equal(report.total_file_seconds,1);
  const manifest=JSON.parse((await readFile(path.join(output,'draft-manifest.jsonl'),'utf8')).trim());assert.equal(manifest.audio.raw_sha256,audio.raw_sha256);
  const again=spawnSync(process.execPath,args,{encoding:'utf8'});assert.equal(again.status,1);
  const duplicate=spawnSync(process.execPath,[script,'--root',root,'--audio','sample.wav','--audio','sample.wav','--output',path.join(root,'duplicate')],{encoding:'utf8'});assert.equal(duplicate.status,1);
 } finally {await rm(root,{recursive:true,force:true});}
});
