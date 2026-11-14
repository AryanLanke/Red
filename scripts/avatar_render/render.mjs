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
const onlySets = arg('sets');            // e.g. topL,topR: only the frames of these sets
if (!vrmPath || !outDir) {
  console.error('usage: node render.mjs --vrm <model.vrm> --out <folder> [--only name1,name2] [--sets topL,topR]');
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

// The PC's GPU is shared with the language model. When it runs short, Edge fails to load textures or to
// compile shaders, and the frames come out white or blank. So every session counts the page's complaints,
// a test frame is rendered first, and a frame is only kept if nothing complained while it rendered;
// otherwise Edge is restarted and the remaining frames are tried again (a few times).
const BAD = /Failed to load texture|Shader Error|INVALID_OPERATION|Context Lost|CONTEXT_LOST/;

async function openSession(testFrame) {
  const browser = await puppeteer.launch({
    executablePath: EDGE,
    headless: true,
    args: ['--enable-unsafe-swiftshader', '--ignore-gpu-blocklist', '--no-first-run'],
  });
  const session = { browser, failures: 0, info: null, page: null };
  const page = await browser.newPage();
  page.on('console', (m) => {
    const text = m.text();
    if (BAD.test(text)) session.failures++;
    else if (!/Failed to load resource/.test(text)) console.log('[page]', text);
  });
  page.on('pageerror', (e) => console.error('[page error]', e.message));
  await page.setViewport({ width: 800, height: 1400 });
  await page.goto(`http://127.0.0.1:${port}/page.html`);
  await page.waitForFunction('window.rendererReady === true', { timeout: 30000 });
  session.info = await page.evaluate((u) => window.loadModel(u), '/model.vrm');
  await page.evaluate((f) => window.renderFrame(f), testFrame);       // the test frame, thrown away
  await new Promise((ok) => setTimeout(ok, 1000));
  session.page = page;
  return session;
}

const wanted = only ? new Set(only.split(',')) : null;
const wantedSets = onlySets ? new Set(onlySets.split(',')) : null;
const frames = FRAMES.filter((f) => (!wanted || wanted.has(f.name)) && (!wantedSets || wantedSets.has(f.set)));
const manifestPath = path.join(outDir, 'frames.json');
const previous = fs.existsSync(manifestPath) ? JSON.parse(fs.readFileSync(manifestPath, 'utf8')).frames : [];
const byName = new Map(previous.map((f) => [f.name, f]));
let info = null;
let todo = [...frames];
try {
  for (let attempt = 1; todo.length; attempt++) {
    if (attempt > 6) { console.error('giving up: Edge keeps failing, the frames would be wrong'); process.exit(3); }
    const session = await openSession(todo[0]);
    info = session.info;
    try {
      if (session.failures) throw new Error(`${session.failures} messages while loading`);
      while (todo.length) {
        const frame = todo[0];
        const before = session.failures;
        const result = await session.page.evaluate((f) => window.renderFrame(f), frame);
        await new Promise((ok) => setTimeout(ok, 30));
        if (session.failures !== before) throw new Error(`the page complained while rendering ${frame.name}`);
        const png = Buffer.from(result.png.split(',')[1], 'base64');
        fs.writeFileSync(path.join(outDir, `${frame.name}.png`), png);
        byName.set(frame.name, {
          name: frame.name, set: frame.set, state: frame.state || null, emotion: frame.emotion || null,
          marks: result.marks, size: [result.size.width, result.size.height], pxPerMetre: result.size.pxPerMetre,
        });
        console.log('rendered', frame.name);
        todo.shift();
      }
    } catch (e) {
      console.error(`attempt ${attempt}: ${e.message}; starting Edge again (${todo.length} frames left)`);
    } finally {
      await session.browser.close();
    }
  }
  // Keep frames.js order; frames rendered earlier (with --only) stay in the manifest.
  const manifest = FRAMES.map((f) => byName.get(f.name)).filter(Boolean);
  fs.writeFileSync(manifestPath, JSON.stringify({ model: info, frames: manifest }, null, 2));
} finally {
  server.close();
}
