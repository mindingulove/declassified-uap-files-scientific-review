#!/usr/bin/env node
const { createRequire } = require('module');
const fs = require('fs');
const path = require('path');
const requireFromRepo = createRequire('./package.json');
const { chromium } = requireFromRepo('playwright');
const API_KEY = 'key-68bb60d16b35e';
function parseCSV(t){const rows=[];let row=[],cell='',q=false;for(let i=0;i<t.length;i++){const ch=t[i],n=t[i+1];if(ch==='"'&&q&&n==='"'){cell+='"';i++;}else if(ch==='"')q=!q;else if(ch===','&&!q){row.push(cell.trim());cell='';}else if((ch==='\n'||ch==='\r')&&!q){if(cell||row.length)rows.push([...row,cell.trim()]);row=[];cell='';if(ch==='\r'&&n==='\n')i++;}else cell+=ch;} if(cell||row.length)rows.push([...row,cell.trim()]);return rows;}
(async()=>{
  const out='./war_ufo_mining/videos'; fs.mkdirSync(out,{recursive:true});
  const rows=parseCSV(fs.readFileSync('/tmp/war_ufo_downloads/uap-csv-live.csv','utf8'));
  const h=rows.shift();
  const idx=Object.fromEntries(h.map((x,i)=>[x,i]));
  const vids=rows.filter(r=>r[idx.Type]==='VID').map(r=>({
    title:r[idx.Title], dvids:r[idx['DVIDS Video ID']], videoTitle:r[idx['Video Title']],
    description:r[idx['Description Blurb']], location:r[idx['Incident Location']], date:r[idx['Incident Date']]
  }));
  const browser=await chromium.launch({headless:false});
  const page=await browser.newPage();
  await page.goto('https://www.war.gov/UFO/',{waitUntil:'domcontentloaded',timeout:90000});
  const enriched=[];
  for(const v of vids){
    process.stdout.write(`${v.dvids} ${v.title} `);
    try{
      const meta=await page.evaluate(async ({id,key})=>{
        const u=`https://api.dvidshub.net/asset?api_key=${key}&id=video:${id}&thumb_width=720`;
        const r=await fetch(u);
        if(!r.ok) throw new Error(`HTTP ${r.status}`);
        return await r.json();
      },{id:v.dvids,key:API_KEY});
      const result=meta?.results?.[0] || meta?.results || meta;
      const files=result?.files || [];
      const mp4s=files.filter(f=>f.type==='video/mp4' || /\.mp4(\?|$)/i.test(f.url||f.uri||''));
      enriched.push({...v, meta: result, files, mp4s});
      console.log(`OK files=${files.length} mp4=${mp4s.length}`);
    }catch(e){
      enriched.push({...v,error:e.message});
      console.log(`FAIL ${e.message}`);
    }
  }
  fs.writeFileSync(path.join(out,'video_meta.json'),JSON.stringify(enriched,null,2));
  console.log(path.join(out,'video_meta.json'));
  await browser.close();
})().catch(e=>{console.error(e);process.exit(1);});
