# SmartSeed 🌱 — seeding interface

The project's interface. The UI is in Spanish by design, with no framework and no build
step: open `index.html` and it runs. It is the root of the GitHub Pages site.

The full idea and the plan are in [guide.md](../guide.md); this file only covers what is in
this folder.

## What it does

1. **Scan.** On open, the page asks you to point the camera at the seed tray (button
   **Escanear**, "Scan"). It locates the tray and its cells (ArUco markers, depth, or the
   vision model; see `scanner.js`) and draws the cell map **over the live image**.
2. **Design.** A cinema-seat-style map: each cell is a square, painted the color of the box
   its seed will come from. The varieties are yours: "+" opens the modal (name, emoji and
   box color, one per seed; the pencil on each one edits or deletes it). Four come by
   default. Drag a variety from the palette or tap the squares. "Rellenar todo el mapa"
   ("Fill the whole map") puts the selected variety in every cell.
3. **Save.** The design is saved as a named template, and the last formula used is
   restored automatically next time.
4. **Seed.** The button **Sembrar** ("Seed") sends the plan to the local backend and
   paints on the same map which cell is being seeded, which are done and which have
   failed, with a **Parar el robot** ("Stop the robot") button.

## Files

| File | What it is |
|---|---|
| `index.html` | Markup: scan screen, tray map, seeding panel |
| `app.css` | All the styles, a single cascade |
| `app.js` | Palette, map, templates and the seeding run against the backend |
| `scanner.js` | Live camera, overlaid grid and tray localization |
| `vendor/` | `js-aruco2` (`cv.js`, `aruco.js`), served from here |
| `fonts/` | DM Sans and Manrope, local |

**Nothing is loaded from a CDN.** At the event the wifi may fail, and marker detection is
the most reliable way to locate the tray: if `aruco.js` came from the internet, it would
disappear without warning. If you add a dependency, keep it here too.

## Connection to the robot

Only the laptop connected to the arm can reach the backend
(`backend/smartseed_robot`, `http://localhost:8000`). The web page published on Pages
cannot reach it, so seeding is simulated and **MODO DEMO** ("DEMO MODE") is shown on screen.

- `POST /plan` — `image_size` and one `{cell_index, row, col, color, u, v}` per cell with a
  seed. `u` and `v` are pixels of the camera frame.
  Optional: `mode` (`full` | `grasp` | `place`) and `drop_z` (m); they are sent by
  **Ajustes** ("Settings") → "Probar coger (ACT)" ("Test grasp (ACT)"), "Probar dejar"
  ("Test release") and "Altura al soltar" ("Release height").
- `WS /robot/progress` — `plan_started`, `cell_started`, `cell_done`, `cell_failed`,
  `finished`, `stopped`, `error`.
- `POST /stop` — stops the sequence; the arm stays where it is, with torque on.

The exact format and the event table are in
[guide.md § Plan format](../guide.md#plan-format).

If the backend is at another address, in the browser console:

```js
localStorage.setItem('smartseed.backendUrl', 'http://IP:8000')
```

A plan that the backend rejects (not calibrated, cell out of reach, seeding in progress)
shows the reason and animates **nothing**: it must never look like a successful seeding.

## Stored data

Everything is in the browser's `localStorage`; nothing leaves the machine:

| Key | What it stores |
|---|---|
| `smartseed.lastLayout` | Last formula used (`{rows, cols, cells}`) |
| `smartseed.templates` | Named templates |
| `smartseed.seeds` | Seeds (`[{id, name, emoji, color}]`); `color` is the box id that `/plan` receives |
| `smartseed.cameraId` | Last camera chosen |
| `smartseed.scanCorners` | Tray corners adjusted by hand |
| `smartseed.backendUrl` | Backend address, if it is not the default one |

The variety keys (`TOMATE`, `PIMIENTO`, `LIMON`, `BERENJENAS`) are stored inside the saved
designs: do not change them without migrating what is stored.

## Testing

```bash
cd ../tests/web
npm install     # first time only
npm test        # jsdom: no backend (demo mode) and with the simulated robot
CHROME_PATH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" npm run render
```

`npm run render` opens the page in a real Chromium at desktop and mobile size, saves
screenshots to `tests/web/shots/` and fails on console errors or horizontal overflow.
