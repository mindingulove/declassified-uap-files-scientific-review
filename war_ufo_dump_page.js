#!/usr/bin/env node
const { createRequire } = require('module');
const fs = require('fs');
const path = require('path');
const requireFromRepo = createRequire('./package.json');
const { chromium } = requireFromRepo('playwright');
(async () => {
  const out = './war_ufo_mining/page_dump';
  fs.mkdirSync(out, { recursive: true });
  const browser = await chromium.launch({ headless: false });
  const page = await browser.newPage();
  await page.goto('https://www.war.gov/UFO/', { waitUntil: 'networkidle', timeout: 90000 });
  await page.waitForTimeout(2000);
  fs.writeFileSync(path.join(out, 'page.html'), await page.content());
  const scripts = await page.evaluate(() => Array.from(document.scripts).map((s, i) => ({ i, src: s.src, text: s.textContent })));
  for (const s of scripts) {
    const file = path.join(out, `script_${String(s.i).padStart(2, '0')}${s.src ? '_src.txt' : '_inline.js'}`);
    fs.writeFileSync(file, s.src ? s.src + '\n' : s.text);
  }
  console.log(`wrote ${out}`);
  await browser.close();
})().catch(e => { console.error(e); process.exit(1); });
