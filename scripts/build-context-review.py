"""Build a private, self-contained audio review worksheet; no network access."""
import argparse
import base64
import hashlib
import html
import json
from pathlib import Path


def build(report, audio):
    if report.get('status') != 'pending_human_review' or report.get('productionEligible') is not False:
        raise ValueError('Expected review-only suggestions')
    if hashlib.sha256(audio).hexdigest() != report['audioSha256']:
        raise ValueError('Audio hash differs from suggestion provenance')
    sections = []
    for row in report['rows']:
        if not row['suggestions']:
            continue
        controls = []
        characters = list(row['rawText'])
        cursor = 0
        expected = ''
        for suggestion in row['suggestions']:
            start, end = suggestion['startCodePoint'], suggestion['endCodePoint']
            if not (isinstance(start, int) and isinstance(end, int) and cursor <= start < end <= len(characters)) or ''.join(characters[start:end]) != suggestion['source'] or suggestion['decision'] != 'pending':
                raise ValueError('Invalid source offsets or pre-approved suggestion')
            expected += ''.join(characters[cursor:start]) + suggestion['suggested']
            cursor = end
            controls.append('<label>' + html.escape(suggestion['source']) + ' → ' + html.escape(suggestion['suggested']) + ' <select aria-label="此筆建議的決定"><option value="pending">待確認</option><option value="accepted">採用此處</option><option value="rejected">拒絕此處</option></select></label>')
        expected += ''.join(characters[cursor:])
        if expected != row['suggestedText']:
            raise ValueError('Preview does not match source edits')
        section = f'<section data-id="{int(row["id"])}"><h2><button class="play" data-start="{float(row["start"])}" data-end="{float(row["end"])}">播放 {float(row["start"]):.2f}–{float(row["end"]):.2f} 秒</button></h2><p>原始辨識：<span class="raw">{html.escape(row["rawText"])}</span></p><p>全部採用時的預覽：{html.escape(row["suggestedText"])}</p>'+''.join(controls)+'</section>'
        sections.append(section)
    if not sections:
        raise ValueError('No suggestions to review')
    # Text values enter HTML only through escaping. Embedded metadata is JSON data, not code.
    data = json.dumps(report, ensure_ascii=False).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    return '''<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>詞彙候選逐段核對</title><style>
body{max-width:1000px;margin:auto;padding:20px;background:#eff7ff;color:#15344c;font:18px/1.7 system-ui}header{position:sticky;top:0;background:#eff7ff;border-bottom:2px solid #9cc6e5;padding:12px 0;z-index:1}audio{width:100%}section{background:white;border:1px solid #b8d4e9;border-radius:10px;margin:18px 0;padding:16px}button,select,input{font:inherit;max-width:100%;border:1px solid #4d7fa2;border-radius:6px;padding:9px;background:#e2f1ff;color:#15344c}button{cursor:pointer}button:focus-visible,select:focus-visible,input:focus-visible{outline:3px solid #205b98}h1{font-size:1.5rem}h2{font-size:1rem}label{display:block;margin:12px 0}p{overflow-wrap:anywhere}#status{font-weight:bold}@media(max-width:600px){body{padding:10px}section{padding:12px}}
</style><header><h1>詞彙候選逐段核對</h1><audio id="audio" controls preload="metadata" src="data:audio/mpeg;base64,'''+base64.b64encode(audio).decode()+'''"></audio><label>核對者代號 <input id="reviewer" autocomplete="off"></label><button id="export">下載核對結果 JSON</button><p id="status" role="status">所有建議均待確認。</p></header><p>本頁只列出有建議的片段，不涵蓋整份錄音。請先播放原音，再逐筆決定是否採用；採用僅表示這個位置，不代表核准全域替換或已完成逐字稿校對。播放器可聽完整原音，檢查片段邊界。</p><p>原始辨識保留不變。沒有自動儲存，離開前請下載 JSON；核對結果需另行匯入，不會變更正式網站。瀏覽器中的資料與音訊均內嵌在此檔案，無伺服器上傳。</p>'''+''.join(sections)+'''<script type="application/json" id="report">'''+data+'''</script><script>
const report=JSON.parse(document.querySelector('#report').textContent);const audio=document.querySelector('#audio');let stopAt=null;
for(const button of document.querySelectorAll('.play'))button.onclick=()=>{audio.currentTime=Math.max(0,Number(button.dataset.start)-.3);stopAt=Number(button.dataset.end)+.3;audio.play().catch(()=>{document.querySelector('#status').textContent='請使用播放器播放。';});};
audio.ontimeupdate=()=>{if(stopAt!==null&&audio.currentTime>=stopAt){audio.pause();stopAt=null;}};
for(const select of document.querySelectorAll('select'))select.onchange=()=>{document.querySelector('#status').textContent='有未下載的決定，離開前請下載。';};
document.querySelector('#export').onclick=()=>{
 const reviewer=document.querySelector('#reviewer').value.trim();const sections=[...document.querySelectorAll('section')];
 const decisions=sections.map(section=>({segmentId:Number(section.dataset.id),items:[...section.querySelectorAll('select')].map((select,index)=>{const source=report.rows.find(row=>row.id===Number(section.dataset.id)).suggestions[index];return {...source,decision:select.value};})}));
 if(decisions.some(r=>r.items.some(i=>i.decision!=='pending'))&&!reviewer){document.querySelector('#status').textContent='請先填寫核對者代號，再下載已決定的項目。';return;}
 const result={schemaVersion:'context-review-decisions-1',audioSha256:report.audioSha256,inputSha256:report.inputSha256,rulesSha256:report.rulesSha256,reviewer:reviewer||null,exportedAt:new Date().toISOString(),decisions,goldReferenceAvailable:false,accuracyMeasured:false,productionEligible:false,sourceCoverage:'suggested_segments_only'};
 const link=document.createElement('a');const url=URL.createObjectURL(new Blob([JSON.stringify(result,null,2)],{type:'application/json'}));link.href=url;link.download='context-review-decisions.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);document.querySelector('#status').textContent='已下載；後續變更請再次下載。';
};
</script></html>'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suggestions', required=True)
    parser.add_argument('--audio', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    report = json.loads(Path(args.suggestions).read_text())
    page = build(report, Path(args.audio).read_bytes())
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x') as stream:
        stream.write(page)
    print(json.dumps({'output': str(output), 'suggestions': report['summary']['suggestions'], 'accuracyMeasured': False}))


if __name__ == '__main__':
    main()
