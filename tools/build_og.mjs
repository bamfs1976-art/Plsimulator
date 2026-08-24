/* Regenerate the static Open Graph card at /og-default.png.
 *
 * Runs the SAME renderer the browser uses (../og-render.js) under headless
 * Chromium, so the social-share preview is drawn by identical code. The
 * card's numbers come from the latest published weekly snapshot in
 * model.json, and the timestamp from season_state.updated — no wall-clock,
 * so the output is deterministic for a given model.json.
 *
 * Usage:
 *   npm i -D playwright-core        # once (or rely on a pre-installed browser)
 *   node tools/build_og.mjs
 *
 * The browser is located via PLAYWRIGHT_BROWSERS_PATH (falling back to
 * /opt/pw-browsers) or PLAYWRIGHT_CHROMIUM_EXECUTABLE. The committed
 * og-default.png is the artifact that ships; this tool refreshes it.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, "..");
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function fmtDate(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || "");
  if (!m) return iso || "";
  return `${+m[3]} ${MONTHS[+m[2] - 1]} ${m[1]}`;
}

function clubColors() {
  const html = fs.readFileSync(path.join(ROOT, "index.html"), "utf8");
  const m = /const CLUB_COLOR = (\{[\s\S]*?\});/.exec(html);
  try { return m ? JSON.parse(m[1]) : {}; } catch (_) { return {}; }
}

function buildData() {
  const model = JSON.parse(fs.readFileSync(path.join(ROOT, "model.json"), "utf8"));
  const hist = model.odds_history || [];
  if (!hist.length) throw new Error("model.json has no odds_history to render");
  const snap = hist[hist.length - 1];
  const clubs = snap.clubs;
  const colors = clubColors();
  const names = Object.keys(clubs);
  const byTitle = [...names].sort((a, b) => clubs[b].title - clubs[a].title);
  const byRel = [...names].sort((a, b) => clubs[b].rel - clubs[a].rel);
  const seasons = (model.meta && model.meta.default_seasons) || 10000;
  return {
    seasons: seasons.toLocaleString("en-US"),
    dateStr: fmtDate((model.season_state && model.season_state.updated) || snap.date),
    favourite: { name: byTitle[0], pct: clubs[byTitle[0]].title.toFixed(0) },
    relegated: { name: byRel[0], pct: clubs[byRel[0]].rel.toFixed(0) },
    top6: byTitle.slice(0, 6).map((t, i) => ({
      rank: i + 1, name: t, color: colors[t] || "#3f8ce8",
      title: clubs[t].title.toFixed(1), top4: (clubs[t].top4 || 0).toFixed(0), rel: clubs[t].rel.toFixed(0),
    })),
  };
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

async function main() {
  const data = buildData();
  const renderer = fs.readFileSync(path.join(ROOT, "og-render.js"), "utf8");
  let chromium;
  try { ({ chromium } = await import("playwright-core")); }
  catch (_) {
    console.error("playwright-core not found. Install it with: npm i -D playwright-core");
    process.exit(2);
  }
  const executablePath = findBrowser();
  if (!executablePath) {
    console.error("No Chromium found. Set PLAYWRIGHT_BROWSERS_PATH or PLAYWRIGHT_CHROMIUM_EXECUTABLE.");
    process.exit(2);
  }
  const browser = await chromium.launch({ executablePath, headless: true });
  try {
    const page = await browser.newPage();
    const html = `<!doctype html><meta charset="utf-8"><canvas id="c" width="1200" height="630"></canvas>` +
      `<script>${renderer}</script>` +
      `<script>window.__DATA=${JSON.stringify(data)};` +
      `window.PLShareCard.draw(document.getElementById('c').getContext('2d'), window.__DATA);` +
      `window.__png=document.getElementById('c').toDataURL('image/png');</script>`;
    await page.setContent(html, { waitUntil: "load" });
    const dataUrl = await page.evaluate(() => window.__png);
    const b64 = dataUrl.replace(/^data:image\/png;base64,/, "");
    const out = path.join(ROOT, "og-default.png");
    fs.writeFileSync(out, Buffer.from(b64, "base64"));
    console.log(`Wrote ${out} (${data.favourite.name} favourite, ${data.relegated.name} most likely down, ${data.dateStr}).`);
  } finally {
    await browser.close();
  }
}

main().catch(e => { console.error(e); process.exit(1); });
