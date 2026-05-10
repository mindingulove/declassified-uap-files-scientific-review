#!/usr/bin/env node
const fs = require('fs');
const path = require('path');
const https = require('https');
const http = require('http');

const meta = require('./war_ufo_mining/videos/video_meta.json');
const outDir = './war_ufo_mining/videos/mp4';
fs.mkdirSync(outDir, { recursive: true });

function slug(s) {
  return s.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 90);
}
function pick(v) {
  const files = v.mp4s || [];
  return files.find(f => f.height === 720) ||
    files.find(f => f.height === 576) ||
    files.sort((a,b)=>(b.height||0)-(a.height||0))[0];
}
function get(url, dest) {
  return new Promise((resolve, reject) => {
    const client = url.startsWith('https:') ? https : http;
    const req = client.get(url, res => {
      if ([301,302,303,307,308].includes(res.statusCode)) return resolve(get(res.headers.location, dest));
      if (res.statusCode !== 200) return reject(new Error(`HTTP ${res.statusCode}`));
      const tmp = dest + '.part';
      const f = fs.createWriteStream(tmp);
      res.pipe(f);
      f.on('finish', () => f.close(() => { fs.renameSync(tmp, dest); resolve(); }));
      f.on('error', reject);
    });
    req.on('error', reject);
  });
}
(async () => {
  const manifest = [];
  for (let i = 0; i < meta.length; i++) {
    const v = meta[i], f = pick(v);
    if (!f?.src) { console.log(`[${i+1}/${meta.length}] no mp4 ${v.title}`); continue; }
    const dest = path.join(outDir, `${v.dvids}-${slug(v.title)}.mp4`);
    manifest.push({ title: v.title, dvids: v.dvids, videoTitle: v.videoTitle, date: v.date, location: v.location, description: v.description, src: f.src, dest, width: f.width, height: f.height, size: f.size });
    if (fs.existsSync(dest) && fs.statSync(dest).size > 1000) {
      console.log(`[${i+1}/${meta.length}] skip ${path.basename(dest)} ${(fs.statSync(dest).size/1048576).toFixed(1)} MB`);
      continue;
    }
    process.stdout.write(`[${i+1}/${meta.length}] download ${path.basename(dest)} ${(f.size/1048576).toFixed(1)} MB `);
    await get(f.src, dest);
    console.log('OK');
  }
  fs.writeFileSync('./war_ufo_mining/videos/video_download_manifest.json', JSON.stringify(manifest, null, 2));
})();
