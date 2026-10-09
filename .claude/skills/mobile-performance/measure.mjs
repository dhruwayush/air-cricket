// Measure what three.js draws per frame during play, on a phone-sized viewport.
//   python3 -m http.server 8123 &          (from the repo root)
//   NODE_PATH=$(npm root -g) node .claude/skills/mobile-performance/measure.mjs [url] [high|fast]
// Prints the renderer's numbers for the last frame and saves perf-<level>.png in the current directory.
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const { chromium } = require('playwright');
const url = process.argv[2] || 'http://localhost:8123/index.html';
const level = process.argv[3] || 'high';

// The game lives in a closure, so wrap THREE.WebGLRenderer to keep a handle on the renderer.
const HOOK = `<script>(() => {
  const R = THREE.WebGLRenderer;
  THREE.WebGLRenderer = function (...a) {
    const r = new R(...a), render = r.render.bind(r);
    return (window.__renderer = r);
  };
})();</script>`;

const browser = await chromium.launch({ args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
const ctx = await browser.newContext({ viewport: { width: 412, height: 915 }, deviceScaleFactor: 2.6, isMobile: true, hasTouch: true });
await ctx.addInitScript(l => { try { localStorage.setItem('ac-gfx', l); } catch (_) {} }, level);
const page = await ctx.newPage();
await page.route(u => u.pathname.endsWith('.html') || u.pathname.endsWith('/'), async route => {
  const res = await route.fetch(), body = await res.text();
  const i = body.indexOf('SkeletonUtils.js"></script>') + 'SkeletonUtils.js"></script>'.length;
  await route.fulfill({ response: res, body: body.slice(0, i) + HOOK + body.slice(i) });
});
const errors = [];
page.on('pageerror', e => errors.push(String(e)));
page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
await page.goto(url, { waitUntil: 'load' });
await page.waitForTimeout(6000);                      // shaders compile, models load
await page.click('#btn-start');                       // menu covers the scene until play starts
await page.waitForTimeout(4000);                      // bowler runs in
const out = await page.evaluate(() => {
  const r = window.__renderer, i = r.info;            // info.render is reset every frame: these are the last frame's numbers
  return { calls: i.render.calls, triangles: i.render.triangles, geometries: i.memory.geometries, textures: i.memory.textures,
           programs: i.programs.length, pixelRatio: r.getPixelRatio(), shadows: r.shadowMap.enabled };
});
console.log(level, JSON.stringify(out));
console.log('errors:', errors.length ? errors.slice(0, 5) : 'none');
await page.screenshot({ path: `perf-${level}.png` });
await browser.close();
