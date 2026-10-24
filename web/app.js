// SmartSeed seed map: palette, tray layout, saved templates and the planting run.
// The live camera and tray localisation live in scanner.js, which drives this module
// through window.smartseedApp.
(() => {
  const $ = id => document.getElementById(id);

  // ── Backend ────────────────────────────────────────────────────────────────
  // Only the laptop wired to the arm can reach it. Published on Pages it is simply
  // unreachable, and the run falls back to a clearly labelled demo simulation.
  const BACKEND_URL = (() => {
    try { return localStorage.getItem('smartseed.backendUrl') || 'http://localhost:8000'; }
    catch (e) { return 'http://localhost:8000'; }
  })();

  window.smartseedBackend = {
    url: BACKEND_URL,
    http: path => BACKEND_URL.replace(/\/$/, '') + path,
    ws: path => BACKEND_URL.replace(/^http/, 'ws').replace(/\/$/, '') + path,
    async fetch(path, opts, ms = 4000) {
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), ms);
      try { return await fetch(this.http(path), { ...opts, signal: ctrl.signal }); }
      finally { clearTimeout(timer); }
    },
  };

  // ── Varieties ──────────────────────────────────────────────────────────────
  // Seeds are user-defined: name + emoji + the colour of the bowl the robot looks for
  // (`box`, the id sent as `color` in POST /plan). They live in localStorage; the ids
  // are stored inside saved layouts, so keep them stable. The first load seeds the list
  // with the original four, whose ids are the old layout keys.
  const SEEDS_KEY = 'smartseed.seeds';
  const MAX_NAME = 20;

  // Bowl colours the picker offers. `id` is what the backend receives (^[a-z][a-z_-]{0,19}$).
  const BOWL_COLORS = [
    { id: 'red',    label: 'Rojo',     boxLabel: 'roja',     base: '#c8372d' },
    { id: 'orange', label: 'Naranja',  boxLabel: 'naranja',  base: '#d9660a' },
    { id: 'yellow', label: 'Amarillo', boxLabel: 'amarilla', base: '#d9a400' },
    { id: 'green',  label: 'Verde',    boxLabel: 'verde',    base: '#2b8a4e' },
    { id: 'blue',   label: 'Azul',     boxLabel: 'azul',     base: '#2563c9' },
    { id: 'purple', label: 'Morado',   boxLabel: 'morada',   base: '#7440b0' },
    { id: 'pink',   label: 'Rosa',     boxLabel: 'rosa',     base: '#d9467f' },
    { id: 'white',  label: 'Blanco',   boxLabel: 'blanca',   base: '#ffffff' },
    { id: 'black',  label: 'Negro',    boxLabel: 'negra',    base: '#24272b' },
  ];
  const COLOR_ID = /^[a-z][a-z_-]{0,19}$/;
  const SEED_ID = /^[A-Z0-9_-]{1,40}$/;

  const DEFAULT_SEEDS = [
    { id: 'TOMATE', name: 'Tomate', emoji: '🍅', color: 'red' },
    { id: 'PIMIENTO', name: 'Pimiento', emoji: '🫑', color: 'green' },
    { id: 'LIMON', name: 'Limón', emoji: '🍋', color: 'yellow' },
    { id: 'BERENJENAS', name: 'Berenjena', emoji: '🍆', color: 'purple' },
  ];

  const EMOJIS = ['🍅', '🫑', '🍋', '🍆', '🥕', '🥬', '🌽', '🥒', '🍓', '🌻', '🌿', '🫘',
    '🧅', '🧄', '🥔', '🍉', '🎃', '🌶️', '🥦', '🫛', '🍠', '🌱', '🍀', '🌷'];

  // Shades of one colour: `strong` fills a planted cell, `tint` and `mid` are its soft
  // versions. A near-white bowl is darkened until it stands out from an empty cell.
  const hexRgb = h => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16));
  const rgbHex = c => '#' + c.map(v => Math.round(v).toString(16).padStart(2, '0')).join('');
  const mixHex = (a, b, t) => { const x = hexRgb(a), y = hexRgb(b); return rgbHex(x.map((v, i) => v * (1 - t) + y[i] * t)); };
  const lum = h => {
    const [r, g, b] = hexRgb(h).map(v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); });
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  const contrastWhite = h => 1.05 / (lum(h) + 0.05);

  function shades(base) {
    let strong = base;
    const floor = lum(base) > 0.85 ? 3 : 1.6;
    for (let i = 0; i < 12 && contrastWhite(strong) < floor; i++) strong = mixHex(strong, '#000000', 0.12);
    return { strong, tint: mixHex(base, '#ffffff', 0.86), mid: mixHex(base, '#ffffff', 0.6), edge: mixHex(strong, '#ffffff', 0.55) };
  }

  const bowlColor = id => BOWL_COLORS.find(c => c.id === id) || { id, label: id, boxLabel: id, base: '#6b7a72' };

  // The live seed table, keyed by id and rebuilt from the stored list.
  let SEEDS = {};

  function seedMetaOf(raw) {
    const c = bowlColor(raw.color);
    return { id: raw.id, label: raw.name, emoji: raw.emoji, box: raw.color, boxLabel: c.boxLabel, colorLabel: c.label, ...shades(c.base) };
  }

  function setSeeds(list) {
    SEEDS = {};
    list.forEach(raw => { SEEDS[raw.id] = seedMetaOf(raw); });
  }

  const seedList = () => Object.values(SEEDS).map(m => ({ id: m.id, name: m.label, emoji: m.emoji, color: m.box }));

  const seedKey = name => String(name || '').toUpperCase().normalize('NFD').replace(/[̀-ͯ]/g, '');

  // Resolves what a saved layout holds (a current id, an old key such as TOMATE / BERENJENAS
  // or a plain name) to the id of a seed that still exists, else null.
  function resolveSeed(raw) {
    const k = seedKey(raw);
    if (!k) return null;
    if (SEEDS[k]) return k;
    if (SEEDS[k + 'S']) return k + 'S';
    const byName = Object.values(SEEDS).find(m => seedKey(m.label) === k || seedKey(m.label) + 'S' === k);
    return byName ? byName.id : null;
  }

  const esc = v => String(v).replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));

  function newSeedId() {
    let id;
    do { id = 'S' + Date.now().toString(36).toUpperCase() + Math.random().toString(36).slice(2, 5).toUpperCase(); } while (SEEDS[id]);
    return id;
  }

  // ── State ──────────────────────────────────────────────────────────────────
  const LAYOUT_KEY = 'smartseed.lastLayout';
  const LEGACY_LAYOUT_KEY = 'smartseed-last-layout';
  const TEMPLATES_KEY = 'smartseed.templates';
  const MAX_CELLS = 200;
  const DEMO_MS_PER_CELL = 1100;

  let selected = null;            // id of the seed a tap places
  let rows = 3, cols = 3;
  let cells = [];                 // flat, row-major; each item is a variety key or null
  let run = null;                 // see startRun()
  let toastTimer = null;
  let mobileDropAt = 0;           // guards the click that follows a mobile pointerup drop

  const total = () => rows * cols;
  const filledCount = () => cells.filter(Boolean).length;

  function toast(msg) {
    const el = $('toast');
    el.textContent = msg;
    el.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove('show'), 2800);
  }
  window.smartseedToast = toast;

  // ── Persistence ────────────────────────────────────────────────────────────

  function readJSON(key, fallback) {
    try { const v = JSON.parse(localStorage.getItem(key)); return v === null ? fallback : v; }
    catch (e) { return fallback; }
  }

  function writeJSON(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch (e) { /* storage full or blocked */ }
  }

  // Accepts both shapes: the current {rows, cols, cells} and the old flat array of
  // {name, emoji} objects saved before the tray size was stored with it.
  function normalizeLayout(raw) {
    if (Array.isArray(raw)) return { rows: 0, cols: 0, cells: raw.map(c => (c ? resolveSeed(c.name) : null)) };
    if (!raw || !Array.isArray(raw.cells)) return null;
    return {
      rows: Number(raw.rows) || 0,
      cols: Number(raw.cols) || 0,
      cells: raw.cells.map(c => (c ? resolveSeed(typeof c === 'string' ? c : c.name) : null)),
    };
  }

  function saveLayout() {
    writeJSON(LAYOUT_KEY, { rows, cols, cells });
  }

  // Accepts only well-formed entries; anything else falls back to the original four.
  function loadSeeds() {
    const raw = readJSON(SEEDS_KEY, null);
    if (!Array.isArray(raw)) return DEFAULT_SEEDS;
    const seen = new Set();
    const list = raw.filter(r => r && typeof r === 'object' && SEED_ID.test(String(r.id)) && !seen.has(r.id) && seen.add(r.id) &&
      typeof r.name === 'string' && r.name.trim() && typeof r.emoji === 'string' && r.emoji &&
      typeof r.color === 'string' && COLOR_ID.test(r.color))
      .map(r => ({ id: r.id, name: r.name.trim().slice(0, MAX_NAME), emoji: r.emoji, color: r.color }));
    return list.length ? list : DEFAULT_SEEDS;
  }

  const saveSeeds = () => writeJSON(SEEDS_KEY, seedList());

  function loadTemplates() {
    const raw = readJSON(TEMPLATES_KEY, {});
    const out = {};
    Object.keys(raw || {}).forEach(name => {
      const layout = normalizeLayout(raw[name]);
      if (layout && layout.rows && layout.cols) out[name] = layout;
    });
    return out;
  }

  // ── Rendering ──────────────────────────────────────────────────────────────

  function renderLegend() {
    const m = SEEDS[selected];
    $('trayLegend').innerHTML = m
      ? '<span class="legend-dot" style="--box:' + m.strong + '"></span>' +
        '<span>Seleccionada: <strong>' + esc(m.emoji + ' ' + m.label) + '</strong></span>'
      : '<span>Crea una semilla con «+» para empezar.</span>';
  }

  function renderBoxLegend() {
    $('boxLegend').innerHTML = Object.values(SEEDS).map(m =>
      '<li><i class="box-dot" style="--box:' + m.strong + '"></i>' +
      '<span><strong>' + esc(m.label) + '</strong> · caja ' + esc(m.boxLabel) + '</span></li>').join('');
  }

  const cellLabel = (m, i) => (m
    ? 'Casilla ' + (i + 1) + ': ' + m.label + ', caja ' + m.boxLabel
    : 'Casilla ' + (i + 1) + ' vacía');

  // Says what the tap will actually do, which depends on the variety now selected.
  const cellTitle = (m, i) => {
    const sel = SEEDS[selected];
    if (m) return m.label + ' · caja ' + m.boxLabel + (m === sel ? ' · toca para vaciar' : sel ? ' · toca para poner ' + sel.label : '');
    return 'Casilla ' + (i + 1) + (sel ? ' · toca para poner ' + sel.label : '');
  };

  const cellInner = (m, i) =>
    '<span class="cell-emoji">' + (m ? esc(m.emoji) : '') + '</span>' +
    '<span class="cell-num">' + String(i + 1).padStart(2, '0') + '</span>' +
    '<span class="cell-state" aria-hidden="true"><svg><use href="#i-check"/></svg></span>' +
    (m ? '<span class="cell-clear" data-clear-cell="' + i + '" aria-hidden="true" title="Vaciar casilla">' +
      '<svg><use href="#i-x"/></svg></span>' : '');

  function cellHtml(key, i) {
    const m = key ? SEEDS[key] : null;
    return '<button type="button" class="tray-cell' + (m ? ' filled' : '') + '" data-cell="' + i + '"' +
      ' aria-label="' + esc(cellLabel(m, i)) + '" title="' + esc(cellTitle(m, i)) + '">' + cellInner(m, i) + '</button>';
  }

  const cellNode = i => $('trayGrid').querySelector('[data-cell="' + i + '"]');

  // Updates one cell in place. Rebuilding the whole grid on every tap would drop the
  // keyboard focus and rebuild up to 200 buttons for a single change.
  function paintCell(i) {
    const node = cellNode(i);
    if (!node) return;
    const m = cells[i] ? SEEDS[cells[i]] : null;
    node.classList.toggle('filled', !!m);
    node.classList.remove('drop-target');
    ['--cell-tint', '--cell-mid', '--cell-strong'].forEach(v => node.style.removeProperty(v));
    if (m) {
      node.style.setProperty('--cell-tint', m.tint);
      node.style.setProperty('--cell-mid', m.mid);
      node.style.setProperty('--cell-strong', m.strong);
    }
    node.setAttribute('aria-label', cellLabel(m, i));
    node.setAttribute('title', cellTitle(m, i));
    node.innerHTML = cellInner(m, i);
  }

  function updateCounts() {
    const n = filledCount();
    $('trayCount').textContent = n + ' / ' + total() + ' huecos';
    $('mapPlantBtn').disabled = n === 0;
    $('mapPlantHint').hidden = n > 0;
  }

  // Full rebuild. Only on a size change, a template load or the first render.
  function renderTray() {
    const grid = $('trayGrid');
    grid.style.setProperty('--tray-rows', rows);
    grid.style.setProperty('--tray-cols', cols);
    const html = cells.map(cellHtml);
    const rowLabel = r => '<span class="row-label" aria-hidden="true">' + (r + 1) + '</span>';
    grid.innerHTML = Array.from({ length: rows }, (_, r) =>
      rowLabel(r) + html.slice(r * cols, (r + 1) * cols).join('') + rowLabel(r)).join('');
    cells.forEach((_, i) => paintCell(i));
    updateCounts();
    if (run) paintRunState();
    if (window.smartseedScan) window.smartseedScan.layoutCells();
  }

  // ── Editing ────────────────────────────────────────────────────────────────

  function setCell(i, key) {
    if (run || i < 0 || i >= total()) return;
    cells[i] = key && SEEDS[key] ? key : null;
    saveLayout();
    paintCell(i);
    updateCounts();
  }

  function fillAll(key) {
    if (run) return;
    if (!total()) { toast('Crea primero un casillero.'); return; }
    if (!SEEDS[key]) { toast('Crea primero una semilla con «+».'); return; }
    cells = cells.map(() => key);
    saveLayout();
    cells.forEach((_, i) => paintCell(i));
    updateCounts();
    toast('Mapa completo con ' + SEEDS[key].label + '.');
  }

  function selectSeed(key) {
    selected = SEEDS[key] ? key : null;
    document.querySelectorAll('.seed').forEach(b => {
      const on = !!selected && b.dataset.seed === selected;
      b.classList.toggle('selected', on);
      b.setAttribute('aria-pressed', String(on));
    });
    renderLegend();
    // Only the titles change; the cells themselves stay as they are.
    $('trayGrid').querySelectorAll('[data-cell]').forEach(node => {
      const i = Number(node.dataset.cell);
      node.setAttribute('title', cellTitle(cells[i] ? SEEDS[cells[i]] : null, i));
    });
  }

  // Keep every seed at the same (row, col) when it still fits the new size.
  function setSize(nextRows, nextCols) {
    const clamp = v => Math.max(1, Math.min(20, Math.floor(Number(v) || 1)));
    nextRows = clamp(nextRows);
    nextCols = clamp(nextCols);
    if (nextRows * nextCols > MAX_CELLS) {
      toast('El casillero puede tener como máximo ' + MAX_CELLS + ' huecos.');
      return false;
    }
    const next = Array(nextRows * nextCols).fill(null);
    cells.forEach((key, i) => {
      const r = Math.floor(i / cols), c = i % cols;
      if (key && r < nextRows && c < nextCols) next[r * nextCols + c] = key;
    });
    rows = nextRows;
    cols = nextCols;
    cells = next;
    saveLayout();
    renderTray();
    return true;
  }

  function openApp(nextRows, nextCols) {
    if (!setSize(nextRows, nextCols)) return;
    $('scannerGate').hidden = true;
    $('mainApp').hidden = false;
    $('mobileSeedDock').hidden = false;
    measureDock();
  }

  // ── Templates ──────────────────────────────────────────────────────────────

  function renderTemplates(current = '') {
    const templates = loadTemplates();
    const names = Object.keys(templates).sort((a, b) => a.localeCompare(b, 'es'));
    $('templateSelect').innerHTML =
      '<option value="">' + (names.length ? 'Plantillas…' : 'Sin plantillas') + '</option>' +
      names.map(n => '<option value="' + n.replace(/"/g, '&quot;') + '"' + (n === current ? ' selected' : '') + '>' +
        n + '</option>').join('');
    $('deleteTemplateBtn').hidden = !current;
  }

  function applyTemplate(name) {
    const layout = loadTemplates()[name];
    if (!layout) return;
    rows = layout.rows;
    cols = layout.cols;
    cells = Array.from({ length: rows * cols }, (_, i) => layout.cells[i] || null);
    saveLayout();
    renderTray();
    renderTemplates(name);
    toast('Plantilla «' + name + '» cargada (' + rows + ' × ' + cols + ').');
  }

  function saveTemplate() {
    if (!filledCount()) { toast('Asigna alguna semilla antes de guardar la plantilla.'); return; }
    const name = (prompt('Nombre de la plantilla:', 'Mapa ' + rows + '×' + cols) || '').trim().slice(0, 40);
    if (!name) return;
    const templates = loadTemplates();
    templates[name] = { rows, cols, cells };
    writeJSON(TEMPLATES_KEY, templates);
    renderTemplates(name);
    toast('Plantilla «' + name + '» guardada.');
  }

  function deleteTemplate() {
    const name = $('templateSelect').value;
    if (!name) return;
    const templates = loadTemplates();
    delete templates[name];
    writeJSON(TEMPLATES_KEY, templates);
    renderTemplates('');
    toast('Plantilla «' + name + '» borrada.');
  }

  // ── Planting run ───────────────────────────────────────────────────────────
  // Wire protocol of backend/smartseed_robot (see guide.md):
  //   POST /plan {image_size:[w,h], cells:[{cell_index,row,col,color,u,v}], mode?, drop_z?} -> 202 {plan_id}
  //     mode: "full" (default) | "grasp" (ACT/taught pick only) | "place" (IK over the cell + open only);
  //     drop_z: tool height in metres when releasing (the "Altura al soltar" setting).
  //   WS   /robot/progress  -> plan_started | cell_started | cell_done | cell_failed
  //                            | finished | stopped | error
  //   POST /stop            -> {stopped}
  // u and v are pixels in the camera frame; the backend turns them into table
  // coordinates with its camera-robot homography, so a plan needs a camera scan.

  // Pixel centre of every cell, by flat index, from the live camera or from the last
  // scan before the camera was closed. null when the tray was never scanned.
  function cellPixels() {
    const scan = window.smartseedScan;
    if (!scan) return null;
    const live = scan.cameraActive();
    const centers = live ? scan.cellCenters() : (scan.lastLayout || {}).cells;
    const size = live ? scan.imageSize() : (scan.lastLayout || {}).imageSize;
    if (!Array.isArray(centers) || !centers.length || !size || !size[0]) return null;
    const byIndex = new Map();
    centers.forEach(c => byIndex.set(c.row * cols + c.col, { u: c.x, v: c.y }));
    return { byIndex, size };
  }

  const order = () => cells.map((key, i) => (key ? i : -1)).filter(i => i >= 0);

  // null when some planted cell has no pixel centre: the robot could not reach it.
  function buildPlan(queue) {
    const pixels = cellPixels();
    if (!pixels) return null;
    const planCells = [];
    for (const i of queue) {
      const at = pixels.byIndex.get(i);
      if (!at) return null;
      planCells.push({
        cell_index: i,
        row: Math.floor(i / cols),
        col: i % cols,
        color: SEEDS[cells[i]].box,  // the bowl colour id the robot looks for
        u: at.u,
        v: at.v,
      });
    }
    return { image_size: pixels.size, cells: planCells };
  }

  // The pick needs no cell: the backend only wants the colour, so send one cell with any centre.
  function buildGraspPlan() {
    const pixels = cellPixels();
    const [i, at] = pixels ? [...pixels.byIndex][0] : [0, { u: 0, v: 0 }];
    return {
      image_size: pixels ? pixels.size : [640, 480],
      cells: [{ cell_index: i, row: Math.floor(i / cols), col: i % cols, color: SEEDS[selected].box, u: at.u, v: at.v }],
    };
  }

  function paintRunState() {
    $('trayGrid').querySelectorAll('[data-cell]').forEach(node => {
      const i = Number(node.dataset.cell);
      const state = run ? run.state[i] : null;
      node.classList.toggle('planting', state === 'planting');
      node.classList.toggle('done', state === 'done');
      node.classList.toggle('failed', state === 'failed');
      const icon = node.querySelector('.cell-state use');
      if (icon) icon.setAttribute('href', state === 'failed' ? '#i-x' : '#i-check');
    });
  }

  // A debug run (one half of the cycle) is labelled so nobody mistakes it for a planting.
  const runLabel = () => (run.test ? 'Prueba: ' + (run.test === 'grasp' ? 'coger' : 'dejar') : 'Sembrando');

  function renderRun() {
    if (!run) return;
    const done = run.queue.filter(i => run.state[i] === 'done').length;
    const failed = run.queue.filter(i => run.state[i] === 'failed').length;
    const pct = run.queue.length ? Math.round(100 * (done + failed) / run.queue.length) : (run.finished ? 100 : 0);
    $('runFill').style.width = pct + '%';
    $('runCount').innerHTML = run.queue.length
      ? '<strong>' + done + '</strong> / ' + run.queue.length + ' huecos ' + (run.test ? 'probados' : 'sembrados') +
        (failed ? ' · ' + failed + ' fallidos' : '')
      : 'Sin casillas: el brazo coge la semilla y se queda con ella';
    $('runDetail').textContent = run.detail;
    $('runTitle').textContent = run.test ? runLabel() + (run.finished ? ' · terminada' : '')
      : (run.finished ? 'Siembra terminada' : 'Sembrando');
    const stop = $('stopRunBtn');
    stop.classList.toggle('danger-btn', !run.finished);
    stop.classList.toggle('secondary-btn', run.finished);
    stop.innerHTML = run.finished
      ? '<svg class="ic" aria-hidden="true"><use href="#i-check"/></svg> Volver al mapa'
      : '<svg class="ic" aria-hidden="true"><use href="#i-stop"/></svg> Parar el robot';
    paintRunState();
  }

  const cellName = i => 'fila ' + (Math.floor(i / cols) + 1) + ', columna ' + (i % cols + 1);

  function markCell(i, status, detail) {
    if (!run || !(i in run.state)) return;
    if (status === 'planting') run.queue.forEach(j => { if (run.state[j] === 'planting') run.state[j] = 'pending'; });
    run.state[i] = status;
    if (status === 'planting') run.detail = (run.test ? 'Probando ' : 'Sembrando ') + cellName(i);
    if (status === 'failed') run.detail = detail || 'Fallo en ' + cellName(i);
    renderRun();
  }

  function setMode(label, demo) {
    $('runMode').textContent = label;
    $('runMode').classList.toggle('demo', !!demo);
  }

  function finishRun(message, detail) {
    if (!run) return;
    run.finished = true;
    run.detail = detail || '';
    clearTimeout(run.timer);
    if (run.ws) { run.ws.onclose = null; run.ws.close(); run.ws = null; }
    renderRun();
    toast(message);
  }

  function closeRun() {
    if (!run) return;
    clearTimeout(run.timer);
    if (run.ws) { run.ws.onclose = null; run.ws.close(); }
    run = null;
    $('runPanel').hidden = true;
    $('trayActions').hidden = false;
    $('mapa-semillero').classList.remove('running');
    document.body.classList.remove('running');
    measureDock();
    renderTray();
  }

  // Published on Pages there is no robot: walk the plan locally so the flow can be shown.
  function runDemo() {
    let step = 0;
    const tick = () => {
      if (!run || run.finished) return;
      if (step >= run.queue.length) {
        finishRun('¡Siembra completada! (simulación)', 'Simulación terminada');
        return;
      }
      const i = run.queue[step];
      markCell(i, 'planting');
      run.timer = setTimeout(() => {
        if (!run || run.finished) return;
        markCell(i, 'done');
        step += 1;
        tick();
      }, DEMO_MS_PER_CELL);
    };
    tick();
  }

  function listenProgress() {
    let ws;
    try { ws = new WebSocket(window.smartseedBackend.ws('/robot/progress')); }
    catch (e) { finishRun('No se ha podido escuchar el progreso del robot.', 'Sin conexión de progreso'); return; }
    run.ws = ws;
    ws.onmessage = ev => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch (e) { return; }
      if (!run || run.finished) return;
      switch (msg.type) {
        case 'plan_started':
          run.detail = 'El robot ha empezado el plan';
          renderRun();
          break;
        case 'cell_started':
          markCell(msg.cell_index, 'planting');
          break;
        case 'cell_done':
          markCell(msg.cell_index, 'done');
          if (msg.empty) toast('En ' + cellName(msg.cell_index) + ' la pinza parecía vacía; se ha abierto sobre la casilla igualmente.');
          break;
        case 'cell_failed':
          markCell(msg.cell_index, 'failed', 'Falló ' + cellName(msg.cell_index) + ': la pinza salió vacía');
          break;
        case 'finished':
          finishRun(run.test ? 'Prueba terminada.' : '¡Siembra completada!', msg.message || 'El robot ha terminado el plan');
          break;
        case 'stopped':
          finishRun(run.test ? 'Prueba detenida.' : 'Siembra detenida.', msg.message || 'Parada solicitada');
          break;
        case 'error':
          finishRun('El robot ha informado de un error.', msg.message || 'Error del robot');
          break;
      }
    };
    ws.onclose = () => { if (run && !run.finished) finishRun('Se ha perdido la conexión con el robot.', 'Conexión cerrada'); };
  }

  // "fake" is the default robot mode: say so, nobody should mistake it for the arm.
  async function labelRobotMode() {
    try {
      const res = await window.smartseedBackend.fetch('/robot/status', {}, 1500);
      const st = await res.json();
      setMode(st.robot === 'real' ? 'ROBOT CONECTADO' : 'ROBOT SIMULADO (fake)', st.robot !== 'real');
    } catch (e) { setMode('ROBOT CONECTADO', false); }
  }

  // The backend answers in English with a `code`; say it in Spanish, and keep its detail
  // when there is no better wording (it carries the list of cells, the missing poses...).
  const REFUSALS = {
    torque_off: 'el par de los motores está desactivado. Pulsa «Bloquear brazo» en Escanear → Calibrar robot antes de sembrar.',
    no_calibration: 'la cámara no está calibrada con el robot: pulsa Escanear → Calibrar robot, marca al menos 4 puntos y pulsa Ajustar.',
    busy: 'ya hay una siembra en curso. Párala antes de empezar otra.',
  };

  function refusalText(body, status) {
    if (REFUSALS[body.code]) return REFUSALS[body.code];
    if (body.code === 'missing_pose') return 'faltan poses enseñadas — ' + body.detail;
    if (body.code === 'unreachable') return 'hay alveolos fuera del alcance del brazo — ' + body.detail;
    return body.detail || 'el robot ha respondido HTTP ' + status + '.';
  }

  // "Altura al soltar" setting (cm), persisted; null when the field holds nonsense.
  const DROP_KEY = 'smartseed.dropHeightCm';
  const DROP_RANGE_CM = [2, 25];
  function dropHeightM() {
    const cm = Number($('dropHeight').value);
    if (!($('dropHeight').value !== '' && cm >= DROP_RANGE_CM[0] && cm <= DROP_RANGE_CM[1])) return null;
    return Math.round(cm * 10) / 1000;
  }

  function startDemo(message) {
    run.mode = 'demo';
    run.detail = 'Sin robot: simulación en el navegador';
    setMode('MODO DEMO', true);
    toast(message);
    runDemo();
    renderRun();
  }

  // `test` is null for a normal planting, or "grasp" / "place" to run one half of the cycle for debugging.
  async function startRun(test) {
    if (run) return;
    test = test === 'grasp' || test === 'place' ? test : null;
    const filled = order();
    if (!filled.length && test !== 'grasp') { toast('Asigna al menos una semilla a una casilla.'); return; }
    const dropZ = dropHeightM();
    if (dropZ === null) { toast('La altura al soltar debe estar entre ' + DROP_RANGE_CM[0] + ' y ' + DROP_RANGE_CM[1] + ' cm.'); return; }
    if (test === 'grasp' && !SEEDS[selected]) { toast('Selecciona una semilla: el robot coge de la caja de su color.'); return; }
    // grasp: no cell is visited, the colour is the selected seed's; place: only the first filled cell
    const queue = test === 'grasp' ? [] : test === 'place' ? filled.slice(0, 1) : filled;
    run = {
      test,
      queue,
      state: Object.fromEntries(queue.map(i => [i, 'pending'])),
      mode: 'robot',
      detail: 'Enviando el plan…',
      finished: false,
      ws: null,
      timer: null,
    };
    $('trayActions').hidden = true;
    $('runPanel').hidden = false;
    $('mapa-semillero').classList.add('running');
    document.body.classList.add('running');
    measureDock();
    setMode('Conectando…', false);
    renderRun();

    let plan = test === 'grasp' ? buildGraspPlan() : buildPlan(queue);
    if (plan) plan = { ...plan, mode: test || 'full', drop_z: dropZ };
    if (!plan) {
      // No pixel centres: a real robot could not place anything. Only simulate when
      // there is no backend to talk to in the first place.
      let reachable = false;
      try { reachable = (await window.smartseedBackend.fetch('/robot/status', {}, 1500)).ok; } catch (e) { /* offline */ }
      if (reachable) {
        toast('Escanea el semillero con la cámara antes de sembrar: el robot necesita la posición de cada hueco.');
        closeRun();
        return;
      }
      startDemo('Sin robot ni escaneo: se muestra la siembra simulada.');
      return;
    }

    let res = null, offline = false;
    try {
      res = await window.smartseedBackend.fetch('/plan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(plan),
      }, 8000);
    } catch (e) { offline = true; }

    if (!run) return;  // stopped while the request was in flight
    if (offline) { startDemo('Sin backend del robot: se muestra la ' + (test ? 'prueba' : 'siembra') + ' simulada.'); return; }

    if (!res.ok) {
      let body = {};
      try { body = await res.json(); } catch (e) { /* no JSON body */ }
      toast('No se puede ' + (test ? 'probar' : 'sembrar') + ': ' + refusalText(body, res.status));
      closeRun();
      return;
    }

    run.mode = 'robot';
    run.detail = 'Plan enviado al robot';
    listenProgress();
    labelRobotMode();
    renderRun();
  }

  async function stopRun() {
    if (!run) return;
    if (run.finished) { closeRun(); return; }
    clearTimeout(run.timer);
    if (run.mode === 'robot') {
      try { await window.smartseedBackend.fetch('/stop', { method: 'POST' }); }
      catch (e) { /* the WebSocket close will report it */ }
    }
    finishRun('Siembra detenida.', 'Parada solicitada');
  }

  // ── Palette ────────────────────────────────────────────────────────────────
  // Written twice from the same markup: the desktop sidebar and the phone dock.

  const isDesktop = () => !!(window.matchMedia && window.matchMedia('(min-width: 900px)').matches);

  // `preview` renders the same tile as a plain, inert box for the modal.
  function seedTileHtml(m, on, preview) {
    const style = '--box:' + m.strong + ';--box-tint:' + m.tint + ';--box-edge:' + m.edge;
    const tag = preview ? 'div' : 'button';
    return '<' + tag + (preview ? '' : ' type="button" data-seed="' + m.id + '" aria-pressed="' + on + '" title="' +
      esc(m.label + ' · caja ' + m.boxLabel) + '"' + (isDesktop() ? ' draggable="true"' : '')) +
      ' class="seed' + (on ? ' selected' : '') + '" style="' + style + '">' +
      '<span class="seed-check" aria-hidden="true"><svg class="ic"><use href="#i-check"/></svg></span>' +
      '<span class="seed-tile" aria-hidden="true">' + esc(m.emoji) + '</span>' +
      '<span class="seed-text"><span class="seed-name">' + esc(m.label) + '</span>' +
      '<span class="seed-box"><i class="box-dot"></i>Caja ' + esc(m.boxLabel) + '</span></span></' + tag + '>';
  }

  function renderPalette() {
    const html = Object.values(SEEDS).map(m =>
      '<div class="seed-item">' + seedTileHtml(m, m.id === selected) +
      '<button type="button" class="seed-edit" data-edit-seed="' + m.id + '" aria-label="Editar ' + esc(m.label) + '"' +
      ' title="Editar o borrar ' + esc(m.label) + '"><svg class="ic" aria-hidden="true"><use href="#i-edit"/></svg></button></div>').join('') +
      '<div class="seed-item seed-item-add"><button type="button" class="seed-add" data-add-seed title="Añadir una semilla nueva">' +
      '<span class="seed-tile" aria-hidden="true"><svg class="ic"><use href="#i-plus"/></svg></span>' +
      '<span class="seed-text"><span class="seed-name">Nueva<span class="seed-name-long"> semilla</span></span><span class="seed-box">Nombre, emoji y color</span></span></button></div>';
    ['seedSidebar', 'seedMobile'].forEach(id => { $(id).querySelector('.seed-grid').innerHTML = html; });
  }

  // Everything that shows seeds, after the list changed.
  function refreshSeeds() {
    if (!SEEDS[selected]) selected = Object.keys(SEEDS)[0] || null;
    renderPalette();
    renderBoxLegend();
    renderLegend();
    renderTray();
  }

  ['seedSidebar', 'seedMobile'].forEach(id => {
    const root = $(id);
    root.addEventListener('click', e => {
      const edit = e.target.closest('[data-edit-seed]');
      if (edit) { openSeedModal(edit.dataset.editSeed, edit); return; }
      const add = e.target.closest('[data-add-seed]');
      if (add) { openSeedModal(null, add); return; }
      const tile = e.target.closest('.seed');
      if (tile) selectSeed(tile.dataset.seed);
    });
    root.addEventListener('dragstart', e => {
      const tile = e.target.closest && e.target.closest('.seed');
      if (!tile) return;
      selectSeed(tile.dataset.seed);
      e.dataTransfer.setData('text/plain', tile.dataset.seed);
      e.dataTransfer.effectAllowed = 'copy';
    });
  });

  const droppedSeed = e => {
    const raw = e.dataTransfer ? e.dataTransfer.getData('text/plain') : '';
    return SEEDS[raw] ? raw : selected;
  };

  document.querySelectorAll('[data-fill-all]').forEach(slot => {
    slot.setAttribute('aria-label', 'Rellenar todo el mapa con la variedad seleccionada');
    slot.addEventListener('click', () => fillAll(selected));
    slot.addEventListener('dragover', e => {
      e.preventDefault();
      slot.classList.add('drop-target');
      if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy';
    });
    slot.addEventListener('dragleave', () => slot.classList.remove('drop-target'));
    slot.addEventListener('drop', e => {
      e.preventDefault();
      slot.classList.remove('drop-target');
      const key = droppedSeed(e);
      selectSeed(key);
      fillAll(key);
    });
  });

  // ── Seed modal ─────────────────────────────────────────────────────────────
  // One dialog for "Nueva semilla" and for editing; delete lives in edit mode.

  const modalEl = $('seedModal');
  const form = $('seedForm');
  const draft = { id: null, emoji: '', color: '' };
  let modalScope = null;          // the palette (sidebar or dock) that opened the modal

  const optionBtn = (cls, attrs, inner) => '<button type="button" role="radio" class="' + cls + '" ' + attrs + '>' + inner + '</button>';

  function usedColors() {
    const used = {};
    Object.values(SEEDS).forEach(m => { if (m.id !== draft.id) used[m.box] = m.label; });
    return used;
  }

  function renderPickers() {
    const used = usedColors();
    $('seedEmojiGrid').innerHTML = EMOJIS.map(em =>
      optionBtn('emoji-opt', 'data-emoji="' + em + '" aria-checked="' + (draft.emoji === em) + '" aria-label="' + em + '"', em)).join('');
    $('seedColorGrid').innerHTML = BOWL_COLORS.map(c => {
      const taken = used[c.id];
      const sh = shades(c.base);
      return optionBtn('color-opt' + (taken ? ' taken' : ''),
        'data-color="' + c.id + '" aria-checked="' + (draft.color === c.id) + '"' + (taken ? ' aria-disabled="true"' : '') +
        ' aria-label="' + c.label + (taken ? ', en uso por ' + esc(taken) : '') + '"' +
        (taken ? ' title="Ya lo usa ' + esc(taken) + ': cada color es una caja distinta."' : ''),
        '<i class="swatch" style="--sw:' + c.base + ';--sw-edge:' + sh.edge + '"></i><span>' + c.label + '</span>' +
        (taken ? '<small>' + esc(taken) + '</small>' : ''));
    }).join('');
    syncPickers();
  }

  // Marks the chosen options in place, so a keyboard user keeps the focus.
  function syncPickers() {
    $('seedEmojiGrid').querySelectorAll('[role="radio"]').forEach(o => o.setAttribute('aria-checked', String(o.dataset.emoji === draft.emoji)));
    $('seedColorGrid').querySelectorAll('[role="radio"]').forEach(o => o.setAttribute('aria-checked', String(o.dataset.color === draft.color)));
    syncRoving($('seedEmojiGrid'));
    syncRoving($('seedColorGrid'));
  }

  // Roving tabindex: one tab stop per group, arrows move inside it.
  function syncRoving(group) {
    const opts = [...group.querySelectorAll('[role="radio"]')];
    const on = opts.find(o => o.getAttribute('aria-checked') === 'true') || opts.find(o => o.getAttribute('aria-disabled') !== 'true');
    opts.forEach(o => { o.tabIndex = o === on ? 0 : -1; });
  }

  function renderPreview() {
    const name = $('seedName').value.trim();
    const base = draft.color ? bowlColor(draft.color) : { id: '', label: '', boxLabel: '', base: '#c6d3d0' };
    const m = {
      id: 'PREVIEW', label: name || 'Nombre', emoji: draft.emoji || '🌱',
      box: draft.color, boxLabel: base.boxLabel || '…', ...shades(base.base),
    };
    $('seedPreview').innerHTML = seedTileHtml(m, false, true);
    $('seedNameCount').textContent = $('seedName').value.length + ' / ' + MAX_NAME;
  }

  function setModalError(msg) {
    $('seedError').textContent = msg || '';
    $('seedName').setAttribute('aria-invalid', String(!!msg));
  }

  function setDraft(patch) {
    Object.assign(draft, patch);
    syncPickers();
    renderPreview();
  }

  function openSeedModal(id, opener) {
    if (id && run) { toast('Espera a que termine la siembra para editar semillas.'); return; }
    modalScope = (opener && opener.closest('#seedSidebar, #seedMobile')) || null;
    const m = id ? SEEDS[id] : null;
    draft.id = m ? m.id : null;
    draft.emoji = m ? m.emoji : '';
    $('seedName').value = m ? m.label : '';
    setModalError('');
    $('seedEmojiCustom').value = '';
    const free = BOWL_COLORS.find(c => !usedColors()[c.id]);
    draft.color = m ? m.box : (free ? free.id : '');
    $('seedModalTitle').textContent = m ? 'Editar semilla' : 'Nueva semilla';
    $('seedSave').textContent = m ? 'Guardar cambios' : 'Guardar';
    $('seedDelete').hidden = !m;
    renderPickers();
    renderPreview();
    modalEl.hidden = false;
    document.body.classList.add('modal-open');
    $('seedName').focus();
  }

  function closeSeedModal() {
    if (modalEl.hidden) return;
    modalEl.hidden = true;
    document.body.classList.remove('modal-open');
    // The palette was rebuilt behind the modal, so the opener is gone: find its twin.
    const target = modalScope && (draft.id && SEEDS[draft.id]
      ? modalScope.querySelector('[data-edit-seed="' + draft.id + '"]')
      : modalScope.querySelector('[data-add-seed]'));
    modalScope = null;
    if (target) target.focus();
  }

  // The first grapheme of what was typed or pasted, when it is an emoji.
  function firstEmoji(text) {
    const v = String(text || '').trim();
    if (!v) return '';
    const first = window.Intl && Intl.Segmenter
      ? [...new Intl.Segmenter(undefined, { granularity: 'grapheme' }).segment(v)][0].segment
      : [...v][0];
    return /\p{Extended_Pictographic}/u.test(first) ? first : '';
  }

  function saveSeedFromModal() {
    const name = $('seedName').value.trim();
    if (!name) { setModalError('Escribe un nombre para la semilla.'); $('seedName').focus(); return; }
    if (!draft.emoji) { setModalError('Elige un emoji.'); return; }
    if (!draft.color) { setModalError('Elige el color de la caja.'); return; }
    if (usedColors()[draft.color]) { setModalError('Ese color ya lo usa otra semilla.'); return; }
    const editing = !!draft.id;
    const id = draft.id || newSeedId();
    const list = seedList();
    const entry = { id, name: name.slice(0, MAX_NAME), emoji: draft.emoji, color: draft.color };
    if (editing) list[list.findIndex(x => x.id === id)] = entry; else list.push(entry);
    setSeeds(list);
    saveSeeds();
    if (!editing) selected = id;
    refreshSeeds();
    closeSeedModal();
    toast('Semilla «' + entry.name + '» ' + (editing ? 'actualizada.' : 'creada.'));
  }

  function deleteSeedFromModal() {
    const m = SEEDS[draft.id];
    if (!m) return;
    if (run) { toast('Espera a que termine la siembra para borrar semillas.'); return; }
    if (Object.keys(SEEDS).length < 2) { setModalError('Debe quedar al menos una semilla.'); return; }
    const used = cells.filter(k => k === m.id).length;
    const ask = used
      ? '«' + m.label + '» está en ' + used + (used === 1 ? ' hueco' : ' huecos') + ' del mapa. Si la borras, esos huecos se vaciarán. ¿Borrar la semilla?'
      : '¿Borrar la semilla «' + m.label + '»?';
    if (!window.confirm(ask)) return;
    const list = seedList().filter(x => x.id !== m.id);
    cells = cells.map(k => (k === m.id ? null : k));
    saveLayout();
    setSeeds(list);
    saveSeeds();
    refreshSeeds();
    closeSeedModal();
    toast('Semilla «' + m.label + '» borrada' + (used ? ' y ' + used + (used === 1 ? ' hueco vaciado.' : ' huecos vaciados.') : '.'));
  }

  function moveRoving(e, group) {
    const keys = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 };
    if (!(e.key in keys)) return;
    const opts = [...group.querySelectorAll('[role="radio"]')];
    const at = opts.indexOf(document.activeElement);
    if (at < 0) return;
    e.preventDefault();
    const next = opts[(at + keys[e.key] + opts.length) % opts.length];
    next.focus();
    next.click();
  }

  $('seedEmojiGrid').addEventListener('click', e => {
    const b = e.target.closest('[data-emoji]');
    if (b) { b.focus(); $('seedEmojiCustom').value = ''; setDraft({ emoji: b.dataset.emoji }); }
  });
  $('seedColorGrid').addEventListener('click', e => {
    const b = e.target.closest('[data-color]');
    if (!b) return;
    b.focus();  // macOS browsers do not focus a button on click
    if (b.getAttribute('aria-disabled') === 'true') { setModalError('Ese color ya lo usa «' + usedColors()[b.dataset.color] + '»: cada color es una caja distinta.'); return; }
    setModalError('');
    setDraft({ color: b.dataset.color });
  });
  $('seedEmojiGrid').addEventListener('keydown', e => moveRoving(e, $('seedEmojiGrid')));
  $('seedColorGrid').addEventListener('keydown', e => moveRoving(e, $('seedColorGrid')));
  $('seedEmojiCustom').addEventListener('input', e => {
    const em = firstEmoji(e.target.value);
    if (e.target.value.trim() && !em) { setModalError('Pega un emoji, por ejemplo 🥑.'); return; }
    setModalError('');
    if (em) setDraft({ emoji: em });
  });
  $('seedName').addEventListener('input', () => { setModalError(''); renderPreview(); });
  form.addEventListener('submit', e => { e.preventDefault(); saveSeedFromModal(); });
  $('seedCancel').addEventListener('click', closeSeedModal);
  $('seedCancelX').addEventListener('click', closeSeedModal);
  $('seedDelete').addEventListener('click', deleteSeedFromModal);
  modalEl.addEventListener('mousedown', e => { if (e.target.matches('[data-modal-close]')) closeSeedModal(); });

  // Esc closes; Tab stays inside the dialog.
  document.addEventListener('keydown', e => {
    if (modalEl.hidden) return;
    if (e.key === 'Escape') { e.preventDefault(); closeSeedModal(); return; }
    if (e.key !== 'Tab') return;
    const items = [...modalEl.querySelectorAll('input, button, [tabindex]')]
      .filter(el => !el.disabled && !el.hidden && el.tabIndex >= 0 && !el.closest('[hidden]'));
    if (!items.length) return;
    const first = items[0], last = items[items.length - 1];
    const outside = !modalEl.contains(document.activeElement);
    if (e.shiftKey && (document.activeElement === first || outside)) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && (document.activeElement === last || outside)) { e.preventDefault(); first.focus(); }
  });

  // ── Tray wiring ────────────────────────────────────────────────────────────

  const grid = $('trayGrid');

  grid.addEventListener('click', e => {
    if (run) return;
    // A mobile drop already assigned this cell on pointerup; swallow the click after it.
    if (mobileDropAt && Date.now() - mobileDropAt < 700) { mobileDropAt = 0; e.preventDefault(); return; }
    const clear = e.target.closest('[data-clear-cell]');
    if (clear) { setCell(Number(clear.dataset.clearCell), null); return; }
    const cell = e.target.closest('[data-cell]');
    if (!cell) return;
    const i = Number(cell.dataset.cell);
    setCell(i, cells[i] === selected ? null : selected);
  });

  grid.addEventListener('dragover', e => {
    const cell = e.target.closest('[data-cell]');
    if (!cell || run) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'copy';
    cell.classList.add('drop-target');
  });

  grid.addEventListener('dragleave', e => {
    const cell = e.target.closest('[data-cell]');
    if (cell && !cell.contains(e.relatedTarget)) cell.classList.remove('drop-target');
  });

  grid.addEventListener('drop', e => {
    const cell = e.target.closest('[data-cell]');
    if (!cell || run) return;
    e.preventDefault();
    cell.classList.remove('drop-target');
    setCell(Number(cell.dataset.cell), droppedSeed(e));
  });

  // On a phone, dragging a palette tile onto a cell ends as a pointerup over the cell.
  document.addEventListener('pointerup', e => {
    if (run || isDesktop() || !e.target.closest) return;
    const cell = e.target.closest('[data-cell]');
    if (!cell) return;
    setCell(Number(cell.dataset.cell), selected);
    mobileDropAt = Date.now();
  });

  $('clearTrayBtn').addEventListener('click', () => {
    if (run) return;
    cells = cells.map(() => null);
    saveLayout();
    cells.forEach((_, i) => paintCell(i));
    updateCounts();
    toast('Mapa vaciado.');
  });

  $('mapPlantBtn').addEventListener('click', () => startRun());
  $('testGraspBtn').addEventListener('click', () => startRun('grasp'));
  $('testPlaceBtn').addEventListener('click', () => startRun('place'));
  $('settingsBtn').addEventListener('click', () => {
    const open = $('settingsPanel').hidden;
    $('settingsPanel').hidden = !open;
    $('settingsBtn').setAttribute('aria-expanded', String(open));
  });
  try { const saved = localStorage.getItem(DROP_KEY); if (saved !== null && Number(saved) > 0) $('dropHeight').value = saved; }
  catch (e) { /* storage blocked: keep the default */ }
  $('dropHeight').addEventListener('input', () => {
    try { localStorage.setItem(DROP_KEY, $('dropHeight').value); } catch (e) { /* storage full or blocked */ }
  });
  $('stopRunBtn').addEventListener('click', stopRun);
  $('saveTemplateBtn').addEventListener('click', saveTemplate);
  $('deleteTemplateBtn').addEventListener('click', deleteTemplate);
  $('templateSelect').addEventListener('change', e => {
    if (run) { e.target.value = ''; return; }
    if (e.target.value) applyTemplate(e.target.value);
    else renderTemplates('');
  });

  // Manual fallback, only reachable when the browser has no live camera.
  $('createCustomTrayBtn').addEventListener('click', () => {
    if (window.smartseedScan && window.smartseedScan.cameraActive()) return;  // scanner.js owns the button then
    openApp($('customRows').value, $('customCols').value);
    toast('Mapa creado: ' + rows + ' × ' + cols + ' (' + total() + ' huecos).');
  });

  // ── Mobile dock height ─────────────────────────────────────────────────────
  // The dock is fixed over the page; --dock-h keeps the padding, the tray size and the
  // toast clear of it, whatever the palette ends up measuring.
  const dock = $('mobileSeedDock');
  const measureDock = () =>
    document.documentElement.style.setProperty('--dock-h', (dock.hidden ? 0 : dock.offsetHeight) + 'px');
  if (window.ResizeObserver) new ResizeObserver(measureDock).observe(dock);
  window.addEventListener('resize', measureDock);

  // ── Boot ───────────────────────────────────────────────────────────────────

  setSeeds(loadSeeds());
  selected = Object.keys(SEEDS)[0] || null;

  const saved = normalizeLayout(readJSON(LAYOUT_KEY, null) ?? readJSON(LEGACY_LAYOUT_KEY, null));
  if (saved && saved.rows && saved.cols) {
    rows = saved.rows;
    cols = saved.cols;
    cells = Array.from({ length: rows * cols }, (_, i) => saved.cells[i] || null);
  } else if (saved) {
    cells = Array.from({ length: total() }, (_, i) => saved.cells[i] || null);
  } else {
    cells = Array(total()).fill(null);
  }
  $('customRows').value = rows;
  $('customCols').value = cols;

  renderTemplates('');
  refreshSeeds();
  selectSeed(selected);

  window.smartseedApp = {
    openApp,
    resizeTray: (r, c) => { if (!run && (r !== rows || c !== cols)) setSize(r, c); },
    dims: () => ({ rows, cols }),
    isRunning: () => !!run,
    seedCount: filledCount,
    seeds: seedList,
  };
})();
