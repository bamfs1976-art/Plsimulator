/* Shared 1200×630 Open Graph / share-card renderer.
 *
 * A single pure drawing routine used two ways:
 *   • the browser wires it to the "Download share image" button
 *     (a live snapshot of the current Monte Carlo run), and
 *   • tools/build_og.mjs runs it under headless Chromium to regenerate
 *     the static /og-default.png referenced from the document head.
 *
 * It touches only the Canvas 2D API — no DOM, no window — so the same
 * code renders identically in a browser tab and in the build step.
 *
 * data = {
 *   seasons: "10,000",              // pre-formatted count
 *   dateStr: "24 Jul 2026",         // pre-formatted timestamp
 *   favourite:  { name, pct },      // pct as a string, e.g. "42"
 *   relegated:  { name, pct },
 *   top6: [ { rank, name, color, title, top4, rel } ]  // strings
 * }
 */
(function (root) {
  "use strict";
  var W = 1200, H = 630;
  var C = {
    bg: "#14171c", panel: "#1b1f26", line: "#2b3038",
    text: "#ffffff", dim: "#9aa3ad", sub: "#c3c2b7",
    blue: "#3f8ce8", gold: "#d4a017", red: "#e0655f",
  };
  var FONT = "system-ui, -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif";
  function font(spec) { return spec + " " + FONT; }

  function rr(ctx, x, y, w, h, r) {
    if (ctx.roundRect) { ctx.beginPath(); ctx.roundRect(x, y, w, h, r); return; }
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }
  /* Shrink a font until the text fits within maxW (keeps long club names
     like "Nottingham Forest" on one line). */
  function fit(ctx, text, maxW, weight, size, min) {
    size = size || 40; min = min || 24;
    for (var s = size; s >= min; s--) {
      ctx.font = font(weight + " " + s + "px");
      if (ctx.measureText(text).width <= maxW) return;
    }
    ctx.font = font(weight + " " + min + "px");
  }

  function headline(ctx, x, y, label, name, sub, accent) {
    var w = 520, h = 122;
    ctx.fillStyle = C.panel; rr(ctx, x, y, w, h, 14); ctx.fill();
    ctx.fillStyle = accent; rr(ctx, x, y, 6, h, 3); ctx.fill();
    ctx.textAlign = "left"; ctx.textBaseline = "alphabetic";
    ctx.fillStyle = C.dim; ctx.font = font("700 18px");
    ctx.fillText(spread(label), x + 28, y + 38);
    ctx.fillStyle = C.text; fit(ctx, name, w - 56, "800", 42, 26);
    ctx.fillText(name, x + 28, y + 84);
    ctx.fillStyle = C.sub; ctx.font = font("400 22px");
    ctx.fillText(sub, x + 28, y + 112);
  }
  /* Cheap letter-spacing for the small uppercase labels. */
  function spread(s) { return s.split("").join(" "); }

  function draw(ctx, d) {
    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = C.bg; ctx.fillRect(0, 0, W, H);

    /* Top accent band — the site's brand gradient. */
    var g = ctx.createLinearGradient(0, 0, W, 0);
    g.addColorStop(0, "#2456b8"); g.addColorStop(0.5, "#2a78d6"); g.addColorStop(1, "#6c56c9");
    ctx.fillStyle = g; ctx.fillRect(0, 0, W, 8);

    /* Wordmark. */
    ctx.fillStyle = C.blue; rr(ctx, 60, 52, 56, 56, 13); ctx.fill();
    ctx.fillStyle = "#fff"; ctx.font = font("800 26px");
    ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.fillText("PL", 88, 81);
    ctx.textAlign = "left"; ctx.textBaseline = "alphabetic";
    ctx.fillStyle = C.text; ctx.font = font("700 40px");
    ctx.fillText("Premier League 2026/27 Simulator", 134, 78);
    ctx.fillStyle = C.dim; ctx.font = font("400 24px");
    ctx.fillText(d.seasons + " simulated seasons · " + d.dateStr, 134, 110);

    /* Two headline answers. */
    headline(ctx, 60, 150, "TITLE FAVOURITE", d.favourite.name, d.favourite.pct + "% champion", C.gold);
    headline(ctx, 620, 150, "MOST LIKELY DOWN", d.relegated.name, d.relegated.pct + "% relegated", C.red);

    /* Top-6 mini table. */
    var tx = 60, ty = 314, rowH = 40;
    var xName = 96, xTitle = 792, xTop4 = 960, xRel = 1128;
    ctx.textBaseline = "alphabetic";
    ctx.fillStyle = C.dim; ctx.font = font("600 20px");
    ctx.textAlign = "left"; ctx.fillText("Club", xName, ty);
    ctx.textAlign = "right";
    ctx.fillText("Title %", xTitle, ty);
    ctx.fillText("Top 4 %", xTop4, ty);
    ctx.fillText("Rel %", xRel, ty);
    ctx.strokeStyle = C.line; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(tx, ty + 12); ctx.lineTo(1140, ty + 12); ctx.stroke();

    (d.top6 || []).forEach(function (r, i) {
      var y = ty + 30 + i * rowH;
      if (i % 2 === 1) { ctx.fillStyle = "#181c22"; ctx.fillRect(tx, y - 26, 1080, rowH); }
      ctx.fillStyle = C.dim; ctx.font = font("600 22px"); ctx.textAlign = "left";
      ctx.fillText(String(r.rank), tx + 6, y);
      ctx.fillStyle = r.color || C.blue; rr(ctx, xName - 34, y - 20, 18, 18, 5); ctx.fill();
      ctx.fillStyle = C.text; ctx.font = font("600 24px");
      var name = r.name;
      ctx.font = font("600 24px");
      while (ctx.measureText(name).width > xTitle - 120 - xName && name.length > 6) name = name.slice(0, -2);
      if (name !== r.name) name = name.replace(/\s?\S*$/, "…");
      ctx.fillText(name === r.name ? r.name : name, xName, y);
      ctx.textAlign = "right";
      ctx.fillStyle = C.text; ctx.font = font("700 24px"); ctx.fillText(r.title, xTitle, y);
      ctx.fillStyle = C.sub; ctx.font = font("400 24px"); ctx.fillText(r.top4, xTop4, y);
      ctx.fillStyle = (parseFloat(r.rel) >= 15) ? C.red : C.sub;
      ctx.font = font("400 24px"); ctx.fillText(r.rel, xRel, y);
    });

    /* Footer wordmark + provenance. */
    ctx.textAlign = "left"; ctx.fillStyle = C.dim; ctx.font = font("400 22px");
    ctx.fillText("plsimulation.netlify.app · recalibrated weekly · within 0.007 RPS of Pinnacle closing odds", 60, 600);
  }

  root.PLShareCard = { draw: draw, WIDTH: W, HEIGHT: H };
})(typeof window !== "undefined" ? window : globalThis);
