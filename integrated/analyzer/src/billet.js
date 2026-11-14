/* Singly curved glulam billet fit (constant radius / straight): minimum-volume billet around a part.
   Same method: bending plane from PCA candidates refined by Nelder-Mead, minimum-area annular sector
   in that plane, depth rounded up to whole lams, CNC section by rotating calipers. Units: mm. */
(function (global) {
  const TWO_PI = 2 * Math.PI, STRAIGHT = 1e-6;
  const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
  const norm = (a) => Math.hypot(a[0], a[1], a[2]);
  const unit = (a) => { const l = norm(a); return [a[0] / l, a[1] / l, a[2] / l]; };

  function nelderMead(f, x0, step, maxEval = 400, xTol = 1e-7, fTol = 1e-9) {
    const dim = x0.length;
    let S = [x0.slice()]; for (let i = 0; i < dim; i++) { const x = x0.slice(); x[i] += step[i]; S.push(x); }
    let V = S.map(f), ev = dim + 1;
    const add = (a, b, k) => a.map((v, i) => v + k * (b[i] - a[i]));
    while (ev < maxEval) {
      const ord = V.map((v, i) => i).sort((a, b) => V[a] - V[b]); S = ord.map(i => S[i]); V = ord.map(i => V[i]);
      let spread = 0; for (let i = 1; i <= dim; i++) for (let j = 0; j < dim; j++) spread = Math.max(spread, Math.abs(S[i][j] - S[0][j]));
      if (isFinite(V[dim]) && spread <= xTol && Math.abs(V[dim] - V[0]) <= fTol * (Math.abs(V[0]) + 1e-30)) break;
      const c = new Array(dim).fill(0); for (let i = 0; i < dim; i++) for (let j = 0; j < dim; j++) c[j] += S[i][j] / dim;
      const xr = add(c, S[dim], -1), fr = f(xr); ev++;
      if (fr < V[0]) { const xe = add(c, S[dim], -2), fe = f(xe); ev++; if (fe < fr) { S[dim] = xe; V[dim] = fe; } else { S[dim] = xr; V[dim] = fr; } }
      else if (fr < V[dim - 1]) { S[dim] = xr; V[dim] = fr; }
      else {
        const xc = fr < V[dim] ? add(c, xr, 0.5) : add(c, S[dim], 0.5), fc = f(xc); ev++;
        if (fc < Math.min(fr, V[dim])) { S[dim] = xc; V[dim] = fc; }
        else { for (let i = 1; i <= dim; i++) { S[i] = add(S[0], S[i], 0.5); V[i] = f(S[i]); } ev += dim; }
      }
    }
    let b = 0; for (let i = 1; i < V.length; i++) if (V[i] < V[b]) b = i;
    return [S[b], V[b]];
  }

  /* symmetric 3x3 eigen (Jacobi). Returns axes sorted by eigenvalue, largest first. */
  function eigSym3(A) {
    const a = A.map(r => r.slice()), Vv = [[1, 0, 0], [0, 1, 0], [0, 0, 1]];
    for (let sweep = 0; sweep < 50; sweep++) {
      const off = a[0][1] ** 2 + a[0][2] ** 2 + a[1][2] ** 2; if (off < 1e-22 * (a[0][0] ** 2 + a[1][1] ** 2 + a[2][2] ** 2 + 1e-300)) break;
      for (const [p, q] of [[0, 1], [0, 2], [1, 2]]) {
        if (Math.abs(a[p][q]) < 1e-300) continue;
        const th = (a[q][q] - a[p][p]) / (2 * a[p][q]), t = Math.sign(th || 1) / (Math.abs(th) + Math.sqrt(th * th + 1));
        const c = 1 / Math.sqrt(t * t + 1), s = t * c;
        for (let k = 0; k < 3; k++) { const akp = a[k][p], akq = a[k][q]; a[k][p] = c * akp - s * akq; a[k][q] = s * akp + c * akq; }
        for (let k = 0; k < 3; k++) { const apk = a[p][k], aqk = a[q][k]; a[p][k] = c * apk - s * aqk; a[q][k] = s * apk + c * aqk; }
        for (let k = 0; k < 3; k++) { const vkp = Vv[k][p], vkq = Vv[k][q]; Vv[k][p] = c * vkp - s * vkq; Vv[k][q] = s * vkp + c * vkq; }
      }
    }
    const idx = [0, 1, 2].sort((i, j) => a[j][j] - a[i][i]);
    return { values: idx.map(i => a[i][i]), axes: idx.map(i => [Vv[0][i], Vv[1][i], Vv[2][i]]) };
  }
  function pcaAxes(P) {
    const n = P.length, c = [0, 0, 0]; for (const p of P) { c[0] += p[0] / n; c[1] += p[1] / n; c[2] += p[2] / n; }
    const C = [[0, 0, 0], [0, 0, 0], [0, 0, 0]];
    for (const p of P) { const d = [p[0] - c[0], p[1] - c[1], p[2] - c[2]]; for (let i = 0; i < 3; i++) for (let j = 0; j < 3; j++) C[i][j] += d[i] * d[j] / (n - 1); }
    return { c, axes: eigSym3(C).axes };
  }
  function planeFrame(nIn, hint) {
    const n = unit(nIn); let u = [hint[0] - dot(hint, n) * n[0], hint[1] - dot(hint, n) * n[1], hint[2] - dot(hint, n) * n[2]];
    if (norm(u) < 1e-9) { u = cross(n, [1, 0, 0]); if (norm(u) < 1e-9) u = cross(n, [0, 1, 0]); }
    u = unit(u); return { u, v: cross(n, u), n };
  }
  function project(P, o, F) {
    const P2 = [], W = [];
    for (const p of P) { const r = [p[0] - o[0], p[1] - o[1], p[2] - o[2]]; P2.push([dot(r, F.u), dot(r, F.v)]); W.push(dot(r, F.n)); }
    return { P2, W };
  }
  function rng(seed) { let s = seed >>> 0; return () => { s = (s + 0x6D2B79F5) >>> 0; let t = s; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }
  function sphereDirs(count) { const D = []; for (let i = 0; i < count; i++) { const z = 1 - 2 * (i + 0.5) / count, r = Math.sqrt(1 - z * z), ph = Math.PI * (3 - Math.sqrt(5)) * (i + 0.5); D.push([r * Math.cos(ph), r * Math.sin(ph), z]); } return D; }
  const DIRS = sphereDirs(100);
  function subset(P, maxCount, seed = 7) {
    if (P.length <= maxCount) return P;
    const R = rng(seed), picked = new Set(); while (picked.size < maxCount) picked.add(Math.floor(R() * P.length));
    const dim = P[0].length;
    for (const d of DIRS) { let mi = 0, ma = 0, vmi = Infinity, vma = -Infinity;
      for (let i = 0; i < P.length; i++) { let v = 0; for (let k = 0; k < dim; k++) v += P[i][k] * d[k]; if (v < vmi) { vmi = v; mi = i; } if (v > vma) { vma = v; ma = i; } }
      picked.add(mi); picked.add(ma); }
    return [...picked].sort((a, b) => a - b).map(i => P[i]);
  }
  const ptp = (arr) => { let a = Infinity, b = -Infinity; for (const v of arr) { if (v < a) a = v; if (v > b) b = v; } return b - a; };

  function angularSpan(angles) {
    const o = angles.map(a => ((a % TWO_PI) + TWO_PI) % TWO_PI).sort((a, b) => a - b);
    let gi = -1, gmax = -1; for (let i = 0; i < o.length - 1; i++) { const g = o[i + 1] - o[i]; if (g > gmax) { gmax = g; gi = i; } }
    const wrap = o[0] + TWO_PI - o[o.length - 1];
    if (gi < 0 || wrap >= gmax) return [o[0], o[o.length - 1] - o[0]];
    return [o[gi + 1], TWO_PI - gmax];
  }
  function sectorFit(P2, cx, cy, allow) {
    let rmin = Infinity, rmax = -Infinity; const ang = new Array(P2.length);
    for (let i = 0; i < P2.length; i++) { const dx = P2[i][0] - cx, dy = P2[i][1] - cy, r = Math.hypot(dx, dy); if (r < rmin) rmin = r; if (r > rmax) rmax = r; ang[i] = Math.atan2(dy, dx); }
    const rIn = rmin - allow, rOut = rmax + allow; if (rIn <= 0) return null;
    let start, span;
    { const mx = P2.reduce((q, p) => q + p[0], 0) / P2.length - cx, my = P2.reduce((q, p) => q + p[1], 0) / P2.length - cy, ref = Math.atan2(my, mx);
      let lo = Infinity, hi = -Infinity;
      for (let i = 0; i < ang.length; i++) { let r = ang[i] - ref; r -= TWO_PI * Math.round(r / TWO_PI); if (r < lo) lo = r; if (r > hi) hi = r; }
      if (hi - lo < Math.PI * 0.9) { start = ref + lo; span = hi - lo; } else [start, span] = angularSpan(ang); }
    const pad = allow / (0.5 * (rIn + rOut)), ps = span + 2 * pad;
    if (ps >= TWO_PI) return null;
    return { rIn: rmin, rOut: rmax, start, span, area: 0.5 * ps * (rOut - rIn) * (rOut + rIn) };
  }
  function stripArea(P2, nx, ny, allow) {
    const l = Math.hypot(nx, ny); nx /= l; ny /= l; const tx = -ny, ty = nx;
    return (ptp(P2.map(p => p[0] * nx + p[1] * ny)) + 2 * allow) * (ptp(P2.map(p => p[0] * tx + p[1] * ty)) + 2 * allow);
  }
  function solve3(A, b) { const M = A.map((r, i) => [...r, b[i]]);
    for (let c = 0; c < 3; c++) { let p = c; for (let r = c + 1; r < 3; r++) if (Math.abs(M[r][c]) > Math.abs(M[p][c])) p = r; [M[c], M[p]] = [M[p], M[c]];
      for (let r = 0; r < 3; r++) if (r !== c) { const f = M[r][c] / M[c][c]; for (let k = c; k < 4; k++) M[r][k] -= f * M[c][k]; } }
    return [M[0][3] / M[0][0], M[1][3] / M[1][1], M[2][3] / M[2][2]]; }
  function kasaCentre(P2) {
    const A = [[0, 0, 0], [0, 0, 0], [0, 0, 0]], b = [0, 0, 0];
    for (const p of P2) { const row = [2 * p[0], 2 * p[1], 1], rhs = p[0] * p[0] + p[1] * p[1];
      for (let i = 0; i < 3; i++) { b[i] += row[i] * rhs; for (let j = 0; j < 3; j++) A[i][j] += row[i] * row[j]; } }
    const s = solve3(A, b); return [s[0], s[1]];
  }
  function cov2minor(P2, c) { let a = 0, b = 0, d = 0; for (const p of P2) { const x = p[0] - c[0], y = p[1] - c[1]; a += x * x; b += x * y; d += y * y; }
    const tr = a + d, det = a * d - b * b, l = tr / 2 - Math.sqrt(Math.max(tr * tr / 4 - det, 0));
    let vx = b, vy = l - a; if (Math.hypot(vx, vy) < 1e-12) { vx = l - d; vy = b; } if (Math.hypot(vx, vy) < 1e-12) { vx = 1; vy = 0; }
    const n = Math.hypot(vx, vy); return [vx / n, vy / n]; }

  /* spines */
  function arcSpine(cx, cy, R, theta0, span) {
    const thetaMid = theta0 + 0.5 * span;
    return { kind: 'arc', cx, cy, R, theta0, span,
      point: (s, d) => { const th = theta0 + s / R, r = R - d; return [cx + r * Math.cos(th), cy + r * Math.sin(th)]; },
      project: (p) => { const dx = p[0] - cx, dy = p[1] - cy, th = Math.atan2(dy, dx);
        const w = ((th - thetaMid + Math.PI) % TWO_PI + TWO_PI) % TWO_PI - Math.PI; return [(w + thetaMid - theta0) * R, R - Math.hypot(dx, dy)]; },
      kappa: 1 / R };
  }
  function lineSpine(o, t) { const tl = Math.hypot(t[0], t[1]), T = [t[0] / tl, t[1] / tl], N = [-T[1], T[0]];
    return { kind: 'line', R: Infinity, point: (s, d) => [o[0] + s * T[0] + d * N[0], o[1] + s * T[1] + d * N[1]],
      project: (p) => { const rx = p[0] - o[0], ry = p[1] - o[1]; return [rx * T[0] + ry * T[1], rx * N[0] + ry * N[1]]; }, kappa: 0 }; }

  function fitArc2d(P2, allow, quick, warm) {
    const n = P2.length, cen = [0, 0]; for (const p of P2) { cen[0] += p[0] / n; cen[1] += p[1] / n; }
    const lc = Math.max(ptp(P2.map(p => p[0])), ptp(P2.map(p => p[1])));
    const dir = (psi) => [Math.cos(psi), Math.sin(psi)];
    const area = (x) => { const [psi, k] = x; const d = dir(psi);
      if (Math.abs(k) < STRAIGHT) return stripArea(P2, d[0], d[1], allow);
      const r = sectorFit(P2, cen[0] + d[0] * lc / k, cen[1] + d[1] * lc / k, allow); return r ? r.area : Infinity; };
    const starts = []; if (warm) starts.push(warm);
    const kc = kasaCentre(P2), kx = kc[0] - cen[0], ky = kc[1] - cen[1], kr = Math.hypot(kx, ky);
    if (isFinite(kr) && kr > 1e-9 * lc) starts.push([Math.atan2(ky, kx), lc / kr]);
    const mn = cov2minor(P2, cen), psiMinor = Math.atan2(mn[1], mn[0]);
    starts.push([psiMinor, 0]); if (!quick) starts.push([psiMinor, 0.5], [psiMinor + Math.PI, 0.5]);
    let best = null, bestA = Infinity;
    for (const st of starts) { const [x, v] = nelderMead(area, st, [0.25, 0.25 * Math.max(1, Math.abs(st[1]))], quick ? 200 : 500); if (v < bestA) { bestA = v; best = x; } }
    const [psi, k] = best;
    if (Math.abs(k) < STRAIGHT) { const d = dir(psi); return { spine: lineSpine(cen, [-d[1], d[0]]), area: bestA, x: best }; }
    const d = dir(psi), cx = cen[0] + d[0] * lc / k, cy = cen[1] + d[1] * lc / k, sec = sectorFit(P2, cx, cy, allow);
    return { spine: arcSpine(cx, cy, 0.5 * (sec.rIn + sec.rOut), sec.start, sec.span), area: bestA, x: best };
  }

  function fitBendingPlane(P, allow, opts = {}) {
    const maxCount = opts.maxCount || 400, outerEval = opts.outerEval == null ? 60 : opts.outerEval;
    const SAMPLE = subset(P, maxCount), { c: origin, axes } = pcaAxes(P), lengthAxis = axes[0], RESCORE = subset(P, 4 * maxCount);
    const vol = (n, quick, warm) => { const F = planeFrame(n, lengthAxis), { P2, W } = project(quick ? SAMPLE : RESCORE, origin, F);
      const r = fitArc2d(P2, allow, quick, warm); return [(ptp(W) + 2 * allow) * r.area, r.x]; };
    const cands = [];
    for (const n0 of [axes[2], axes[1]]) {
      if (outerEval <= 0) { cands.push(n0, n0); continue; }
      const F0 = planeFrame(n0, lengthAxis), ea = F0.u, eb = F0.v; let warm = null;
      const obj = (x) => { const r = vol(unit([n0[0] + x[0] * ea[0] + x[1] * eb[0], n0[1] + x[0] * ea[1] + x[1] * eb[1], n0[2] + x[0] * ea[2] + x[1] * eb[2]]), true, warm); warm = r[1]; return r[0]; };
      const [x] = nelderMead(obj, [0, 0], [0.12, 0.12], outerEval);
      cands.push(n0, unit([n0[0] + x[0] * ea[0] + x[1] * eb[0], n0[1] + x[0] * ea[1] + x[1] * eb[1], n0[2] + x[0] * ea[2] + x[1] * eb[2]]));
    }
    let best = [Infinity, null];
    for (let i = 0; i < cands.length; i += 2) {
      const s0 = vol(cands[i], !!opts.quick)[0], s1 = cands[i + 1] === cands[i] ? s0 : vol(cands[i + 1], !!opts.quick)[0];
      const [sc, n] = s1 < s0 * (1 - 5e-4) ? [s1, cands[i + 1]] : [s0, cands[i]];
      if (sc < best[0]) best = [sc, n];
    }
    return { origin, ...planeFrame(best[1], lengthAxis) };
  }

  function extents(spine, P2, W, allow, lamT) {
    let sLo = Infinity, sHi = -Infinity, dLo = Infinity, dHi = -Infinity;
    for (const p of P2) { const [s, d] = spine.project(p); if (s < sLo) sLo = s; if (s > sHi) sHi = s; if (d < dLo) dLo = d; if (d > dHi) dHi = d; }
    const need = dHi - dLo + 2 * allow, lamCount = Math.max(1, Math.ceil(need / lamT - 1e-6)), extra = lamCount * lamT - need, dLow = dLo - allow - 0.5 * extra;
    let wLo = Infinity, wHi = -Infinity; for (const w of W) { if (w < wLo) wLo = w; if (w > wHi) wHi = w; }
    return { sLow: sLo - allow, sHigh: sHi + allow, dLow, dHigh: dLow + lamCount * lamT, wLow: wLo - allow, wHigh: wHi + allow, lamCount, depthNeeded: need };
  }
  function bandArea(spine, e) { return (e.dHigh - e.dLow) * (e.sHigh - e.sLow) * (1 - spine.kappa * 0.5 * (e.dLow + e.dHigh)); }

  function convexHull(P) {
    const pts = P.map(p => [p[0], p[1]]).sort((a, b) => a[0] - b[0] || a[1] - b[1]);
    const cr = (o, a, b) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
    const lo = [], up = [];
    for (const p of pts) { while (lo.length >= 2 && cr(lo[lo.length - 2], lo[lo.length - 1], p) <= 0) lo.pop(); lo.push(p); }
    for (let i = pts.length - 1; i >= 0; i--) { const p = pts[i]; while (up.length >= 2 && cr(up[up.length - 2], up[up.length - 1], p) <= 0) up.pop(); up.push(p); }
    return lo.slice(0, -1).concat(up.slice(0, -1));
  }
  function minWidthBox(P) {
    const H = convexHull(P); let best = null;
    for (let i = 0; i < H.length; i++) { const a = H[i], b = H[(i + 1) % H.length], ex = b[0] - a[0], ey = b[1] - a[1], l = Math.hypot(ex, ey); if (l < 1e-12) continue;
      const fx = ex / l, fy = ey / l, ax = -fy, ay = fx; let w = ptp(H.map(p => p[0] * ax + p[1] * ay)), L = ptp(H.map(p => p[0] * fx + p[1] * fy));
      if (!best || w < best.width) best = { width: w, length: L }; }
    return best || { width: 0, length: 0 };
  }

  /* Full fit for one part given its surface points (mm). */
  function fitBillet(P, o) {
    const allow = o.allow, lamT = o.lamT;
    const lvl = o.level || (o.quick ? 'quick' : 'full');
    const pl = fitBendingPlane(P, allow, lvl === 'quick' ? { maxCount: 160, outerEval: 0, quick: true } : lvl === 'medium' ? { maxCount: 150, outerEval: 30, quick: true } : { maxCount: 400, outerEval: 60 });
    const F = { u: pl.u, v: pl.v, n: pl.n }, { P2, W } = project(P, pl.origin, F);
    const fit = fitArc2d(subset(P2, lvl === 'full' ? 1500 : 300), allow, lvl === 'quick');
    const sp = fit.spine, e = extents(sp, P2, W, allow, lamT);
    const width = e.wHigh - e.wLow, depth = e.dHigh - e.dLow, length = e.sHigh - e.sLow;
    const volume = width * bandArea(sp, e);
    let rLam = Infinity, cusp = false;
    if (sp.kind === 'arc') { const a = sp.R - e.dLow, b = sp.R - e.dHigh; if (a <= 0 || b <= 0) cusp = true; rLam = Math.min(Math.abs(a), Math.abs(b)); }
    const outline = []; for (let k = 0; k <= 48; k++) { const s = e.sLow + (e.sHigh - e.sLow) * k / 48; outline.push(sp.point(s, e.dLow), sp.point(s, e.dHigh)); }
    const box = minWidthBox(outline);
    return { origin: pl.origin, u: F.u, v: F.v, n: F.n, spine: sp, ext: e, width, depth, length, volume, lamCount: e.lamCount, lamT,
      R: sp.R, rLam, cusp, cncInPlane: box.width, cncFeed: box.length };
  }
  function checkMachine(b, m) {
    const opts = [['flat', b.cncInPlane, b.width], ['on edge', b.width, b.cncInPlane]].map(([label, across, height]) => ({ label, margin: Math.min(m.w - across, m.h - height) }));
    const fit = opts.filter(o => o.margin >= 0), best = (fit.length ? fit : opts).reduce((a, c) => c.margin > a.margin ? c : a);
    return { fits: fit.length > 0, best, lengthOk: !m.L || b.cncFeed <= m.L };
  }
  /* Billet solid as a sampled sweep: returns 3D corner rings [lo-in, lo-out, hi-out, hi-in] per station. */
  function billetRings(b, samples = 24) {
    const e = b.ext, sp = b.spine, R = [];
    const to3 = (p2, w) => [b.origin[0] + p2[0] * b.u[0] + p2[1] * b.v[0] + w * b.n[0], b.origin[1] + p2[0] * b.u[1] + p2[1] * b.v[1] + w * b.n[1], b.origin[2] + p2[0] * b.u[2] + p2[1] * b.v[2] + w * b.n[2]];
    const ns = sp.kind === 'line' ? 1 : samples;
    for (let k = 0; k <= ns; k++) { const s = e.sLow + (e.sHigh - e.sLow) * k / ns;
      R.push([to3(sp.point(s, e.dLow), e.wLow), to3(sp.point(s, e.dHigh), e.wLow), to3(sp.point(s, e.dHigh), e.wHigh), to3(sp.point(s, e.dLow), e.wHigh)]); }
    return R;
  }
  global.Billet = { nelderMead, eigSym3, pcaAxes, fitArc2d, fitBendingPlane, fitBillet, checkMachine, billetRings, minWidthBox, subset };
})(typeof window !== 'undefined' ? window : globalThis);
