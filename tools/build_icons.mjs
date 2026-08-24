/* Generate the app icon + logo set from one vector source.
 *
 * The mark: the brand blue->purple gradient with a bold "PL" monogram
 * (drawn as vector strokes, so it needs no font) sitting over a subtle
 * distribution-histogram accent — a nod to the finishing-position charts
 * the simulator is built around. Rendered to PNG through the pre-installed
 * headless Chromium (same approach as tools/build_og.mjs), so there are no
 * new runtime dependencies.
 *
 *   npm i -D playwright-core   # once (or rely on a pre-installed browser)
 *   node tools/build_icons.mjs
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, "..");

/* Diagonal brand gradient (matches --grad in index.html). */
function grad(id) {
  return `<linearGradient id="${id}" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#2456b8"/>
      <stop offset="0.5" stop-color="#2a78d6"/>
      <stop offset="1" stop-color="#6c56c9"/>
    </linearGradient>`;
}

/* The "PL" monogram + histogram accent, drawn in a 100x100 box, centred.
   `mark` scales/positions the whole group; `accent` toggles the bars. */
function markGroup({ accent = true } = {}) {
  // Histogram accent: a distribution-shaped row of rounded bars, sitting
  // cleanly below the monogram.
  const bars = [0.45, 0.75, 1.0, 0.7, 0.4];
  const bw = 7, gap = 3.4, baseY = 82, maxH = 16;
  const totalW = bars.length * bw + (bars.length - 1) * gap;
  const startX = 50 - totalW / 2;
  const hist = accent
    ? bars.map((v, i) => {
        const h = 4.5 + maxH * v, x = startX + i * (bw + gap);
        return `<rect x="${x.toFixed(2)}" y="${(baseY - h).toFixed(2)}" width="${bw}" height="${h.toFixed(2)}" rx="2.4" fill="#fff" opacity="${(0.42 + 0.4 * v).toFixed(2)}"/>`;
      }).join("")
    : "";
  // PL monogram as round-capped strokes, centred in the box.
  const sw = 9;
  const pl = `<g transform="translate(-5,0)" fill="none" stroke="#fff" stroke-width="${sw}" stroke-linecap="round" stroke-linejoin="round">
      <path d="M30 54 V16 H42 a11 11 0 0 1 0 22 H30"/>
      <path d="M60 16 V54 H80"/>
    </g>`;
  return `<g>${pl}${hist}</g>`;
}

function iconSVG(size, { radius = 0, accent = true } = {}) {
  const r = radius;
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 100 100">
    <defs>${grad("g")}
      <filter id="sh" x="-20%" y="-20%" width="140%" height="140%">
        <feDropShadow dx="0" dy="1.1" stdDeviation="1.1" flood-color="#0b1a3a" flood-opacity="0.28"/>
      </filter>
    </defs>
    <rect x="0" y="0" width="100" height="100" rx="${r}" fill="url(#g)"/>
    <g filter="url(#sh)">${markGroup({ accent })}</g>
  </svg>`;
}

/* Horizontal logo lockup: the tile mark + wordmark. Uses the app's font
   stack (Bricolage Grotesque where available). */
function logoSVG({ w = 760, h = 200, dark = false } = {}) {
  const tile = 152, pad = 24, tx = pad, ty = (h - tile) / 2;
  const text1 = dark ? "#fff" : "#1a1a19";
  const text2 = dark ? "#c3c2b7" : "#55544e";
  const bg = dark ? "#1a1a19" : "#ffffff";
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">
    <defs>${grad("gl")}</defs>
    <rect width="${w}" height="${h}" fill="${bg}"/>
    <g transform="translate(${tx},${ty})">
      <svg width="${tile}" height="${tile}" viewBox="0 0 100 100">
        <rect width="100" height="100" rx="22" fill="url(#gl)"/>
        <g>${markGroup({ accent: true })}</g>
      </svg>
    </g>
    <g font-family="'Bricolage Grotesque', system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif">
      <text x="${tx + tile + 28}" y="${h / 2 - 8}" font-size="46" font-weight="800" fill="${text1}" letter-spacing="-1">Premier League</text>
      <text x="${tx + tile + 28}" y="${h / 2 + 40}" font-size="30" font-weight="600" fill="${text2}" letter-spacing="-0.5">2026/27 Simulator</text>
    </g>
  </svg>`;
}

function findBrowser() {
  if (process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE) return process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE;
  const base = process.env.PLAYWRIGHT_BROWSERS_PATH || "/opt/pw-browsers";
  if (!fs.existsSync(base)) return null;
  const dir = fs.readdirSync(base).find(d => d.startsWith("chromium-") && !d.includes("headless"));
  if (!dir) return null;
  const exe = path.join(base, dir, "chrome-linux", "chrome");
  return fs.existsSync(exe) ? exe : null;
}

async function shoot(page, svg) {
  await page.setContent(
    `<!doctype html><meta charset="utf-8"><style>html,body{margin:0}svg{display:block}</style>${svg}`,
    { waitUntil: "load" });
  return page.locator("svg").first().screenshot({ omitBackground: true });
}

async function main() {
  let chromium;
  try { ({ chromium } = await import("playwright-core")); }
  catch (_) { console.error("playwright-core not found. Install it: npm i -D playwright-core"); process.exit(2); }
  const executablePath = findBrowser();
  if (!executablePath) { console.error("No Chromium found (PLAYWRIGHT_BROWSERS_PATH / PLAYWRIGHT_CHROMIUM_EXECUTABLE)."); process.exit(2); }

  // Static SVG assets (crisp at any size).
  fs.writeFileSync(path.join(ROOT, "favicon.svg"), iconSVG(64, { radius: 14, accent: false }) + "\n");
  fs.writeFileSync(path.join(ROOT, "logo.svg"), logoSVG({}) + "\n");
  fs.writeFileSync(path.join(ROOT, "logo-dark.svg"), logoSVG({ dark: true }) + "\n");

  const browser = await chromium.launch({ executablePath, headless: true });
  try {
    const page = await browser.newPage({ deviceScaleFactor: 1 });
    // PWA icons: full-bleed square gradient so they double as maskable.
    const jobs = [
      ["icon-512.png", iconSVG(512, { radius: 0, accent: true })],
      ["icon-192.png", iconSVG(192, { radius: 0, accent: true })],
      ["apple-touch-icon.png", iconSVG(180, { radius: 40, accent: true })],
      ["logo.png", logoSVG({})],
      ["logo-dark.png", logoSVG({ dark: true })],
    ];
    for (const [name, svg] of jobs) {
      fs.writeFileSync(path.join(ROOT, name), await shoot(page, svg));
      console.log(`wrote ${name}`);
    }
    console.log("wrote favicon.svg, logo.svg, logo-dark.svg");
  } finally {
    await browser.close();
  }
}

main().catch(e => { console.error(e); process.exit(1); });
