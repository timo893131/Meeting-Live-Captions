// Text-only metrics. Indexes refer to normalized Unicode code points, not UTF-16 units.
export const NORMALIZER = 'nfc-strip-punctuation-space-v1';
export const METRIC_VERSION = 'character-alignment-v1';
export function normalize(text) {
  return text.normalize('NFC').replace(/[\p{P}\s]/gu, '');
}
export function align(reference, hypothesis) {
  const ref = Array.from(reference), hyp = Array.from(hypothesis);
  if (ref.length > 500 || hyp.length > 500) throw new Error('Split text into segments of at most 500 normalized code points');
  const width = hyp.length + 1;
  const costs = new Uint32Array((ref.length + 1) * width);
  for (let i = 0; i <= ref.length; i++) costs[i * width] = i;
  for (let j = 0; j <= hyp.length; j++) costs[j] = j;
  for (let i = 1; i <= ref.length; i++) for (let j = 1; j <= hyp.length; j++) {
    costs[i * width + j] = Math.min(costs[(i-1)*width+j-1] + Number(ref[i-1] !== hyp[j-1]), costs[(i-1)*width+j]+1, costs[i*width+j-1]+1);
  }
  const positions = Array(ref.length).fill(null);
  let i = ref.length, j = hyp.length, substitutions = 0, deletions = 0, insertions = 0;
  // Deterministic tie order: equal/substitution, deletion, insertion.
  while (i || j) {
    if (i && j && costs[i*width+j] === costs[(i-1)*width+j-1] + Number(ref[i-1] !== hyp[j-1])) {
      if (ref[i-1] === hyp[j-1]) positions[i-1] = j-1; else substitutions++;
      i--; j--;
    } else if (i && costs[i*width+j] === costs[(i-1)*width+j]+1) { deletions++; i--; }
    else { insertions++; j--; }
  }
  return {substitutions, deletions, insertions, referenceCharacters: ref.length, positions};
}
export function spanCorrect(alignment, start, end) {
  const positions = alignment.positions.slice(start, end);
  return positions.length === end-start && positions.length > 0 && positions.every((position, index) => position !== null && position === positions[0]+index);
}
export function emptyTotals() {
  return {cases: 0, substitutions: 0, deletions: 0, insertions: 0, referenceCharacters: 0, termOccurrences: 0, correctTerms: 0, originallyCorrectTerms: 0, falseCorrections: 0};
}
export function summarize(totals) {
  return {...totals,
    cer: totals.referenceCharacters ? (totals.substitutions+totals.deletions+totals.insertions)/totals.referenceCharacters : null,
    termAccuracy: totals.termOccurrences ? totals.correctTerms/totals.termOccurrences : null,
    falseCorrectionRate: totals.originallyCorrectTerms ? totals.falseCorrections/totals.originallyCorrectTerms : null};
}
export function score(reference, hypothesis, terms, rawAlignment) {
  const alignment = align(reference, hypothesis);
  const totals = {...emptyTotals(), cases: 1};
  for (const field of ['substitutions','deletions','insertions','referenceCharacters']) totals[field] = alignment[field];
  for (const term of terms) {
    const correct = spanCorrect(alignment, term.start, term.end);
    const originallyCorrect = spanCorrect(rawAlignment, term.start, term.end);
    totals.termOccurrences++; totals.correctTerms += Number(correct);
    totals.originallyCorrectTerms += Number(originallyCorrect);
    totals.falseCorrections += Number(originallyCorrect && !correct);
  }
  return totals;
}
