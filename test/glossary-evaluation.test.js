import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {align, normalize, spanCorrect, score, summarize, NORMALIZER} from '../scripts/glossary-metrics.mjs';
import {evaluate,candidatePairs} from '../scripts/evaluate-glossary.mjs';

test('character alignment distinguishes substitution, deletion and insertion',()=>{
 assert.equal(align('abc','axc').substitutions,1);
 assert.equal(align('abc','ac').deletions,1);
 assert.equal(align('ac','abc').insertions,1);
 const empty=score('','x',[],align('','x'));
 assert.equal(empty.insertions,1);assert.equal(summarize(empty).cer,null);
});
test('normalization preserves script, numbers and Unicode code points',()=>{
 assert.equal(normalize(' 約翰福音，三章！ '),'約翰福音三章');
 assert.notEqual(normalize('靈'),normalize('灵'));
 assert.notEqual(normalize('十六'),normalize('十七'));
 assert.equal(align('😀靈','😀靈').referenceCharacters,2);
});
test('term scoring uses aligned occurrence rather than a later matching string',()=>{
 const alignment=align('耶穌與耶穌','耶蘇與耶穌');
 assert.equal(spanCorrect(alignment,0,2),false);
 assert.equal(spanCorrect(alignment,3,5),true);
 assert.equal(spanCorrect(align('耶穌','耶大穌'),0,2),false);
 assert.equal(spanCorrect(align('耶穌','啊耶穌啊'),0,2),true);
});
test('false corrections count only previously correct annotated occurrences',()=>{
 const reference='創世紀',raw=align(reference,reference);
 const result=score(reference,'創世記',[{start:0,end:3,value:reference}],raw);
 assert.equal(result.originallyCorrectTerms,1);assert.equal(result.falseCorrections,1);
 assert.equal(summarize(result).falseCorrectionRate,1);
});
test('empty fixture, duplicate IDs, bad spans and overlong segments fail',()=>{
 const base={kind:'authored_synthetic_development',normalizer:NORMALIZER,version:'test',cases:[]};
 assert.throws(()=>evaluate(base));
 const item={id:'a',cohort:'test',input:'abc',reference:'abc',terms:[]};
 assert.throws(()=>evaluate({...base,cases:[item,item]}));
 assert.throws(()=>evaluate({...base,cases:[{...item,terms:[{start:0,end:1,value:'b'}]}]}));
 assert.throws(()=>align('x'.repeat(501),''));
});
test('baseline provenance and conservative experiment regression are explicit',async()=>{
 const dataset=JSON.parse(await readFile(new URL('../evaluation/glossary/development-cases.json',import.meta.url)));
 const patch=JSON.parse(await readFile(new URL('../evaluation/glossary/context-prefix-experiment.json',import.meta.url)));
 assert.throws(()=>candidatePairs({...patch,baselineSha256:'unknown'}));
 const result=evaluate(dataset,candidatePairs(patch));
 assert.equal(result.sampleCount,21);
 assert.equal(result.productionPromotion,'not_evaluated');assert.equal(result.realAudioEvaluated,false);
 assert.equal(result.fixtureGate,'failed');
 assert.ok(result.regressions.some(item=>item.cohort==='bible_books'));
 const proper=result.rows.find(item=>item.id==='drama-title');
 assert.equal(proper.scores.baseline.falseCorrections,1);assert.equal(proper.scores.candidate.falseCorrections,0);
});
