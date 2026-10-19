import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,writeFile,readFile,rm} from 'node:fs/promises';
import path from 'node:path';
import {tmpdir} from 'node:os';
import {spawnSync} from 'node:child_process';
import {applyDecisions,hash,toSrt} from '../scripts/apply-context-decisions.mjs';
import {proposeReport} from '../scripts/propose-context-corrections.mjs';
const encode=obj=>Buffer.from(JSON.stringify(obj));
function fixture() {
 const asr={status:'machine_generated',reference_used_as_prompt:false,glossary_applied:false,audio_sha256:'a'.repeat(64),segments:[{id:0,start:59.9996,end:61.25,text:'😀說甲與丙完'},{id:1,start:62,end:63,text:'無建議'}]};
 const rules={version:'synthetic-test',status:'development_review_only',productionEligible:false,rules:[{id:'first',source:'甲',target:'乙乙',contexts:[{before:'說'}]},{id:'second',source:'丙',target:'丁',contexts:[{after:'完'}]}]};
 const input=encode(asr),ruleBytes=encode(rules),proposal={...proposeReport(asr,rules),inputSha256:hash(input),rulesSha256:hash(ruleBytes)};
 const review={schemaVersion:'context-review-decisions-1',audioSha256:asr.audio_sha256,inputSha256:hash(input),rulesSha256:hash(ruleBytes),reviewer:'synthetic-reviewer',exportedAt:'2026-10-19T00:00:00Z',goldReferenceAvailable:false,accuracyMeasured:false,productionEligible:false,sourceCoverage:'suggested_segments_only',decisions:[{segmentId:0,items:proposal.rows[0].suggestions.map((s,i)=>({...s,decision:i?'rejected':'accepted'}))}]};
 return {input,ruleBytes,proposal,review};
}
const run=f=>applyDecisions(f.input,f.ruleBytes,encode(f.proposal),encode(f.review));
test('only accepted occurrences change; Unicode offsets and original evidence survive',()=>{
 const f=fixture(),report=run(f);
 assert.equal(report.segments[0].rawText,'😀說甲與丙完');assert.equal(report.segments[0].text,'😀說乙乙與丙完');assert.equal(report.segments[1].text,'無建議');
 assert.deepEqual(report.summary,{segments:2,changedSegments:1,accepted:1,rejected:1,pending:0});
 assert.equal(report.goldReferenceAvailable,false);assert.equal(report.accuracyMeasured,false);assert.equal(report.productionEligible,false);assert.equal(report.cer,null);
 f.review.decisions[0].items[0].decision='pending';assert.equal(run(f).segments[0].text,'😀說甲與丙完');
});
test('stale audio, input, or rules provenance is rejected',()=>{
 for(const field of ['audioSha256','inputSha256','rulesSha256']) {
  const f=fixture();f.review[field]='b'.repeat(64);assert.throws(()=>run(f),/Provenance mismatch/);
 }
 const f=fixture();f.proposal.rows[0].rawText='tampered';assert.throws(()=>run(f),/Proposal differs/);
});
test('missing, repeated, foreign, edited or incomplete decisions fail closed',()=>{
 const edits=[r=>r.decisions=[],r=>r.decisions.push(r.decisions[0]),r=>r.decisions[0].segmentId=999,r=>r.decisions[0].items.pop(),r=>r.decisions[0].items[0].source='其他',r=>r.decisions[0].items[0].suggested='未提議內容',r=>r.decisions[0].items[0].startCodePoint++,r=>r.decisions[0].items[0].decision='__proto__',r=>r.decisions[0].items[1]={...r.decisions[0].items[0]},r=>r.goldReferenceAvailable=true,r=>r.reviewer=''];
 for(const edit of edits) {const f=fixture();edit(f.review);assert.throws(()=>run(f));}
});
test('subtitle formatting preserves edited text and rounds timestamp rollovers',()=>{
 const srt=toSrt(run(fixture()).segments);assert.match(srt,/00:01:00,000 --> 00:01:01,250/);assert.ok(srt.includes('😀說乙乙與丙完'));assert.ok(srt.includes('00:01:02,000 --> 00:01:03,000'));
});
test('CLI saves immutable artifacts and exact review bytes',async()=>{
 const root=await mkdtemp(path.join(tmpdir(),'apply-context-'));
 try {
  const f=fixture(),files={'asr.json':f.input,'rules.json':f.ruleBytes,'proposals.json':encode(f.proposal),'decisions.json':encode(f.review)};
  await Promise.all(Object.entries(files).map(([name,bytes])=>writeFile(path.join(root,name),bytes)));
  const args=['scripts/apply-context-decisions.mjs','--asr',path.join(root,'asr.json'),'--rules',path.join(root,'rules.json'),'--proposals',path.join(root,'proposals.json'),'--decisions',path.join(root,'decisions.json'),'--output',path.join(root,'result')];
  const result=spawnSync(process.execPath,args,{encoding:'utf8'});assert.equal(result.status,0,result.stderr);
  assert.deepEqual(await readFile(path.join(root,'result/review-decisions.json')),files['decisions.json']);
  const saved=await readFile(path.join(root,'result/reviewed-corrections.json'));assert.match(await readFile(path.join(root,'result/corrected-transcript.txt'),'utf8'),/😀說乙乙與丙完/);
  assert.equal(spawnSync(process.execPath,args,{encoding:'utf8'}).status,1);assert.deepEqual(await readFile(path.join(root,'result/reviewed-corrections.json')),saved);
 } finally {await rm(root,{recursive:true,force:true});}
});
