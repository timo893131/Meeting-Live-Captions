import {readFile, realpath, mkdir, writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {normalize, NORMALIZER} from './glossary-metrics.mjs';

// Deliberately limited to the keywords in our versioned manifest schema.
export function checkShape(value, schema, root=schema, location='$') {
  if (schema.$ref) return checkShape(value, schema.$ref.slice(2).split('/').reduce((v,k)=>v[k],root),root,location);
  const errors=[], fail=message=>errors.push(`${location}: ${message}`);
  const type=value===null?'null':Array.isArray(value)?'array':typeof value==='object'?'object':typeof value;
  if (schema.type && ![].concat(schema.type).some(t=>t===type || t==='integer' && Number.isInteger(value))) { fail('invalid type');return errors; }
  if ('const' in schema && value!==schema.const) fail('invalid constant');
  if (schema.enum && !schema.enum.includes(value)) fail('invalid enum');
  if (typeof value==='string') {
    if (schema.minLength && Array.from(value).length<schema.minLength) fail('too short');
    if (schema.pattern && !new RegExp(schema.pattern,'u').test(value)) fail('invalid pattern');
    if (schema.format==='date-time' && (!/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)$/.test(value) || !Number.isFinite(Date.parse(value)))) fail('invalid date-time');
  }
  if (typeof value==='number' && (!Number.isFinite(value) || schema.minimum!==undefined && value<schema.minimum || schema.exclusiveMinimum!==undefined && value<=schema.exclusiveMinimum)) fail('invalid number');
  if (type==='object') {
    for (const key of schema.required||[]) if (!Object.hasOwn(value,key)) fail(`missing ${key}`);
    for (const key of Object.keys(value)) {
      if (schema.properties && Object.hasOwn(schema.properties,key)) errors.push(...checkShape(value[key],schema.properties[key],root,`${location}.${key}`));
      else if (schema.additionalProperties===false) fail(`unknown field ${key}`);
    }
  }
  if (type==='array') {
    if (schema.uniqueItems && new Set(value.map(v=>JSON.stringify(v))).size!==value.length) fail('duplicate items');
    if (schema.items) value.forEach((v,i)=>errors.push(...checkShape(v,schema.items,root,`${location}[${i}]`)));
  }
  return errors;
}
export function checkRecords(records,schema,{purpose='internal_evaluation',speakerDisjoint=false,now=Date.now()}={}) {
  if (!['internal_evaluation','training','split_audit'].includes(purpose)) throw new Error('Unsupported purpose');
  const errors=[], ids=new Set(), groups=new Map();
  if (!records.length) errors.push('Manifest is empty');
  records.forEach((r,i)=>{
    const tag=`row ${i+1}`, shape=checkShape(r,schema);
    if(shape.length) { errors.push(...shape.map(e=>`${tag} ${e}`));return; }
    const fail=m=>errors.push(`${tag}: ${m}`);
    if(ids.has(r.segment_id)) fail('duplicate segment_id');ids.add(r.segment_id);
    if(r.example_only) fail('example_only cannot be used as real data');
    if(r.excluded_reason!==null) fail('excluded record must be removed from the selected manifest');
    const rights=r.rights;
    const requiredUse=purpose==='split_audit' ? (r.split==='train'?'training':'internal_evaluation') : purpose;
    if(rights.status!=='approved' || !rights.allowed_uses.includes(requiredUse) || !['granted','not_required_with_basis'].includes(rights.consent_status) || !rights.license?.trim() || !rights.evidence_ref?.trim()) fail('rights or consent incomplete for requested purpose');
    if(rights.retention_until && Date.parse(rights.retention_until)<=now) fail('retention expired');
    if(!r.source.uri || !r.source.version || !r.source.retrieved_at) fail('source provenance incomplete');
    if(r.split==='unassigned') fail('split unassigned');
    if(purpose==='internal_evaluation' && !['validation','sealed_test'].includes(r.split)) fail('evaluation requires validation or sealed_test');
    if(purpose==='training' && r.split!=='train') fail('training requires train split');
    if(r.reference.status!=='human_verified' || typeof r.reference.raw_text!=='string' || r.reference.normalizer_version!==NORMALIZER || r.reference.normalized_text!==normalize(r.reference.raw_text||'')) fail('reference must be human verified with matching normalization');
    const a=r.audio;
    if(!a.raw_sha256 || a.duration_seconds===null || a.sample_rate_hz===null || a.channels===null || a.start_seconds===null || a.end_seconds===null || a.end_seconds<=a.start_seconds || a.end_seconds>a.duration_seconds) fail('audio metadata or segment bounds incomplete');
    if((a.processed_path===null)!==(a.processed_sha256===null)) fail('processed path/hash must occur together');
    if(a.processed_path && (!r.transform.tool || !r.transform.version)) fail('processed audio requires transform provenance');
    const keys=[['session',r.session_id],['group',r.group_id],['audio',a.raw_sha256],...(speakerDisjoint?[['speaker',r.speaker_id]]:[])];
    if(speakerDisjoint && !r.speaker_id) fail('speaker ID required for speaker-disjoint policy');
    if(r.reference.normalized_text) keys.push(['text',createHash('sha256').update(r.reference.normalized_text).digest('hex')]);
    for(const [kind,key] of keys) if(key) {
      const identity=JSON.stringify([kind,key]), previous=groups.get(identity);
      if(previous && previous!==r.split) fail(`cross-split ${kind} overlap`);
      groups.set(identity,r.split);
    }
  });
  return errors;
}
export async function checkAssets(records,root) {
  const errors=[], base=await realpath(root), cache=new Map();
  for(let i=0;i<records.length;i++) {
    const r=records[i];
    for(const kind of ['raw','processed']) {
      const relative=r.audio[`${kind}_path`];if(relative===null) continue;
      try {
        if(path.isAbsolute(relative)) throw new Error('absolute path');
        const file=await realpath(path.resolve(base,relative));
        if(!file.startsWith(base+path.sep)) throw new Error('path outside root');
        let asset=cache.get(file);
        if(!asset) {
          // Hash streaming avoids loading full recordings into memory.
          const {createReadStream}=await import('node:fs');
          const hash=createHash('sha256');for await(const chunk of createReadStream(file)) hash.update(chunk);
          const probe=JSON.parse(execFileSync('ffprobe',['-v','error','-show_entries','format=duration:stream=codec_type,sample_rate,channels','-of','json',file],{encoding:'utf8',timeout:20000,maxBuffer:1024*1024}));
          asset={hash:hash.digest('hex'),probe};cache.set(file,asset);
        }
        if(asset.hash!==r.audio[`${kind}_sha256`]) throw new Error('hash mismatch');
        const audio=asset.probe.streams.filter(s=>s.codec_type==='audio');
        if(audio.length!==1) throw new Error('expected one audio stream');
        // Metadata describes raw audio; processed rate/channels may differ by transform.
        if(kind==='raw' && (Number(audio[0].sample_rate)!==r.audio.sample_rate_hz || audio[0].channels!==r.audio.channels || !Number.isFinite(Number(asset.probe.format.duration)) || Math.abs(Number(asset.probe.format.duration)-r.audio.duration_seconds)>0.1)) throw new Error('raw audio metadata mismatch');
      } catch { errors.push(`row ${i+1}: ${kind} audio missing, unsafe path, hash/probe mismatch or ffprobe unavailable`); }
    }
  }
  return errors;
}
async function main() {
  const args=process.argv.slice(2), options={};
  for(let i=0;i<args.length;i+=2) {
    if(!['--manifest','--root','--purpose','--speaker-disjoint','--output'].includes(args[i]) || !args[i+1]) throw new Error('Invalid arguments');
    options[args[i]]=args[i+1];
  }
  if(!options['--manifest'] || !options['--root']) throw new Error('Required: --manifest file.jsonl --root data-directory');
  if(options['--speaker-disjoint'] && !['true','false'].includes(options['--speaker-disjoint'])) throw new Error('speaker-disjoint must be true or false');
  const bytes=await readFile(options['--manifest']);
  const records=bytes.toString('utf8').split(/\r?\n/).filter(l=>l.trim()).map(l=>JSON.parse(l));
  const schema=JSON.parse(await readFile(new URL('../docs/schemas/audio-segment.schema.json',import.meta.url)));
  const policy={purpose:options['--purpose']||'internal_evaluation',speakerDisjoint:options['--speaker-disjoint']==='true'};
  const errors=checkRecords(records,schema,policy);
  const assetsChecked=errors.length===0;
  if(assetsChecked) errors.push(...await checkAssets(records,options['--root']));
  const report={createdAt:new Date().toISOString(),manifestSha256:createHash('sha256').update(bytes).digest('hex'),policy,records:records.length,assetsChecked,status:errors.length?'failed':'passed',errors,modelRun:false,trainingRun:false,limitations:['No human listening verification','No near-duplicate acoustic matching','No semantic transcript alignment validation','Rights evidence is recorded, not independently authenticated']};
  const output=options['--output']||`artifacts/manifest-check/${Date.now()}/report.json`;
  await mkdir(path.dirname(output),{recursive:true});await writeFile(output,JSON.stringify(report,null,2)+'\n',{flag:'wx'});
  console.log(JSON.stringify({report:output,...report},null,2));if(errors.length) process.exitCode=1;
}
if(process.argv[1] && import.meta.url===pathToFileURL(path.resolve(process.argv[1])).href) main().catch(()=>{console.error('Manifest check could not complete: check arguments, JSON and local file access.');process.exitCode=1;});
