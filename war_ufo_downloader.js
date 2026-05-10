#!/usr/bin/env node
const { createRequire } = require('module');
const fs = require('fs');
const path = require('path');

const requireFromRepo = createRequire('./package.json');
const { chromium } = requireFromRepo('playwright');

const OUT = '/tmp/war_ufo_downloads';
const PDF_DIR = path.join(OUT, 'pdf');
const IMG_DIR = path.join(OUT, 'img');
const EXISTING_DIRS = [
  './pdfs',
  PDF_DIR,
  IMG_DIR,
];
const CSV_PATH = path.join(OUT, 'uap-csv-live.csv');
const RECORDS_PATH = path.join(OUT, 'records-live.json');
const FAIL_PATH = path.join(OUT, 'failures.json');

function parseCSV(text) {
  const rows = [];
  let row = [], cell = '', q = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i], next = text[i + 1];
    if (ch === '"' && q && next === '"') { cell += '"'; i++; }
    else if (ch === '"') q = !q;
    else if (ch === ',' && !q) { row.push(cell.trim()); cell = ''; }
    else if ((ch === '\n' || ch === '\r') && !q) {
      if (cell || row.length) rows.push([...row, cell.trim()]);
      row = []; cell = '';
      if (ch === '\r' && next === '\n') i++;
    } else cell += ch;
  }
  if (cell || row.length) rows.push([...row, cell.trim()]);
  return rows;
}

function filenameFor(url, type, title) {
  let name = decodeURIComponent(path.basename(new URL(url).pathname));
  if (!name || !name.includes('.')) {
    name = title.toLowerCase().replace(/[^a-z0-9._-]+/g, '-').replace(/^-|-$/g, '');
    if (type === 'PDF') name += '.pdf';
    if (type === 'IMG') name += '.jpg';
  }
  return name;
}

function existingFile(name) {
  for (const dir of EXISTING_DIRS) {
    const candidate = path.join(dir, name);
    if (fs.existsSync(candidate) && fs.statSync(candidate).size > 1000) return candidate;
  }
  return null;
}

async function newBrowser() {
  const browser = await chromium.launch({ headless: false });
  const page = await browser.newPage();
  await page.goto('https://www.war.gov/UFO/', { waitUntil: 'domcontentloaded', timeout: 60000 });
  return { browser, page };
}

async function fetchText(page, url) {
  return page.evaluate(async (u) => {
    const r = await fetch(u);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.text();
  }, url);
}

async function sizeOf(page, url) {
  return page.evaluate(async (u) => {
    const r = await fetch(u, { method: 'HEAD' });
    if (!r.ok) return -r.status;
    return Number(r.headers.get('content-length') || 0);
  }, url);
}

async function fetchBytes(page, url, start, end) {
  return page.evaluate(async ({ u, s, e }) => {
    const headers = s == null ? {} : { Range: `bytes=${s}-${e}` };
    const r = await fetch(u, { headers });
    if (!r.ok && r.status !== 206) throw new Error(`HTTP ${r.status}`);
    const ab = await r.arrayBuffer();
    const bytes = new Uint8Array(ab);
    let bin = '';
    for (let i = 0; i < bytes.length; i += 32768) {
      bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 32768));
    }
    return btoa(bin);
  }, { u: url, s: start, e: end });
}

async function download(page, url, dest) {
  const size = await sizeOf(page, url);
  if (size < 0) throw new Error(`HTTP ${-size}`);
  const tmp = `${dest}.part`;
  const chunk = 4 * 1024 * 1024;
  const fd = fs.openSync(tmp, 'w');
  let written = 0;
  try {
    if (size > 0 && size > 50 * 1024 * 1024) {
      for (let start = 0; start < size; start += chunk) {
        const end = Math.min(start + chunk - 1, size - 1);
        const b64 = await fetchBytes(page, url, start, end);
        const buf = Buffer.from(b64, 'base64');
        fs.writeSync(fd, buf, 0, buf.length, written);
        written += buf.length;
        process.stdout.write(`${Math.round((written / size) * 100)}% `);
      }
    } else {
      const b64 = await fetchBytes(page, url);
      const buf = Buffer.from(b64, 'base64');
      fs.writeSync(fd, buf, 0, buf.length, 0);
    }
  } finally {
    fs.closeSync(fd);
  }
  fs.renameSync(tmp, dest);
}

async function main() {
  fs.mkdirSync(PDF_DIR, { recursive: true });
  fs.mkdirSync(IMG_DIR, { recursive: true });

  let { browser, page } = await newBrowser();
  console.log('Browser session established.');

  const csvUrl = await page.evaluate(() => {
    for (const s of document.querySelectorAll('script')) {
      const m = s.textContent.match(/csvUrl\s*=\s*"([^"]+)"/);
      if (m) return new URL(m[1], location.origin).href;
    }
    return 'https://www.war.gov/Portals/1/Interactive/2026/UFO/uap-csv.csv';
  });
  const csv = await fetchText(page, csvUrl);
  fs.writeFileSync(CSV_PATH, csv);

  const rows = parseCSV(csv);
  const headers = rows.shift();
  const records = rows
    .filter(r => r[2] && r[3])
    .map(r => ({
      title: r[2].trim(),
      type: r[3].trim(),
      description: (r[6] || '').trim(),
      agency: (r[9] || '').trim(),
      incident_date: (r[10] || '').trim(),
      incident_location: (r[11] || '').trim(),
      link: (r[12] || '').trim(),
    }));
  fs.writeFileSync(RECORDS_PATH, JSON.stringify({ headers, records }, null, 2));

  const targets = records.filter(r => (r.type === 'PDF' || r.type === 'IMG') && /^https?:/.test(r.link));
  const noDirect = records.filter(r => !/^https?:/.test(r.link));
  console.log(`Live records: ${records.length}. Direct downloadable PDF/IMG: ${targets.length}. No direct link: ${noDirect.length}.`);

  const failures = [];
  for (let i = 0; i < targets.length; i++) {
    const r = targets[i];
    const dir = r.type === 'IMG' ? IMG_DIR : PDF_DIR;
    const dest = path.join(dir, filenameFor(r.link, r.type, r.title));
    const already = existingFile(path.basename(dest));
    if (already) {
      console.log(`[${i + 1}/${targets.length}] skip ${path.basename(dest)} from ${path.dirname(already)} (${(fs.statSync(already).size / 1048576).toFixed(1)} MB)`);
      continue;
    }
    process.stdout.write(`[${i + 1}/${targets.length}] get ${path.basename(dest)} `);
    let ok = false;
    for (let attempt = 1; attempt <= 3 && !ok; attempt++) {
      try {
        await download(page, r.link, dest);
        console.log(`OK (${(fs.statSync(dest).size / 1048576).toFixed(1)} MB)`);
        ok = true;
      } catch (e) {
        process.stdout.write(`attempt ${attempt} failed: ${e.message} `);
        try { await browser.close(); } catch {}
        ({ browser, page } = await newBrowser());
      }
    }
    if (!ok) {
      console.log('FAILED');
      failures.push({ title: r.title, type: r.type, link: r.link });
    }
  }
  fs.writeFileSync(FAIL_PATH, JSON.stringify(failures, null, 2));
  await browser.close();
  console.log(`Done. Failures: ${failures.length}. Output: ${OUT}`);
}

main().catch(err => {
  console.error(err);
  process.exit(1);
});
