# SmartSeed 🌱 — interfaz de siembra

Interfaz del proyecto, en español, sin framework ni compilación: abre `index.html` y ya
está. Es la raíz del sitio de GitHub Pages.

La idea completa y el plan están en [guide.md](../guide.md); aquí solo va lo de esta
carpeta.

## Qué hace

1. **Escanear.** Al abrir, la web pide enfocar el semillero con la cámara. Localiza la
   bandeja y sus huecos (marcadores ArUco, profundidad o el modelo de visión, ver
   `scanner.js`) y pinta el mapa de alveolos **encima de la imagen en directo**.
2. **Diseñar.** Mapa tipo butacas de cine: cada alveolo es una casilla y se pinta del
   color de la caja de la que saldrá su semilla. Cuatro variedades, una caja por color.
   Arrastra una variedad desde la paleta o toca las casillas. "Rellenar todo el mapa"
   pone la variedad seleccionada en todos los huecos.
3. **Guardar.** El diseño se guarda como plantilla con nombre, y la última fórmula usada
   se restaura sola la próxima vez.
4. **Sembrar.** Manda el plan al backend local y pinta en el mismo mapa qué hueco se está
   sembrando, cuáles ya están y cuáles han fallado, con un botón de **Parar el robot**.

## Ficheros

| Fichero | Qué es |
|---|---|
| `index.html` | Marcado: pantalla de escaneo, mapa del semillero, panel de siembra |
| `app.css` | Todos los estilos, una sola cascada |
| `app.js` | Paleta, mapa, plantillas y la siembra contra el backend |
| `scanner.js` | Cámara en directo, rejilla superpuesta y localización de la bandeja |
| `vendor/` | `js-aruco2` (`cv.js`, `aruco.js`), servido desde aquí |
| `fonts/` | DM Sans y Manrope en local |

**Nada se carga de un CDN.** En el evento el wifi puede fallar y la detección de
marcadores es la vía más fiable para localizar la bandeja: si `aruco.js` viniera de
internet, desaparecería sin avisar. Si añades una dependencia, déjala también aquí.

## Conexión con el robot

Solo el portátil conectado al brazo alcanza el backend
(`backend/smartseed_robot`, `http://localhost:8000`). La web publicada en Pages no puede
llegar a él, así que la siembra se simula y se marca **MODO DEMO** en pantalla.

- `POST /plan` — `image_size` y un `{cell_index, row, col, color, u, v}` por alveolo con
  semilla. `u` y `v` son píxeles del fotograma de la cámara.
- `WS /robot/progress` — `plan_started`, `cell_started`, `cell_done`, `cell_failed`,
  `finished`, `stopped`, `error`.
- `POST /stop` — para la secuencia; el brazo se queda donde está, con par.

El formato exacto y la tabla de eventos están en
[guide.md § Formato del plan](../guide.md#formato-del-plan).

Si el backend está en otra dirección, en la consola del navegador:

```js
localStorage.setItem('smartseed.backendUrl', 'http://IP:8000')
```

Un plan que el backend rechaza (sin calibrar, alveolo fuera de alcance, siembra en curso)
muestra el motivo y **no** anima nada: nunca debe parecer una siembra correcta.

## Datos guardados

Todo en `localStorage` del navegador, nada sale de la máquina:

| Clave | Qué guarda |
|---|---|
| `smartseed.lastLayout` | Última fórmula usada (`{rows, cols, cells}`) |
| `smartseed.templates` | Plantillas con nombre |
| `smartseed.cameraId` | Última cámara elegida |
| `smartseed.scanCorners` | Esquinas de la bandeja ajustadas a mano |
| `smartseed.backendUrl` | Dirección del backend, si no es la de por defecto |

Las claves de las variedades (`TOMATE`, `PIMIENTO`, `LIMON`, `BERENJENAS`) van dentro de
los diseños guardados: no las cambies sin migrar lo almacenado.

## Probar

```bash
cd ../tests/web
npm install     # la primera vez
npm test        # jsdom: sin backend (modo demo) y con el robot simulado
CHROME_PATH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" npm run render
```

`npm run render` abre la página en un Chromium real a tamaño escritorio y móvil, guarda
capturas en `tests/web/shots/` y falla si hay errores de consola o desbordamiento
horizontal.
