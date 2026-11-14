// node tests/test_integration.js : regression tests for the defects fixed when the drop moved to integrated/analyzer
const path = require('path'), fs = require('fs'), os = require('os'), { spawnSync } = require('child_process');
require('../src/helpers.js'); const H = globalThis.Helpers;
const root = path.join(__dirname, '..'), page = fs.readFileSync(path.join(root, 'src/page.html'), 'utf8');
let fails = 0;
const check = (name, ok, detail) => { if (!ok) fails++; console.log(`${ok ? 'ok  ' : 'FAIL'} ${name}${detail ? ': ' + detail : ''}`); };

// 1. CNC max length between 0 and 0.2 m made Lmax <= 0 and the split loop never ended.
{
  const Ltot = 12000, modes = { alwaysOk: () => ({ ok: true }), neverOk: () => ({ ok: false }), shortOnly: (a, e) => ({ ok: e - a <= 600 }) };
  let all = true, worst = '';
  for (const Lm of [0, 0.0001, 0.05, 0.1, 0.15, 0.199, 0.2, 0.2001, 0.21, 1, 18, NaN, -5, Infinity]) {
    const Lmax = H.pieceMaxLength(Lm * 1000);
    for (const [k, f] of Object.entries(modes)) {
      let r, err = null; try { r = H.segment(Ltot, Lmax, f); } catch (e) { err = e.message; }
      const inc = r && r.cuts.every((c, i) => i === 0 || c > r.cuts[i - 1]);
      const ok = !err && inc && r.cuts[0] === 0 && Math.abs(r.cuts[r.cuts.length - 1] - Ltot) < 1 + 1e-9 && r.fits.length === r.cuts.length - 1;
      if (!ok) { all = false; worst = `L=${Lm} m, ${k}: ${err || JSON.stringify(r && r.cuts.slice(0, 5))}`; }
    }
  }
  check('cnc_max_length_any_setting_terminates', all, worst);
  check('cnc_max_length_clamped_positive', [0.0001, 0.1, 0.2].every(m => H.pieceMaxLength(m * 1000) >= H.MIN_PIECE) && H.pieceMaxLength(0) === Infinity && H.pieceMaxLength(18000) === 17800);
  // The drop's formula (M.L ? M.L - 200 : Infinity) with L = 0.1 m gives a negative piece length: no progress.
  // The drop's loop, verbatim apart from an iteration cap, with its own Lmax formula at L = 0.1 m:
  const ML = 100, oldLmax = ML ? ML - 200 : Infinity, Lmin = Math.min(800, Ltot); let a = 0, it = 0;
  while (a < Ltot - 1 && it < 10000) { it++; const end = Math.min(Ltot, a + oldLmax);
    if (modes.alwaysOk(a, end).ok) { a = end; continue; } const lo = Math.min(a + Lmin, end); a = lo; }
  check('cnc_max_length_drop_loop_never_ends (discriminates)', it === 10000, `after ${it} steps the start is at ${a} mm`);
}

// 3. Buy quantities ignored the number of layers stacked through the thickness.
{
  const t1 = H.boardTotals([2400, 2400, 1200], 1, 2438.4), t3 = H.boardTotals([2400, 2400, 1200], 3, 2438.4);
  check('buy_quantity_scales_with_layers', t1.buy === 3 && t3.buy === 9 && t3.linearBuy === 3 * t1.linearBuy && t3.waste === t1.waste, `1 layer ${t1.buy}, 3 layers ${t3.buy}`);
  check('page_uses_layers_for_buy (cut list, PDF, CSV)', page.includes('Helpers.boardTotals(pieces.map(q=>q.len), billetMode?1:prm.layers, Lst)')
    && page.includes('<b>${t.buy}</b>') && page.includes('${S.boards.tot.buy} pcs') && page.includes('surface,qty_to_buy'));
}

// 4. Member width was measured along the transverse isocurve: a sheared plane got 31 boards where 22 fit.
{
  const nu = 41, nv = 41, Lu = 4000, Wperp = 830, b = 38, c = Math.SQRT1_2;
  const Wiso = Wperp / c, P = new Float64Array(nu * nv * 3);   // transverse isocurve runs at 45 degrees to the members
  for (let j = 0; j < nv; j++) for (let i = 0; i < nu; i++) { const u = i / (nu - 1), v = j / (nv - 1), q = (j * nu + i) * 3;
    P[q] = u * Lu + v * Wiso * c; P[q + 1] = v * Wiso * c; P[q + 2] = 0; }
  const tc = H.transverseCoords(P, nu, nv, true), boards = Math.ceil(tc.maxS / b);
  let iso = 0; for (let j = 1; j < nv; j++) iso += Math.hypot(P[j * nu * 3] - P[(j - 1) * nu * 3], P[j * nu * 3 + 1] - P[(j - 1) * nu * 3 + 1]);
  check('sheared_plane_board_count_is_22', boards === 22, `perpendicular ${tc.maxS.toFixed(1)} mm -> ${boards} boards (along the isocurve it was ${Math.ceil(iso / b)})`);
  check('sheared_plane_drop_count_was_31 (discriminates)', Math.ceil(iso / b) === 31);
  // an orthogonal grid is unchanged
  for (let j = 0; j < nv; j++) for (let i = 0; i < nu; i++) { const q = (j * nu + i) * 3; P[q] = i / (nu - 1) * Lu; P[q + 1] = j / (nv - 1) * Wperp; }
  check('orthogonal_grid_width_unchanged', Math.abs(H.transverseCoords(P, nu, nv, true).maxS - Wperp) < 1e-6 && Math.abs(H.transverseCoords(P, nu, nv, false).maxS - Lu) < 1e-6);
}

// 5. One shared debounce timer dropped an edit when two inputs changed within 250 ms.
{
  let now = 0, q = [], id = 0; const setT = (fn, ms) => { const t = { id: ++id, at: now + ms, fn }; q.push(t); return t; }, clearT = t => { q = q.filter(x => x !== t); };
  const flush = () => { now += 1000; const due = q.filter(t => t.at <= now); q = q.filter(t => t.at > now); due.forEach(t => t.fn()); };
  const ran = []; const reclassify = () => ran.push('reclassify'), rebillet = () => ran.push('rebillet');
  const deb = H.debouncer(250, setT, clearT);
  deb(reclassify); now += 100; deb(rebillet); now += 50; deb(reclassify); flush();
  check('debounce_two_inputs_both_run', ran.includes('reclassify') && ran.includes('rebillet') && ran.length === 2, ran.join(','));
  // the drop's shared timer, same sequence
  let tmr = null; const old = fn => { clearT(tmr); tmr = setT(fn, 250); }; ran.length = 0; old(reclassify); old(rebillet); flush();
  check('debounce_drop_shared_timer_dropped_one (discriminates)', ran.length === 1);
  check('page_uses_per_callback_debounce', page.includes('const deb=Helpers.debouncer(250)') && !/let tmr=null/.test(page));
}

// 6. Object and layer names from a .3dm went into innerHTML unescaped.
{
  const evil = `<img src=x onerror=alert(1)>" onmouseover="x`;
  const out = H.escapeHtml(evil);
  check('escape_html_blocks_markup_and_attribute_breakout', !/[<>"]/.test(out) && out.includes('&lt;img') && out.includes('&quot;'));
  const objRow = page.slice(page.indexOf('const ol=$(\'objlist\')'), page.indexOf('ol.appendChild(d)'));
  check('page_object_list_escapes_names', objRow.includes('Helpers.escapeHtml(p.name)') && !objRow.includes('${p.name}'));
}

// 8. Billet mode exported object names and summary.json said "2x6 on edge".
{
  const lbl = H.stockLabel('billet', '2x6', 'on edge', 17, '2x6');
  check('billet_route_names_not_board_size', !/on edge|^2x6/.test(lbl) && lbl.includes('17 mm lams'), lbl);
  check('board_route_names_unchanged', H.stockLabel('boards', '2x6', 'on edge', 38, '2x6') === '2x6 on edge');
  const sumLine = page.split('\n').find(l => l.includes("orientation:S.route==='billet'"));
  check('summary_json_keeps_its_fields', !!sumLine && !/\/\/.*stock_bend_limit_m/.test(sumLine) && /stock_bend_limit_m:st\.stockRmin/.test(sumLine));
  check('page_names_billet_route',page.includes("orientation:S.route==='billet'? null : prm.orient") && page.includes("B.billetMode? 'billet piece' : S.size") && page.includes('${Helpers.stockLabel(S.route,S.size,S.orientLabel(),prm.lamT,prm.lamStock)} · ${st_T()} mm'));
}

// 7. build.py read and wrote with the platform encoding; a cp1252 machine fails on some UTF-8 text.
{
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'analyzer-build-'));
  for (const d of ['src', 'vendor']) fs.cpSync(path.join(root, d), path.join(tmp, d), { recursive: true });
  fs.copyFileSync(path.join(root, 'build.py'), path.join(tmp, 'build.py'));
  fs.appendFileSync(path.join(tmp, 'src/page.html'), '\n<!-- Łódź × ² … -->\n', 'utf8');  // "Ł" is C5 81; 0x81 is undefined in cp1252
  const py = process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
  const r = spawnSync(py, ['build.py'], { cwd: tmp, env: { ...process.env, PYTHONUTF8: '0' }, encoding: 'utf8' });
  const out = r.status === 0 ? fs.readFileSync(path.join(tmp, 'dist/index.html'), 'utf8') : '';
  check('build_py_utf8_round_trip', r.status === 0 && out.includes('Łódź × ² …') && out.includes('global.Helpers') && out.includes('global.Billet') && !out.includes('/*__CORE__*/'), r.status === 0 ? '' : (r.stderr || '').trim().split('\n').pop());
  const vendored = ['three/build/three.module.js', 'three/examples/jsm/controls/OrbitControls.js', 'jspdf/jspdf.umd.min.js', 'fflate/umd/index.js'];
  check('build_copies_vendored_libraries', r.status === 0 && vendored.every(f => fs.existsSync(path.join(tmp, 'dist/vendor', f))));
  fs.rmSync(tmp, { recursive: true, force: true });
}

// Libraries are vendored: the page references no remote URL, and every vendored file matches vendor/README.md.
{
  const urls = [...page.matchAll(/(?:src|href)\s*=\s*["']([^"']+)["']|["'](https?:\/\/[^"']+)["']/g)].map(m => m[1] || m[2]).filter(u => /^(https?:)?\/\//.test(u));
  check('page_makes_no_remote_requests', urls.length === 0, urls.join(' '));
  const crypto = require('crypto'), readme = fs.readFileSync(path.join(root, 'vendor/README.md'), 'utf8');
  const rows = [...readme.matchAll(/`([a-z]+\/[^`]+)`[^|]*\| (\d+) \| `([0-9a-f]{64})`/g)];
  const bad = rows.filter(([, f, n, h]) => { const b = fs.readFileSync(path.join(root, 'vendor', f)); return b.length !== +n || crypto.createHash('sha256').update(b).digest('hex') !== h; });
  check('vendored_files_match_readme_sha256', rows.length === 7 && bad.length === 0, bad.map(b => b[1]).join(' '));
}

// 2 and the trimmed-face flag need the rhino3dm runtime (vendored); run them last.
const rhino3dm = require('../vendor/rhino3dm.min.js');
rhino3dm({ locateFile: p => path.join(root, 'vendor', p) }).then(rh => {
  const doc = new rh.File3dm(); doc.settings().modelUnitSystem = rh.UnitSystem.Millimeters;
  const m = new rh.Mesh(); m.vertices().add(0, 0, 0); m.vertices().add(1000, 0, 0); m.vertices().add(0, 1000, 0); m.faces().addTriFace(0, 1, 2);
  doc.objects().addMesh(m, new rh.ObjectAttributes());
  const head = b => Buffer.from(b.slice(0, 32)).toString('latin1');
  const v7 = H.toRhino7Bytes(rh, doc), back = rh.File3dm.fromByteArray(v7);
  check('export_3dm_is_rhino7_archive', head(v7) === '3D Geometry File Format       70' && back && back.objects().count === 1, JSON.stringify(head(v7)));
  check('export_3dm_default_was_rhino8 (discriminates)', head(doc.toByteArray()).endsWith('80'));
  check('page_export_uses_rhino7_writer', page.includes('Helpers.toRhino7Bytes(rh, doc)') && !/return doc\.toByteArray\(\)/.test(page));
  // trimmed faces: flagged so the UI can say they are analysed untrimmed
  const trimmed = rh.Brep.createTrimmedPlane(rh.Plane.worldXY(), new rh.Circle(300).toNurbsCurve());
  const whole = rh.Brep.createFromSurface(rh.NurbsSurface.createRuledSurface(new rh.LineCurve([0, 0, 0], [1000, 0, 0]), new rh.LineCurve([0, 800, 0], [1000, 800, 300])));
  check('trimmed_face_is_flagged', H.faceIsTrimmed(trimmed.faces().get(0)) === true && H.faceIsTrimmed(whole.faces().get(0)) === false);
  check('page_shows_trimmed_note', page.includes('id="trimNote"') && page.includes('pt.trimmed=Helpers.faceIsTrimmed(face)===true'));
  console.log(fails ? `${fails} FAILED` : 'all passed'); process.exit(fails ? 1 : 0);
}).catch(e => { console.log('FAIL rhino3dm runtime: ' + e.message); process.exit(1); });
