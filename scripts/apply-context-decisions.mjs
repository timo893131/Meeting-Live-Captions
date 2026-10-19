import {readFile,mkdir,writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {isDeepStrictEqual} from 'node:util';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {proposeReport} from './propose-context-corrections.mjs';
export const hash=bytes=>createHash('sha256').update(bytes).digest('hex');
const identity=s=>JSON.stringify([s.ruleId,s.startCodePoint,s.endCodePoint,s.source,s.suggested]);
export function applyDecisions(asrBytes,rulesBytes,proposalBytes,decisionBytes) {
  const asr=JSON.parse(asrBytes),rules=JSON.parse(rulesBytes),proposal=JSON.parse(proposalBytes),decision=JSON.parse(decisionBytes);
  const expected=proposeReport(asr,rules);
  for(const [key,value] of Object.entries({audioSha256:asr.audio_sha256,inputSha256:hash(asrBytes),rulesSha256:hash(rulesBytes)})) {
    if(proposal[key]!==value || decision[key]!==value) throw new Error(`Provenance mismatch: ${key}`);
  }
  if(proposal.status!=='pending_human_review' || proposal.productionEligible!==false || !isDeepStrictEqual(expected.rows,proposal.rows)) throw new Error('Proposal differs from original ASR and current rule evidence');
  if(decision.schemaVersion!=='context-review-decisions-1' || decision.sourceCoverage!=='suggested_segments_only' || decision.goldReferenceAvailable!==false || decision.accuracyMeasured!==false || decision.productionEligible!==false || typeof decision.reviewer!=='string' || !decision.reviewer.trim() || decision.reviewer.length>100 || typeof decision.exportedAt!=='string' || !Number.isFinite(Date.parse(decision.exportedAt)) || !Array.isArray(decision.decisions)) throw new Error('Invalid review metadata or unsupported review scope');
  const expectedRows=new Map(expected.rows.filter(r=>r.suggestions.length).map(r=>[r.id,r]));
  const reviewed=new Map(),seenRows=new Set();const counts={accepted:0,rejected:0,pending:0};
  for(const row of decision.decisions) {
    const source=expectedRows.get(row?.segmentId);
    if(!source || seenRows.has(row.segmentId) || !Array.isArray(row.items) || row.items.length!==source.suggestions.length) throw new Error('Missing, duplicate or unknown decision segment');
    seenRows.add(row.segmentId);const allowed=new Set(source.suggestions.map(identity)),seen=new Set();
    for(const item of row.items) {
      if(!item || !Object.hasOwn(counts,item.decision) || !allowed.has(identity(item)) || seen.has(identity(item))) throw new Error('Unknown, duplicate or changed suggestion');
      seen.add(identity(item));counts[item.decision]++;
    }
    reviewed.set(row.segmentId,new Map(row.items.map(item=>[identity(item),item.decision])));
  }
  if(seenRows.size!==expectedRows.size) throw new Error('Review must include every proposed segment; use pending for undecided items');
  const segments=expected.rows.map(row=>{
    const characters=Array.from(row.rawText),ledger=[];let cursor=0,text='';
    for(const suggestion of row.suggestions) {
      const state=reviewed.get(row.id).get(identity(suggestion));
      text+=characters.slice(cursor,suggestion.startCodePoint).join('')+(state==='accepted'?suggestion.suggested:suggestion.source);
      cursor=suggestion.endCodePoint;ledger.push({...suggestion,decision:state});
    }
    text+=characters.slice(cursor).join('');
    return {id:row.id,start:row.start,end:row.end,rawText:row.rawText,text,referenceStatus:'not_fully_verified',reviewedSuggestions:ledger};
  });
  return {schemaVersion:'reviewed-occurrence-corrections-1',status:'occurrence_decisions_applied',audioSha256:asr.audio_sha256,inputSha256:hash(asrBytes),rulesSha256:hash(rulesBytes),proposalSha256:hash(proposalBytes),decisionSha256:hash(decisionBytes),reviewer:decision.reviewer,reviewExportedAt:decision.exportedAt,createdAt:new Date().toISOString(),segments,summary:{segments:segments.length,changedSegments:segments.filter(s=>s.text!==s.rawText).length,...counts},reviewScope:'approved_occurrences_only',goldReferenceAvailable:false,accuracyMeasured:false,cer:null,productionEligible:false,trainingRun:false};
}
export function toSrt(segments) {
  const stamp=seconds=>{const ms=Math.round(seconds*1000);return `${String(Math.floor(ms/3600000)).padStart(2,'0')}:${String(Math.floor(ms/60000)%60).padStart(2,'0')}:${String(Math.floor(ms/1000)%60).padStart(2,'0')},${String(ms%1000).padStart(3,'0')}`;};
  return segments.map((s,i)=>`${i+1}\n${stamp(s.start)} --> ${stamp(s.end)}\n${s.text.trim()}\n`).join('\n');
}
async function main() {
  const options={},args=process.argv.slice(2);
  for(let i=0;i<args.length;i+=2) {
    if(!['--asr','--rules','--proposals','--decisions','--output'].includes(args[i]) || !args[i+1]) throw new Error('Usage: --asr raw.json --rules rules.json --proposals suggestions.json --decisions review.json --output new-private-directory');
    options[args[i]]=args[i+1];
  }
  if(['--asr','--rules','--proposals','--decisions','--output'].some(k=>!options[k])) throw new Error('All five arguments are required');
  const bytes=await Promise.all(['--asr','--rules','--proposals','--decisions'].map(k=>readFile(options[k])));
  const report=applyDecisions(...bytes);report.implementationSha256=hash(await readFile(new URL(import.meta.url)));
  const output=path.resolve(options['--output']);await mkdir(path.dirname(output),{recursive:true});await mkdir(output);
  await writeFile(path.join(output,'reviewed-corrections.json'),JSON.stringify(report,null,2)+'\n',{flag:'wx'});
  await writeFile(path.join(output,'corrected-transcript.txt'),report.segments.map(s=>s.text).join('\n')+'\n',{flag:'wx'});
  await writeFile(path.join(output,'corrected-subtitles.srt'),toSrt(report.segments),{flag:'wx'});
  // Keep exact uploaded review bytes alongside the derived result, without altering the source file.
  await writeFile(path.join(output,'review-decisions.json'),bytes[3],{flag:'wx'});
  console.log(JSON.stringify({output,...report.summary,goldReferenceAvailable:false,accuracyMeasured:false,productionEligible:false}));
}
if(process.argv[1] && import.meta.url===pathToFileURL(path.resolve(process.argv[1])).href) main().catch(error=>{console.error(error.message);process.exitCode=1;});
