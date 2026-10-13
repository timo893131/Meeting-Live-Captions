import express from 'express';
import { createServer } from 'node:http';
import { randomBytes, scryptSync, timingSafeEqual } from 'node:crypto';
import { WebSocketServer, WebSocket } from 'ws';
import QRCode from 'qrcode';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

export function createApp() {
  const app = express();
  const server = createServer(app);
  const wss = new WebSocketServer({ server, maxPayload: 16384 });
  const rooms = new Map(), limits = new Map();
  app.disable('x-powered-by');
  app.use((req,res,next) => { res.set('Referrer-Policy','no-referrer'); res.set('X-Content-Type-Options','nosniff'); res.set('Cache-Control','no-store'); next(); });
  app.use(express.json({limit:'16kb'}));
  function limited(key, max) {
    const now = Date.now(), old = limits.get(key);
    const item = !old || old.until < now ? {count:0,until:now+60000} : old;
    limits.set(key,item); return ++item.count > max;
  }
  function broadcast(room, payload) {
    const data = JSON.stringify(payload);
    for (const client of room.clients) if (client.readyState === WebSocket.OPEN) {
      if (client.bufferedAmount > 1000000) client.close(1013); else client.send(data);
    }
  }
  function closeRoom(id) {
    const room=rooms.get(id); if (!room) return;
    broadcast(room,{type:'closed'});
    for (const client of room.clients) client.close(1000);
    rooms.delete(id);
  }
  app.get('/api/health', (req,res) => res.json({ok:true}));
  app.post('/api/rooms', (req,res) => {
    if (limited('create:'+req.socket.remoteAddress,10)) return res.status(429).json({error:'建立太頻繁，請稍後再試。'});
    if (rooms.size >= 1000) return res.status(503).json({error:'房間已滿。'});
    const id=randomBytes(5).toString('hex'), password=randomBytes(4).toString('hex'), hostToken=randomBytes(32).toString('hex'), salt=randomBytes(16), viewerToken=randomBytes(24).toString('hex');
    rooms.set(id,{viewerToken,salt,hash:scryptSync(password,salt,32),hostToken,clients:new Set(),history:[],interim:'',host:null,created:Date.now()});
    res.status(201).json({id,password,hostToken,viewerToken});
  });
  app.delete('/api/rooms/:id', (req,res) => {
    const room=rooms.get(req.params.id);
    if (!room || req.get('Authorization') !== 'Bearer '+room.hostToken) return res.status(403).json({error:'沒有房主權限。'});
    closeRoom(req.params.id); res.json({ok:true});
  });
  app.get('/api/qr', async (req,res) => {
    const room = typeof req.query.room === 'string' ? req.query.room : '';
    if (!rooms.has(room)) return res.sendStatus(404);
    if (req.get('Authorization') !== 'Bearer '+rooms.get(room).hostToken) return res.sendStatus(403);
    // PUBLIC_URL is administrator-controlled; never trust the request Host header.
    const base = process.env.PUBLIC_URL || 'http://localhost:'+ (server.address()?.port || 3000);
    const url = new URL('/?room='+encodeURIComponent(room),base);
    url.hash='invite='+rooms.get(room).viewerToken;
    res.type('png').send(await QRCode.toBuffer(url.toString(),{width:300,margin:2}));
  });
  app.use(express.static(path.join(path.dirname(fileURLToPath(import.meta.url)),'public')));
  app.get('/glossary.js', (req,res) => res.sendFile(path.join(path.dirname(fileURLToPath(import.meta.url)),'glossary.js')));
  wss.on('connection',(ws,req) => {
    let joined=null, role=null;
    const authTimeout=setTimeout(()=>ws.close(1008,'請先加入房間'),10000);
    ws.on('message', raw => {
      let msg; try {msg=JSON.parse(raw.toString());} catch {return ws.close(1008);}
      if (!msg || typeof msg !== 'object') return ws.close(1008);
      if (!joined) {
        if (limited('auth:'+req.socket.remoteAddress,300)) return ws.close(1008,'嘗試太頻繁');
        const room=rooms.get(msg.room);
        if (!room || msg.type !== 'join') return ws.close(1008,'房間或密碼錯誤');
        if (msg.role === 'host' && msg.token === room.hostToken) {
          role='host'; if (room.host) room.host.close(1000,'房主重新連線'); room.host=ws;
        } else {
          if (msg.invite !== room.viewerToken && (typeof msg.password !== 'string' || msg.password.length>128 || !timingSafeEqual(scryptSync(msg.password,room.salt,32),room.hash))) return ws.close(1008,'房間或密碼錯誤');
          role='viewer';
        }
        joined=room; room.clients.add(ws); clearTimeout(authTimeout);
        ws.send(JSON.stringify({type:'ready',history:room.history,interim:room.interim,hostOnline:!!room.host}));
        broadcast(room,{type:'presence',hostOnline:!!room.host}); return;
      }
      if (role !== 'host' || joined.host !== ws) return;
      if (msg.type === 'caption' && typeof msg.text === 'string' && msg.text.length <= 8000 && !limited('caption:'+joined.hostToken,600)) {
        if (msg.final === true) {
          const entry={text:msg.text,time:Date.now(),id:randomBytes(8).toString('hex')};
          joined.history.push(entry); joined.history=joined.history.slice(-200); joined.interim='';
          broadcast(joined,{type:'final',entry});
        } else {joined.interim=msg.text; broadcast(joined,{type:'interim',text:msg.text});}
      }
    });
    ws.on('close',()=> {clearTimeout(authTimeout); if(joined) {joined.clients.delete(ws); if(joined.host===ws) {joined.host=null; joined.interim=''; broadcast(joined,{type:'presence',hostOnline:false});}}});
    ws.on('error',()=>{});
  });
  const cleanup=setInterval(()=>{
    for (const [id,room] of rooms) if(Date.now()-room.created>12*60*60*1000) closeRoom(id);
    for (const [key,item] of limits) if(item.until<Date.now()) limits.delete(key);
  },60000); cleanup.unref();
  server.on('close',()=>clearInterval(cleanup));
  return {app,server,wss};
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const {server}=createApp(); server.listen(Number(process.env.PORT)||3000,'0.0.0.0',()=>console.log('Meeting Live Captions server started'));
}
