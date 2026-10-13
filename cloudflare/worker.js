import { DurableObject } from 'cloudflare:workers';
import QRCode from 'qrcode';

const LIFETIME=12*60*60*1000;
const randomHex=bytes=>Array.from(crypto.getRandomValues(new Uint8Array(bytes)),b=>b.toString(16).padStart(2,'0')).join('');
const json=(body,status=200)=>Response.json(body,{status,headers:{'Cache-Control':'no-store','Referrer-Policy':'no-referrer','X-Content-Type-Options':'nosniff'}});
const hex=buffer=>Array.from(new Uint8Array(buffer),b=>b.toString(16).padStart(2,'0')).join('');
async function passwordHash(password,salt) {
  const key=await crypto.subtle.importKey('raw',new TextEncoder().encode(password),'PBKDF2',false,['deriveBits']);
  return hex(await crypto.subtle.deriveBits({name:'PBKDF2',salt:new TextEncoder().encode(salt),iterations:100000,hash:'SHA-256'},key,256));
}
function equal(a,b) {
  if(typeof a!=='string'||typeof b!=='string'||a.length!==b.length)return false;
  let diff=0;for(let i=0;i<a.length;i++)diff|=a.charCodeAt(i)^b.charCodeAt(i);return diff===0;
}

export default {
  async fetch(request,env) {
    const url=new URL(request.url);
    if(url.pathname==='/api/health')return json({ok:true,runtime:'cloudflare'});
    if(url.pathname==='/api/rooms' && request.method==='POST') {
      const gate=env.CREATE_LIMIT.get(env.CREATE_LIMIT.idFromName('create-limit'));
      const permitted=await gate.fetch(new Request('https://internal/check',{headers:{'client-ip':request.headers.get('CF-Connecting-IP')||'local'}}));
      if(!permitted.ok)return json({error:'建立太頻繁，請稍後再試。'},429);
      const id=randomHex(5),password=randomHex(4),hostToken=randomHex(32),viewerToken=randomHex(24);
      const stub=env.ROOMS.get(env.ROOMS.idFromName(id));
      const result=await stub.fetch(new Request('https://internal/init',{method:'POST',body:JSON.stringify({id,password,hostToken,viewerToken})}));
      if(!result.ok)return json({error:'無法建立房間。'},503);
      return json({id,password,hostToken,viewerToken},201);
    }
    let id,route;
    if(url.pathname==='/ws') {id=url.searchParams.get('room');route='/ws';}
    else if(url.pathname==='/api/qr') {id=url.searchParams.get('room');route='/qr';}
    else if(/^\/api\/rooms\/[a-f0-9]{10}$/.test(url.pathname)&&request.method==='DELETE') {id=url.pathname.split('/').pop();route='/close';}
    if(route) {
      if(!/^[a-f0-9]{10}$/.test(id||''))return json({error:'房間不存在。'},404);
      const target=new URL(request.url);target.pathname=route;
      return env.ROOMS.get(env.ROOMS.idFromName(id)).fetch(new Request(target,request));
    }
    if(url.pathname.startsWith('/api/'))return json({error:'找不到此操作。'},404);
    return env.ASSETS.fetch(request);
  }
};

export class CreateLimit extends DurableObject {
  async fetch(request) {
    // Global object preserves the limit across Worker isolates and restarts.
    const ip=hex(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(request.headers.get('client-ip')||'local')));
    let allowed=false;
    await this.ctx.blockConcurrencyWhile(async()=>{
      const now=Date.now();const buckets=await this.ctx.storage.get('buckets')||{};
      for(const [key,item] of Object.entries(buckets))if(item.until<now)delete buckets[key];
      if(!buckets[ip]) {
        if(Object.keys(buckets).length>=1000)return;
        buckets[ip]={count:0,until:now+60000};
      }
      allowed=++buckets[ip].count<=10;
      await this.ctx.storage.put('buckets',buckets);
      await this.ctx.storage.setAlarm(now+60000);
    });
    return json({ok:allowed},allowed?200:429);
  }
  async alarm(){await this.ctx.storage.deleteAll();await this.ctx.storage.deleteAlarm();}
}

export class CaptionRoom extends DurableObject {
  constructor(ctx,env) {
    super(ctx,env);this.meta=null;this.history=[];this.authTimers=new Map();
    ctx.blockConcurrencyWhile(async()=>{
      this.meta=await ctx.storage.get('meta')||null;
      this.history=await ctx.storage.get('history')||[];
    });
  }
  attachment(ws){try{return ws.deserializeAttachment()||{};}catch{return {};}}
  sockets(){return this.ctx.getWebSockets().filter(ws=>this.attachment(ws).role);}
  host(){return this.sockets().find(ws=>this.attachment(ws).role==='host');}
  broadcast(payload){const data=JSON.stringify(payload);for(const ws of this.sockets())try{ws.send(data);}catch{ws.close(1011);}}
  async closeRoom(){
    this.broadcast({type:'closed'});for(const ws of this.ctx.getWebSockets())try{ws.close(1000);}catch{}
    for(const timer of this.authTimers.values())clearTimeout(timer);this.authTimers.clear();
    this.meta=null;this.history=[];await this.ctx.storage.deleteAll();await this.ctx.storage.deleteAlarm();
  }
  async fetch(request) {
    const url=new URL(request.url);
    if(url.pathname==='/init'&&request.method==='POST') {
      if(this.meta)return json({error:'already exists'},409);
      const data=await request.json(),salt=randomHex(16);
      this.meta={id:data.id,hostToken:data.hostToken,viewerToken:data.viewerToken,salt,hash:await passwordHash(data.password,salt),created:Date.now()};
      await this.ctx.storage.put('meta',this.meta);await this.ctx.storage.setAlarm(this.meta.created+LIFETIME);
      return json({ok:true});
    }
    if(!this.meta)return json({error:'房間不存在或已結束。'},404);
    if(Date.now()-this.meta.created>=LIFETIME){await this.closeRoom();return json({error:'房間已到期。'},404);}
    if(url.pathname==='/close'&&request.method==='DELETE') {
      if(!equal(request.headers.get('Authorization'),'Bearer '+this.meta.hostToken))return json({error:'沒有房主權限。'},403);
      await this.closeRoom();return json({ok:true});
    }
    if(url.pathname==='/qr') {
      if(!equal(request.headers.get('Authorization'),'Bearer '+this.meta.hostToken))return json({error:'沒有房主權限。'},403);
      const invite=new URL('/?room='+this.meta.id,url.origin);invite.hash='invite='+this.meta.viewerToken;
      const svg=await QRCode.toString(invite.toString(),{type:'svg',width:300,margin:2});
      return new Response(svg,{headers:{'Content-Type':'image/svg+xml','Cache-Control':'no-store','Referrer-Policy':'no-referrer'}});
    }
    if(url.pathname==='/ws') {
      if(request.headers.get('Upgrade')?.toLowerCase()!=='websocket')return json({error:'WebSocket required'},426);
      if(this.ctx.getWebSockets().length>=200)return json({error:'房間人數已滿。'},503);
      const pair=new WebSocketPair(),[client,server]=Object.values(pair);
      this.ctx.acceptWebSocket(server);
      const ipKey=hex(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(request.headers.get('CF-Connecting-IP')||'local')));
      server.serializeAttachment({role:null,joined:Date.now(),ipKey});
      this.authTimers.set(server,setTimeout(()=>{try{server.close(1008,'請先加入房間');}catch{}this.authTimers.delete(server);},10000));
      return new Response(null,{status:101,webSocket:client});
    }
    return json({error:'not found'},404);
  }
  async webSocketMessage(ws,raw) {
    if(!this.meta)return ws.close(1008,'房間已結束');
    const meta=this.meta;
    if(Date.now()-this.meta.created>=LIFETIME)return this.closeRoom();
    if(typeof raw!=='string'||new TextEncoder().encode(raw).length>16384)return ws.close(1008,'訊息過大');
    let msg;try{msg=JSON.parse(raw);}catch{return ws.close(1008);}
    if(!msg||typeof msg!=='object')return ws.close(1008);
    const attached=this.attachment(ws);
    if(!attached.role) {
      if(msg.type!=='join'||msg.room!==this.meta.id||Date.now()-attached.joined>10000)return ws.close(1008,'房間或密碼錯誤');
      // Persist the auth attempt counter so hibernation cannot reset it.
      let permitted=false;
      await this.ctx.blockConcurrencyWhile(async()=>{
        const now=Date.now();let attempts=await this.ctx.storage.get('attempts');
        if(!attempts||attempts.until<now)attempts={count:0,until:now+60000,ips:{}};
        const ipCount=(attempts.ips[attached.ipKey]||0)+1;attempts.ips[attached.ipKey]=ipCount;
        permitted=++attempts.count<=600 && ipCount<=300;await this.ctx.storage.put('attempts',attempts);
      });
      if(!permitted)return ws.close(1008,'嘗試太頻繁');
      let role;
      if(msg.role==='host'&&equal(msg.token,meta.hostToken))role='host';
      else if(equal(msg.invite,meta.viewerToken))role='viewer';
      else if(typeof msg.password==='string'&&msg.password.length<=128&&equal(await passwordHash(msg.password,meta.salt),meta.hash))role='viewer';
      else return ws.close(1008,'房間或密碼錯誤');
      // Room may have closed while the password hash was being computed.
      if(this.meta!==meta)return ws.close(1008,'房間已結束');
      if(role==='host')for(const old of this.sockets())if(this.attachment(old).role==='host') {old.serializeAttachment({role:null});old.close(1000,'房主重新連線');}
      clearTimeout(this.authTimers.get(ws));this.authTimers.delete(ws);
      ws.serializeAttachment({role,interim:'',count:0,until:Date.now()+60000});
      ws.send(JSON.stringify({type:'ready',history:this.history,interim:this.host()?this.attachment(this.host()).interim||'':'',hostOnline:!!this.host()}));
      this.broadcast({type:'presence',hostOnline:!!this.host()});return;
    }
    if(attached.role!=='host'||msg.type!=='caption'||typeof msg.text!=='string'||msg.text.length>8000)return;
    if(attached.until<Date.now()){attached.count=0;attached.until=Date.now()+60000;}
    if(++attached.count>600)return;
    if(msg.final===true) {
      attached.interim='';ws.serializeAttachment(attached);
      const entry={id:randomHex(8),text:msg.text,time:Date.now()};
      await this.ctx.blockConcurrencyWhile(async()=>{
        this.history.push(entry);this.history=this.history.slice(-200);
        while(new TextEncoder().encode(JSON.stringify(this.history)).length>90000)this.history.shift();
        await this.ctx.storage.put('history',this.history);
      });
      this.broadcast({type:'final',entry});
    }else{attached.interim=msg.text;ws.serializeAttachment(attached);this.broadcast({type:'interim',text:msg.text});}
  }
  webSocketClose(ws,code,reason) {
    clearTimeout(this.authTimers.get(ws));this.authTimers.delete(ws);
    const attached=this.attachment(ws);ws.serializeAttachment({role:null});
    try{ws.close(code===1005?1000:code,reason);}catch{}
    if(attached.role==='host')this.broadcast({type:'presence',hostOnline:!!this.host()});
  }
  webSocketError(ws){this.webSocketClose(ws,1011,'連線錯誤');}
  async alarm(){await this.closeRoom();}
}
