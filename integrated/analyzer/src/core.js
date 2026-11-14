/* Curvature core — pure functions, no DOM. Units: millimetres throughout. */
(function (global) {
  const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
  const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
  const len = (a) => Math.sqrt(dot(a, a));

  /**
   * Sample a parametric surface on an nu x nv grid and compute differential geometry
   * by central finite differences. ev(u,v) -> [x,y,z] in mm.
   */
  function analyzePatch(ev, dom, nu, nv, flip) {
    const n = nu * nv;
    const P = new Float64Array(n * 3), N = new Float64Array(n * 3);
    const K = new Float64Array(n), H = new Float64Array(n), k1 = new Float64Array(n), k2 = new Float64Array(n);
    const A = new Float64Array(n), ok = new Uint8Array(n), UV = new Float64Array(n * 2);
    const knU = new Float64Array(n), knV = new Float64Array(n);
    const du = dom.u1 - dom.u0, dv = dom.v1 - dom.v0;
    const hu = du * 1e-3, hv = dv * 1e-3;
    const cellU = du / (nu - 1), cellV = dv / (nv - 1);
    const s = flip ? -1 : 1;
    for (let j = 0; j < nv; j++) {
      const v = dom.v0 + dv * j / (nv - 1);
      const vc = Math.min(Math.max(v, dom.v0 + hv), dom.v1 - hv);
      for (let i = 0; i < nu; i++) {
        const idx = j * nu + i;
        const u = dom.u0 + du * i / (nu - 1);
        const uc = Math.min(Math.max(u, dom.u0 + hu), dom.u1 - hu);
        UV[idx * 2] = u; UV[idx * 2 + 1] = v;
        const p = ev(u, v);
        P[idx * 3] = p[0]; P[idx * 3 + 1] = p[1]; P[idx * 3 + 2] = p[2];
        const c = ev(uc, vc);
        const pu = ev(uc + hu, vc), mu = ev(uc - hu, vc), pv = ev(uc, vc + hv), mv = ev(uc, vc - hv);
        const pp = ev(uc + hu, vc + hv), pm = ev(uc + hu, vc - hv), mp = ev(uc - hu, vc + hv), mm = ev(uc - hu, vc - hv);
        const Su = [], Sv = [], Suu = [], Svv = [], Suv = [];
        for (let k = 0; k < 3; k++) {
          Su[k] = (pu[k] - mu[k]) / (2 * hu);
          Sv[k] = (pv[k] - mv[k]) / (2 * hv);
          Suu[k] = (pu[k] - 2 * c[k] + mu[k]) / (hu * hu);
          Svv[k] = (pv[k] - 2 * c[k] + mv[k]) / (hv * hv);
          Suv[k] = (pp[k] - pm[k] - mp[k] + mm[k]) / (4 * hu * hv);
        }
        const nr = cross(Su, Sv), l = len(nr);
        const ref = len(Su) * len(Sv);
        if (!(l > 1e-9 * ref) || !isFinite(l)) { ok[idx] = 0; continue; }
        const nn = [s * nr[0] / l, s * nr[1] / l, s * nr[2] / l];
        N[idx * 3] = nn[0]; N[idx * 3 + 1] = nn[1]; N[idx * 3 + 2] = nn[2];
        const E = dot(Su, Su), F = dot(Su, Sv), G = dot(Sv, Sv);
        const L = dot(Suu, nn), M = dot(Suv, nn), NN = dot(Svv, nn);
        const W = E * G - F * F;
        const kk = (L * NN - M * M) / W;
        const hh = (E * NN - 2 * F * M + G * L) / (2 * W);
        const disc = Math.sqrt(Math.max(hh * hh - kk, 0));
        K[idx] = kk; H[idx] = hh; k1[idx] = hh + disc; k2[idx] = hh - disc;
        knU[idx] = L / E; knV[idx] = NN / G;
        const wi = (i === 0 || i === nu - 1) ? 0.5 : 1, wj = (j === 0 || j === nv - 1) ? 0.5 : 1;
        A[idx] = Math.sqrt(W) * cellU * cellV * wi * wj;
        ok[idx] = 1;
      }
    }
    return { nu, nv, P, N, K, H, k1, k2, A, ok, UV, knU, knV };
  }

  /** Offset range [dLo, dHi] (mm) along the normal for a given thickness mode. */
  function offsetRange(T, mode) {
    if (mode === 'in') return [-T, 0];
    if (mode === 'center') return [-T / 2, T / 2];
    return [0, T];
  }

  /** Board geometry for the chosen stock. h = dimension the board bends through, b = width lying on the surface. */
  function stockDims(prm) {
    if (prm.route === 'billet') return { h: prm.lamT, b: prm.memberW, T: prm.memberD, Rmin: prm.lamT * prm.rt };
    const edge = prm.orient === 'edge';
    const h = edge ? prm.d : prm.t, b = edge ? prm.t : prm.d;
    return { h, b, T: h * prm.layers, Rmin: prm.E * h / (2 * prm.fb) };
  }

  /** Utilisation of a board running along `dir` ('u' or 'v') at every sample. */
  function evalDir(res, prm, dir) {
    const n = res.nu * res.nv, { h, b } = stockDims(prm);
    const U = new Float32Array(n), Ub = new Float32Array(n), Uf = new Float32Array(n);
    let failA = 0, sumU = 0, A = 0;
    for (let i = 0; i < n; i++) {
      if (!res.ok[i]) continue;
      const kl = dir === 'u' ? res.knU[i] : res.knV[i];   // normal curvature along the board
      const kt = 2 * res.H[i] - kl;                       // normal curvature across the board
      const billet = prm.route === 'billet';
      const ub = billet ? prm.lamT * prm.rt * Math.abs(kl)            // lam R/t check along the member
                        : prm.E * h * Math.abs(kl) / (2 * prm.fb);   // bending stress / forming limit
      const uf = billet ? 0 : b * b * Math.abs(kt) / (8 * prm.tol);  // billet: second curvature is machined
      Ub[i] = ub; Uf[i] = uf; U[i] = Math.max(ub, uf);
      A += res.A[i]; sumU += res.A[i] * Math.min(U[i], 5);
      if (U[i] > 1) failA += res.A[i];
    }
    return { U, Ub, Uf, failA, meanU: sumU / (A || 1) };
  }

  /**
   * Per-sample classification.
   * type: 0 planar, 1 singly curved, 2 synclastic (dome), 3 anticlastic (saddle), 255 invalid
   * fab:  0 OK (U<=0.8), 1 tight (<=1), 2 fails (<=1.5), 3 fails badly (>1.5), 4 thickness self-intersects, 255 invalid
   */
  function classify(res, prm) {
    const n = res.nu * res.nv;
    const type = new Uint8Array(n), fab = new Uint8Array(n), R = new Float64Array(n);
    const kFlat = 1 / prm.flatR;
    const sd = stockDims(prm);
    const [dLo, dHi] = offsetRange(sd.T, prm.mode);
    let dir = prm.dir, ev;
    if (dir === 'auto') {
      const eu = evalDir(res, prm, 'u'), evv = evalDir(res, prm, 'v');
      const better = (eu.failA < evv.failA - 1e-9) || (Math.abs(eu.failA - evv.failA) <= 1e-9 && eu.meanU <= evv.meanU);
      dir = better ? 'u' : 'v'; ev = better ? eu : evv;
    } else ev = evalDir(res, prm, dir);
    for (let i = 0; i < n; i++) {
      if (!res.ok[i]) { type[i] = 255; fab[i] = 255; R[i] = NaN; continue; }
      const a = res.k1[i], b = res.k2[i];
      const kmax = Math.max(Math.abs(a), Math.abs(b));
      R[i] = kmax > 0 ? 1 / kmax : Infinity;
      const fa = Math.abs(a) < kFlat, fb = Math.abs(b) < kFlat;
      if (fa && fb) type[i] = 0;
      else if (fa || fb) type[i] = 1;
      else type[i] = res.K[i] > 0 ? 2 : 3;
      const off = (a * dHi >= 1) || (b * dHi >= 1) || (a * dLo >= 1) || (b * dLo >= 1);
      const u = ev.U[i];
      fab[i] = off ? 4 : u <= 0.8 ? 0 : u <= 1 ? 1 : u <= 1.5 ? 2 : 3;
    }
    return { type, fab, R, U: ev.U, Ub: ev.Ub, Uf: ev.Uf, dir };
  }

  function percentile(arr, p) {
    if (!arr.length) return NaN;
    const a = Float64Array.from(arr).sort();
    const k = Math.min(a.length - 1, Math.max(0, Math.round((a.length - 1) * p)));
    return a[k];
  }

  function summarize(patches, prm) {
    const st = {
      area: 0, typeArea: [0, 0, 0, 0], fabArea: [0, 0, 0, 0, 0], govBend: 0, govFit: 0, Umax: 0,
      Kmin: Infinity, Kmax: -Infinity, Hmin: Infinity, Hmax: -Infinity,
      Rmin: Infinity, RminAt: null, RminPatch: null,
      kPosMax: 0, kNegMax: 0, bbox: [Infinity, Infinity, Infinity, -Infinity, -Infinity, -Infinity],
      absK: [], Rs: [], Hs: [], samples: 0, invalid: 0,
    };
    for (const p of patches) {
      const r = p.res, c = p.cls; if (!r) continue;
      const n = r.nu * r.nv;
      for (let i = 0; i < n; i++) {
        st.samples++;
        const x = r.P[i * 3], y = r.P[i * 3 + 1], z = r.P[i * 3 + 2];
        const b = st.bbox;
        if (x < b[0]) b[0] = x; if (y < b[1]) b[1] = y; if (z < b[2]) b[2] = z;
        if (x > b[3]) b[3] = x; if (y > b[4]) b[4] = y; if (z > b[5]) b[5] = z;
        if (!r.ok[i]) { st.invalid++; continue; }
        const a = r.A[i];
        st.area += a;
        st.typeArea[c.type[i]] += a;
        st.fabArea[c.fab[i]] += a;
        if (c.U[i] > 1) { if (c.Ub[i] >= c.Uf[i]) st.govBend += a; else st.govFit += a; }
        if (c.U[i] > st.Umax) st.Umax = c.U[i];
        const K = r.K[i], H = r.H[i];
        if (K < st.Kmin) st.Kmin = K; if (K > st.Kmax) st.Kmax = K;
        if (H < st.Hmin) st.Hmin = H; if (H > st.Hmax) st.Hmax = H;
        if (c.R[i] < st.Rmin) { st.Rmin = c.R[i]; st.RminAt = [x, y, z]; st.RminPatch = p.name; st.RminRef = { p, i }; }
        st.kPosMax = Math.max(st.kPosMax, r.k1[i], 0);
        st.kNegMax = Math.max(st.kNegMax, -r.k2[i], 0);
        st.absK.push(Math.abs(K)); st.Hs.push(Math.abs(H));
        if (isFinite(c.R[i])) st.Rs.push(c.R[i]);
      }
    }
    const A = st.area || 1;
    st.typeFrac = st.typeArea.map(a => a / A);
    st.fabFrac = st.fabArea.map(a => a / A);
    const dbl = st.typeFrac[2] + st.typeFrac[3];
    st.doubleFrac = dbl;
    if (dbl >= 0.1) st.verdict = 'Doubly curved';
    else if (st.typeFrac[1] >= 0.1) st.verdict = 'Singly curved';
    else st.verdict = 'Planar / near-flat';
    if (dbl >= 0.1) {
      st.verdictDetail = st.typeFrac[2] > 0.7 * dbl ? 'mostly synclastic (dome-like)'
        : st.typeFrac[3] > 0.7 * dbl ? 'mostly anticlastic (saddle-like)' : 'mixed synclastic / anticlastic';
    } else st.verdictDetail = '';
    st.Kclip = percentile(st.absK, 0.95) || 1e-12;
    st.Hclip = percentile(st.Hs, 0.95) || 1e-12;
    const sd = stockDims(prm);
    const T = sd.T;
    st.T = T; st.stockRmin = sd.Rmin; st.h = sd.h; st.b = sd.b;
    st.feasible = st.fabFrac[0] + st.fabFrac[1];
    st.governing = st.govBend + st.govFit > 0 ? (prm.route === 'billet' ? 'lam bend radius' : st.govBend >= st.govFit ? 'bending stress' : 'fit across width') : 'none';
    st.Tmax = prm.mode === 'in' ? 1 / st.kNegMax : prm.mode === 'center' ? 2 / Math.max(st.kPosMax, st.kNegMax) : 1 / st.kPosMax;
    st.volume = st.area * T; // mm^3
    let rLo = percentile(st.Rs, 0.02), rHi = Math.min(percentile(st.Rs, 0.98), prm.flatR);
    if (!isFinite(rLo)) { rLo = 1000; rHi = 100000; }
    if (!(rHi > rLo * 1.05)) rHi = rLo * 10;
    st.rLo = rLo; st.rHi = rHi;
    delete st.absK; delete st.Hs; delete st.Rs;
    return st;
  }

  global.Core = { analyzePatch, classify, summarize, offsetRange, percentile, stockDims, evalDir };
})(typeof window !== 'undefined' ? window : globalThis);
