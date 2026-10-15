import {readFile,realpath,mkdir,writeFile} from 'node:fs/promises';
import {createReadStream} from 'node:fs';
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import path from 'node:path';
import {pathToFileURL} from 'node:url';

export async function inspectAudio(root,relative) {
  if(!relative || path.isAbsolute(relative)) throw new Error('Audio must be a path relative to --root');
  const base=await realpath(root), file=await realpath(path.resolve(base,relative));
  if(!file.startsWith(base+path.sep)) throw new Error('Audio resolves outside --root');
  const probe=JSON.parse(execFileSync('ffprobe',['-v','error','-show_entries','format=duration:stream=codec_type,sample_rate,channels','-of','json',file],{encoding:'utf8',timeout:20000,maxBuffer:1024*1024,stdio:['ignore','pipe','pipe']}));
  const streams=probe.streams?.filter(s=>s.codec_type==='audio')||[],duration=Number(probe.format?.duration);
  if(streams.length!==1 || !Number.isFinite(duration) || duration<=0 || !Number.isInteger(Number(streams[0].sample_rate)) || Number(streams[0].sample_rate)<=0 || !Number.isInteger(streams[0].channels) || streams[0].channels<=0) throw new Error('Expected one audio stream with valid duration, sample rate and channels');
  const hash=createHash('sha256');for await(const bytes of createReadStream(file)) hash.update(bytes);
  return {raw_path:relative,processed_path:null,raw_sha256:hash.digest('hex'),processed_sha256:null,sample_rate_hz:Number(streams[0].sample_rate),channels:streams[0].channels,duration_seconds:duration,start_seconds:0,end_seconds:duration};
}
export function draftRecord(audio,index,template) {
  const record=structuredClone(template);
  record.example_only=false;record.segment_id=`intake-${String(index+1).padStart(3,'0')}-${audio.raw_sha256.slice(0,12)}`;
  record.source={source_id:`sha256:${audio.raw_sha256}`,uri:`urn:sha256:${audio.raw_sha256}`,version:audio.raw_sha256,retrieved_at:new Date().toISOString()};
  record.audio=audio;
  // Session/speaker/source grouping cannot be inferred from a filename or hash.
  record.session_id=null;record.speaker_id=null;record.group_id=null;record.split='unassigned';record.cohorts=[];
  return record;
}
async function main() {
  const args=process.argv.slice(2),options={audio:[]};
  for(let i=0;i<args.length;i+=2) {
    if(!['--root','--audio','--output'].includes(args[i]) || !args[i+1]) throw new Error('Usage: --root directory --audio relative-file [--audio another-file] --output new-directory');
    if(args[i]==='--audio') options.audio.push(args[i+1]);else options[args[i]]=args[i+1];
  }
  if(!options['--root'] || !options['--output'] || !options.audio.length) throw new Error('Required: --root, at least one --audio, --output');
  const template=JSON.parse(await readFile(new URL('../docs/templates/audio-segment.example.json',import.meta.url)));
  const targets=JSON.parse(await readFile(new URL('../evaluation/glossary/approved-targets.json',import.meta.url)));
  const records=[];for(const file of options.audio) records.push(draftRecord(await inspectAudio(options['--root'],file),records.length,template));
  if(new Set(records.map(r=>r.audio.raw_sha256)).size!==records.length) throw new Error('Duplicate input audio; select each original recording once');
  const output=path.resolve(options['--output']);await mkdir(path.dirname(output),{recursive:true});await mkdir(output);
  await writeFile(path.join(output,'draft-manifest.jsonl'),records.map(r=>JSON.stringify(r)).join('\n')+'\n',{flag:'wx'});
  await writeFile(path.join(output,'target-scope.json'),JSON.stringify(targets,null,2)+'\n',{flag:'wx'});
  const report={created_at:new Date().toISOString(),status:'intake_draft_only',files:records.length,total_file_seconds:records.reduce((n,r)=>n+r.audio.duration_seconds,0),target_scope_sha256:createHash('sha256').update(JSON.stringify(targets)).digest('hex'),recordings_received:true,asr_run:false,reference_verified:false,training_run:false,permission_context:'User reports intended meeting recordings are permitted for evaluation; each selected file still needs its actual rights metadata.',remaining:['Record actual source and permission/consent basis per recording','Assign real session/group and pseudonymous speaker IDs','Choose validation and independently reserved test sessions','Segment recordings and verify spoken references','Capture raw ASR before correction; record engine/runtime','Annotate target occurrences and ambiguous spelling policy']};
  await writeFile(path.join(output,'intake-report.json'),JSON.stringify(report,null,2)+'\n',{flag:'wx'});
  console.log(JSON.stringify({output,status:report.status,files:report.files,totalFileSeconds:report.total_file_seconds,asrRun:false,trainingRun:false}));
}
if(process.argv[1] && import.meta.url===pathToFileURL(path.resolve(process.argv[1])).href) main().catch(()=>{console.error('Audio intake failed. Check arguments, paths, unique inputs, ffprobe support and a new output directory.');process.exitCode=1;});
