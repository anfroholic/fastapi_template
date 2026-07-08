/* Metal Halftone Studio — live browser preview.
 *
 * Mirrors the generator pipeline from art.md so what you see is what the CLI
 * emits: paste-over-white -> resize to the metal grid FIRST -> per-pixel HSV
 * classify -> on-grid screen synthesis -> 2x2 morphological open -> declobber.
 * The style registry + thresholds below are vendored from the spec (art.md §3,
 * §7.3) and must not drift from the generator's registry.
 */
(() => {
  "use strict";

  // ---- locked v1.1 registry (art.md §3.1) ----------------------------------
  // hue band (deg) -> screen style; reached only when S >= satFloor, V >= solidV.
  // Grey (below satFloor) maps to clustered dots — see classify().
  const HUE_BANDS = [
    { lo: 340, hi: 360, style: "xmesh" },  // red (wraps)
    { lo: 0,   hi: 20,  style: "xmesh" },  // red
    { lo: 20,  hi: 45,  style: "brick" },  // orange
    { lo: 45,  hi: 75,  style: "d45"   },  // yellow
    { lo: 75,  hi: 150, style: "mesh"  },  // green
    { lo: 150, hi: 200, style: "d135"  },  // cyan
    { lo: 200, hi: 250, style: "hline" },  // blue
    { lo: 250, hi: 290, style: "weave" },  // violet
    { lo: 290, hi: 340, style: "vline" },  // magenta
  ];

  // Per-style boolean generators (art.md §4.4): metal at (x, y) for pitch P,
  // feature width w. ((x-y)%P) needs the +P to stay non-negative in JS.
  const STYLES = {
    solid: () => true,
    empty: () => false,
    hline: (x, y, P, w) => (y % P) < w,
    vline: (x, y, P, w) => (x % P) < w,
    d45:   (x, y, P, w) => ((x + y) % P) < w,
    d135:  (x, y, P, w) => (((x - y) % P) + P) % P < w,
    mesh:  (x, y, P, w) => (y % P) < w || (x % P) < w,
    xmesh: (x, y, P, w) => ((x + y) % P) < w || ((((x - y) % P) + P) % P) < w,
    dot:   (x, y, P, w) => {
      const lo = (P - w) >> 1, cx = x % P, cy = y % P;
      return cx >= lo && cx < lo + w && cy >= lo && cy < lo + w;
    },
    // running-bond brick: courses w tall, mortar P-w (>= 2 by feat clamp),
    // head joints offset half a brick every other course
    brick: (x, y, P, w) => {
      const off = (Math.floor(y / P) & 1) ? P : 0;
      return (y % P) < w && ((x + off) % (2 * P)) < (2 * P - (P - w));
    },
    // basket weave: cells checker between horizontal and vertical stripes
    weave: (x, y, P, w) =>
      ((Math.floor(x / P) + Math.floor(y / P)) & 1)
        ? (x % P) < w
        : (y % P) < w,
  };

  // Dropdown labels for the per-color remap panel ("dotm" is the grey matrix).
  const STYLE_LABELS = {
    solid: "█ solid (slotted)", empty: "· empty",
    dotm: "• dots (halftone)", hline: "─ horizontal", vline: "‖ vertical",
    d45: "⟋ 45°", d135: "⟍ 135°", mesh: "# mesh", xmesh: "╳ crosshatch",
    dot: "▪ dot grid", brick: "▦ brick", weave: "▤ weave",
  };

  const T = {              // tone thresholds (art.md §3.1 / §7.3), 0..1
    solidV: 0.28, solidS: 0.35,
    emptyV: 0.90,
    satFloor: 0.12,        // drives both grey_s_max and color_s_floor
    colorDiv: 0.55, colorFloor: 0.20,
    // grey density floor is derived, not configured: 4.5 / dotPitch² (§4.4)
  };

  const state = { pixelSize: 0.60, pitch: 5, dotPitch: 10, sizeW: 480, sizeH: 480 };
  const MAX_GRID = 5000;   // browser safety clamp on grid dimension (px) — a full
                           // 2.5 mm chip at 0.50 µm/px; big grids render in seconds
  const MSLOT_UM = 28;     // guard margin under the 30 µm wide-metal rule (art.md §4.8)

  // ---- pipeline ------------------------------------------------------------
  function hsv(r, g, b) {
    const mx = Math.max(r, g, b), mn = Math.min(r, g, b), d = mx - mn;
    let h = 0;
    if (d) {
      if (mx === r) h = ((g - b) / d) % 6;
      else if (mx === g) h = (b - r) / d + 2;
      else h = (r - g) / d + 4;
      h *= 60; if (h < 0) h += 360;
    }
    return [h, mx ? d / mx : 0, mx / 255];
  }

  function hueStyle(h) {
    for (const b of HUE_BANDS) if (h >= b.lo && h < b.hi) return b.style;
    return "xmesh";
  }

  function classify(h, s, v) {
    if (v < T.solidV && s < T.solidS) return ["solid", 1];
    if (v > T.emptyV && s < T.satFloor) return ["empty", 0];
    if (s < T.satFloor && v >= T.solidV && v <= T.emptyV)   // grey: darker = bigger dots
      return ["dotm", (T.emptyV - v) / (T.emptyV - T.solidV)];
    if (s >= T.satFloor && v >= T.solidV)
      return [hueStyle(h), Math.min(1, Math.max(T.colorFloor, s / T.colorDiv))];
    return ["solid", 1];   // dark-but-saturated falls through: dark reads as metal
  }

  // density -> on-grid feature width; both feature and gap stay >= 2 px so they
  // survive the 2x2 open and clear min-width / min-space (art.md §4.4)
  function feat(density, P) {
    const lo = 2, hi = Math.max(2, P - 2);
    return Math.min(hi, Math.max(lo, Math.round(lo + density * (hi - lo))));
  }

  // Clustered-dot threshold matrix (art.md §4.4): cell positions ranked by
  // distance from center, so the dot grows one grid pixel per tone step ->
  // ~P^2 grey levels instead of the 2-3 that feat()'s width quantization gives.
  // The quarter-pixel center offset makes ranks 0-3 a 2x2 seed block, so the
  // smallest dot already survives the 2x2 open (a 1px center dot would not).
  const matrixCache = new Map();
  function dotMatrix(P) {
    let T = matrixCache.get(P);
    if (T) return T;
    const c = (P - 1) / 2 - 0.25;
    const ranked = [];
    for (let y = 0; y < P; y++)
      for (let x = 0; x < P; x++) {
        // the far-corner 2x2 block is forced to rank LAST: at the density cap
        // (1 - 4/P²) it stays empty, so the darkest tone keeps a 2x2 slot hole
        // per cell and dark grey can never close into unslotted wide metal
        const hole = (x >= P - 2 && y >= P - 2) ? 1 : 0;
        ranked.push([hole, Math.hypot(x - c, y - c), y * P + x]);
      }
    ranked.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
    T = new Float32Array(P * P);
    ranked.forEach(([, , idx], rank) => { T[idx] = (rank + 0.5) / (P * P); });
    matrixCache.set(P, T);
    return T;
  }

  // 2x2 morphological opening: erode then dilate; removes sub-2px slivers
  function open2(M, W, H) {
    const E = new Uint8Array(W * H);
    for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
      const i = y * W + x;
      E[i] = (x + 1 < W && y + 1 < H &&
              M[i] && M[i + 1] && M[i + W] && M[i + W + 1]) ? 1 : 0;
    }
    for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
      const i = y * W + x;
      M[i] = (E[i] ||
              (x > 0 && E[i - 1]) ||
              (y > 0 && E[i - W]) ||
              (x > 0 && y > 0 && E[i - W - 1])) ? 1 : 0;
    }
  }

  // Wide-metal (MSLOT) guard, art.md §4.8: a region >= ~30 µm in BOTH axes needs
  // stress-relief slots. Detect conservatively by sliding an SxS all-metal window
  // (summed-area table) over the post-cleanup bitmap; cluster hits into boxes.
  let mslotBoxes = [], mslotS = 0;
  function mslotCheck(M, W, H, S) {
    mslotBoxes = []; mslotS = S;
    if (S < 2 || S > W || S > H) return;
    const W1 = W + 1;
    const sat = new Int32Array(W1 * (H + 1));
    for (let y = 0; y < H; y++) {
      let row = 0;
      for (let x = 0; x < W; x++) {
        row += M[y * W + x];
        sat[(y + 1) * W1 + (x + 1)] = sat[y * W1 + (x + 1)] + row;
      }
    }
    const area = S * S;
    for (let y = 0; y + S <= H; y++) {
      for (let x = 0; x + S <= W; x++) {
        const sum = sat[(y + S) * W1 + (x + S)] - sat[y * W1 + (x + S)]
                  - sat[(y + S) * W1 + x] + sat[y * W1 + x];
        if (sum !== area) continue;
        let hit = null;
        for (const b of mslotBoxes)
          if (x >= b.x0 - S && x <= b.x1 + S && y >= b.y0 - S && y <= b.y1 + S) { hit = b; break; }
        if (hit) {
          if (x < hit.x0) hit.x0 = x;
          if (y < hit.y0) hit.y0 = y;
          if (x > hit.x1) hit.x1 = x;
          if (y > hit.y1) hit.y1 = y;
        } else if (mslotBoxes.length < 32) {
          mslotBoxes.push({ x0: x, y0: y, x1: x, y1: y });
        }
      }
    }
  }

  // Break 2x2 checkerboards: a metal-metal diagonal touch is a zero-width
  // pinch and its empty-empty complement a zero-space pinch; filling one
  // corner clears both (art.md §4.5). Two passes, like the generator.
  function declobber(M, W, H) {
    for (let pass = 0; pass < 2; pass++)
      for (let y = 0; y < H - 1; y++) for (let x = 0; x < W - 1; x++) {
        const i = y * W + x;
        const a = M[i], b = M[i + 1], c = M[i + W], d = M[i + W + 1];
        if (a && d && !b && !c) M[i + 1] = 1;
        else if (b && c && !a && !d) M[i] = 1;
      }
  }

  // ---- DOM -----------------------------------------------------------------
  const $ = (id) => document.getElementById(id);
  const control = $("control"), output = $("output"), zoom = $("zoom");
  const cctx = control.getContext("2d", { willReadFrequently: true });
  const octx = output.getContext("2d");
  const zctx = zoom.getContext("2d");

  const grid = document.createElement("canvas");        // stencil at grid res
  const gctx = grid.getContext("2d", { willReadFrequently: true });
  let M = null, gridW = 0, gridH = 0;                    // last stencil buffer

  const METAL = [23, 26, 33], EMPTY = [242, 239, 232];   // stencil display colors

  // ---- per-color remap -----------------------------------------------------
  // Colors are grouped by a 4-bit/channel quantization key (4096 buckets), so
  // anti-aliased fringes cluster with their parent color. An override replaces
  // the automatic HSV classification for every pixel in that bucket.
  const QBITS = 4, QMASK = 0xF0;
  const qkeyOf = (r, g, b) => ((r & QMASK) << (2 * QBITS - 4)) | ((g & QMASK) << (QBITS - 4)) | (b >> QBITS);
  const overrides = new Map();   // qkey -> {style: name|"auto", density: 0..1|null}

  // Global grey tone curve (art.md §4.4): d' = (d^gamma − 0.5)·contrast + 0.5 + brightness,
  // applied to every auto grey density before clamping. d' <= 0 renders empty, so
  // brightness can push the lightest greys all the way to bare silicon.
  const tone = { bright: 0, contrast: 1, gamma: 1 };

  function synth() {
    const t0 = performance.now();
    // grid dims from the macro µm size; a single scale factor keeps the
    // aspect ratio exact even when one dimension hits the browser clamp
    let gw = Math.max(8, Math.round(state.sizeW / state.pixelSize));
    let gh = Math.max(8, Math.round(state.sizeH / state.pixelSize));
    const clamp = Math.min(1, MAX_GRID / Math.max(gw, gh));
    gridW = Math.max(50, Math.round(gw * clamp));
    gridH = Math.max(50, Math.round(gh * clamp));
    const P = state.pitch;

    // resize FIRST, compositing over white (the alpha gotcha, art.md §4.1-4.2)
    grid.width = gridW; grid.height = gridH;
    gctx.imageSmoothingEnabled = true;
    gctx.fillStyle = "#fff";
    gctx.fillRect(0, 0, gridW, gridH);
    gctx.drawImage(control, 0, 0, gridW, gridH);
    const src = gctx.getImageData(0, 0, gridW, gridH).data;

    // palette accumulators (per quant bucket): count + summed RGB for the chip
    const cnt = new Uint32Array(4096);
    const rSum = new Uint32Array(4096), gSum = new Uint32Array(4096), bSum = new Uint32Array(4096);
    let ovLut = null;
    if (overrides.size) {
      ovLut = new Array(4096);
      for (const [k, o] of overrides) ovLut[k] = o;
    }

    M = new Uint8Array(gridW * gridH);
    const Pd = state.dotPitch;           // grey halftone cell, decoupled from P (§4.4)
    const Tm = dotMatrix(Pd);
    const seedFloor = 4.5 / (Pd * Pd);   // lightest tone: just the 2x2 seed dot
    const dMax = 1 - 4 / (Pd * Pd);      // darkest tone: keep the 2x2 slot hole
    const toneOn = tone.bright !== 0 || tone.contrast !== 1 || tone.gamma !== 1;
    for (let y = 0; y < gridH; y++) {
      for (let x = 0; x < gridW; x++) {
        const i = y * gridW + x, j = i * 4;
        const r = src[j], g = src[j + 1], b = src[j + 2];
        const q = qkeyOf(r, g, b);
        cnt[q]++; rSum[q] += r; gSum[q] += g; bSum[q] += b;

        const [h, s, v] = hsv(r, g, b);
        let [style, density] = classify(h, s, v);
        let pinned = false;          // per-color override wins over the tone curve
        if (ovLut) {
          const ov = ovLut[q];
          if (ov) {
            if (ov.style !== "auto") style = ov.style;
            if (ov.density != null) { density = ov.density; pinned = true; }
          }
        }
        if (style === "dotm" && !pinned && toneOn)
          density = (Math.pow(density, tone.gamma) - 0.5) * tone.contrast + 0.5 + tone.bright;
        if (style === "solid")       // auto-slotted solid = the darkest grey tone
          M[i] = ((x % Pd) >= Pd - 2 && (y % Pd) >= Pd - 2) ? 0 : 1;
        else if (style === "empty") M[i] = 0;
        else if (style === "dotm")   // ordered dither, clamped to [seed, slotted-max]
          M[i] = density <= 0 ? 0 :
                 (Math.min(dMax, Math.max(seedFloor, density)) >
                  Tm[(y % Pd) * Pd + (x % Pd)] ? 1 : 0);
        else M[i] = STYLES[style](x, y, P, feat(density, P)) ? 1 : 0;
      }
    }
    open2(M, gridW, gridH);
    declobber(M, gridW, gridH);
    mslotCheck(M, gridW, gridH, Math.round(MSLOT_UM / state.pixelSize));

    // paint stencil + stats
    const img = gctx.createImageData(gridW, gridH);
    let metal = 0, runs = 0;
    for (let y = 0; y < gridH; y++) {
      let prev = 0;
      for (let x = 0; x < gridW; x++) {
        const i = y * gridW + x, m = M[i], c = m ? METAL : EMPTY, j = i * 4;
        img.data[j] = c[0]; img.data[j + 1] = c[1]; img.data[j + 2] = c[2];
        img.data[j + 3] = 255;
        metal += m;
        if (m && !prev) runs++;
        prev = m;
      }
    }
    gctx.putImageData(img, 0, 0);
    // output shown 1:1 at grid resolution; CSS scales it, preserving aspect
    output.width = gridW; output.height = gridH;
    octx.imageSmoothingEnabled = false;
    octx.drawImage(grid, 0, 0);
    if (mslotBoxes.length) {
      octx.strokeStyle = "#ff2d55";
      octx.lineWidth = Math.max(2, Math.round(gridW / 300));
      for (const b of mslotBoxes)
        octx.strokeRect(b.x0 - 0.5, b.y0 - 0.5, b.x1 - b.x0 + mslotS, b.y1 - b.y0 + mslotS);
    }

    const mslotEl = $("mslotinfo");
    if (mslotBoxes.length) {
      const n = mslotBoxes.length;
      mslotEl.textContent = `MSLOT ⚠ ${n} solid region${n > 1 ? "s" : ""} ≥ ${MSLOT_UM} µm in both axes`;
      mslotEl.title = "Wide metal needs stress-relief slots (art.md §4.8). With " +
        "auto-slotted solids this should not normally fire — inspect the outlined " +
        "region; some style/pitch combination produced ≥28 µm of unbroken metal.";
      mslotEl.className = "stat mslot-bad";
    } else {
      mslotEl.textContent = "MSLOT ✓ no wide metal";
      mslotEl.title = "No solid region is ≥ " + MSLOT_UM + " µm in both axes (art.md §4.8).";
      mslotEl.className = "stat mslot-ok";
    }

    $("coverage").textContent = (100 * metal / (gridW * gridH)).toFixed(1) + " %";
    $("gridinfo").textContent =
      `grid ${gridW} × ${gridH} px = ${(gridW * state.pixelSize).toFixed(0)} × ` +
      `${(gridH * state.pixelSize).toFixed(0)} µm @ ${state.pixelSize.toFixed(2)} µm/px` +
      (clamp < 1 ? ` — CLAMPED to ${MAX_GRID} px for preview (raise pixel size, or let the CLI render full size)` : "");
    // settle the paired size/grid inputs (skip whichever is being edited)
    for (const [id, v] of [["sizew", Math.round(state.sizeW)], ["sizeh", Math.round(state.sizeH)],
                           ["gridw", gridW], ["gridh", gridH]]) {
      const el = $(id);
      if (document.activeElement !== el) el.value = v;
    }
    $("shapeinfo").textContent =
      `~${runs.toLocaleString()} shapes (pre-merge) · ${Math.round(performance.now() - t0)} ms`;

    updatePalette(cnt, rSum, gSum, bSum, gridW * gridH);
    if (!fullview.hidden) fvDraw();
  }

  let queued = false;
  function schedule() {
    if (queued) return;
    queued = true;
    requestAnimationFrame(() => { queued = false; synth(); });
  }

  // ---- per-color remap panel ------------------------------------------------
  const paletteBox = $("palette");
  // the tone knobs + palette travel together to the full view and back
  const paletteTools = $("palette-tools");
  const paletteHome = paletteTools.parentElement;
  const paletteNext = paletteTools.nextElementSibling;
  let paletteSig = "";
  const paletteRows = new Map();   // qkey -> {pct} live spans

  function updatePalette(cnt, rSum, gSum, bSum, total) {
    // colors worth a row: >= 0.2% of pixels (skips anti-alias fringe buckets)
    const minN = Math.max(40, total * 0.002);
    const entries = [];
    for (let k = 0; k < 4096; k++)
      if (cnt[k] >= minN)
        entries.push({
          key: k, n: cnt[k],
          r: Math.round(rSum[k] / cnt[k]),
          g: Math.round(gSum[k] / cnt[k]),
          b: Math.round(bSum[k] / cnt[k]),
        });
    entries.sort((a, b) => b.n - a.n);
    const shown = entries.slice(0, 16);

    // set-signature is order-independent so rows don't reshuffle mid-drag
    const sig = shown.map((e) => e.key).sort((a, b) => a - b).join(",");
    if (sig === paletteSig) {
      for (const e of shown) {
        const row = paletteRows.get(e.key);
        if (row) row.pct.textContent = (100 * e.n / total).toFixed(1) + "%";
      }
      return;
    }
    paletteSig = sig;
    paletteRows.clear();
    paletteBox.innerHTML = "";

    for (const e of shown) {
      const [h, s, v] = hsv(e.r, e.g, e.b);
      const [autoStyle, autoDen] = classify(h, s, v);
      const ov = overrides.get(e.key);

      const row = document.createElement("div");
      row.className = "palette-row" + (ov ? " overridden" : "");

      const chip = document.createElement("span");
      chip.className = "pal-chip";
      chip.style.background = `rgb(${e.r},${e.g},${e.b})`;

      const sel = document.createElement("select");
      sel.className = "pal-select";
      const autoOpt = document.createElement("option");
      autoOpt.value = "auto";
      autoOpt.textContent = `auto — ${STYLE_LABELS[autoStyle]}`;
      sel.appendChild(autoOpt);
      for (const name of Object.keys(STYLE_LABELS)) {
        const o = document.createElement("option");
        o.value = name;
        o.textContent = STYLE_LABELS[name];
        sel.appendChild(o);
      }
      sel.value = ov ? ov.style : "auto";

      const pct = document.createElement("span");
      pct.className = "pal-pct mono";
      pct.textContent = (100 * e.n / total).toFixed(1) + "%";

      const reset = document.createElement("button");
      reset.className = "pal-reset";
      reset.title = "reset to automatic mapping";
      reset.textContent = "↺";

      const den = document.createElement("input");
      den.type = "range";
      den.min = "0.05"; den.max = "1"; den.step = "0.01";
      den.value = ov && ov.density != null ? ov.density : autoDen.toFixed(2);
      den.title = "density — how heavy the fill is";

      const denVal = document.createElement("span");
      denVal.className = "pal-den mono";
      denVal.textContent = parseFloat(den.value).toFixed(2);

      const ensure = () => {
        let o = overrides.get(e.key);
        if (!o) { o = { style: "auto", density: null }; overrides.set(e.key, o); }
        row.classList.add("overridden");
        return o;
      };
      sel.addEventListener("change", () => { ensure().style = sel.value; schedule(); });
      den.addEventListener("input", () => {
        ensure().density = parseFloat(den.value);
        denVal.textContent = parseFloat(den.value).toFixed(2);
        schedule();
      });
      reset.addEventListener("click", () => {
        overrides.delete(e.key);
        sel.value = "auto";
        den.value = autoDen.toFixed(2);
        denVal.textContent = autoDen.toFixed(2);
        row.classList.remove("overridden");
        schedule();
      });

      const top = document.createElement("div");
      top.className = "pal-top";
      top.append(chip, sel, reset);
      const bottom = document.createElement("div");
      bottom.className = "pal-bottom";
      bottom.append(den, denVal, pct);
      row.append(top, bottom);
      paletteBox.appendChild(row);
      paletteRows.set(e.key, { pct });
    }
    if (!shown.length)
      paletteBox.innerHTML = '<p class="small muted">No colors yet — paint or load an image.</p>';
  }

  // ---- pixel inspector -----------------------------------------------------
  const ZCELLS = 21, ZPX = 9;   // 21x21 grid pixels at 9x
  function drawZoom(gx, gy) {
    zctx.fillStyle = "#e6eaf2";
    zctx.fillRect(0, 0, zoom.width, zoom.height);
    if (!M) return;
    const half = ZCELLS >> 1;
    for (let dy = 0; dy < ZCELLS; dy++) {
      for (let dx = 0; dx < ZCELLS; dx++) {
        const x = gx - half + dx, y = gy - half + dy;
        if (x < 0 || y < 0 || x >= gridW || y >= gridH) continue;
        const m = M[y * gridW + x];
        zctx.fillStyle = m ? "rgb(23,26,33)" : "rgb(242,239,232)";
        zctx.fillRect(dx * ZPX, dy * ZPX, ZPX - 1, ZPX - 1);
      }
    }
    zctx.strokeStyle = "#ff6b57";
    zctx.strokeRect(half * ZPX - 1.5, half * ZPX - 1.5, ZPX + 2, ZPX + 2);
  }
  output.addEventListener("mousemove", (ev) => {
    const r = output.getBoundingClientRect();
    drawZoom(
      Math.floor((ev.clientX - r.left) / r.width * gridW),
      Math.floor((ev.clientY - r.top) / r.height * gridH),
    );
  });

  // ---- full-screen view ----------------------------------------------------
  const fullview = $("fullview"), fvCanvas = $("fvcanvas");
  const fvctx = fvCanvas.getContext("2d");
  const fvState = { z: 1, ox: 0, oy: 0, src: "stencil" };

  function fvSrc() { return fvState.src === "stencil" ? grid : control; }

  function fvDraw() {
    const cw = fvCanvas.clientWidth, ch = fvCanvas.clientHeight;
    if (fvCanvas.width !== cw) fvCanvas.width = cw;
    if (fvCanvas.height !== ch) fvCanvas.height = ch;
    fvctx.fillStyle = "#12151b";
    fvctx.fillRect(0, 0, cw, ch);
    // nearest-neighbor keeps grid pixels crisp when zoomed in; smooth when
    // zoomed out so dot fields average to their tone instead of aliasing
    fvctx.imageSmoothingEnabled = fvState.src === "control" || fvState.z < 1;
    fvctx.setTransform(fvState.z, 0, 0, fvState.z, fvState.ox, fvState.oy);
    fvctx.drawImage(fvSrc(), 0, 0);
    if (fvState.src === "stencil" && mslotBoxes.length) {
      fvctx.strokeStyle = "#ff2d55";
      fvctx.lineWidth = 2 / fvState.z;
      for (const b of mslotBoxes)
        fvctx.strokeRect(b.x0 - 0.5, b.y0 - 0.5, b.x1 - b.x0 + mslotS, b.y1 - b.y0 + mslotS);
    }
    fvctx.setTransform(1, 0, 0, 1, 0, 0);
    const umPerScreenPx = fvState.src === "stencil"
      ? ` · ${(state.pixelSize / fvState.z).toFixed(2)} µm/screen-px`
      : "";
    $("fv-zoom").textContent = `${fvState.z.toFixed(2)}×${umPerScreenPx}`;
  }

  function fvFit() {
    const s = fvSrc();
    const cw = fvCanvas.clientWidth, ch = fvCanvas.clientHeight;
    fvState.z = Math.min(cw / s.width, ch / s.height) * 0.95;
    fvState.ox = (cw - s.width * fvState.z) / 2;
    fvState.oy = (ch - s.height * fvState.z) / 2;
    fvDraw();
  }

  function fvOpen() {
    fullview.hidden = false;
    // borrow the live remap tools (listeners, overrides, tone state come along)
    $("fv-palette-slot").appendChild(paletteTools);
    fvFit();
  }
  function fvClose() {
    fullview.hidden = true;
    paletteHome.insertBefore(paletteTools, paletteNext);
  }

  $("fullbtn").addEventListener("click", fvOpen);
  output.addEventListener("click", fvOpen);
  $("fv-close").addEventListener("click", fvClose);
  $("fv-fit").addEventListener("click", fvFit);
  $("fv-100").addEventListener("click", () => {
    // 1:1 = one grid pixel per screen pixel, centered on the current view center
    const cw = fvCanvas.clientWidth, ch = fvCanvas.clientHeight;
    const cx = (cw / 2 - fvState.ox) / fvState.z, cy = (ch / 2 - fvState.oy) / fvState.z;
    fvState.z = 1;
    fvState.ox = cw / 2 - cx; fvState.oy = ch / 2 - cy;
    fvDraw();
  });
  $("fv-src").addEventListener("click", () => {
    fvState.src = fvState.src === "stencil" ? "control" : "stencil";
    $("fv-src").textContent = fvState.src === "stencil" ? "show control" : "show stencil";
    $("fv-title").textContent = fvState.src === "stencil"
      ? "Stencil — full view" : "Control map — full view";
    fvFit();
  });
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape" && !fullview.hidden) fvClose();
  });
  window.addEventListener("resize", () => { if (!fullview.hidden) fvDraw(); });

  fvCanvas.addEventListener("wheel", (ev) => {
    ev.preventDefault();
    const k = Math.exp(-ev.deltaY * 0.0015);
    const nz = Math.min(40, Math.max(0.05, fvState.z * k));
    const r = fvCanvas.getBoundingClientRect();
    const mx = ev.clientX - r.left, my = ev.clientY - r.top;
    // zoom about the cursor: keep the image point under the mouse fixed
    fvState.ox = mx - (mx - fvState.ox) * (nz / fvState.z);
    fvState.oy = my - (my - fvState.oy) * (nz / fvState.z);
    fvState.z = nz;
    fvDraw();
  }, { passive: false });

  let fvDragging = false, fvLast = null;
  fvCanvas.addEventListener("pointerdown", (ev) => {
    fvDragging = true;
    fvCanvas.setPointerCapture(ev.pointerId);
    fvLast = [ev.clientX, ev.clientY];
  });
  fvCanvas.addEventListener("pointermove", (ev) => {
    if (!fvDragging) return;
    fvState.ox += ev.clientX - fvLast[0];
    fvState.oy += ev.clientY - fvLast[1];
    fvLast = [ev.clientX, ev.clientY];
    fvDraw();
  });
  fvCanvas.addEventListener("pointerup", () => { fvDragging = false; });

  // ---- painting ------------------------------------------------------------
  const SWATCHES = [
    ["#111111", "black — solid metal (auto-slotted: one 2×2 hole per dot-pitch cell)"], ["#ffffff", "empty (erase)"],
    ["#c9c9c9", "light grey — sparse dots"], ["#8a8a8a", "grey — dots"],
    ["#4a4a4a", "dark grey — dense dots"],
    ["hsl(0,90%,50%)", "red — ╳ crosshatch"], ["hsl(30,92%,50%)", "orange — ▦ brick"],
    ["hsl(55,95%,50%)", "yellow — ⟋ 45°"], ["hsl(120,80%,42%)", "green — # mesh"],
    ["hsl(175,85%,42%)", "cyan — ⟍ 135°"], ["hsl(225,85%,55%)", "blue — ─ horizontal"],
    ["hsl(270,80%,55%)", "violet — ▤ weave"], ["hsl(315,85%,52%)", "magenta — ‖ vertical"],
  ];
  let paintColor = SWATCHES[5][0], brush = 26, painting = false, last = null;

  const swatchBox = $("swatches");
  SWATCHES.forEach(([color, title], i) => {
    const b = document.createElement("button");
    b.className = "swatch" + (i === 5 ? " active" : "");
    b.style.background = color;
    b.title = title;
    b.addEventListener("click", () => {
      paintColor = color;
      swatchBox.querySelectorAll(".swatch").forEach((s) => s.classList.remove("active"));
      b.classList.add("active");
    });
    swatchBox.appendChild(b);
  });

  function canvasPos(ev) {
    const r = control.getBoundingClientRect();
    return [
      (ev.clientX - r.left) / r.width * control.width,
      (ev.clientY - r.top) / r.height * control.height,
    ];
  }
  function dab(x, y) {
    cctx.fillStyle = paintColor;
    cctx.beginPath();
    cctx.arc(x, y, brush, 0, Math.PI * 2);
    cctx.fill();
  }
  control.addEventListener("pointerdown", (ev) => {
    painting = true;
    control.setPointerCapture(ev.pointerId);
    last = canvasPos(ev);
    dab(...last);
    schedule();
  });
  control.addEventListener("pointermove", (ev) => {
    if (!painting) return;
    const [x, y] = canvasPos(ev);
    // stamp along the segment so fast strokes stay continuous
    const [lx, ly] = last, dist = Math.hypot(x - lx, y - ly), step = brush / 2;
    for (let d = step; d < dist; d += step)
      dab(lx + (x - lx) * d / dist, ly + (y - ly) * d / dist);
    dab(x, y);
    last = [x, y];
    schedule();
  });
  control.addEventListener("pointerup", () => { painting = false; });

  // ---- controls ------------------------------------------------------------
  function bindSlider(id, valId, fmt, apply) {
    const el = $(id);
    el.addEventListener("input", () => {
      apply(parseFloat(el.value));
      $(valId).textContent = fmt(parseFloat(el.value));
      schedule();
    });
  }
  bindSlider("pxsize", "pxsizeval", (v) => v.toFixed(2) + " µm", (v) => state.pixelSize = v);
  bindSlider("pitch", "pitchval", (v) => v + " px", (v) => state.pitch = v);
  bindSlider("dotpitch", "dotpitchval", (v) => v + " px", (v) => state.dotPitch = v);
  bindSlider("gbright", "gbrightval", (v) => v.toFixed(2), (v) => tone.bright = v);
  bindSlider("gcontrast", "gcontrastval", (v) => v.toFixed(2), (v) => tone.contrast = v);
  bindSlider("ggamma", "ggammaval", (v) => v.toFixed(2), (v) => tone.gamma = v);
  $("gtreset").addEventListener("click", () => {
    tone.bright = 0; tone.contrast = 1; tone.gamma = 1;
    for (const [id, val, disp] of [["gbright", 0, "0.00"], ["gcontrast", 1, "1.00"], ["ggamma", 1, "1.00"]]) {
      $(id).value = val;
      $(id + "val").textContent = disp;
    }
    schedule();
  });
  bindSlider("brush", "brushval", (v) => v, (v) => brush = v);
  bindSlider("solidv", "solidvval", (v) => v.toFixed(2), (v) => T.solidV = v);
  bindSlider("emptyv", "emptyvval", (v) => v.toFixed(2), (v) => T.emptyV = v);
  bindSlider("satfloor", "satfloorval", (v) => v.toFixed(2), (v) => T.satFloor = v);
  // size (µm) and grid (px) are two views of the same thing: grid = µm / pixel_size.
  // Editing either drives the other; synth() writes the settled values back.
  let aspectLocked = true;
  const clampUm = (v) => Math.max(60, Math.min(3000, v));
  function setSizeUm(key, v) {
    v = clampUm(v);
    if (aspectLocked) {
      const a = state.sizeW / state.sizeH;   // capture before mutating
      if (key === "sizeW") { state.sizeW = v; state.sizeH = clampUm(v / a); }
      else { state.sizeH = v; state.sizeW = clampUm(v * a); }
    } else {
      state[key] = v;
    }
  }
  for (const [id, key] of [["sizew", "sizeW"], ["sizeh", "sizeH"]])
    $(id).addEventListener("change", (ev) => {
      setSizeUm(key, parseFloat(ev.target.value) || 480);
      schedule();
    });
  for (const [id, key] of [["gridw", "sizeW"], ["gridh", "sizeH"]])
    $(id).addEventListener("change", (ev) => {
      const px = Math.max(50, Math.min(MAX_GRID, Math.round(parseFloat(ev.target.value) || 800)));
      setSizeUm(key, px * state.pixelSize);   // µm follows the grid
      schedule();
    });
  const lockBtn = $("aspectlock");
  lockBtn.addEventListener("click", (ev) => {
    ev.preventDefault();   // inside a <label>: don't focus/toggle the inputs
    aspectLocked = !aspectLocked;
    lockBtn.textContent = aspectLocked ? "🔒" : "🔓";
    lockBtn.title = aspectLocked
      ? "aspect locked — editing one side scales the other"
      : "aspect unlocked — sides move independently";
  });

  function setMacroSize(w, h) {
    state.sizeW = Math.round(w); state.sizeH = Math.round(h);
    $("sizew").value = state.sizeW;
    $("sizeh").value = state.sizeH;
  }

  // Resize the control canvas itself to an aspect ratio (max side 800) — the
  // whole chain (canvas -> grid -> macro µm) then shares one aspect, so loaded
  // art is never letterboxed or stretched.
  function setControlAspect(aspect) {
    const w = aspect >= 1 ? 800 : Math.max(200, Math.round(800 * aspect));
    const h = aspect >= 1 ? Math.max(200, Math.round(800 / aspect)) : 800;
    control.width = w; control.height = h;
    // carry the aspect into the macro size, keeping the longer side where it was
    const base = Math.min(3000, Math.max(60, Math.max(state.sizeW, state.sizeH)));
    if (aspect >= 1) setMacroSize(base, base / aspect);
    else setMacroSize(base * aspect, base);
  }

  $("clear").addEventListener("click", () => {
    setControlAspect(1);
    cctx.fillStyle = "#fff";
    cctx.fillRect(0, 0, control.width, control.height);
    schedule();
  });

  $("file").addEventListener("change", (ev) => {
    const f = ev.target.files[0];
    if (!f) return;
    const img = new Image();
    img.onload = () => {
      // keep the image at NATIVE resolution (up to the grid cap) so a large
      // chip isn't downsampled through a small canvas on its way to the grid;
      // CSS scales the display. Adopt its aspect end-to-end, paste over white
      // (forces the no-alpha case to behave, art.md §4.1).
      const k = Math.min(1, MAX_GRID / Math.max(img.width, img.height));
      control.width = Math.max(50, Math.round(img.width * k));
      control.height = Math.max(50, Math.round(img.height * k));
      const aspect = img.width / img.height;
      const base = Math.min(3000, Math.max(60, Math.max(state.sizeW, state.sizeH)));
      if (aspect >= 1) setMacroSize(base, base / aspect);
      else setMacroSize(base * aspect, base);
      cctx.fillStyle = "#fff";
      cctx.fillRect(0, 0, control.width, control.height);
      cctx.drawImage(img, 0, 0, control.width, control.height);
      URL.revokeObjectURL(img.src);
      schedule();
    };
    img.src = URL.createObjectURL(f);
    ev.target.value = "";
  });

  function download(canvas, name) {
    canvas.toBlob((blob) => {
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = name;
      a.click();
      URL.revokeObjectURL(a.href);
    }, "image/png");
  }
  $("dl-control").addEventListener("click", () => download(control, "control.png"));
  $("dl-stencil").addEventListener("click", () => download(grid, "stencil.png"));

  // ---- legend --------------------------------------------------------------
  const LEGEND = [
    ["#111111", "black", "solid metal — auto-slotted (a tiny 2×2 slot hole per dot-pitch cell; MSLOT-safe)"],
    ["#ffffff", "white", "bare silicon (nothing drawn)"],
    ["#8a8a8a", "grey", "• clustered dots (photo halftone) — darker = denser; dot pitch sets how sparse the lights go"],
    ["hsl(0,90%,50%)", "red", "╳ crosshatch (45°+135°)"],
    ["hsl(30,92%,50%)", "orange", "▦ brick (running bond)"],
    ["hsl(55,95%,50%)", "yellow", "⟋ diagonal lines (45°)"],
    ["hsl(120,80%,42%)", "green", "# mesh grid (H+V)"],
    ["hsl(175,85%,42%)", "cyan", "⟍ diagonal lines (135°)"],
    ["hsl(225,85%,55%)", "blue", "─ horizontal lines"],
    ["hsl(270,80%,55%)", "violet", "▤ basket weave"],
    ["hsl(315,85%,52%)", "magenta", "‖ vertical lines"],
  ];
  $("legend").innerHTML = LEGEND.map(([c, name, desc]) =>
    `<li><span class="chip" style="background:${c}"></span><b>${name}</b> ${desc}</li>`
  ).join("");

  // ---- demo scene so the page never opens empty -----------------------------
  function demo() {
    const W = control.width, H = control.height;
    cctx.fillStyle = "#fff";
    cctx.fillRect(0, 0, W, H);
    const ring = [
      "hsl(0,90%,50%)", "hsl(30,92%,50%)", "hsl(55,95%,50%)", "hsl(120,80%,42%)",
      "hsl(175,85%,42%)", "hsl(225,85%,55%)", "hsl(270,80%,55%)", "hsl(315,85%,52%)",
    ];
    ring.forEach((c, i) => {
      const a = i / ring.length * Math.PI * 2 - Math.PI / 2;
      cctx.fillStyle = c;
      cctx.beginPath();
      cctx.arc(W / 2 + Math.cos(a) * 275, H / 2 + Math.sin(a) * 275, 82, 0, Math.PI * 2);
      cctx.fill();
    });
    cctx.fillStyle = "#111";
    cctx.font = "900 150px 'Segoe UI', system-ui, sans-serif";
    cctx.textAlign = "center";
    cctx.textBaseline = "middle";
    cctx.fillText("OSCE", W / 2, H / 2 - 40);
    // smooth grey ramp: white -> black sweeps empty -> growing dots -> solid
    const ramp = cctx.createLinearGradient(W / 2 - 250, 0, W / 2 + 250, 0);
    ramp.addColorStop(0, "#ffffff");
    ramp.addColorStop(1, "#000000");
    cctx.fillStyle = ramp;
    cctx.fillRect(W / 2 - 250, H / 2 + 60, 500, 90);
    cctx.textBaseline = "alphabetic";
  }

  // ?w=2500&h=2500 presets the macro size (µm) — bookmarkable per-chip setups
  const qp = new URLSearchParams(location.search);
  if (qp.has("w")) state.sizeW = Math.max(60, Math.min(3000, parseFloat(qp.get("w")) || 480));
  if (qp.has("h")) state.sizeH = Math.max(60, Math.min(3000, parseFloat(qp.get("h")) || 480));

  demo();
  synth();
  drawZoom(gridW >> 1, gridH >> 1);
  if (location.hash === "#fullview") fvOpen();
})();
