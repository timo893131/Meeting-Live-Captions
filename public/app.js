import {defaultGlossary,parseGlossary,correctText} from '/glossary.js';
const $=id=>document.getElementById(id);
let mode='personal', room=null, socket=null, recognition=null, listening=false, entries=[], reconnectTimer=null, generation=0, creating=false;
const SpeechRecognition=window.SpeechRecognition||window.webkitSpeechRecognition;
let saved; try{saved=localStorage.getItem('churchGlossary');}catch{}
$('glossary').value=saved ?? defaultGlossary.map(p=>p.join('=')).join('\n');
function message(text){$('message').textContent=text;}
function status(text){$('status').textContent=text;}
function addEntry(entry){entries.push(entry);entries=entries.slice(-200);render();}
function render(){const root=$('captions');root.replaceChildren();for(const entry of entries){const p=document.createElement('p');p.textContent=entry.text;root.append(p);}root.scrollTop=root.scrollHeight;}
function sendCaption(text,final){if(mode==='host'){if(socket?.readyState===WebSocket.OPEN) socket.send(JSON.stringify({type:'caption',text,final}));else message('房間已斷線，這段字幕未廣播。');}else if(final)addEntry({text,time:Date.now()});$('interim').textContent=final?'':text;}
function stop(){listening=false;recognition?.stop();$('start').disabled=mode==='viewer';$('stop').disabled=true;$('interim').textContent='';if(mode==='host' && socket?.readyState===WebSocket.OPEN)socket.send(JSON.stringify({type:'caption',text:'',final:false}));status('已停止收音');}
function start(){
 if(!SpeechRecognition)return message('此瀏覽器不支援語音辨識，請使用桌面版 Chrome，或加入房間觀看字幕。');
 if(mode==='host' && socket?.readyState!==WebSocket.OPEN)return message('請等待房間連線完成。');
 if(!window.isSecureContext)return message('麥克風需要 HTTPS。請使用具 HTTPS 的網站位址。');
 message('');listening=true;recognition=new SpeechRecognition();recognition.lang=$('language').value;recognition.continuous=true;recognition.interimResults=true;
 recognition.onresult=event=>{let interim='';const glossary=parseGlossary($('glossary').value);for(let i=event.resultIndex;i<event.results.length;i++){const text=correctText(event.results[i][0].transcript,glossary);if(event.results[i].isFinal)sendCaption(text,true);else interim+=text;}sendCaption(interim,false);};
 recognition.onerror=event=>{message('語音辨識：'+event.error+'。請檢查麥克風權限、網路與瀏覽器支援。');if(event.error!=='no-speech')stop();};
 recognition.onend=()=>{if(listening){try{recognition.start();}catch{stop();message('辨識已停止，請重新開始收音。');}}};
 try{recognition.start();$('start').disabled=true;$('stop').disabled=false;status('收音中');}catch{stop();message('無法啟動語音辨識。');}
}
function disconnect(){generation++;clearTimeout(reconnectTimer);socket?.close();socket=null;}
function connect(role){
 const current=generation;
 socket=new WebSocket((location.protocol==='https:'?'wss://':'ws://')+location.host+'/ws?room='+encodeURIComponent(room.id));
 const ws=socket;status('連線中');
 ws.onopen=()=>ws.send(JSON.stringify({type:'join',room:room.id,role,token:role==='host'?room.hostToken:undefined,password:role==='viewer'?room.password:undefined,invite:role==='viewer'?room.invite:undefined}));
 ws.onmessage=event=>{if(current!==generation)return;const msg=JSON.parse(event.data);if(msg.type==='ready'){entries=msg.history;render();$('interim').textContent=msg.interim;status(role==='host'?'房間已連線':msg.hostOnline?'等待字幕':'房主暫時離線');message('');}
 if(msg.type==='final'){addEntry(msg.entry);$('interim').textContent='';}if(msg.type==='interim')$('interim').textContent=msg.text;
 if(msg.type==='presence' && role==='viewer'){status(msg.hostOnline?'接收字幕中':'房主暫時離線');if(!msg.hostOnline)$('interim').textContent='';}
 if(msg.type==='closed'){disconnect();stop();room=null;$('sharePanel').hidden=true;status('房間已結束');message('房主已結束此房間。');}};
 ws.onclose=event=>{if(current!==generation)return;if(listening)stop();status('連線已中斷');if(event.code===1008 || event.code===1000){message(event.reason||'房間已結束或無法加入。');return;}message('連線中斷，正在重新連線。重新連線後請重新開始收音。');reconnectTimer=setTimeout(()=>{if(room&&current===generation)connect(role);},3000);};
 ws.onerror=()=>message('無法連接字幕伺服器。');
}
async function selectMode(next){
 if(mode===next || creating)return;
 if(room?.hostToken){message('請先按「結束房間」，再切換模式。');return;}
 stop();disconnect();room=null;mode=next;entries=[];render();message('');
 for(const id of ['personal','host','viewer'])$(id).classList.toggle('selected',id===mode);
 $('joinPanel').hidden=mode!=='viewer';$('settings').hidden=mode==='viewer';$('start').hidden=mode==='viewer';$('stop').hidden=mode==='viewer';$('start').disabled=mode==='viewer';
 if(mode==='host'){
  creating=true;
  try{const res=await fetch('/api/rooms',{method:'POST'});const body=await res.json();if(!res.ok)throw new Error(body.error);room=body;$('shareId').textContent=room.id;$('sharePassword').textContent=room.password;const qr=await fetch('/api/qr?room='+room.id,{headers:{Authorization:'Bearer '+room.hostToken}});if(!qr.ok)throw Error('無法產生 QR Code。');const oldQr=$('qr').src;if(oldQr.startsWith('blob:'))URL.revokeObjectURL(oldQr);$('qr').src=URL.createObjectURL(await qr.blob());$('sharePanel').hidden=false;connect('host');}catch(e){if(room?.hostToken){await fetch('/api/rooms/'+room.id,{method:'DELETE',headers:{Authorization:'Bearer '+room.hostToken}}).catch(()=>{});}room=null;$('sharePanel').hidden=true;message(e.message);mode='personal';$('personal').classList.add('selected');$('host').classList.remove('selected');}finally{creating=false;}
 }else status('準備就緒');
}
for(const id of ['personal','host','viewer'])$(id).onclick=()=>selectMode(id);
$('start').onclick=start;$('stop').onclick=stop;
$('joinForm').onsubmit=event=>{event.preventDefault();disconnect();room={id:$('roomId').value.trim(),password:$('password').value.trim()};connect('viewer');};
$('closeRoom').onclick=async()=>{if(!room?.hostToken)return;try{const res=await fetch('/api/rooms/'+room.id,{method:'DELETE',headers:{Authorization:'Bearer '+room.hostToken}});if(!res.ok)throw Error('無法結束房間，請重試。');disconnect();stop();room=null;$('sharePanel').hidden=true;await selectMode('personal');}catch(e){message(e.message);}};
$('copyLink').onclick=async()=>{try{await navigator.clipboard.writeText(location.origin+'/?room='+room.id+'#invite='+room.viewerToken);message('已複製邀請連結，開啟即可加入。請只分享給參與者。');}catch{message('無法複製，請使用房間代碼或 QR Code。');}};
$('fontSize').oninput=()=>{for(const id of ['captions','interim'])$(id).style.fontSize=$('fontSize').value+'px';};
$('saveGlossary').onclick=()=>{try{localStorage.setItem('churchGlossary',$('glossary').value);message('詞彙表已儲存。');}catch{message('瀏覽器無法儲存，詞彙表仍在本次使用期間生效。');}};
$('resetGlossary').onclick=()=>{$('glossary').value=defaultGlossary.map(p=>p.join('=')).join('\n');};
$('export').onclick=()=>{const blob=new Blob([entries.map(e=>new Date(e.time).toLocaleTimeString('zh-TW')+' '+e.text).join('\n')],{type:'text/plain;charset=utf-8'});const link=document.createElement('a');link.href=URL.createObjectURL(blob);link.download='聚會字幕.txt';link.click();setTimeout(()=>URL.revokeObjectURL(link.href),1000);};
const queryRoom=new URLSearchParams(location.search).get('room');const invite=new URLSearchParams(location.hash.slice(1)).get('invite');if(queryRoom){$('roomId').value=queryRoom;selectMode('viewer');if(invite){history.replaceState(null,'','/?room='+encodeURIComponent(queryRoom));room={id:queryRoom,invite};$('joinPanel').hidden=true;connect('viewer');}}
if(!SpeechRecognition)message('此瀏覽器不支援語音辨識；仍可加入房間觀看字幕。');
