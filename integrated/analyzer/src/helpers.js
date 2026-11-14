/* Pure helpers pulled out of page.html during integration so they can be tested under node.
   No DOM, no three.js. build.py inlines this file into dist/index.html next to core.js and billet.js. */
(function (global) {
  /** Shortest member piece the segmenter will cut (mm). Keeps every CNC length setting finite. */
  const MIN_PIECE = 100;
  /** Allowance kept off the CNC max length when splitting members (mm), as in the original drop. */
  const CNC_ALLOWANCE = 200;

  /** Longest piece to try for a CNC max length L (mm). 0, empty or invalid means no limit. */
  function pieceMaxLength(L) {
    if (!(L > 0) || !isFinite(L)) return Infinity;
    return Math.max(MIN_PIECE, L - CNC_ALLOWANCE);
  }

  /**
   * Greedy segmentation of a member of length Ltot (mm), unchanged from the drop except for the guards:
   * longest piece from the current start whose billet passes; evalAt(a, e) returns { ok, ... }.
   * Every step advances by at least MIN_PIECE (or to the end), so any setting terminates.
   */
  function segment(Ltot, Lmax, evalAt) {
    const cuts = [0], fits = [];
    if (!(Ltot > 0) || !isFinite(Ltot)) return { cuts: [0, Math.max(0, +Ltot || 0)], fits };
    if (!(Lmax > 0)) Lmax = MIN_PIECE;
    const Lmin = Math.min(800, Ltot), step = Math.max(MIN_PIECE, Math.min(Lmax, Lmin));
    const maxIter = Math.ceil(Ltot / Math.min(step, Ltot)) + 2;
    let a = 0, iter = 0;
    while (a < Ltot - 1) {
      if (++iter > maxIter) throw new Error('segment: no progress (guard)');
      const end = Math.min(Ltot, a + Lmax);
      const r = evalAt(a, end); if (r.ok) { cuts.push(end); fits.push(r); a = end; continue; }
      const lo = Math.min(a + Lmin, end), rlo = evalAt(a, lo);
      if (!rlo.ok) { cuts.push(lo); fits.push(rlo); a = lo; continue; }
      let best = lo, bestR = rlo, hi = end;
      while (hi - best > Math.max(150, 0.03 * (hi - a))) { const mid = (best + hi) / 2, rm = evalAt(a, mid); if (rm.ok) { best = mid; bestR = rm; } else hi = mid; }
      if (Ltot - best < 400 && best < Ltot) { const mid = (a + Ltot) / 2; if (mid > a) { const rm = evalAt(a, mid); if (rm.ok) { best = mid; bestR = rm; } } }
      cuts.push(best); fits.push(bestR); a = best;
    }
    return { cuts, fits };
  }

  /** Write a File3dm as a Rhino 7 archive (Rhino 7 cannot open the Rhino 8 default). */
  function toRhino7Bytes(rh, doc) {
    const o = new rh.File3dmWriteOptions(); o.version = 7;
    const bytes = doc.toByteArrayOptions(o);
    if (o.delete) o.delete();
    return bytes;
  }

  /** True when a rhino3dm BrepFace has real trims, false when it is its whole surface, null when unknown. */
  function faceIsTrimmed(face) {
    try { const d = face.duplicateFace(false); if (!d) return null; const t = !d.isSurface; if (d.delete) d.delete(); return t; }
    catch (e) { return null; }
  }

  /**
   * Board coordinate across the members, measured perpendicular to the member direction.
   * The drop measured it along the transverse isocurve, which over-counts boards on sheared parameterisations.
   * P: flat xyz array (nu*nv*3); alongU: members run along u. Returns sArr (per sample), maxS, mean spacing.
   */
  function transverseCoords(P, nu, nv, alongU) {
    const nL = alongU ? nu : nv, nT = alongU ? nv : nu, id = (l, t) => alongU ? (t * nu + l) : (l * nu + t);
    const sArr = new Float64Array(nu * nv); let maxS = 0, spacing = 0, cnt = 0;
    for (let l = 0; l < nL; l++) {
      let s = 0;
      for (let t = 0; t < nT; t++) {
        const i = id(l, t);
        if (t > 0) {
          const j = id(l, t - 1);
          const dx = P[i * 3] - P[j * 3], dy = P[i * 3 + 1] - P[j * 3 + 1], dz = P[i * 3 + 2] - P[j * 3 + 2];
          // member tangent at the midpoint of the step: average of the two samples' along-member differences
          let tx = 0, ty = 0, tz = 0;
          for (const k of [i, j]) {
            const kt = alongU ? Math.floor(k / nu) : k % nu, kl = alongU ? k % nu : Math.floor(k / nu);
            const a = id(Math.max(0, kl - 1), kt), b = id(Math.min(nL - 1, kl + 1), kt);
            tx += P[b * 3] - P[a * 3]; ty += P[b * 3 + 1] - P[a * 3 + 1]; tz += P[b * 3 + 2] - P[a * 3 + 2];
          }
          const tl = Math.hypot(tx, ty, tz);
          let d;
          if (tl > 0) { const dot = (dx * tx + dy * ty + dz * tz) / tl; d = Math.sqrt(Math.max(0, dx * dx + dy * dy + dz * dz - dot * dot)); }
          else d = Math.hypot(dx, dy, dz);
          s += d; spacing += d; cnt++;
        }
        sArr[i] = s;
      }
      maxS = Math.max(maxS, s);
    }
    return { sArr, maxS, meanSpacing: spacing / (cnt || 1), nL, nT };
  }

  /** Board route totals. `layers` boards are stacked through the thickness at every piece, so buying scales with it. */
  function boardTotals(lengths, layers, Lst) {
    const n = Math.max(1, Math.round(+layers || 1)), linear = lengths.reduce((a, x) => a + x, 0);
    return { pieces: lengths.length, layers: n, buy: lengths.length * n, linear, linearBuy: linear * n,
      waste: 1 - linear / (lengths.length * Lst || 1), full: lengths.filter(x => x >= Lst - 1).length };
  }

  /** Debounce per function: each callback keeps its own timer, so two edits inside the delay both run. */
  function debouncer(delay, setT, clearT) {
    setT = setT || setTimeout; clearT = clearT || clearTimeout;
    const timers = new Map();
    return fn => { clearT(timers.get(fn)); timers.set(fn, setT(() => { timers.delete(fn); fn(); }, delay)); };
  }

  /** Escape text for innerHTML (element content and quoted attributes). */
  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
  }

  /** Stock description for names and summaries: the board size in board mode, the billet make-up in billet mode. */
  function stockLabel(route, size, orientLabel, lamT, lamStock) {
    if (route === 'billet') return `glulam billet, ${lamT} mm lams from ${String(lamStock).replace('x', '×')}`;
    return `${size} ${orientLabel}`;
  }

  global.Helpers = { MIN_PIECE, CNC_ALLOWANCE, pieceMaxLength, segment, toRhino7Bytes, faceIsTrimmed,
    transverseCoords, boardTotals, debouncer, escapeHtml, stockLabel };
})(typeof window !== 'undefined' ? window : globalThis);
