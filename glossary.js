export const defaultGlossary = [
  ['耶穌基度', '耶穌基督'], ['耶蘇', '耶穌'], ['基度', '基督'],
  ['聖零', '聖靈'], ['聖經經文', '聖經經文'], ['以馬內力', '以馬內利'],
  ['哈利路亞', '哈利路亞'], ['阿門', '阿們'], ['哥林多', '哥林多'],
  ['提摩太', '提摩太'], ['腓力比', '腓立比'], ['帖撒羅尼迦', '帖撒羅尼迦'],
  ['啟示錄', '啟示錄'], ['羅馬書', '羅馬書'], ['創世紀', '創世記'],
  ['受洗', '受洗'], ['敬拜', '敬拜'], ['團契', '團契'], ['擘餅', '擘餅'],
  ['福音', '福音'], ['恩典', '恩典'], ['救贖', '救贖'], ['禱告', '禱告']
];
export function parseGlossary(value) {
  return value.split('\n').map(line => line.split('=')).filter(parts => parts.length === 2 && parts.every(p => p.trim())).map(([a,b]) => [a.trim(),b.trim()]);
}
export function correctText(text, entries) {
  // Longest match wins; replacement text is never processed a second time.
  const pairs = [...entries].filter(([a,b]) => a && b).sort((a,b) => b[0].length-a[0].length);
  if (!pairs.length) return text;
  const map = new Map(pairs);
  const escape = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return text.replace(new RegExp([...map.keys()].map(escape).join('|'), 'gu'), match => map.get(match));
}
