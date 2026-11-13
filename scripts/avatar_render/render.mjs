// Renders a VRM into the sprite frames listed in frames.js, using the PC's own Edge in headless mode.
//   node render.mjs --vrm D:\RED\config\companion\avatar.vrm --out D:\RED\models\companion\raw
// Then run finish.py to crop, scale and make the contact sheet.
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import puppeteer from 'puppeteer-core';
import { FRAMES } from './frames.js';

const here = path.dirname(fileURLToPath(import.meta.url));
const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';

function arg(name, fallback) {
  const i = process.argv.indexOf(`--${name}`);
  return i > 0 ? process.argv[i + 1] : fallback;
}

const vrmPath = arg('vrm');
const outDir = arg('out');
const only = arg('only');
if (!vrmPath || !outDir) {
  console.error('usage: node render.mjs --vrm <model.vrm> --out <folder> [--only name1,name2]');
  process.exit(2);
}
fs.mkdirSync(outDir, { recursive: true });

const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.mjs': 'text/javascript', '.vrm': 'model/gltf-binary' };

// Serves only this folder, its node_modules and the one model file, on loopback.
const server = http.createServer((req, res) => {
  const url = decodeURIComponent(new URL(req.url, 'http://x').pathname);
  let file;
  if (url === '/' || url === '/page.html') file = path.join(here, 'page.html');
  else if (url === '/model.vrm') file = vrmPath;
  else {
    file = path.normalize(path.join(here, url));
    if (!file.startsWith(here + path.sep)) { res.writeHead(403); res.end(); return; }
  }
  fs.readFile(file, (err, data) => {
    if (err) { res.writeHead(404); res.end(); return; }
    res.writeHead(200, { 'Content-Type': TYPES[path.extname(file)] || 'application/octet-stream' });
    res.end(data);
  });
});
await new Promise((ok) => server.listen(0, '127.0.0.1', ok));
const port = server.address().port;

const browser = await puppeteer.launch({
  executablePath: EDGE,
  headless: true,
  args: ['--enable-unsafe-swiftshader', '--ignore-gpu-blocklist', '--no-first-run'],
});
try {
  const page = await browser.newPage();
  page.on('console', (m) => console.log('[page]', m.text()));
  page.on('pageerror', (e) => console.error('[page error]', e.message));
  await page.setViewport({ width: 800, height: 1400 });
  await page.goto(`http://127.0.0.1:${port}/page.html`);
  await page.waitForFunction('window.rendererReady === true', { timeout: 30000 });
  const info = await page.evaluate((u) => window.loadModel(u), '/model.vrm');
  console.log('model:', JSON.stringify(info));

  const wanted = only ? new Set(only.split(',')) : null;
  const frames = FRAMES.filter((f) => !wanted || wanted.has(f.name));
  for (const frame of frames) {
    const dataUrl = await page.evaluate((f) => window.renderFrame(f), frame);
    const png = Buffer.from(dataUrl.split(',')[1], 'base64');
    fs.writeFileSync(path.join(outDir, `${frame.name}.png`), png);
    console.log('rendered', frame.name);
  }
  const manifest = FRAMES.map(({ name, state, emotion }) => ({ name, state: state || null, emotion: emotion || null }));
  fs.writeFileSync(path.join(outDir, 'frames.json'), JSON.stringify({ model: info, frames: manifest }, null, 2));
} finally {
  await browser.close();
  server.close();
}
