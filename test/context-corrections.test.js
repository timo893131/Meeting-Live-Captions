import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile,mkdtemp,rm} from 'node:fs/promises';
import path from 'node:path';
import {tmpdir} from 'node:os';
import {spawnSync} from 'node:child_process';
import {proposeText,proposeReport,validateRules} from '../scripts/propose-context-corrections.mjs';
const config=JSON.parse(await readFile(new URL('../evaluation/glossary/context-review-rules.json',import.meta.url)));
const example=rules=>({version:'test',status:'development_review_only',productionEligible:false,rules});
const asr=segments=>({status:'machine_generated',reference_used_as_prompt:false,glossary_applied:false,audio_sha256:'a'.repeat(64),segments});

test('authored church-context positives keep original text and pending decisions',()=>{
 const cases=[['門徒倒不靜時','門徒倒不禁食'],['主耶穌是高揚','主耶穌是羔羊'],['除去我們罪的高揚','除去我們罪的羔羊'],['高揚是救贖主','羔羊是救贖主'],['用靈為我們施敬','用靈為我們施浸'],['我們是同女','我們是童女'],['我們都必須是同女','我們都必須是童女'],['詔會的聚會','召會的聚會']];
 for(const [input,expected] of cases) {
  const result=proposeText(input,config);assert.equal(result.rawText,input);assert.equal(result.suggestedText,expected);assert.ok(result.suggestions.every(s=>s.decision==='pending'));
 }
});
test('general language and insufficient context are preserved',()=>{
 for(const input of ['高揚的妻子正在散步','婚姻需要彼此尊重','明天舉行消防演習','同女兒一起吃飯','這段文字提到靜時','高揚的妻','我們曾經提到同女','我們是同，女','門徒倒不靜 時']) {
  assert.equal(proposeText(input,config).suggestedText,input);
  assert.equal(proposeText(input,config).suggestions.length,0);
 }
});
test('Unicode positions, repeated occurrences and non-cascading rules remain exact',()=>{
 const result=proposeText('😀主耶穌是高揚，主耶穌是高揚',config);
 assert.equal(result.suggestions.length,2);assert.equal(result.suggestions[0].startCodePoint,5);assert.equal(result.suggestions[0].endCodePoint,7);
 const rules=example([{id:'first',source:'甲',target:'乙',contexts:[{before:'說'}]},{id:'second',source:'乙',target:'丙',contexts:[{before:'說'}]}]);
 assert.equal(proposeText('說甲與說乙',rules).suggestedText,'說乙與說丙');
 const both=example([{id:'both',source:'甲',target:'乙',contexts:[{before:'左',after:'右'}]}]);
 assert.equal(proposeText('左甲右',both).suggestedText,'左乙右');assert.equal(proposeText('左甲別',both).suggestedText,'左甲別');
});
test('ambiguous, unconditional and malformed rules fail rather than silently select',()=>{
 const rule={id:'one',source:'甲',target:'乙',contexts:[{before:'說'}]};
 assert.throws(()=>validateRules(example([{...rule,contexts:[{}]}])));
 assert.throws(()=>validateRules(example([rule,{...rule}])));
 assert.throws(()=>validateRules({...config,productionEligible:true}));
 assert.throws(()=>proposeText('說甲',example([rule,{...rule,id:'two',target:'丙'}])),/overlapping/);
 assert.throws(()=>proposeText('x'.repeat(501),config));
});
test('private ASR report does not cross segment boundaries or claim measured accuracy',()=>{
 const rows=[{id:1,start:0,end:1,text:'主耶穌是'},{id:2,start:1,end:2,text:'高揚'}];
 const result=proposeReport(asr(rows),config);assert.equal(result.summary.suggestions,0);assert.equal(result.accuracyMeasured,false);assert.equal(result.cer,null);assert.equal(result.productionEligible,false);
 assert.throws(()=>proposeReport(asr([rows[0],rows[0]]),config));
 assert.throws(()=>proposeReport({...asr(rows),reference_used_as_prompt:true},config));
 assert.throws(()=>proposeReport(asr([{...rows[0],end:NaN}]),config));
});
test('CLI creates lossless artifacts without overwriting review output',async()=>{
 const root=await mkdtemp(path.join(tmpdir(),'context-review-'));
 try {
  const {writeFile}=await import('node:fs/promises');
  const input=path.join(root,'input.json');await writeFile(input,JSON.stringify(asr([{id:0,start:0,end:1,text:'主耶穌是高揚'}])));
  const args=['scripts/propose-context-corrections.mjs','--asr',input,'--rules','evaluation/glossary/context-review-rules.json','--output',path.join(root,'review')];
  const result=spawnSync(process.execPath,args,{encoding:'utf8'});assert.equal(result.status,0,result.stderr);
  const report=JSON.parse(await readFile(path.join(root,'review/suggestions.json'),'utf8'));assert.equal(report.summary.suggestions,1);assert.match(report.inputSha256,/^[a-f0-9]{64}$/);assert.equal(report.rows[0].rawText,'主耶穌是高揚');
  const again=spawnSync(process.execPath,args,{encoding:'utf8'});assert.equal(again.status,1);
 } finally {await rm(root,{recursive:true,force:true});}
});
