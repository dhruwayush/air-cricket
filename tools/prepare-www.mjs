// Builds www/ for the Android app from index.html.
//   node tools/prepare-www.mjs
// three.js and the two fonts are copied in from node_modules so the game
// works offline. Hand tracking (MediaPipe) still loads from the internet
// the first time, exactly like on the website.
import { readFileSync, writeFileSync, mkdirSync, copyFileSync, rmSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const NM = join(ROOT, 'node_modules');
const WWW = join(ROOT, 'www');

rmSync(WWW, { recursive: true, force: true });
mkdirSync(join(WWW, 'vendor'), { recursive: true });
mkdirSync(join(WWW, 'fonts'), { recursive: true });

let html = readFileSync(join(ROOT, 'index.html'), 'utf8');

function swap(from, to) {
  if (!html.includes(from)) throw new Error('index.html no longer contains: ' + from);
  html = html.split(from).join(to);
}

// three.js r128 from the CDN -> local copies of the same version
const scripts = {
  'https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js': 'three/build/three.min.js',
  'https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/loaders/GLTFLoader.js': 'three/examples/js/loaders/GLTFLoader.js',
  'https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/utils/SkeletonUtils.js': 'three/examples/js/utils/SkeletonUtils.js',
};
for (const [url, rel] of Object.entries(scripts)) {
  const name = rel.split('/').pop();
  copyFileSync(join(NM, rel), join(WWW, 'vendor', name));
  swap(`src="${url}"`, `src="vendor/${name}"`);
}

// Google Fonts -> bundled woff2 files
const fonts = [
  ['Big Shoulders Display', 'big-shoulders-display', [700, 800, 900]],
  ['Barlow Semi Condensed', 'barlow-semi-condensed', [500, 600, 700]],
];
let css = '';
for (const [family, pkg, weights] of fonts) {
  for (const w of weights) {
    const file = `${pkg}-latin-${w}-normal.woff2`;
    copyFileSync(join(NM, '@fontsource', pkg, 'files', file), join(WWW, 'fonts', file));
    css += `@font-face{font-family:"${family}";font-style:normal;font-weight:${w};font-display:swap;src:url(${file}) format("woff2")}\n`;
  }
}
writeFileSync(join(WWW, 'fonts', 'fonts.css'), css);
html = html.replace(/<link rel="preconnect" href="https:\/\/fonts\.g[^"]+"[^>]*>\n?/g, '');
html = html.replace(/<link rel="stylesheet" href="https:\/\/fonts\.googleapis\.com[^"]+">/, '<link rel="stylesheet" href="fonts/fonts.css">');
if (html.includes('fonts.googleapis.com')) throw new Error('Google Fonts link was not replaced');

writeFileSync(join(WWW, 'index.html'), html);
console.log('www/ ready,', Math.round(html.length / 1024), 'KB page');
