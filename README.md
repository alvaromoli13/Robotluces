# SmartSeed 🌱 — criterios y reproducción

Hackathon Robotekin LeRobot · Vitoria-Gasteiz, 23-25 octubre 2026 · entrega domingo 13:00.

Siembra asistida con un brazo **SO-101**: el cliente diseña su semillero en una interfaz
tipo butacas de cine y el robot siembra cada alveolo con la semilla elegida.

> La idea completa, la arquitectura y el plan de trabajo están en **[guide.md](guide.md)**.
> Este README recoge solo **cómo resolvemos cada criterio** y **los pasos para repetir
> nuestro resultado**.

## Criterios

| Criterio | Qué se valora | Puntos | Cómo lo resolvemos |
|---|---|---|---|
| Demo en vivo | Cinco intentos seguidos de la tarea completa sin tocar el robot. Cada éxito suma 6 puntos. | 30 | Tarea de demo corta y fija: plantilla de 4 alveolos. La secuencia es siempre la misma (pose de inicio → agarre con la policy → cinemática inversa al alveolo → soltar). El backend **valida el plan entero antes de mover un motor**: resuelve la cinemática inversa de todas las celdas y, si algo no cuadra, lo rechaza con un código (`unreachable`, `no_calibration`, `missing_pose`, `torque_off`, `busy`) sin tocar el brazo. Al soltar se acerca desde 8 cm por encima y **corrige en lazo cerrado** hasta quedarse a menos de 5 mm del hueco. Si el agarre sale vacío, el brazo va igualmente a la celda, abre y sigue: un fallo de agarre no rompe el intento. El semillero completo se reserva para el vídeo. |
| Datos y entrenamiento | Cantidad, variedad y consistencia de las demostraciones, cámaras y encuadre, y cómo habéis iterado sobre los fallos. | 20 | Un dataset por color de cuenco (50 episodios de 20 s cada uno) grabado con `lerobot-record`, con **los dos cuencos en la mesa y cambiados de sitio entre episodios**, para que la policy aprenda a buscar el suyo por color y no por posición; la luz también varía. Dos cámaras fijas y siempre el mismo encuadre: cenital (`top`) para la escena y muñeca (`wrist`) para el agarre. Antes de grabar todo, tanda de prueba de ~10 episodios con pocos pasos de entrenamiento para validar el pipeline. Todo se publica en el Hub con las etiquetas del equipo. Cada iteración, su fallo y su arreglo quedan apuntados en los documentos de tarea de [`odd/tasks/`](odd/tasks/), sección *Progress / evidence*, que es de donde sale el relato al jurado. |
| Dificultad de la tarea | Ambición realista para 48 horas: desde coger un objeto hasta tareas de varios pasos que toleran cambios de posición o de luz. | 15 | Tarea de varios pasos y no de un solo agarre: elegir la caja del color correcto → coger → transportar → soltar en el alveolo (fila, columna) que pide el plan. Tolera cambios de posición por los dos lados: las **cajas se mueven** dentro de su zona y la policy corrige la diferencia; el **semillero va donde lo deje el agricultor** y se localiza por visión **sin pegarle nada encima** (huecos por profundidad, detector de vocabulario abierto o esquinas a mano), sin posiciones fijas y sin marcadores. La web además marca en ámbar los huecos que ya tienen algo dentro. |
| Utilidad e impacto | Si la solución resuelve un problema real. | 15 | La siembra de semilleros alveolados en viveros y huertos es trabajo manual, repetitivo y a medida. SmartSeed deja que el cliente diseñe la mezcla de variedades alveolo a alveolo, guarde plantillas y repita la última fórmula, sin tocar código ni el robot. |
| Innovación e ingenio | Originalidad del enfoque y de la solución. | 10 | Interfaz de selector de butacas sobre la imagen en directo de la cámara cenital, con la rejilla **detectada** superpuesta y el progreso visible a simple vista. Enfoque **híbrido**: se aprende solo la parte difícil de percepción (una ACT por color de cuenco, que lo busca aunque lo cambies de sitio) y la geometría se calcula exacta con homografía y cinemática inversa. Detección del semillero **sin marcadores**: los alveolos se encuentran como **cuencas rodeadas de paredes** en un mapa de profundidad monocular, así que funciona con cualquier forma de bandeja. Y como con el brazo estirado los servos ceden, el soltado **se corrige solo**: mide dónde ha quedado la punta y vuelve a apuntar por lo que le faltaba. |
| Presentación y equipo | Cómo contáis lo que habéis hecho y respondéis a las preguntas del jurado. | 10 | Relato en cuatro pasos: problema → interfaz → robot sembrando → resultado, el mismo del vídeo de 1 minuto. Llevamos preparadas las respuestas a las preguntas probables: cuántos datos, qué fallaba y cómo se arregló, por qué híbrido y no todo aprendido, qué precisión tiene, qué utilidad real tiene y qué pasa si se cae el wifi. |
| Bonus | Dataset publicado en Hugging Face (+3) y repositorio reproducible (+2). | +5 | Los datasets se suben al Hub en cuanto se graban, con las etiquetas del equipo, y se enlazan aquí. El repositorio es reproducible de verdad: los comandos exactos de instalación, grabación, entrenamiento y ejecución están en la sección siguiente, `scripts/stack.sh` levanta todo con una orden, lerobot está fijado al commit `e595b79`, el URDF y las mallas del SO-101 viven en el repo, la web no carga nada de un CDN, y la suite de pruebas (147 funciones de test en `backend/tests/` más el smoke de la interfaz) corre **sin hardware** gracias al robot falso. |

## Estado

| Parte | Estado |
|---|---|
| Interfaz web (rejilla, semillas propias, plantillas, última fórmula) | ✅ funcionando, publicada en GitHub Pages en modo demo |
| Botón **Sembrar** conectado a `POST /plan` con progreso en directo y **Parar** | ✅ en la web, con el protocolo cubierto por el smoke test |
| Visión: localizar el semillero, contar alveolos y ver cuáles están ocupados | ✅ backend local con tests, incluidas fotos de la bandeja real |
| Calibración cámara-robot desde el navegador y panel de **Ajustes** con medias pruebas | ✅ |
| Leader y follower montados y calibrados | ✅ viernes 23 |
| Ejecutor del robot: cinemática, homografía, poses, cola de siembra y Stop | ✅ en código, con robot falso y tests |
| Policy ACT por color, modos de media prueba y soltado corregido en lazo cerrado | ✅ en código, con tests |
| Pruebas automáticas del backend y de la interfaz | ✅ `uv run pytest` y `npm test`, sin hardware |
| Puesta a punto con el brazo real: poses enseñadas y calibración cámara-robot | 🔜 |
| Escena: pelotas, cuencos de colores, zonas marcadas, cámaras fijas | 🔜 |
| Datasets por color y segunda policy ACT (la del cuenco negro ya está en el Hub) | 🔜 |
| Demo ensayada 5 veces seguidas, vídeo (a [la carpeta de Drive](https://drive.google.com/drive/folders/1uDB6e2SAj96LFbZUaVXhP8_1dHKJPw7n)) y dataset en el Hub | 🔜 |

Checklist detallada por día: [guide.md](guide.md).

## Pasos para repetir nuestro resultado

### 0. Requisitos

- Mac con Python 3.12 y [uv](https://docs.astral.sh/uv/).
- Un brazo **SO-101** (leader + follower) y dos cámaras USB: cenital (`top`) y muñeca (`wrist`).
- LeRobot (`lerobot[feetech,kinematics]`, fijado al commit `e595b79`) ya es dependencia del
  backend: lo instala `uv sync`. El URDF y las mallas del SO-101 están en el repositorio
  (`backend/assets/so101/`, con su procedencia en `SOURCE.md`), no hay que descargarlos.
- **No hace falta pegar nada en la bandeja**: el semillero se localiza sin marcadores.

### 1. Interfaz

```bash
open web/index.html        # sin compilación ni dependencias
```

Se publica en GitHub Pages: <https://alvaromoli13.github.io/Robotluces/> (la raíz redirige a
`web/`). Pages está en modo *deploy from branch* (`main`, carpeta raíz), así que **cada push a
`main` publica todo el repositorio**, no solo `web/`: no subas nada privado.

### 2. Backend (visión + robot)

```bash
cd backend
uv sync                    # la primera vez: torch, transformers, OpenCV en backend/.venv
./run.sh                   # http://localhost:8000 · GET /health · POST /vision/tray
uv run pytest              # tests con bandejas y mapas de profundidad sintéticos
```

En la web, **Escanear con cámara**. Si el backend está en otra dirección, en la consola
del navegador:

```js
localStorage.setItem('smartseed.backendUrl', 'http://IP:8000')
```

El mismo servicio expone la visión y el ejecutor del robot. Por defecto usa un **robot
falso** (`SMARTSEED_ROBOT=fake`) y no abre ningún puerto serie. Con el brazo real:

```bash
SMARTSEED_ROBOT=real SMARTSEED_ROBOT_PORT=/dev/tty.usbmodemXXXX ./run.sh
```

| Endpoint | Para qué |
|---|---|
| `GET /health` | estado del servicio y si los modelos están cargados |
| `POST /vision/tray` | fotograma → esquinas, filas × columnas, huecos y cuáles están ocupados. Campo opcional `tray_hint` (JSON con las 4 esquinas normalizadas de la respuesta anterior): salta OWLv2 y busca solo alrededor (`source: "hint"`); si no encuentra bandeja con huecos, detecta desde cero. La web lo envía mientras la bandeja se ve y fuerza una detección completa cada 5 peticiones |
| `GET /robot/status` | estado del ejecutor, par, poses, calibración y colores con policy |
| `GET /robot/joints` | ángulos y posición de la punta (`tool`), por cinemática directa |
| `POST /robot/poses/{nombre}` · `GET /robot/poses` | enseñar y listar poses |
| `POST /robot/goto/{nombre}` | volver a una pose enseñada |
| `POST /robot/calibration/points` · `/fit` · `DELETE /points` | calibración cámara-robot y su error en mm |
| `POST /robot/torque-on` · `/robot/torque-off` | activar o quitar el par de los motores |
| `POST /plan` · `POST /stop` | sembrar un plan (con `mode` y `drop_z` opcionales) · cortar la secuencia |
| `WS /robot/progress` | progreso celda a celda |

Variables de entorno generales (las de la policy van en "Sembrar con policy ACT"):

| Variable | Por defecto | Qué hace |
|---|---|---|
| `SMARTSEED_ROBOT` | `fake` | `fake` no abre ningún puerto serie; `real` mueve el brazo |
| `SMARTSEED_ROBOT_PORT` | — | puerto del follower cuando `SMARTSEED_ROBOT=real` |
| `SMARTSEED_DATA_DIR` | `backend/data/` | dónde se guardan `poses.json` y `calibration.json` (fuera de git) |
| `SMARTSEED_DISABLE_MODEL` | — | `1` arranca sin OWLv2 ni profundidad (solo contornos), para probar rápido |

### 3. Escena y calibración

1. Marcar en la mesa la **zona de trabajo** del semillero y la zona de cada cuenco de color.
2. Colocar las cámaras `top` y `wrist`. **A partir de aquí, cámaras y robot no se mueven.**
3. Comprobar en la web que la bandeja se detecta: debe salir una casilla por alveolo sobre
   la imagen en directo (y en ámbar las que ya tienen algo). Si no acierta, arrastra las 4
   esquinas a mano y escribe filas y columnas: es la red de seguridad y funciona sin backend.

Con el backend arrancado en modo `real`, todo lo demás se hace por HTTP contra
`http://127.0.0.1:8000`. Para mover el brazo a mano, primero `POST /robot/torque-off`:

4. **Comprobar la cinemática directa**: `GET /robot/joints` devuelve los ángulos y `tool`
   (x, y, z en metros desde la base). Medir la punta con una regla y comparar.
5. **Enseñar poses**: colocar el brazo y `POST /robot/poses/{nombre}` para `home`,
   `above_box_<color>` (por defecto `red|yellow|green|purple`; cualquier id de color que
   uses en la web, p. ej. `above_box_blue`) y `grasp_<color>` (la pose bajada para coger; sin
   ella la pinza se cierra sin bajar).
   **Con policy ACT** (ver "Sembrar con policy ACT" abajo) basta `home` y `act_start`: no
   hacen falta `above_box_<color>` para los colores que tienen policy.
6. **Volver a activar el par**: `POST /robot/torque-on`. Antes de activarlo fija como
   destino la posición actual, así que el brazo no salta. Mientras el par está quitado,
   `POST /robot/goto/{nombre}` y `POST /plan` responden `409` con `code: "torque_off"`;
   `GET /robot/status` lo indica en el campo `torque`.
7. **Comprobar cada pose**: `POST /robot/goto/{nombre}` vuelve a ella.
8. **Calibrar cámara-robot**: con la punta sobre un punto visible de la bandeja,
   `POST /robot/calibration/points {"u":..,"v":..,"image_size":[w,h]}` (x, y salen de la
   cinemática directa, así que la calibración también se puede hacer con el par quitado y
   el brazo movido a mano). Al menos 4 puntos repartidos y `POST /robot/calibration/fit`,
   que devuelve el error en mm.
9. **Medir el error** con una prueba de 10 alveolos antes de seguir.

#### Cómo suelta sobre la celda

La IK prefiere la pinza vertical (`pitch` 0) y, si el brazo no llega así, la inclina hacia
fuera en pasos de 15° (15, 30 ... 90) hasta el primero que alcanza la celda: la punta queda lo
más hacia abajo posible. Solo si ninguna inclinación llega cuenta solo la posición. Con el
brazo estirado los servos ceden por gravedad, así que tras mover sobre la celda el ejecutor
espera `settle_s`, lee las articulaciones, calcula con FK dónde está la punta y, si falla más de
`place_tolerance_m` (5 mm), apunta más allá por lo que faltaba y repite hasta
`place_corrections` veces (2). Entonces abre y emite `drop_pose` por WS (`target`, `reached`,
`error_mm`, `corrections`); la web enseña "Soltado a N mm del hueco".

#### Sembrar con policy ACT

Un color con policy ACT no usa `above_box_<color>`: por celda el ejecutor va a `act_start`,
corre la policy a 30 Hz durante `SMARTSEED_ACT_DURATION_S` (va al cuenco, coge la semilla y
vuelve con ella), sube con IK a la celda, abre la pinza y vuelve a `act_start`. Los colores
sin policy siguen con las poses enseñadas.

1. **Enseñar `act_start`**: con el par quitado, colocar el brazo como al empezar los
   episodios (cerca de reposo) y `POST /robot/poses/act_start`. Sin enseñar se usa la media
   de los episodios grabados `[1.1, -102.7, 96.8, 47.7, -6.0, 6.3]`.
2. **Variables de entorno**:

   | Variable | Por defecto | Qué hace |
   |---|---|---|
   | `SMARTSEED_ACT_POLICIES` | vacío | JSON `{"<color>": "<repo HF o ruta>"}`; sin ella no hay ACT |
   | `SMARTSEED_ACT_DURATION_S` | `10` | segundos de policy por celda |
   | `SMARTSEED_CAM_TOP` / `SMARTSEED_CAM_WRIST` | `0` / `1` | índice (o ruta) OpenCV de cada cámara, 640x480@30 |
   | `SMARTSEED_POLICY_DEVICE` | `mps` si hay, si no `cpu` | dispositivo de inferencia |

   Las policies se cargan en la primera celda de ese color (la primera vez descarga ~200 MB).
   `GET /robot/status` lista los colores con policy en `policies`. En modo `fake` no se abren
   puertos ni cámaras (las imágenes son negras).
3. **Arrancar el servidor real desde Terminal.app** (o VS Code): macOS da el permiso de
   cámara a la app que lanza el proceso, y Unpeel no lo tiene.

   ```bash
   cd backend
   SMARTSEED_ROBOT=real SMARTSEED_ROBOT_PORT=/dev/tty.usbmodem5B8E1124861 \
   SMARTSEED_ACT_DURATION_S=15 SMARTSEED_ACT_POLICIES='{"<color>":"RafaelJaime/act-smartseed-grasp-merged"}' ./run.sh
   ```

   Si el color de la política no coincide con el de la web, ese color se rechaza con `409`
   (`missing_pose`) salvo que tenga `above_box_<color>`.

### Proceso completo (local)

Con el brazo conectado y las policies publicadas:

1. Desde **Terminal.app** (permiso de cámara): `scripts/stack.sh`. Por defecto usa la policy `RafaelJaime/act-smartseed-grasp` para el cuenco negro (`black`); para otra configuración, `SMARTSEED_ACT_POLICIES='{"<color>":"<repo>"}' scripts/stack.sh`.
   Arranca el backend en modo real (solo `127.0.0.1:8000`) y la web en `http://localhost:8080/`;
   `Ctrl-C` cierra los dos. Se niega a arrancar si el puerto 8000 ya está ocupado.
2. Abre la web y pulsa **Escanear** → **Calibrar robot**: «Soltar brazo», lleva la punta de la
   pinza a un punto de la bandeja y haz clic en ese punto de la imagen. Con al menos 4 puntos
   repartidos, **Ajustar** (muestra el error en mm).
3. **Guardar pose de inicio** (el brazo donde empiezan los episodios de la policy) y, si
   hace falta, **Guardar home**. Después **Bloquear brazo**.
4. Escanea la bandeja, asigna las semillas a las casillas y pulsa **Sembrar**.

Para depurar, el botón **Ajustes** (engranaje, bajo la cámara) esconde el estado del escaneo,
las filas y columnas, **Calibrar robot** y **Cerrar cámara**, y añade:

- **Altura al soltar (cm)** (por defecto 6, se recuerda en el navegador): altura de la punta
  sobre la casilla al abrir la pinza. Se manda como `drop_z` (m, 0.02–0.25) en cada plan; si
  el brazo empuja la bandeja al soltar, súbela.
- **Probar coger (ACT)**: solo la primera mitad. Va a la pose de inicio, ejecuta la policy del
  color de la semilla seleccionada y se queda con la semilla en la pinza (`mode: "grasp"`).
- **Probar dejar**: solo la segunda mitad. Va a la última casilla a la que asignaste una semilla (si ya
  no la tiene, a la primera con semilla): se coloca 8 cm por encima (`approach_clearance`), baja
  con la pinza como esté, la abre, sube otra vez y vuelve a la pose de inicio (`mode: "place"`; no necesita policy
  ni cajas enseñadas, sí calibración). Hay que haber cogido antes una semilla (o ponerla a mano).

Las pruebas usan el mismo panel de progreso, rotulado «Prueba: coger» / «Prueba: dejar».

Si el agarre falla (la pinza se queda vacía), el brazo va igualmente a la casilla, abre la pinza
y vuelve; la casilla cuenta como hecha y la web avisa de que la pinza parecía vacía.

### 4. Datos

Dos policies ACT, **una por color de cuenco**, cada una con su dataset. Un episodio va de
`home` al cuenco de ese color, coge una semilla y vuelve a `home`; los dos cuencos están en
la mesa y se cambian de sitio entre episodios, para que la policy aprenda a buscar el color.

```bash
lerobot-record \
  --robot.type=so101_follower \
  --teleop.type=so101_leader \
  --dataset.repo_id=<usuario>/smartseed-pick-<color> \
  --dataset.single_task="pick the seed from the <color> bowl and return home" \
  --dataset.num_episodes=50 --dataset.episode_time_s=20 \
  --dataset.tags='["BraboRobots","smartseed","robotekin-hackathon","lerobot","so101"]'
```

Con el entorno del hackathon (`LeRobot competition/`) es `./scripts/11_record.sh`, que lee
puertos, cámaras, tarea y etiquetas del `.env` (`TASK_NAME=smartseed-pick-<color>`,
`TASK_PROMPT`, `NUM_EPISODES=50`, `EPISODE_TIME_S=20`, `HF_TAGS`);
`RESUME=1 ./scripts/11_record.sh` continúa una grabación cortada. Antes de grabar hay que
parar el backend en modo `real`: los dos usan el puerto del follower.

**Etiquetas en Hugging Face**: todos los datasets y modelos se publican con las etiquetas
`BraboRobots`, `smartseed`, `robotekin-hackathon`, `lerobot` y `so101` (`--dataset.tags`
al grabar, `--policy.tags` al entrenar). En el Hub no existe la cuenta `@BraboRobots`, así
que va como etiqueta, no como mención.

### 5. Entrenamiento

```bash
lerobot-train \
  --policy.type=act \
  --dataset.repo_id=<usuario>/smartseed-pick-<color> \
  --steps=20000 \
  --policy.repo_id=<usuario>/act-smartseed-pick-<color> \
  --policy.tags='["BraboRobots","smartseed","robotekin-hackathon","lerobot","so101"]'
```

Una ejecución por color. En la nube (`./scripts/21_train_cloud.sh`, Hugging Face Jobs)
es alrededor de 1 h cada una; en el Mac (`./scripts/20_train_local.sh`) unas 4 h cada una.

### 6. Ejecución

Con el backend y la web levantados: escanear el semillero, diseñar el plan en la interfaz
y pulsar **Sembrar**. El plan llega como `POST /plan` con `image_size` y una lista de celdas
(`cell_index`, `row`, `col`, `color`, `u`, `v`), se convierte en una cola de
`(color de cuenco → alveolo fila, columna)` y por cada celda se ejecuta una de estas dos:

```
con policy:  pose de inicio → la ACT va al cuenco y vuelve con la semilla
             → encima de la celda (cinemática inversa) → abrir pinza → pose de inicio

sin policy:  inicio → encima del cuenco (pose enseñada) → coger (un reintento si sale vacío)
             → subir → encima de la celda → abrir pinza → inicio
```

Al soltar, el brazo se pone primero 8 cm por encima de la celda y baja desde ahí, para no
rozar la bandeja. Como con el brazo estirado los servos ceden, mide con la cinemática
directa dónde ha quedado la punta y, si falla más de 5 mm, vuelve a apuntar por lo que le
faltaba (hasta 2 correcciones) antes de abrir; el error final viaja en el evento `drop_pose`
y la web lo enseña como "Soltado a N mm del hueco".

El progreso se sigue por `WS /robot/progress`, y un cliente que se conecta a mitad del plan
lo recibe desde el principio (recargar el navegador durante una siembra no pierde nada). Si
la pinza parece vacía, **la celda se completa igual**: el brazo va, abre y continúa, y el
evento `cell_done` llega con `empty: true` para que la web lo avise. **Stop** es
`POST /stop`: corta la secuencia y el brazo **se queda en su sitio con par**;
`POST /robot/torque-off` solo cuando el brazo esté en un lugar seguro, y
`POST /robot/torque-on` antes de volver a moverlo.

### 7. Comprobar que todo sigue en pie

Nada de esto necesita el brazo ni las cámaras: el robot falso y las imágenes sintéticas
sustituyen al hardware, así que cualquiera puede clonar el repo y comprobar que funciona.

```bash
cd backend && uv run pytest        # 147 funciones de test: visión, cinemática, calibración, ACT, ejecutor y API

cd tests/web && npm install        # la primera vez
npm test                           # 2 pasadas: sin backend (modo demo) y con el robot simulado
CHROME_PATH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" npm run render
CHROME_PATH="..." npm run camera   # cámara sintética de Chromium: escaneo y mapa sobre el vídeo
```

Qué cubre cada uno está en [guide.md § Pruebas automáticas](guide.md#pruebas-automáticas).

### Datasets y modelos

- Datasets `smartseed-pick-<color>` (uno por color): _pendiente de publicar en el Hub_.
- Policies `act-smartseed-pick-<color>`: _pendiente de publicar en el Hub_.
- **Vídeo final (1 minuto como máximo)**: se sube a la carpeta de Drive del equipo,
  <https://drive.google.com/drive/folders/1uDB6e2SAj96LFbZUaVXhP8_1dHKJPw7n>, en cuanto esté terminado.

## Seguridad

La web publicada **no controla el robot**: funciona en modo demo. Solo el backend local
del portátil conectado al brazo manda acciones. Ten a mano el cable de alimentación del
follower la primera vez que pruebes cada cambio.
