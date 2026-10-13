import test from 'node:test';
import assert from 'node:assert/strict';
import {once} from 'node:events';
import WebSocket from 'ws';
import {createApp} from '../server.js';
import {correctText,parseGlossary} from '../glossary.js';
function inbox(ws){const queue=[],waiters=[];ws.on('message',raw=>{const m=JSON.parse(raw);if(waiters.length)waiters.shift()(m);else queue.push(m);});return async type=>{for(;;){const m=queue.length?queue.shift():await new Promise(resolve=>waiters.push(resolve));if(m.type===type)return m;}};}
test('church vocabulary uses longest literal match without cascades',()=>{
 assert.equal(correctText('耶蘇說阿門',parseGlossary('耶蘇=耶穌\n阿門=阿們')), '耶穌說阿們');
 assert.equal(correctText('a+b aa', [['a+b','x'],['a','b'],['aa','a'],['b','c']]),'x a');
});
test('room authentication, live captions, history, QR and closure', {timeout:15000},async t=>{
 const {server,wss}=createApp();await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 t.after(async()=>{for(const client of wss.clients)client.terminate();await new Promise(resolve=>server.close(resolve));wss.close();});
 const base='http://127.0.0.1:'+server.address().port;
 assert.deepEqual(await (await fetch(base+'/api/health')).json(),{ok:true});
 assert.match(await (await fetch(base)).text(),/聚會字幕/);
 const room=await (await fetch(base+'/api/rooms',{method:'POST'})).json();
 const open=async credentials=>{const ws=new WebSocket(base.replace('http','ws'));const next=inbox(ws);await once(ws,'open');ws.send(JSON.stringify({type:'join',room:room.id,...credentials}));return {ws,next};};
 const bad=await open({password:'wrong'});assert.equal((await once(bad.ws,'close'))[0],1008);
 const host=await open({role:'host',token:room.hostToken});await host.next('ready');
 const viewer=await open({role:'viewer',password:room.password});assert.equal((await viewer.next('ready')).hostOnline,true);
 host.ws.send(JSON.stringify({type:'caption',text:'平安',final:false}));assert.equal((await viewer.next('interim')).text,'平安');
 viewer.ws.send(JSON.stringify({type:'caption',text:'unauthorized',final:true}));
 host.ws.send(JSON.stringify({type:'caption',text:'耶穌基督的恩典',final:true}));assert.equal((await viewer.next('final')).entry.text,'耶穌基督的恩典');
 const late=await open({password:room.password});assert.deepEqual((await late.next('ready')).history.map(e=>e.text),['耶穌基督的恩典']);
 const invited=await open({invite:room.viewerToken});assert.equal((await invited.next('ready')).history.length,1);
 assert.equal((await fetch(base+'/api/qr?room='+room.id)).status,403);
 const qr=await fetch(base+'/api/qr?room='+room.id,{headers:{Authorization:'Bearer '+room.hostToken}});assert.equal(qr.headers.get('content-type'),'image/png');assert.equal(Buffer.from(await qr.arrayBuffer()).subarray(1,4).toString(),'PNG');
 assert.equal((await fetch(base+'/api/rooms/'+room.id,{method:'DELETE'})).status,403);
 assert.equal((await fetch(base+'/api/rooms/'+room.id,{method:'DELETE',headers:{Authorization:'Bearer '+room.hostToken}})).status,200);
 await viewer.next('closed');assert.equal((await fetch(base+'/api/qr?room='+room.id)).status,404);
});
