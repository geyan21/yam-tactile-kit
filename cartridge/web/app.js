/* Page wiring: the pressable taxel pad in the hero, and the 3D viewer controls. */
(function () {
  "use strict";
  const D = window.CARTRIDGE;
  if (!D) return;
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // ---------------------------------------------------------------- taxel pad
  function padDemo(canvas) {
    const L = D.layout, ctx = canvas.getContext("2d");
    const N = L.rows * L.cols, val = new Float32Array(N), tgt = new Float32Array(N);
    const half = L.sense_half_x + L.skin_side;              // skin outer half-width
    const x0 = -half - 6.2, x1 = half + 2.2, zb = L.tcp_z - 4.2, zt = L.skin_top_z + 1.2;   // left margin holds the row labels
    const rowPin = r => D.pinmap.rows.find(p => p.signal === "ROW" + String(r).padStart(2, "0")).tail_pin;
    const colPin = c => D.pinmap.cols.find(p => p.signal === "COL" + c).tail_pin;
    let W = 0, H = 0, s = 1, ox = 0, oy = 0, cursor = null, pressing = false, anim = 0;
    const X = x => ox + (x - x0) * s, Y = z => oy + (zt - z) * s;
    const cellCentre = (r, c) => [-L.act_w / 2 + L.pitch * (c + 0.5), L.act_z0 + L.pitch * (r + 0.5)];

    function layout() {
      const b = canvas.getBoundingClientRect(), dpr = Math.min(2, window.devicePixelRatio || 1);
      W = b.width; H = b.height;
      canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      s = Math.min(W / (x1 - x0), H / (zt - zb));
      ox = (W - s * (x1 - x0)) / 2; oy = (H - s * (zt - zb)) / 2;
      draw();
    }

    const stops = [[0, [239, 227, 201]], [0.22, [242, 193, 78]], [0.5, [217, 150, 30]], [0.78, [162, 86, 15]], [1, [92, 42, 7]]];
    function heat(t) {
      t = Math.max(0, Math.min(1, t));
      for (let i = 1; i < stops.length; i++) if (t <= stops[i][0]) {
        const [a, ca] = stops[i - 1], [b, cb] = stops[i], u = (t - a) / (b - a);
        return "rgb(" + ca.map((v, k) => Math.round(v + (cb[k] - v) * u)).join(",") + ")";
      }
      return "rgb(92,42,7)";
    }

    function rrect(xa, za, xb, zb2, r) {   // rounded rect in mm (za bottom, zb2 top)
      const l = X(xa), rgt = X(xb), top = Y(zb2), bot = Y(za), rr = r * s;
      ctx.beginPath();
      ctx.moveTo(l + rr, top); ctx.lineTo(rgt - rr, top); ctx.quadraticCurveTo(rgt, top, rgt, top + rr);
      ctx.lineTo(rgt, bot - rr); ctx.quadraticCurveTo(rgt, bot, rgt - rr, bot);
      ctx.lineTo(l + rr, bot); ctx.quadraticCurveTo(l, bot, l, bot - rr);
      ctx.lineTo(l, top + rr); ctx.quadraticCurveTo(l, top, l + rr, top); ctx.closePath();
    }

    function draw() {
      if (!W) return;
      ctx.clearRect(0, 0, W, H);
      // skin face (open at the top, where it meets the core)
      const g = ctx.createLinearGradient(0, Y(L.skin_top_z), 0, Y(L.skin_top_z - 6));
      g.addColorStop(0, "rgba(247,240,229,0)"); g.addColorStop(1, "rgba(247,240,229,1)");
      rrect(-half, L.tcp_z, half, L.skin_top_z + 2, 4.5); ctx.fillStyle = g; ctx.fill();
      ctx.strokeStyle = "#c9b8a2"; ctx.lineWidth = 1; ctx.stroke();
      // pad laminate
      rrect(-L.pad_half_x, L.pad_z[0], L.pad_half_x, L.pad_z[1], 1.5);
      ctx.fillStyle = "#f2dca6"; ctx.fill(); ctx.strokeStyle = "#c98f1e"; ctx.stroke();
      // electrodes: rows on one layer, columns on the other
      const e = L.electrode, aw = L.act_w, al = L.rows * L.pitch;
      ctx.fillStyle = "rgba(176,99,31,.20)";
      for (let r = 0; r < L.rows; r++) { const z = L.act_z0 + L.pitch * (r + 0.5); ctx.fillRect(X(-aw / 2), Y(z + e / 2), aw * s, e * s); }
      for (let c = 0; c < L.cols; c++) { const x = -aw / 2 + L.pitch * (c + 0.5); ctx.fillRect(X(x - e / 2), Y(L.act_z0 + al), e * s, al * s); }
      // taxels
      for (let r = 0; r < L.rows; r++) for (let c = 0; c < L.cols; c++) {
        const [x, z] = cellCentre(r, c), v = val[r * L.cols + c];
        ctx.fillStyle = v > 0.01 ? heat(v) : "rgba(176,99,31,.42)";
        ctx.fillRect(X(x - e / 2), Y(z + e / 2), e * s, e * s);
      }
      if (cursor) {
        const [x, z] = cellCentre(cursor[0], cursor[1]);
        ctx.strokeStyle = "#1b2b34"; ctx.lineWidth = 2;
        ctx.strokeRect(X(x - e / 2) - 2, Y(z + e / 2) - 2, e * s + 4, e * s + 4);
      }
      // labels
      ctx.fillStyle = "#4b5b64"; ctx.font = "12px Archivo, system-ui, sans-serif"; ctx.textBaseline = "middle";
      ctx.textAlign = "right";
      ctx.fillText("row 0", X(-L.pad_half_x) - 4, Y(cellCentre(0, 0)[1]));
      ctx.fillText("row " + (L.rows - 1), X(-L.pad_half_x) - 4, Y(cellCentre(L.rows - 1, 0)[1]));
      ctx.textAlign = "center"; ctx.textBaseline = "top";
      ctx.fillText("fingertip", X(0), Y(L.tcp_z) + 6);
      ctx.textBaseline = "bottom";
      ctx.fillText("col 0", X(cellCentre(0, 0)[0]), Y(L.pad_z[1]) - 4);
      ctx.fillText("col " + (L.cols - 1), X(cellCentre(0, L.cols - 1)[0]), Y(L.pad_z[1]) - 4);
    }

    const out = id => document.getElementById(id);
    function report() {
      let total = 0;
      for (let i = 0; i < N; i++) total += val[i];
      out("r-total").textContent = total < 0.05 ? "0" : total.toFixed(1) + " (arbitrary units)";
      if (!cursor) return;
      const [r, c] = cursor, rr = String(r).padStart(2, "0"), p = rowPin(r);
      out("r-taxel").textContent = "Row " + r + ", column " + c;
      out("r-index").textContent = String(r * L.cols + c) + " (row × " + L.cols + " + column)";
      out("r-row").textContent = "ROW" + rr + " on tail pin " + p + ", readout line " + (p - 1);
      out("r-col").textContent = "COL" + c + " on tail pin " + colPin(c);
      out("r-height").textContent = (cellCentre(r, c)[1] - L.tcp_z).toFixed(1) + " mm";
    }

    function press(x, z) {
      const sig = 2.4;
      for (let r = 0; r < L.rows; r++) for (let c = 0; c < L.cols; c++) {
        const [cx, cz] = cellCentre(r, c), d2 = (cx - x) ** 2 + (cz - z) ** 2;
        tgt[r * L.cols + c] = Math.exp(-d2 / (2 * sig * sig));
      }
    }
    function release() { tgt.fill(0); }
    function step() {
      let moving = false;
      for (let i = 0; i < N; i++) {
        const d = tgt[i] - val[i];
        if (Math.abs(d) > 0.002) { val[i] += d * (d > 0 ? 0.35 : 0.12); moving = true; } else val[i] = tgt[i];
      }
      draw(); report();
      anim = moving ? requestAnimationFrame(step) : 0;
    }
    function kick() {
      if (reduce) { val.set(tgt); draw(); report(); return; }
      if (!anim) anim = requestAnimationFrame(step);
    }
    function locate(e) {
      const b = canvas.getBoundingClientRect(), px = e.clientX - b.left, py = e.clientY - b.top;
      const x = x0 + (px - ox) / s, z = zt - (py - oy) / s;
      const c = Math.floor((x + L.act_w / 2) / L.pitch), r = Math.floor((z - L.act_z0) / L.pitch);
      cursor = r >= 0 && r < L.rows && c >= 0 && c < L.cols ? [r, c] : cursor;
      return [x, z];
    }
    canvas.addEventListener("pointerdown", e => { canvas.setPointerCapture(e.pointerId); pressing = true; const [x, z] = locate(e); press(x, z); kick(); });
    canvas.addEventListener("pointermove", e => { const [x, z] = locate(e); if (pressing) { press(x, z); kick(); } else { draw(); report(); } });
    const up = () => { if (!pressing) return; pressing = false; release(); kick(); };
    canvas.addEventListener("pointerup", up);
    canvas.addEventListener("pointercancel", up);
    canvas.addEventListener("pointerleave", () => { if (!pressing) { draw(); } });
    canvas.addEventListener("keydown", e => {
      if (!cursor) cursor = [Math.floor(L.rows / 2), Math.floor(L.cols / 2)];
      const [r, c] = cursor, k = e.key;
      if (k === "ArrowUp") cursor = [Math.min(L.rows - 1, r + 1), c];
      else if (k === "ArrowDown") cursor = [Math.max(0, r - 1), c];
      else if (k === "ArrowLeft") cursor = [r, Math.max(0, c - 1)];
      else if (k === "ArrowRight") cursor = [r, Math.min(L.cols - 1, c + 1)];
      else if (k === " " || k === "Enter") { e.preventDefault(); const [x, z] = cellCentre(...cursor); press(x, z); kick(); return; }
      else return;
      e.preventDefault();
      if (pressing || tgt.some(v => v > 0)) { const [x, z] = cellCentre(...cursor); press(x, z); kick(); } else { draw(); report(); }
    });
    canvas.addEventListener("keyup", e => { if (e.key === " " || e.key === "Enter") { release(); kick(); } });
    canvas.addEventListener("focus", () => { if (!cursor) { cursor = [Math.floor(L.rows / 2), Math.floor(L.cols / 2)]; draw(); report(); } });
    new ResizeObserver(layout).observe(canvas);
    layout();
  }

  // ---------------------------------------------------------------- 3D viewer
  function viewer() {
    const canvas = document.getElementById("view");
    let v = null;
    try { v = new window.CartridgeViewer(canvas, D); } catch (err) { v = null; }
    if (!v || !v.ok) {
      const img = document.createElement("img");
      img.src = "../out/renders/hero.png"; img.alt = "Rendered view of the YAM gripper with two tactile cartridges";
      canvas.replaceWith(img);
      const note = document.createElement("p");
      note.className = "view-fallback";
      note.textContent = "This browser has WebGL turned off, so a rendered picture is shown instead of the 3D view.";
      img.after(note);
      return;
    }
    const $ = id => document.getElementById(id);
    $("explode").addEventListener("input", e => v.setExplode(e.target.value / 100));
    $("t-skin").addEventListener("change", e => v.setHidden("skin", !e.target.checked));
    $("t-xray").addEventListener("change", e => v.setXray(e.target.checked));
    $("t-socket").addEventListener("change", e => v.setHidden("socket", !e.target.checked));
    $("t-electronics").addEventListener("change", e => v.setHidden("electronics", !e.target.checked));
    $("zoom-in").addEventListener("click", () => v.zoom(0.85));
    $("zoom-out").addEventListener("click", () => v.zoom(1 / 0.85));
    $("reset-view").addEventListener("click", () => v.reset());
    const seen = new Set(), legend = $("legend");
    for (const p of v.parts) {
      if (seen.has(p.label)) continue;
      seen.add(p.label);
      const li = document.createElement("li"), sw = document.createElement("i");
      sw.style.background = p.color; li.append(sw, document.createTextNode(p.label));
      legend.append(li);
    }
  }

  function start() {
    padDemo(document.getElementById("pad"));
    viewer();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else start();
})();
