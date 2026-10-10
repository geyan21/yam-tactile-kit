/* Minimal WebGL viewer for the cartridge meshes in data.js. No dependencies.
   Flat shading + feature edges (CAD look), translucent skin, explode, orbit, pinch/ctrl-wheel zoom. */
(function () {
  "use strict";
  const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
  const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
  const norm = a => { const l = Math.hypot(a[0], a[1], a[2]) || 1; return [a[0] / l, a[1] / l, a[2] / l]; };
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const hex = h => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16) / 255);

  function perspective(fovy, aspect, near, far) {
    const f = 1 / Math.tan(fovy / 2), nf = 1 / (near - far);
    return new Float32Array([f / aspect, 0, 0, 0, 0, f, 0, 0, 0, 0, (far + near) * nf, -1, 0, 0, 2 * far * near * nf, 0]);
  }
  function lookAt(eye, target, up) {
    const z = norm(sub(eye, target)), x = norm(cross(up, z)), y = cross(z, x);
    return new Float32Array([x[0], y[0], z[0], 0, x[1], y[1], z[1], 0, x[2], y[2], z[2], 0, -dot(x, eye), -dot(y, eye), -dot(z, eye), 1]);
  }
  function mul(a, b) {
    const o = new Float32Array(16);
    for (let c = 0; c < 4; c++) for (let r = 0; r < 4; r++) {
      let s = 0;
      for (let k = 0; k < 4; k++) s += a[k * 4 + r] * b[c * 4 + k];
      o[c * 4 + r] = s;
    }
    return o;
  }

  const VS = "attribute vec3 aPos;attribute vec3 aNor;uniform mat4 uMVP;uniform mat3 uNM;uniform vec3 uOff;varying vec3 vN;" +
    "void main(){gl_Position=uMVP*vec4(aPos+uOff,1.0);vN=uNM*aNor;}";
  const FS = "precision mediump float;uniform vec3 uCol;uniform float uA;uniform float uLit;varying vec3 vN;" +
    "void main(){vec3 n=normalize(vN);if(!gl_FrontFacing)n=-n;" +
    "float key=max(dot(n,normalize(vec3(0.35,0.55,0.75))),0.0);float fill=max(dot(n,normalize(vec3(-0.6,-0.25,0.45))),0.0);" +
    "vec3 lit=uCol*(0.34+0.60*key+0.20*fill);gl_FragColor=vec4(mix(uCol,lit,uLit),uA);}";

  function shader(gl, type, src) {
    const s = gl.createShader(type);
    gl.shaderSource(s, src); gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s));
    return s;
  }

  class CartridgeViewer {
    constructor(canvas, data) {
      this.canvas = canvas;
      const gl = canvas.getContext("webgl", { antialias: true, alpha: false, preserveDrawingBuffer: false }) ||
        canvas.getContext("experimental-webgl");
      if (!gl) { this.ok = false; return; }
      this.gl = gl; this.ok = true;
      const p = gl.createProgram();
      gl.attachShader(p, shader(gl, gl.VERTEX_SHADER, VS));
      gl.attachShader(p, shader(gl, gl.FRAGMENT_SHADER, FS));
      gl.linkProgram(p);
      if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p));
      this.prog = p;
      this.loc = {};
      for (const n of ["aPos", "aNor"]) this.loc[n] = gl.getAttribLocation(p, n);
      for (const n of ["uMVP", "uNM", "uOff", "uCol", "uA", "uLit"]) this.loc[n] = gl.getUniformLocation(p, n);

      this.parts = [];
      for (const [name, m] of Object.entries(data.meshes)) this.parts.push(this.build(name, m));
      this.parts.push(this.build("taxels", this.taxelMesh(data.layout)));
      this.explode = 0; this.xray = true;
      this.hidden = new Set();
      this.reset(false);
      this.bind();
      new ResizeObserver(() => this.request()).observe(canvas);
      this.request();
    }

    taxelMesh(L) {
      // 1.4 mm squares at every row/column crossing, just in front of the pad face
      const v = [], f = [], y = Math.round((L.y_face - 0.03) * 100), h = L.electrode / 2;
      for (let r = 0; r < L.rows; r++) for (let c = 0; c < L.cols; c++) {
        const x = -L.act_w / 2 + L.pitch * (c + 0.5), z = L.act_z0 + L.pitch * (r + 0.5), b = v.length / 3;
        for (const [dx, dz] of [[-h, -h], [h, -h], [h, h], [-h, h]]) v.push(Math.round((x + dx) * 100), y, Math.round((z + dz) * 100));
        f.push(b, b + 1, b + 2, b, b + 2, b + 3);
      }
      return { label: "Taxels", color: "#b0631f", explode: [0, -12, 0], group: "pad", v, f, e: [] };
    }

    build(name, m) {
      const gl = this.gl, V = m.v, F = m.f, E = m.e, n = F.length / 3;
      const pos = new Float32Array(n * 9), nor = new Float32Array(n * 9);
      const lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];
      for (let t = 0; t < n; t++) {
        const pts = [0, 1, 2].map(k => { const i = F[3 * t + k] * 3; return [V[i] / 100, V[i + 1] / 100, V[i + 2] / 100]; });
        const nn = norm(cross(sub(pts[1], pts[0]), sub(pts[2], pts[0])));
        for (let k = 0; k < 3; k++) {
          pos.set(pts[k], 9 * t + 3 * k); nor.set(nn, 9 * t + 3 * k);
          for (let a = 0; a < 3; a++) { lo[a] = Math.min(lo[a], pts[k][a]); hi[a] = Math.max(hi[a], pts[k][a]); }
        }
      }
      const lines = new Float32Array(E.length * 3);
      for (let i = 0; i < E.length; i++) { const j = E[i] * 3; lines[3 * i] = V[j] / 100; lines[3 * i + 1] = V[j + 1] / 100; lines[3 * i + 2] = V[j + 2] / 100; }
      const buf = data => { const b = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, b); gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW); return b; };
      const col = hex(m.color);
      return {
        name, label: m.label, color: m.color, group: m.group, explode: m.explode, lo, hi,
        pos: buf(pos), nor: buf(nor), count: n * 3, lines: buf(lines), lineCount: E.length,
        col, edge: col.map(c => c * 0.42 + 0.06)
      };
    }

    visible(p) { return !this.hidden.has(p.group) && !(p.name === "taxels" && this.hidden.has("pad")); }
    offset(p) { return p.explode.map(v => v * this.explode); }

    bounds() {
      const lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];
      for (const p of this.parts) {
        if (!this.visible(p)) continue;
        const o = this.offset(p);
        for (let a = 0; a < 3; a++) { lo[a] = Math.min(lo[a], p.lo[a] + o[a]); hi[a] = Math.max(hi[a], p.hi[a] + o[a]); }
      }
      return { center: lo.map((v, a) => (v + hi[a]) / 2), radius: Math.max(1, Math.hypot(hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]) / 2) };
    }

    reset(draw = true) {
      this.yaw = -2.05; this.pitch = 0.3; this.zoomF = 2.6;
      if (draw) this.request();
    }
    zoom(f) { this.zoomF = clamp(this.zoomF * f, 0.7, 7); this.request(); }
    setExplode(v) { this.explode = v; this.request(); }
    setHidden(group, hide) { hide ? this.hidden.add(group) : this.hidden.delete(group); this.request(); }
    setXray(on) { this.xray = on; this.request(); }

    bind() {
      const c = this.canvas, ptrs = new Map();
      let pinch = null;
      c.addEventListener("pointerdown", e => { c.setPointerCapture(e.pointerId); ptrs.set(e.pointerId, [e.clientX, e.clientY]); c.classList.add("dragging"); });
      c.addEventListener("pointermove", e => {
        if (!ptrs.has(e.pointerId)) return;
        const prev = ptrs.get(e.pointerId);
        ptrs.set(e.pointerId, [e.clientX, e.clientY]);
        if (ptrs.size === 1) {
          this.yaw -= (e.clientX - prev[0]) * 0.008;
          this.pitch = clamp(this.pitch + (e.clientY - prev[1]) * 0.008, -1.45, 1.45);
          this.request();
        } else if (ptrs.size === 2) {
          const [a, b] = [...ptrs.values()], d = Math.hypot(a[0] - b[0], a[1] - b[1]);
          if (pinch) this.zoom(pinch / d);
          pinch = d;
        }
      });
      const end = e => { ptrs.delete(e.pointerId); if (ptrs.size < 2) pinch = null; if (!ptrs.size) c.classList.remove("dragging"); };
      c.addEventListener("pointerup", end);
      c.addEventListener("pointercancel", end);
      // Plain wheel scrolls the page; ctrl+wheel (and trackpad pinch, which sends ctrl) zooms.
      c.addEventListener("wheel", e => { if (!e.ctrlKey) return; e.preventDefault(); this.zoom(Math.exp(e.deltaY * 0.01)); }, { passive: false });
      c.addEventListener("dblclick", () => this.reset());
      c.addEventListener("keydown", e => {
        const k = e.key, step = 0.1;
        if (k === "ArrowLeft") this.yaw += step;
        else if (k === "ArrowRight") this.yaw -= step;
        else if (k === "ArrowUp") this.pitch = clamp(this.pitch - step, -1.45, 1.45);
        else if (k === "ArrowDown") this.pitch = clamp(this.pitch + step, -1.45, 1.45);
        else if (k === "+" || k === "=") return void (e.preventDefault(), this.zoom(0.85));
        else if (k === "-" || k === "_") return void (e.preventDefault(), this.zoom(1 / 0.85));
        else if (k === "Home" || k === "0") return void (e.preventDefault(), this.reset());
        else return;
        e.preventDefault(); this.request();
      });
    }

    request() {
      if (this.pending) return;
      this.pending = true;
      requestAnimationFrame(() => { this.pending = false; this.draw(); });
    }

    faces(p, alpha) {
      const gl = this.gl, L = this.loc;
      gl.uniform3fv(L.uOff, this.offset(p));
      gl.uniform1f(L.uA, alpha);
      gl.uniform1f(L.uLit, 1);
      gl.uniform3fv(L.uCol, p.col);
      gl.bindBuffer(gl.ARRAY_BUFFER, p.pos); gl.vertexAttribPointer(L.aPos, 3, gl.FLOAT, false, 0, 0);
      gl.enableVertexAttribArray(L.aNor);
      gl.bindBuffer(gl.ARRAY_BUFFER, p.nor); gl.vertexAttribPointer(L.aNor, 3, gl.FLOAT, false, 0, 0);
      gl.drawArrays(gl.TRIANGLES, 0, p.count);
    }

    edges(p, alpha) {
      if (!p.lineCount) return;
      const gl = this.gl, L = this.loc;
      gl.uniform3fv(L.uOff, this.offset(p));
      gl.disableVertexAttribArray(L.aNor); gl.vertexAttrib3f(L.aNor, 0, 0, 1);
      gl.uniform1f(L.uLit, 0);
      gl.uniform3fv(L.uCol, p.edge);
      gl.uniform1f(L.uA, alpha);
      gl.bindBuffer(gl.ARRAY_BUFFER, p.lines); gl.vertexAttribPointer(L.aPos, 3, gl.FLOAT, false, 0, 0);
      gl.drawArrays(gl.LINES, 0, p.lineCount);
    }

    draw() {
      const gl = this.gl, c = this.canvas, dpr = Math.min(2, window.devicePixelRatio || 1);
      const w = Math.max(1, Math.round(c.clientWidth * dpr)), h = Math.max(1, Math.round(c.clientHeight * dpr));
      if (c.width !== w || c.height !== h) { c.width = w; c.height = h; }
      gl.viewport(0, 0, w, h);
      gl.clearColor(0.910, 0.929, 0.941, 1);
      gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
      const { center, radius } = this.bounds();
      // fit the assembly's bounding sphere to the narrower side of the canvas, times the zoom factor
      const fov = 0.52, fit = radius / Math.sin(fov / 2) / Math.min(1, w / h);
      const dist = fit * this.zoomF / 2.6;
      const dir = [Math.cos(this.pitch) * Math.cos(this.yaw), Math.cos(this.pitch) * Math.sin(this.yaw), Math.sin(this.pitch)];
      const eye = center.map((v, i) => v + dir[i] * dist);
      const view = lookAt(eye, center, [0, 0, 1]);
      const proj = perspective(fov, w / h, dist * 0.05, dist * 12);
      gl.useProgram(this.prog);
      gl.uniformMatrix4fv(this.loc.uMVP, false, mul(proj, view));
      gl.uniformMatrix3fv(this.loc.uNM, false, new Float32Array([view[0], view[1], view[2], view[4], view[5], view[6], view[8], view[9], view[10]]));
      gl.enableVertexAttribArray(this.loc.aPos);
      gl.enable(gl.DEPTH_TEST); gl.depthMask(true); gl.disable(gl.BLEND);
      const shown = this.parts.filter(p => this.visible(p));
      const glass = shown.filter(p => p.name === "skin" && this.xray);
      const solid = shown.filter(p => !glass.includes(p));
      gl.enable(gl.POLYGON_OFFSET_FILL); gl.polygonOffset(1, 1);
      for (const p of solid) this.faces(p, 1);
      gl.disable(gl.POLYGON_OFFSET_FILL);
      for (const p of solid) this.edges(p, 1);
      if (glass.length) {
        gl.enable(gl.BLEND); gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA); gl.depthMask(false);
        for (const p of glass) { this.faces(p, 0.28); this.edges(p, 0.5); }
        gl.depthMask(true); gl.disable(gl.BLEND);
      }
      c.dataset.rendered = String((+c.dataset.rendered || 0) + 1);
    }
  }
  window.CartridgeViewer = CartridgeViewer;
})();
