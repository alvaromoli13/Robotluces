// Live tray scanner: camera picker, real-time grid overlay and tray localisation.
// Sources, by priority: ArUco markers (ARUCO_MIP_36h12; id 0 top-left, 1 top-right,
// 2 bottom-right, 3 bottom-left) > local vision backend (backend/, OWLv2 + OpenCV, gives
// corners and rows x cols) > corners dragged by hand. Without backend the page still works.
(() => {
  const q = id => document.getElementById(id);
  const notify = msg => (typeof toast === 'function' ? toast(msg) : console.log(msg));
  const CAM_KEY = 'smartseed.cameraId';
  const CORNERS_KEY = 'smartseed.scanCorners';
  const DETECT_EVERY_MS = 100;
  const DETECT_WIDTH = 640;
  const HANDLE_RADIUS = 14;
  const MODEL_EVERY_MS = 1000;
  const HEALTH_RETRY_MS = 5000;
  const BACKEND_URL = (() => {
    try { return localStorage.getItem('smartseed.backendUrl') || 'http://localhost:8000'; } catch (e) { return 'http://localhost:8000'; }
  })();

  const video = q('cameraPreview');
  const overlay = q('scanOverlay');
  const ctx = overlay.getContext('2d');
  const work = document.createElement('canvas');
  const workCtx = work.getContext('2d', { willReadFrequently: true });
  const detector = window.AR ? new AR.Detector({ dictionaryName: 'ARUCO_MIP_36h12' }) : null;

  let stream = null;
  let rafId = 0;
  let lastDetect = 0;
  let locked = false;
  let markersSeen = 0;
  let dragIndex = -1;
  let backendOk = false;
  let lastHealth = -Infinity;
  let lastModel = 0;
  let modelBusy = false;
  let modelFound = false;
  let userSetSize = false;
  // Normalized (0..1) corners: top-left, top-right, bottom-right, bottom-left.
  let corners = loadCorners();

  function loadCorners() {
    try {
      const saved = JSON.parse(localStorage.getItem(CORNERS_KEY));
      if (Array.isArray(saved) && saved.length === 4) return saved;
    } catch (e) { /* storage unavailable: fall back to default */ }
    return [[0.15, 0.15], [0.85, 0.15], [0.85, 0.85], [0.15, 0.85]];
  }

  function saveCorners() {
    try { localStorage.setItem(CORNERS_KEY, JSON.stringify(corners)); } catch (e) { /* ignore */ }
  }

  const rows = () => Math.max(1, Math.min(20, Math.floor(Number(q('customRows').value) || 1)));
  const cols = () => Math.max(1, Math.min(20, Math.floor(Number(q('customCols').value) || 1)));

  // Bilinear point inside the tray quad; u along columns, v along rows (0..1).
  function quadPoint(u, v) {
    const [tl, tr, br, bl] = corners;
    const top = [tl[0] + (tr[0] - tl[0]) * u, tl[1] + (tr[1] - tl[1]) * u];
    const bot = [bl[0] + (br[0] - bl[0]) * u, bl[1] + (br[1] - bl[1]) * u];
    return [top[0] + (bot[0] - top[0]) * v, top[1] + (bot[1] - top[1]) * v];
  }

  // Cell centers in video pixels, row by row. Exposed for the robot backend.
  function cellCenters() {
    const w = video.videoWidth, h = video.videoHeight, r = rows(), c = cols();
    const out = [];
    for (let i = 0; i < r; i++) for (let j = 0; j < c; j++) {
      const [x, y] = quadPoint((j + 0.5) / c, (i + 0.5) / r);
      out.push({ row: i, col: j, x: Math.round(x * w), y: Math.round(y * h) });
    }
    return out;
  }

  function stopCamera() {
    cancelAnimationFrame(rafId);
    if (stream) { stream.getTracks().forEach(t => t.stop()); stream = null; }
    video.srcObject = null;
  }

  async function openCamera(id) {
    stopCamera();
    stream = await navigator.mediaDevices.getUserMedia({ video: id ? { deviceId: { exact: id } } : true, audio: false });
    video.srcObject = stream;
    const active = stream.getVideoTracks()[0].getSettings().deviceId;
    if (active) { try { localStorage.setItem(CAM_KEY, active); } catch (e) { /* ignore */ } }
    rafId = requestAnimationFrame(loop);
    return active;
  }

  async function listCameras(selected) {
    const cams = (await navigator.mediaDevices.enumerateDevices()).filter(d => d.kind === 'videoinput');
    const sel = q('cameraSelect');
    sel.innerHTML = '';
    cams.forEach((c, i) => {
      const o = document.createElement('option');
      o.value = c.deviceId;
      o.textContent = c.label || 'Cámara ' + (i + 1);
      o.selected = c.deviceId === selected;
      sel.appendChild(o);
    });
  }

  function detectMarkers() {
    if (!detector || !video.videoWidth) return;
    const scale = Math.min(1, DETECT_WIDTH / video.videoWidth);
    work.width = Math.round(video.videoWidth * scale);
    work.height = Math.round(video.videoHeight * scale);
    workCtx.drawImage(video, 0, 0, work.width, work.height);
    const markers = detector.detect(workCtx.getImageData(0, 0, work.width, work.height));
    const byId = {};
    markers.forEach(m => {
      if (m.id > 3) return;
      const cx = m.corners.reduce((s, p) => s + p.x, 0) / 4 / work.width;
      const cy = m.corners.reduce((s, p) => s + p.y, 0) / 4 / work.height;
      byId[m.id] = [cx, cy];
    });
    markersSeen = Object.keys(byId).length;
    locked = markersSeen === 4;
    if (locked && dragIndex < 0) { corners = [byId[0], byId[1], byId[2], byId[3]]; saveCorners(); }
  }

  async function fetchWithTimeout(url, opts, ms) {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), ms);
    try { return await fetch(url, { ...opts, signal: ctrl.signal }); } finally { clearTimeout(timer); }
  }

  async function checkBackend() {
    try {
      const res = await fetchWithTimeout(BACKEND_URL + '/health', {}, 1500);
      backendOk = res.ok;
    } catch (e) { backendOk = false; }
  }

  async function askModel() {
    modelBusy = true;
    try {
      work.width = video.videoWidth; work.height = video.videoHeight;
      workCtx.drawImage(video, 0, 0);
      const blob = await new Promise(resolve => work.toBlob(resolve, 'image/jpeg', 0.85));
      const form = new FormData();
      form.append('image', blob, 'frame.jpg');
      const res = await fetchWithTimeout(BACKEND_URL + '/vision/tray', { method: 'POST', body: form }, 8000);
      if (!res.ok) throw new Error('HTTP ' + res.status);
      const data = await res.json();
      modelFound = !!data.found;
      // ArUco or a drag may have taken over while the request was in flight.
      if (data.found && !locked && dragIndex < 0) {
        corners = data.corners.map(p => p.slice());
        saveCorners();
        if (!userSetSize && data.rows && data.cols) {
          q('customRows').value = data.rows;
          q('customCols').value = data.cols;
        }
      }
    } catch (e) {
      backendOk = false;
      modelFound = false;
    } finally {
      modelBusy = false;
    }
  }

  function statusText(r, c) {
    if (locked) return 'Bandeja localizada con los 4 marcadores · ' + r + ' × ' + c + ' huecos';
    if (backendOk && modelFound) return 'Bandeja detectada por el modelo de visión · ' + r + ' × ' + c + ' huecos · puedes corregir filas, columnas o esquinas';
    const markers = detector ? 'Marcadores detectados: ' + markersSeen + '/4 · ' : '';
    const model = backendOk ? 'Modelo de visión buscando la bandeja… · ' : 'Modelo de visión no disponible (arranca backend/) · ';
    return markers + model + 'Arrastra las esquinas amarillas hasta las esquinas de la bandeja';
  }

  function draw() {
    const rect = video.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    if (overlay.width !== Math.round(rect.width * dpr) || overlay.height !== Math.round(rect.height * dpr)) {
      overlay.width = Math.round(rect.width * dpr);
      overlay.height = Math.round(rect.height * dpr);
    }
    const W = overlay.width, H = overlay.height, r = rows(), c = cols();
    const px = ([x, y]) => [x * W, y * H];
    ctx.clearRect(0, 0, W, H);
    ctx.lineWidth = 2 * dpr;
    ctx.strokeStyle = locked ? '#7ddc5a' : (backendOk && modelFound ? '#5ac8f0' : '#ffd23f');
    ctx.beginPath();
    for (let j = 0; j <= c; j++) {
      ctx.moveTo(...px(quadPoint(j / c, 0)));
      ctx.lineTo(...px(quadPoint(j / c, 1)));
    }
    for (let i = 0; i <= r; i++) {
      ctx.moveTo(...px(quadPoint(0, i / r)));
      ctx.lineTo(...px(quadPoint(1, i / r)));
    }
    ctx.stroke();
    ctx.fillStyle = ctx.strokeStyle;
    for (let i = 0; i < r; i++) for (let j = 0; j < c; j++) {
      const [x, y] = px(quadPoint((j + 0.5) / c, (i + 0.5) / r));
      ctx.beginPath(); ctx.arc(x, y, 3 * dpr, 0, Math.PI * 2); ctx.fill();
    }
    if (!locked) {
      corners.forEach(p => {
        const [x, y] = px(p);
        ctx.beginPath(); ctx.arc(x, y, HANDLE_RADIUS * dpr * 0.6, 0, Math.PI * 2);
        ctx.fillStyle = '#ffffffcc'; ctx.fill(); ctx.stroke();
      });
    }
    q('scanStatus').textContent = statusText(r, c);
  }

  function loop(t) {
    if (!stream) return;
    if (t - lastDetect > DETECT_EVERY_MS) { lastDetect = t; detectMarkers(); }
    if (!backendOk && t - lastHealth > HEALTH_RETRY_MS) { lastHealth = t; checkBackend(); }
    if (backendOk && !locked && dragIndex < 0 && !modelBusy && video.videoWidth && t - lastModel > MODEL_EVERY_MS) {
      lastModel = t;
      askModel();
    }
    draw();
    rafId = requestAnimationFrame(loop);
  }

  function pointerPos(e) {
    const rect = overlay.getBoundingClientRect();
    return [(e.clientX - rect.left) / rect.width, (e.clientY - rect.top) / rect.height];
  }

  overlay.addEventListener('pointerdown', e => {
    if (locked) return;
    const [x, y] = pointerPos(e);
    const rect = overlay.getBoundingClientRect();
    let best = -1, bestDist = Infinity;
    corners.forEach(([cx, cy], i) => {
      const d = Math.hypot((cx - x) * rect.width, (cy - y) * rect.height);
      if (d < bestDist) { bestDist = d; best = i; }
    });
    if (bestDist <= HANDLE_RADIUS * 2) { dragIndex = best; overlay.setPointerCapture(e.pointerId); e.preventDefault(); }
  });
  overlay.addEventListener('pointermove', e => {
    if (dragIndex < 0) return;
    const [x, y] = pointerPos(e);
    corners[dragIndex] = [Math.min(1, Math.max(0, x)), Math.min(1, Math.max(0, y))];
  });
  const endDrag = () => { if (dragIndex >= 0) { dragIndex = -1; saveCorners(); } };
  overlay.addEventListener('pointerup', endDrag);
  overlay.addEventListener('pointercancel', endDrag);

  q('startScanBtn').addEventListener('click', async () => {
    if (!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia)) { q('cameraInput').click(); return; }
    let saved = null;
    try { saved = localStorage.getItem(CAM_KEY); } catch (e) { /* ignore */ }
    try {
      let active;
      try { active = await openCamera(saved); } catch (e) { if (!saved) throw e; active = await openCamera(null); }
      await listCameras(active);
      q('cameraPanel').hidden = false;
      q('customTrayForm').hidden = false;
      q('scanResult').hidden = true;
      q('startScanBtn').hidden = true;
    } catch (err) {
      notify('No se ha podido abrir la cámara: ' + (err.message || err.name));
      q('cameraInput').click();
    }
  });
  ['customRows', 'customCols'].forEach(id => q(id).addEventListener('input', () => { userSetSize = true; }));
  q('cameraSelect').addEventListener('change', e =>
    openCamera(e.target.value).catch(err => notify('No se ha podido abrir esa cámara: ' + (err.message || err.name))));
  q('closeCameraBtn').addEventListener('click', () => {
    stopCamera();
    q('cameraPanel').hidden = true;
    q('startScanBtn').hidden = false;
  });
  q('createCustomTrayBtn').addEventListener('click', () => {
    if (!stream) return;
    window.smartseedScan.lastLayout = { corners: corners.map(p => p.slice()), cells: cellCenters(), locked };
    stopCamera();
    q('cameraPanel').hidden = true;
    q('startScanBtn').hidden = false;
  });
  window.addEventListener('pagehide', stopCamera);

  window.smartseedScan = { cellCenters, get corners() { return corners; }, get locked() { return locked; }, lastLayout: null };
})();
