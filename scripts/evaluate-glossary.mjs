import {readFile, mkdir, writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import path from 'node:path';
import {pathToFileURL,fileURLToPath} from 'node:url';
import {defaultGlossary, correctText} from '../glossary.js';
import {NORMALIZER, METRIC_VERSION, normalize, align, score, emptyTotals, summarize} from './glossary-metrics.mjs';
export const glossaryHash = pairs => createHash('sha256').update(JSON.stringify(pairs)).digest('hex');
export function candidatePairs(patch) {
  if (patch.baselineSha256 !== glossaryHash(defaultGlossary)) throw new Error('Candidate baseline hash differs from current glossary; review the patch');
  if (!Array.isArray(patch.removeSources) || !Array.isArray(patch.addPairs)) throw new Error('Invalid candidate patch');
  if (patch.addPairs.some(pair => !Array.isArray(pair) || pair.length!==2 || pair.some(value => typeof value!=='string' || !value))) throw new Error('Invalid candidate pairs');
  return [...defaultGlossary.filter(([source]) => !patch.removeSources.includes(source)), ...patch.addPairs];
}
export function evaluate(dataset, candidate) {
  if (dataset.kind!=='authored_synthetic_development' || dataset.normalizer!==NORMALIZER || !Array.isArray(dataset.cases) || !dataset.cases.length || dataset.cases.length>500) throw new Error('Expected nonempty, versioned synthetic development fixture (maximum 500 cases)');
  const ids = new Set(), totals = {}, cohorts = {}, rows = [];
  const variants = {raw: null, baseline: defaultGlossary, ...(candidate ? {candidate} : {})};
  for (const name of Object.keys(variants)) { totals[name] = emptyTotals(); cohorts[name] = Object.create(null); }
  for (const item of dataset.cases) {
    if (typeof item.id!=='string' || ids.has(item.id) || typeof item.input!=='string' || typeof item.reference!=='string' || typeof item.cohort!=='string' || !Array.isArray(item.terms)) throw new Error('Invalid or duplicated evaluation case');
    ids.add(item.id);
    const reference = normalize(item.reference), raw = normalize(item.input), characters = Array.from(reference);
    let end = 0;
    for (const term of item.terms) {
      if (!Number.isInteger(term.start) || !Number.isInteger(term.end) || term.start<end || term.end<=term.start || term.end>characters.length || characters.slice(term.start,term.end).join('')!==term.value) throw new Error('Term spans must be nonoverlapping normalized reference code-point positions');
      end = term.end;
    }
    const rawAlignment = align(reference, raw), row = {id: item.id, cohort: item.cohort, outputs: {}, scores: {}};
    for (const [name,pairs] of Object.entries(variants)) {
      const output = pairs ? correctText(item.input,pairs) : item.input;
      const result = score(reference,normalize(output),item.terms,rawAlignment);
      row.outputs[name] = output; row.scores[name] = summarize(result);
      const cohort = cohorts[name][item.cohort] ||= emptyTotals();
      for (const field of Object.keys(result)) { totals[name][field] += result[field]; cohort[field] += result[field]; }
    }
    rows.push(row);
  }
  const summary = Object.fromEntries(Object.entries(totals).map(([name,value]) => [name,summarize(value)]));
  const byCohort = Object.fromEntries(Object.entries(cohorts).map(([name,values]) => [name,Object.fromEntries(Object.entries(values).map(([group,value]) => [group,summarize(value)]))]));
  const regressions = [];
  if (candidate) for (const [cohort,baseline] of Object.entries(byCohort.baseline)) {
    const result = byCohort.candidate[cohort];
    if (baseline.cer!==null && result.cer>baseline.cer) regressions.push({cohort,metric:'cer'});
    if (baseline.termAccuracy!==null && result.termAccuracy<baseline.termAccuracy) regressions.push({cohort,metric:'termAccuracy'});
    if (result.falseCorrections>baseline.falseCorrections) regressions.push({cohort,metric:'falseCorrections'});
  }
  return {fixtureKind:dataset.kind, fixtureVersion:dataset.version, sampleCount:dataset.cases.length, normalizer:NORMALIZER, metricVersion:METRIC_VERSION, summary, byCohort, regressions, fixtureGate: candidate ? (regressions.length ? 'failed' : 'passed') : 'unrun', productionPromotion:'not_evaluated', realAudioEvaluated:false, rows};
}
async function main() {
  const options = {};
  for (let i=2;i<process.argv.length;i+=2) {
    if (!['--cases','--candidate','--output'].includes(process.argv[i]) || !process.argv[i+1]) throw new Error('Usage: --cases file [--candidate patch.json] [--output new-report.json]');
    options[process.argv[i]] = process.argv[i+1];
  }
  if (!options['--cases']) throw new Error('--cases is required');
  const bytes = await readFile(options['--cases']);
  const patch = options['--candidate'] ? JSON.parse(await readFile(options['--candidate'],'utf8')) : null;
  const report = evaluate(JSON.parse(bytes),patch ? candidatePairs(patch) : null);
  const projectRoot = fileURLToPath(new URL('../',import.meta.url));
  let commit = 'unknown', workingTreeDirty = null;
  try {
    commit=execFileSync('git',['-C',projectRoot,'rev-parse','HEAD'],{encoding:'utf8'}).trim();
    workingTreeDirty=!!execFileSync('git',['-C',projectRoot,'status','--porcelain'],{encoding:'utf8'}).trim();
  } catch {}
  const codeHash=createHash('sha256');
  for (const name of ['evaluate-glossary.mjs','glossary-metrics.mjs']) { codeHash.update(name+'\0');codeHash.update(await readFile(new URL(name,import.meta.url))); }
  Object.assign(report,{createdAt:new Date().toISOString(), codeCommit:commit, workingTreeDirty, metricCodeSha256:codeHash.digest('hex'), fixtureSha256:createHash('sha256').update(bytes).digest('hex'), baselineSha256:glossaryHash(defaultGlossary), candidateSha256:patch ? glossaryHash(candidatePairs(patch)) : null, usage:{tokens:null,cost:null,metadataSource:'unavailable'}});
  const output = options['--output'] || `artifacts/glossary-evaluation/${Date.now()}/report.json`;
  await mkdir(path.dirname(output),{recursive:true}); await writeFile(output,JSON.stringify(report,null,2)+'\n',{flag:'wx'});
  console.log(JSON.stringify({report:output, sampleCount:report.sampleCount, summary:report.summary, fixtureGate:report.fixtureGate, regressions:report.regressions, productionPromotion:report.productionPromotion, realAudioEvaluated:false},null,2));
  if (report.fixtureGate==='failed') process.exitCode=1;
}
if (process.argv[1] && import.meta.url===pathToFileURL(path.resolve(process.argv[1])).href) main().catch(error=>{console.error(error.message);process.exitCode=1;});
