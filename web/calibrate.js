// Camera-robot calibration from the browser. The user drags the gripper tip by hand over
// a point of the tray (torque off), clicks that point on the camera image, and repeats;
// the backend pairs each click with the tool position from forward kinematics and fits
// the homography. Clicks use the same pixel frame as the plan cells: video resolution.
(() => {
  const q = id => document.getElementById(id);
  const notify = msg => (window.smartseedToast ? window.smartseedToast(msg) : console.log(msg));
  const backend = window.smartseedBackend;
  const MARK_RADIUS = 7;

  const stage = document.querySelector('.scan-stage');
  const video = q('cameraPreview');
  const canvas = q('calOverlay');
  const ctx = canvas.getContext('2d');
  const panel = q('calPanel');
  let active = false;
  let points = []; // normalised [0..1] click positions, kept for the markers
  let fitted = false;

  const frame = () => [video.videoWidth, video.videoHeight];

  async function call(path, method = 'GET', body) {
    const opts = { method };
    if (body) { opts.headers = { 'Content-Type': 'application/json' }; opts.body = JSON.stringify(body); }
    const res = await backend.fetch(path, opts);
    let data = null;
    try { data = await res.json(); } catch (e) { /* empty body */ }
    if (!res.ok) throw new Error((data && data.detail) || 'el robot ha respondido HTTP ' + res.status);
    return data;
  }

  function draw() {
    if (!ctx) return; // no 2D canvas (headless tests)
    const rect = canvas.getBoundingClientRect();
    if (canvas.width !== Math.round(rect.width) || canvas.height !== Math.round(rect.height)) {
      canvas.width = Math.round(rect.width);
      canvas.height = Math.round(rect.height);
    }
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.lineWidth = 2;
    points.forEach(([x, y], i) => {
      const px = x * canvas.width, py = y * canvas.height;
      ctx.strokeStyle = fitted ? '#7ddc5a' : '#ffd23f';
      ctx.fillStyle = '#ffffffcc';
      ctx.beginPath(); ctx.arc(px, py, MARK_RADIUS, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
      ctx.fillStyle = '#122d24';
      ctx.font = 'bold 10px sans-serif';
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.fillText(String(i + 1), px, py);
    });
  }

  function render() {
    q('calCount').textContent = points.length + (points.length === 1 ? ' punto' : ' puntos') +
      (points.length < 4 ? ' (mínimo 4)' : '');
    q('calFitBtn').disabled = points.length < 4;
    draw();
  }

  async function refreshStatus() {
    const line = q('calStatus');
    try {
      const st = await call('/robot/status');
      line.textContent = (st.robot === 'real' ? 'Robot real' : 'Robot simulado (fake)') +
        ' · par ' + (st.torque ? 'activado' : 'desactivado') +
        ' · ' + (st.calibrated ? 'calibrado' : 'sin calibrar') +
        ' · políticas ACT: ' + ((st.policies || []).join(', ') || 'ninguna');
    } catch (e) { line.textContent = 'Sin conexión con el robot (¿está arrancado el backend?)'; }
  }

  async function loadPoints() {
    try {
      const cal = await call('/robot/calibration');
      const [w, h] = cal.image_size || frame();
      points = cal.points.map(p => [p.u / w, p.v / h]);
      fitted = cal.fitted;
    } catch (e) { points = []; fitted = false; }
    render();
  }

  async function open() {
    if (window.smartseedApp.isRunning()) { notify('Para el robot antes de calibrar.'); return; }
    if (!video.videoWidth) { notify('Espera a que la cámara muestre imagen.'); return; }
    active = true;
    panel.hidden = false;
    stage.classList.add('calibrating');
    q('calibrateBtn').setAttribute('aria-pressed', 'true');
    await Promise.all([loadPoints(), refreshStatus()]);
  }

  function close() {
    active = false;
    panel.hidden = true;
    stage.classList.remove('calibrating');
    q('calibrateBtn').setAttribute('aria-pressed', 'false');
    if (ctx) ctx.clearRect(0, 0, canvas.width, canvas.height);
  }

  const act = (label, fn) => async e => {
    try { await fn(e); } catch (e) { notify(label + ': ' + e.message); }
    refreshStatus();
  };

  canvas.addEventListener('pointerdown', act('No se ha podido añadir el punto', async e => {
    if (!active) return;
    const rect = canvas.getBoundingClientRect();
    const nx = (e.clientX - rect.left) / rect.width, ny = (e.clientY - rect.top) / rect.height;
    const [w, h] = frame();
    await call('/robot/calibration/points', 'POST', { u: nx * w, v: ny * h, image_size: [w, h] });
    points.push([nx, ny]);
    fitted = false;
    render();
  }));

  q('calibrateBtn').addEventListener('click', () => (active ? close() : open()));
  q('calCloseBtn').addEventListener('click', close);
  q('calTorqueOffBtn').addEventListener('click', act('No se ha podido soltar el brazo', async () => {
    await call('/robot/torque-off', 'POST');
    notify('Brazo suelto: muévelo a mano.');
  }));
  q('calTorqueOnBtn').addEventListener('click', act('No se ha podido bloquear el brazo', async () => {
    await call('/robot/torque-on', 'POST');
    notify('Brazo bloqueado.');
  }));
  q('calFitBtn').addEventListener('click', act('No se ha podido ajustar', async () => {
    const st = await call('/robot/calibration/fit', 'POST');
    fitted = true;
    q('calResult').textContent = 'Error medio ' + st.mean_error_mm.toFixed(1) + ' mm · máximo ' + st.max_error_mm.toFixed(1) + ' mm (' + st.n + ' puntos)';
    render();
  }));
  q('calClearBtn').addEventListener('click', act('No se han podido borrar los puntos', async () => {
    await call('/robot/calibration/points', 'DELETE');
    points = [];
    fitted = false;
    q('calResult').textContent = '';
    render();
  }));
  q('calSaveStartBtn').addEventListener('click', act('No se ha podido guardar la pose de inicio', async () => {
    await call('/robot/poses/act_start', 'POST');
    notify('Pose de inicio guardada con la posición actual del brazo.');
  }));
  q('calSaveHomeBtn').addEventListener('click', act('No se ha podido guardar home', async () => {
    await call('/robot/poses/home', 'POST');
    notify('Home guardado con la posición actual del brazo.');
  }));

  // Without a camera there is nothing to click on.
  q('closeCameraBtn').addEventListener('click', close);
  window.addEventListener('resize', () => active && draw());
  window.smartseedCalibration = { isActive: () => active };
})();
