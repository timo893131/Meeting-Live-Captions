import test from 'node:test';
import assert from 'node:assert/strict';
import {once} from 'node:events';
import WebSocket from 'ws';
const base=process.env.CAPTION_TEST_URL||'http://127.0.0.1:8787';
function inbox(ws){const queue=[],waiters=[];ws.on('message',raw=>{const m=JSON.parse(raw);if(waiters.length)waiters.shift()(m);else queue.push(m);});return async type=>{for(;;){const m=queue.length?queue.shift():await new Promise(resolve=>waiters.push(resolve));if(m.type===type)return m;}};}
test('Cloudflare assets, password/invite auth, broadcast, QR and room deletion',{timeout:20000},async t=>{
 const sockets=[];let room;
 t.after(async()=>{if(room)await fetch(base+'/api/rooms/'+room.id,{method:'DELETE',headers:{Authorization:'Bearer '+room.hostToken}}).catch(()=>{});for(const ws of sockets)ws.terminate();});
 const health=await (await fetch(base+'/api/health')).json();assert.equal(health.ok,true);assert.equal(health.runtime,'cloudflare');
 assert.match(await (await fetch(base)).text(),/聚會字幕/);assert.match(await (await fetch(base+'/glossary.js')).text(),/correctText/);
 const response=await fetch(base+'/api/rooms',{method:'POST'});assert.equal(response.status,201);room=await response.json();
 const open=async credentials=>{const ws=new WebSocket(base.replace(/^http/,'ws')+'/ws?room='+room.id);sockets.push(ws);const next=inbox(ws);await once(ws,'open');ws.send(JSON.stringify({type:'join',room:room.id,...credentials}));return {ws,next};};
 const bad=await open({password:'wrong'});assert.equal((await once(bad.ws,'close'))[0],1008);
 const host=await open({role:'host',token:room.hostToken});await host.next('ready');
 const viewer=await open({password:room.password});assert.equal((await viewer.next('ready')).hostOnline,true);
 const invited=await open({invite:room.viewerToken});await invited.next('ready');
 host.ws.send(JSON.stringify({type:'caption',text:'平安',final:false}));assert.equal((await viewer.next('interim')).text,'平安');
 viewer.ws.send(JSON.stringify({type:'caption',text:'unauthorized',final:true}));
 host.ws.send(JSON.stringify({type:'caption',text:'耶穌基督的恩典',final:true}));assert.equal((await viewer.next('final')).entry.text,'耶穌基督的恩典');assert.equal((await invited.next('final')).entry.text,'耶穌基督的恩典');
 const late=await open({password:room.password});assert.deepEqual((await late.next('ready')).history.map(e=>e.text),['耶穌基督的恩典']);
 assert.equal((await fetch(base+'/api/qr?room='+room.id)).status,403);
 const qr=await fetch(base+'/api/qr?room='+room.id,{headers:{Authorization:'Bearer '+room.hostToken}});assert.match(qr.headers.get('content-type'),/image\/svg\+xml/);assert.match(await qr.text(),/<svg/);
 assert.equal((await fetch(base+'/api/rooms/'+room.id,{method:'DELETE'})).status,403);
 assert.equal((await fetch(base+'/api/rooms/'+room.id,{method:'DELETE',headers:{Authorization:'Bearer '+room.hostToken}})).status,200);
 await viewer.next('closed');assert.equal((await fetch(base+'/api/qr?room='+room.id)).status,404);
 const unavailable=await fetch(base+'/api/rooms/invalid',{method:'DELETE'});assert.equal(unavailable.status,404);
});
