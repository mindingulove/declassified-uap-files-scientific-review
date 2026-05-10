#!/usr/bin/env node
const { createRequire } = require('module');
const fs = require('fs');
const path = require('path');
const requireFromRepo = createRequire('./package.json');
const { chromium } = requireFromRepo('playwright');

const outDir = '/tmp/war_ufo_mining';
fs.mkdirSync(outDir, { recursive: true });

function uniq(xs) {
  return Array.from(new Set(xs.filter(Boolean)));
}

(async () => {
  const browser = await chromium.launch({ headless: false });
  const page = await browser.newPage();
  const seen = [];
  page.on('response', async (res) => {
    const url = res.url();
    if (/\.(mp4|mov|m4v|webm|mp3|wav|m3u8)(\?|$)/i.test(url) || /video|audio|ufo|dvids|media/i.test(url)) {
      seen.push({ url, status: res.status(), contentType: res.headers()['content-type'] || '' });
    }
  });
  await page.goto('https://www.war.gov/UFO/', { waitUntil: 'networkidle', timeout: 90000 });
  await page.waitForTimeout(5000);

  const info = await page.evaluate(() => {
    const scripts = Array.from(document.scripts).map(s => ({
      src: s.src || '',
      text: s.src ? '' : s.textContent.slice(0, 300000),
    }));
    const html = document.documentElement.outerHTML;
    const urls = [];
    const re = /https?:\/\/[^"'\\\s<>]+|\/[^"'\\\s<>]+\.(?:mp4|mov|m4v|webm|mp3|wav|m3u8|json|csv)(?:\?[^"'\\\s<>]*)?/gi;
    for (const blob of [html, ...scripts.map(s => s.src + '\n' + s.text)]) {
      let m;
      while ((m = re.exec(blob))) {
        try { urls.push(new URL(m[0], location.origin).href); } catch {}
      }
    }
    const globals = {};
    for (const k of Object.keys(window)) {
      if (/uap|ufo|release|record|video|csv/i.test(k)) {
        try {
          const v = window[k];
          globals[k] = typeof v === 'string' ? v.slice(0, 1000) : Object.prototype.toString.call(v);
        } catch {}
      }
    }
    return {
      title: document.title,
      scripts: scripts.map(s => s.src).filter(Boolean),
      urls,
      globals,
      text: document.body.innerText.slice(0, 20000),
    };
  });

  const scriptTexts = [];
  for (const src of info.scripts) {
    try {
      const txt = await page.evaluate(async (u) => {
        const r = await fetch(u);
        if (!r.ok) return '';
        return await r.text();
      }, src);
      scriptTexts.push({ src, text: txt.slice(0, 1000000) });
    } catch {}
  }
  for (const s of scriptTexts) {
    const re = /https?:\/\/[^"'\\\s<>]+|\/[^"'\\\s<>]+\.(?:mp4|mov|m4v|webm|mp3|wav|m3u8|json|csv)(?:\?[^"'\\\s<>]*)?/gi;
    let m;
    while ((m = re.exec(s.text))) {
      try { info.urls.push(new URL(m[0], s.src).href); } catch {}
    }
  }

  const payload = {
    ...info,
    urls: uniq(info.urls),
    network: uniq(seen.map(x => JSON.stringify(x))).map(JSON.parse),
    scriptHits: scriptTexts.map(s => ({
      src: s.src,
      hasMp4: /\.mp4/i.test(s.text),
      hasDvids: /dvids/i.test(s.text),
      hasVideo: /video/i.test(s.text),
      hits: uniq((s.text.match(/.{0,80}(?:mp4|m3u8|dvids|video|uap|ufo).{0,120}/ig) || []).slice(0, 80)),
    })),
  };
  fs.writeFileSync(path.join(outDir, 'video_probe.json'), JSON.stringify(payload, null, 2));
  console.log(`wrote ${path.join(outDir, 'video_probe.json')}`);
  console.log(`urls=${payload.urls.length} network=${payload.network.length}`);
  for (const u of payload.urls.filter(u => /\.(mp4|mov|m4v|webm|mp3|wav|m3u8)(\?|$)/i.test(u))) console.log(u);
  await browser.close();
})().catch(e => {
  console.error(e);
  process.exit(1);
});
