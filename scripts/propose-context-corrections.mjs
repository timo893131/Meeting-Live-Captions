import {readFile,mkdir,writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import path from 'node:path';
import {pathToFileURL} from 'node:url';

export function validateRules(config) {
  if(config?.status!=='development_review_only' || config.productionEligible!==false || typeof config.version!=='string' || !Array.isArray(config.rules) || !config.rules.length || config.rules.length>100) throw new Error('Expected bounded review-only rule configuration');
  const ids=new Set();
  const validText=(v,max)=>typeof v==='string' && v.trim().length>0 && Array.from(v).length<=max;
  for(const r of config.rules) {
    if(!r || !validText(r.id,100) || ids.has(r.id) || !validText(r.source,50) || !validText(r.target,50) || r.source===r.target || !Array.isArray(r.contexts) || !r.contexts.length || r.contexts.length>20) throw new Error('Invalid or duplicate rule');
    ids.add(r.id);
    for(const c of r.contexts) {
      if(!c || typeof c!=='object' || Array.isArray(c) || !Object.keys(c).length || Object.keys(c).some(k=>!['before','after'].includes(k) || !validText(c[k],100))) throw new Error('Every context requires nonempty before and/or after literal text');
    }
  }
}
export function proposeText(text,config) {
  validateRules(config);
  if(typeof text!=='string' || Array.from(text).length>500) throw new Error('Expected text of at most 500 code points');
  const hits=[];
  for(const rule of config.rules) {
    let from=0;
    while(from<=text.length) {
      const start=text.indexOf(rule.source,from);if(start<0) break;
      const end=start+rule.source.length;
      if(rule.contexts.some(c=>(c.before===undefined || text.slice(0,start).endsWith(c.before)) && (c.after===undefined || text.slice(end).startsWith(c.after)))) hits.push({start,end,rule});
      from=start+1;
    }
  }
  hits.sort((a,b)=>a.start-b.start || a.end-b.end);
  let cursor=0,suggestedText='';const suggestions=[];
  for(const hit of hits) {
    if(hit.start<cursor) throw new Error('Ambiguous overlapping suggestions; refine rules');
    suggestedText+=text.slice(cursor,hit.start)+hit.rule.target;
    suggestions.push({ruleId:hit.rule.id,startCodePoint:Array.from(text.slice(0,hit.start)).length,endCodePoint:Array.from(text.slice(0,hit.end)).length,source:hit.rule.source,suggested:hit.rule.target,decision:'pending'});
    cursor=hit.end;
  }
  suggestedText+=text.slice(cursor);
  return {rawText:text,suggestedText,suggestions};
}
export function proposeReport(asr,config) {
  validateRules(config);
  if(asr?.status!=='machine_generated' || asr.reference_used_as_prompt!==false || asr.glossary_applied!==false || typeof asr.audio_sha256!=='string' || !/^[a-f0-9]{64}$/.test(asr.audio_sha256) || !Array.isArray(asr.segments) || !asr.segments.length || asr.segments.length>5000) throw new Error('Expected bounded raw machine ASR with no reference prompt or prior correction');
  const ids=new Set();
  const rows=asr.segments.map(segment=>{
    if(!Number.isInteger(segment.id) || ids.has(segment.id) || !Number.isFinite(segment.start) || !Number.isFinite(segment.end) || segment.start<0 || segment.end<=segment.start) throw new Error('Invalid segment ID or timestamps');
    ids.add(segment.id);
    return {id:segment.id,start:segment.start,end:segment.end,...proposeText(segment.text,config)};
  });
  return {status:'pending_human_review',audioSha256:asr.audio_sha256,ruleVersion:config.version,productionEligible:false,sourceKind:'seen_development_recording',rows,summary:{segments:rows.length,changedSegments:rows.filter(r=>r.suggestions.length).length,suggestions:rows.reduce((n,r)=>n+r.suggestions.length,0)},goldReferenceAvailable:false,accuracyMeasured:false,cer:null,trainingRun:false,notes:['Suggestion counts are not correct-word counts or accuracy improvement.','Literal contexts only apply inside each original ASR segment; no normalization, cross-segment context or cascading.','The combined suggestedText is a review preview, not an approved corrected transcript.']};
}
const hash=bytes=>createHash('sha256').update(bytes).digest('hex');
async function main() {
  const args=process.argv.slice(2),options={};
  for(let i=0;i<args.length;i+=2) {
    if(!['--asr','--rules','--output'].includes(args[i]) || !args[i+1]) throw new Error('Usage: --asr raw-asr.json --rules rules.json --output new-private-directory');
    options[args[i]]=args[i+1];
  }
  if(!options['--asr'] || !options['--rules'] || !options['--output']) throw new Error('Required: --asr, --rules, --output');
  const input=await readFile(options['--asr']),rules=await readFile(options['--rules']);
  const report=proposeReport(JSON.parse(input),JSON.parse(rules));
  Object.assign(report,{createdAt:new Date().toISOString(),inputSha256:hash(input),rulesSha256:hash(rules),implementationSha256:hash(await readFile(new URL(import.meta.url)))});
  const output=path.resolve(options['--output']);await mkdir(path.dirname(output),{recursive:true});await mkdir(output);
  await writeFile(path.join(output,'suggestions.json'),JSON.stringify(report,null,2)+'\n',{flag:'wx'});
  // TSV is for inspection only: JSON remains the lossless source for text containing tabs/newlines.
  const cell=value=>JSON.stringify(value);
  const tsv=['segment_id\tstart\tend\trule\tsource\tsuggestion\tstatus',...report.rows.flatMap(r=>r.suggestions.map(s=>[r.id,r.start,r.end,cell(s.ruleId),cell(s.source),cell(s.suggested),s.decision].join('\t')))];
  await writeFile(path.join(output,'review.tsv'),tsv.join('\n')+'\n',{flag:'wx'});
  console.log(JSON.stringify({output,...report.summary,status:report.status,accuracyMeasured:false,productionEligible:false}));
}
if(process.argv[1] && import.meta.url===pathToFileURL(path.resolve(process.argv[1])).href) main().catch(error=>{console.error(error.message);process.exitCode=1;});
