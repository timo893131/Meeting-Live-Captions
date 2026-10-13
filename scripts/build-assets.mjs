import {cp, mkdir, writeFile} from 'node:fs/promises';
await mkdir('.cloudflare-assets',{recursive:true});
await cp('public','.cloudflare-assets',{recursive:true});
await cp('glossary.js','.cloudflare-assets/glossary.js');
await writeFile('.cloudflare-assets/_headers','/*\n  Referrer-Policy: no-referrer\n  X-Content-Type-Options: nosniff\n');
console.log('Cloudflare static assets prepared.');
