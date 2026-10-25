# SmartSeed 🌱 — Siembra asistida con un brazo SO-101

Guía del proyecto: idea, arquitectura y plan de trabajo. Para los criterios
resueltos y los pasos de reproducción, ver [README.md](README.md).

Proyecto para el **Hackathon Robotekin LeRobot** (Vitoria-Gasteiz, 23-25 octubre 2026).
Entrega: **domingo 13:00**. Presentaciones: 14:15.

## La idea

Un brazo robótico **SO-101** (LeRobot) siembra un semillero alveolado siguiendo el
diseño que el cliente elige en una interfaz gráfica.

- Las semillas las define el usuario en la web (botón «+»: nombre, emoji y **color de su caja**);
  vienen 4 por defecto, cada una en una **caja de un color distinto**.
- El semillero es una bandeja de alveolos en rejilla (filas × columnas).
- La interfaz funciona como el **selector de asientos de un cine o de un estadio**: cada
  alveolo es una casilla y se pinta del color de la semilla que llevará.
- Cuando el cliente pulsa **Sembrar**, el robot coge las semillas de las cajas de colores y
  va sembrando cada alveolo según el plan.

## Entregables y evaluación

**Entregables** (antes del domingo a las 13:00):
1. **Demo en vivo** ante el jurado.
2. **Vídeo de 1 minuto como máximo.** Cuando esté terminado se deja en la carpeta de Drive
   del equipo: <https://drive.google.com/drive/folders/1uDB6e2SAj96LFbZUaVXhP8_1dHKJPw7n>.
3. **Dataset publicado en Hugging Face** (bonus +3).
4. **Repositorio reproducible**, este (bonus +2).
5. **Presentación** del proyecto y turno de preguntas del jurado.

**Criterios.** Cada jurado puntúa a cada equipo y la nota final es la media de todos.

| Criterio | Qué se valora | Puntos |
|---|---|---|
| Demo en vivo | 5 intentos seguidos de la tarea completa **sin tocar el robot**; cada éxito suma 6 puntos | 30 |
| Datos y entrenamiento | Cantidad, variedad y consistencia de las demostraciones; cámaras y encuadre; cómo se ha iterado sobre los fallos | 20 |
| Dificultad de la tarea | Ambición realista para 48 h: desde coger un objeto hasta tareas de varios pasos que aguantan cambios de posición o de luz | 15 |
| Utilidad e impacto | Que resuelva un problema real | 15 |
| Innovación e ingenio | Originalidad del enfoque y de la solución | 10 |
| Presentación y equipo | Cómo se cuenta lo hecho y cómo se responde al jurado | 10 |
| Bonus | Dataset en Hugging Face (+3) y repositorio reproducible (+2) | +5 |

**Qué implica para el proyecto:**
- **La demo es lo que más puntúa** (30). La "tarea completa" de la demo tiene que ser
  algo que el robot haga bien **5 veces seguidas**, por ejemplo una plantilla pequeña
  fija de 4 alveolos, uno por color. Es mejor una demo corta y fiable que el semillero
  entero con fallos. El semillero completo puede salir en el vídeo.
- **Datos (20)**: muchas demostraciones y consistentes, variando un poco la posición de
  las semillas y la luz. Hay que apuntar los fallos de cada iteración y cómo se
  arreglaron (en los documentos de tarea de `odd/tasks/`, sección *Progress / evidence*),
  porque es lo que se cuenta al jurado.
- **Dificultad (15)**: la tarea es de varios pasos (elegir caja → coger → llevar →
  soltar en el alveolo correcto), lo que ya es ambicioso. Hay que demostrar que aguanta
  cambios de posición o de luz.
- **Utilidad (15)**: siembra a medida para viveros y huertos; el cliente diseña su
  semillero sin trabajo manual repetitivo.
- **Innovación (10)**: la interfaz tipo butacas de cine con la cámara en directo, las
  plantillas reutilizables y la detección del semillero **sin marcadores**.
- **Bonus (+5)**: subir los datasets al Hub en cuanto se graben y dejar en el repo los
  comandos exactos para grabar, entrenar y ejecutar.

## Flujo de uso

0. **Colocar el semillero**: el agricultor deja la bandeja **en cualquier sitio de la zona
   de trabajo** de la mesa, sin pegarle nada ni alinearla. La cámara cenital la detecta y la web muestra la rejilla real
   (número de alveolos y su posición) sobre la imagen en directo.
1. **Elegir plantilla**: al abrir la app se carga la **última fórmula usada**. También se
   puede escoger una **plantilla guardada**.
2. **Editar**: el cliente toca alveolos para cambiar su semilla (cada alveolo puede llevar
   una semilla distinta), o usa los botones de
   **rellenar todo de un color**. Los alveolos vacíos se quedan sin sembrar.
3. **Guardar (opcional)**: el diseño se puede guardar como plantilla con nombre.
4. **Sembrar**: se envía el plan al robot. La interfaz muestra en directo qué alveolo se
   está sembrando y cuáles ya están hechos.
5. **Terminado**: la fórmula queda guardada como "última usada" para la próxima vez.

La rejilla se muestra **sobre la imagen de la cámara cenital**, de modo que el cliente ve
el semillero real con el plan superpuesto, y el progreso se puede comprobar a simple vista.

## Arquitectura

```
┌──────────────┐  plan (JSON)  ┌──────────────────┐  acciones  ┌──────────┐
│  Web (web/)  │ ────────────▶ │ Backend local    │ ─────────▶ │  SO-101  │
│ rejilla +    │ ◀──────────── │ (Mac, Python,    │ ◀───────── │ follower │
│ cámara       │  progreso     │  LeRobot)        │  estado    │ + cámaras│
└──────────────┘  (WebSocket)  └──────────────────┘            └──────────┘
```

- **Web** (`web/`): HTML/CSS/JS sin framework. Plantillas y última fórmula en
  `localStorage`. Se publica en GitHub Pages en **modo demo**, sin robot.
- **Backend local**: servidor en Python en el portátil conectado al robot. Recibe el plan,
  lo convierte en una cola de tareas `(color de caja → alveolo fila,columna)` y transmite
  la cámara y el progreso. También detecta el semillero en la imagen. Es el único sitio
  que habla con el hardware.
- **Ejecución en el robot**: enfoque híbrido, ver la sección siguiente.

El plan que cruza de la web al backend **no lleva coordenadas del robot: lleva píxeles**.
La conversión a metros y a ángulos la hace el backend, que es quien conoce la calibración.

## Enfoque del robot: híbrido

Cada alveolo del plan se siembra en dos fases:

| Fase | Cómo se hace | Qué se mueve en la escena |
|---|---|---|
| 1. **Coger** la "semilla" del cuenco del color X | **Policy aprendida** (ACT) del color X: desde la pose de inicio va al cuenco, coge y vuelve, guiándose por las cámaras | Los **cuencos pueden moverse**: la policy busca el suyo por color, no por posición |
| 2. **Soltarla** en el alveolo (fila, columna) | **Visión + cinemática inversa**: la cámara localiza el alveolo y el brazo calcula cómo llegar encima | El **semillero va donde lo deje el agricultor**, dentro de la zona de trabajo |

- **Policy: una ACT por color de cuenco.** Desde la pose de inicio (`act_start`), la policy
  del color que toca hace el ciclo entero de recogida: ir al cuenco, coger y volver. Los
  episodios se graban con **los dos cuencos en la mesa y cambiados de sitio**, así que la
  policy aprende a buscar el suyo **por color** y no por posición. Un color sin policy cae
  en la ruta de poses enseñadas, que sigue funcionando.
- **Por qué una por color y no una sola para todos**: una única policy con los dos cuencos
  delante no tiene forma de saber a cuál ir, porque la ACT no recibe el color como entrada.
  Separarlas es lo que convierte "coge algo" en "coge del cuenco rojo".
- **Lo que cuesta**: unos 50 episodios de 20 s por color y un entrenamiento por color
  (alrededor de 1 h en la nube con Hugging Face Jobs, unas 4 h en el Mac).
- Alternativa descartada por tiempo: una SmolVLA que reciba el color como texto.
- **Por qué no se aprende todo**: ACT no recibe "a qué alveolo voy". Aprender
  "caja X → alveolo (fila, columna)" exigiría demostraciones para 4 colores × 40 alveolos,
  cientos de combinaciones, y no cabe en 48 horas. La parte geométrica (dónde está cada
  alveolo) es un cálculo exacto; la parte difícil de percepción (coger de una caja que se
  ha movido) es la que se aprende.
- **Lo que suma puntos**: mover los cuencos entre episodios es lo que demuestra el criterio
  de dificultad ("aguanta cambios de posición o de luz") y el de datos y entrenamiento.
- **Dónde encaja en el código**: el ejecutor mira primero si ese color tiene policy
  (`ActGrasp` en `act.py`, declaradas en `SMARTSEED_ACT_POLICIES`). Si la tiene, corre la
  policy en lazo cerrado a 30 Hz durante `SMARTSEED_ACT_DURATION_S`; si no, cae en el
  `Grasper` de poses enseñadas (`TaughtGrasp`: baja a `grasp_<color>` o aplica unos deltas
  y cierra). Las dos rutas desembocan en el mismo soltado.
- **Plan B de la recogida**: si una policy no es fiable a tiempo, ese cuenco se fija y su
  recogida se hace con posiciones enseñadas. La demo sale igual y la policy queda como
  mejora.

## Secuencia de siembra

El ejecutor del backend recorre el plan celda a celda. La recogida tiene dos rutas según
haya policy para ese color o no; el soltado es el mismo en las dos:

```
con policy:  act_start → la ACT va al cuenco, coge y vuelve
             → encima de la celda (cinemática inversa) → abrir pinza → act_start

sin policy:  inicio → encima del cuenco (pose enseñada) → coger → ¿lleva algo?
             → subir → encima de la celda → abrir pinza → inicio
```

1. **Recogida con policy**: el brazo va a `act_start` (la pose en la que empiezan los
   episodios) y la ACT de ese color manda acciones a 30 Hz durante los segundos
   configurados. En esta ruta no se juzga el agarre: la policy deja la pinza casi cerrada
   sobre la semilla y eso es indistinguible de una pinza vacía.
2. **Recogida con poses enseñadas**: `home` → `above_box_<color>` → el `Grasper` baja y
   cierra. Tras 0,3 s de reposo se mira la posición de la pinza (`gripper.pos`, de 0 a
   100): si se ha cerrado del todo (≤ 8), no hay nada dentro, y se **reintenta una vez**.
   Después sube a la pose de encima del cuenco con lo que tenga.
3. **Soltado**, igual en las dos rutas: el centro de la celda en píxeles pasa a (x, y) del
   robot con la homografía, el brazo se coloca primero **8 cm por encima** de la altura de
   soltado y baja desde ahí, para no rozar la bandeja al llegar.
4. **Corrección en lazo cerrado**: con el brazo estirado los servos ceden por gravedad, así
   que después de mover el ejecutor lee las articulaciones, calcula con cinemática directa
   dónde ha quedado la punta y, si falla más de **5 mm**, vuelve a apuntar más allá por lo
   que le faltaba y repite, hasta **2 correcciones**. El error final sale en el evento
   `drop_pose` y la web lo enseña como "Soltado a N mm del hueco".
5. **Abrir pinza**, subir otra vez a la pose de aproximación y volver al inicio de la ruta.

**Si la pinza parece vacía, la celda se completa igual**: el brazo va a la celda, abre y
sigue. El evento `cell_done` llega con `empty: true` y la web lo avisa. Es deliberado: en
una demo de 5 intentos seguidos es mejor completar la pasada y que se vea qué celda salió
vacía, que abortar.

**Medias pruebas.** El plan acepta un `mode` para depurar sin hacer el ciclo entero:
`"grasp"` solo recoge y se queda con la semilla (no necesita calibración), `"place"` solo
suelta sobre la celda con la pinza como esté (no necesita policy ni cuencos enseñados).
Son los botones **Probar coger** y **Probar dejar** del panel de Ajustes. También acepta
`drop_z` (0,02-0,25 m) para cambiar la altura de soltado solo en ese plan.

**Cómo se mueve el brazo.** El SO-101 recibe ángulos de articulación en grados:
`robot.send_action({"shoulder_pan.pos": …, "shoulder_lift.pos": …, "elbow_flex.pos": …,
"wrist_flex.pos": …, "wrist_roll.pos": …, "gripper.pos": 0-100})`. El destino no se manda
de golpe: se interpola entre la posición actual y la final a 30 Hz con un límite de
45 °/s en la articulación que más recorrido tiene, y `max_relative_target` (8) en la
configuración del follower limita además cuánto puede moverse en cada paso.

**Antes de mover un solo motor** el ejecutor valida el plan entero: campos y colores, que
haya calibración, que estén enseñadas las poses de los colores sin policy y que la
cinemática inversa resuelva **todas** las celdas. Si algo falla, el plan se rechaza con su
código y el brazo no se mueve.

**Stop**: `POST /stop` corta la secuencia y el brazo **se queda donde está, con par**; no
se desactivan los motores, para no soltar la pieza en el aire ni dejar caer el brazo.
Quitar el par es una acción aparte y explícita (`POST /robot/torque-off`), solo cuando el
brazo esté en un sitio seguro.

**Parámetros reales del ejecutor** (`ExecutorConfig`), los que conviene saberse:

| Parámetro | Valor | Qué es |
|---|---|---|
| `drop_z` | 0,06 m | altura de la punta sobre la bandeja al soltar (ajustable por plan) |
| `approach_clearance` | 0,08 m | cuánto por encima se coloca antes de bajar |
| `place_tolerance_m` | 5 mm | error aceptado sobre el hueco al soltar |
| `place_corrections` | 2 | reintentos de puntería por celda |
| `hz` | 30 | frecuencia de control (y de la policy) |
| `max_speed` | 45 °/s | límite en la articulación que más gira |
| `max_relative_target` | 8 | tope por paso en el follower |
| `gripper_open` / `gripper_closed` | 60 / 0 | pinza abierta y cerrada |
| `empty_below` | 8 | por debajo de esto, la pinza va vacía (solo ruta enseñada) |
| `settle_s` | 0,3 s | reposo antes de juzgar el agarre y antes de medir la punta |
| `retries` | 1 | reintentos de agarre (solo ruta enseñada) |
| Tolerancia IK | 3 mm | con hasta 6 rondas de solver por inclinación |

## Semillero libre: detección y cinemática inversa

### 1. Detectar el semillero

La bandeja se localiza **sin pegarle nada encima**, lo que evita preparar el material y
hace que funcione con la bandeja que traiga el cliente. Hay tres vías y manda la primera
que esté disponible; el color de lo que se dibuja sobre el vídeo indica cuál está activa.
Mientras no haya bandeja detectada no se dibuja ninguna rejilla: una rejilla inventada
sobre la mesa es peor que ninguna.

1. **Huecos por profundidad** (círculos azules, backend). **Depth Anything V2 Small**
   (`depth-anything/Depth-Anything-V2-Small-hf`) estima la profundidad relativa de cada
   píxel (unos 130 ms por fotograma en MPS). La mesa alrededor de la caja está tan baja
   como el fondo de un compartimento, así que «hondo» no basta: un hueco es una **cuenca
   rodeada de paredes**, una zona de la que el agua no podría salir hasta el borde de la
   imagen sin pasar por encima de una pared (relleno morfológico desde el borde del
   fotograma). Cada cuenca da el centro de un hueco; se descartan las cuencas sueltas y las
   que caen fuera de la bandeja, y las que quedan se numeran en coordenadas de la bandeja,
   no de la imagen, así que las filas y columnas salen bien aunque esté girada.
2. **Rejilla del modelo de visión** (azul, backend). **OWLv2**
   (`google/owlv2-base-patch16-ensemble`), un detector abierto que busca objetos a partir
   de texto ("a black plastic seed tray"), localiza la bandeja en la imagen; **OpenCV**
   saca dentro de esa zona las 4 esquinas exactas (probando manchas oscuras, claras y
   saturadas, para que también valgan las cajas de cartón), endereza la bandeja y **cuenta
   filas y columnas** por la periodicidad de los bordes de los alveolos. Un contorno sin
   hoyos en el mapa de profundidad **no** cuenta como bandeja: los contornos solos también
   encajan con texto impreso o con baldosas. En el Mac (MPS) tarda unos 0,7 s por
   fotograma; la primera vez, unos 12 s más mientras carga el modelo.
3. **Esquinas a mano** (amarillo, siempre disponible). El usuario arrastra las 4 esquinas
   sobre el vídeo y escribe filas y columnas. Funciona **sin backend**, así que es la red
   de seguridad de la demo. Si el usuario escribe filas o columnas a mano, se vuelve a la
   rejilla y el modelo ya no las sobrescribe.

Con las 4 esquinas y el número de filas × columnas se calcula el centro de cada alveolo en
píxeles por interpolación bilineal, aunque la bandeja esté girada; con los huecos por
profundidad el centro sale directamente de cada cuenca. Un recuento nuevo de huecos tiene
que repetirse dos veces seguidas antes de redimensionar la bandeja, para que un fotograma
ruidoso no borre las semillas ya asignadas.

**Huecos ya ocupados.** Cada hueco se compara con el material de la propia bandeja,
muestreado en el borde **entre** los huecos y no contra los demás huecos, así que sigue
funcionando con casi todo el semillero lleno. Un hueco cuenta como ocupado si su color se
aleja del borde (cromaticidad en Lab, para que las sombras no cuenten) o si su brillo se
vuelve irregular (piedras, semillas y sus sombras). La web los pinta en **ámbar**. Medido
sobre la bandeja de cartón real: vacíos ≤ 4,5 de croma y ≤ 16 de desviación; con piedras,
17 y 30.

**Marcadores ArUco: soportados, pero no los usamos.** `web/scanner.js` sabe detectar 4
marcadores `ARUCO_MIP_36h12` en las esquinas con `js-aruco2` (vendorizado en `web/vendor/`,
sin CDN) y tendrían prioridad sobre todo lo demás si estuvieran pegados. No los usamos: la
gracia es que el agricultor deje la bandeja y ya está. Queda como opción si la detección
sin marcadores se tuerce con la bandeja real.

Arrancar el backend (en el portátil del robot):

```bash
cd backend
uv sync          # la primera vez; instala torch, transformers, OpenCV y lerobot en backend/.venv
./run.sh         # http://localhost:8000 · GET /health · POST /vision/tray
```

Después abre la web (publicada o `web/index.html`) y pulsa **Escanear con cámara**. Si
el backend está en otra dirección, ejecuta esto en la consola del navegador:
`localStorage.setItem('smartseed.backendUrl', 'http://IP:8000')`.

Los umbrales están ajustados con imágenes sintéticas y con dos fotos de la bandeja de
cartón real (vacía y con piedras), que viven en `backend/tests/fixtures/` y se usan en los
tests. Con otra bandeja hay que volver a comprobar los brillos sobre el plástico negro, una
mesa oscura que se confunda con la bandeja y si cuenta bien los huecos. Tests:
`cd backend && uv run pytest`.

### 2. Calibrar la cámara con el robot (una vez)
- Se lleva la punta de la pinza a 4-6 marcas de la mesa. En cada una se guarda el píxel
  donde la ve la cámara y la posición de la punta que da la cinemática directa.
- `cv2.findHomography` convierte esas parejas en una transformación **píxel de la mesa →
  coordenadas (x, y) del robot**, y devuelve el error medio y máximo en mm. Como esas
  posiciones salen del mismo modelo del brazo que luego usa la cinemática inversa, buena
  parte de los errores del modelo se compensan.
- **Desde el navegador**: **Escanear** → **Calibrar robot** hace todo el ciclo sin tocar la
  consola: «Soltar brazo», llevar la punta a un punto de la bandeja, hacer clic en ese
  punto de la imagen, y con 4 puntos repartidos, **Ajustar** (enseña el error en mm).
  También se puede hacer a mano con `POST /robot/calibration/points` y `/fit`.
- La calibración se guarda en `backend/data/calibration.json` y se recarga al arrancar; si
  el fotograma llega con otro tamaño, los píxeles se reescalan solos.
- Unos 15 minutos. Solo se repite si se mueve la cámara cenital o el robot.

### 3. Soltar en el alveolo
- Para cada alveolo: píxel → (x, y) del robot → **cinemática inversa** a 6 cm por encima
  del alveolo → abrir la pinza.
- **La pinza apunta lo más hacia abajo que el brazo permita**: el solver prueba primero
  vertical y, si no llega, la va inclinando hacia fuera en pasos de 15° (15, 30 … 90) y se
  queda con la primera inclinación que alcanza; solo si ninguna llega deja de importar la
  orientación y cuenta únicamente la posición. Así se gana alcance en las celdas lejanas
  sin renunciar a entrar recto en las cercanas.
- La aproximación es desde arriba (8 cm por encima) y con **corrección en lazo cerrado**:
  ver [Secuencia de siembra](#secuencia-de-siembra).
- LeRobot trae la cinemática: `lerobot.model.kinematics.RobotKinematics`
  (`forward_kinematics` / `inverse_kinematics`), que usa `placo`. Lo instala `uv sync` con
  el extra `kinematics`; el URDF del SO-101 (`so101_new_calib.urdf`) y sus mallas están
  vendorizados en `backend/assets/so101/` (procedencia y commit en `SOURCE.md`), así que no
  hay que descargar nada.

### Riesgos y cómo mitigarlos
- **El URDF tiene que coincidir con nuestra calibración**: `so101_new_calib` está pensado
  para la calibración de LeRobot, pero hay que comprobarlo en 10 minutos. Se mueve el brazo
  a mano y se mira que la posición que da `forward_kinematics` coincida con la real
  (`GET /robot/joints` devuelve `tool`).
- **Precisión**: entre la calibración y la cinemática se acumula error. La corrección en
  lazo cerrado al soltar lo absorbe en buena parte (deja la punta a menos de 5 mm cuando
  llega a tiempo), pero hay que **medirlo** con una prueba de 10 alveolos; el error de cada
  soltado sale en el evento `drop_pose` y en la propia web. Con alveolos de 4 cm y pelotas
  de 2,5 cm el margen es justo: mitigación, soltar desde un poco más arriba (el panel de
  Ajustes cambia la altura sin tocar código), pelotas algo más pequeñas o una bandeja con
  alveolos más grandes.
- **Detección ajustada con pocas fotos reales**: es el riesgo nuevo desde que no usamos
  marcadores. Mitigación inmediata: las esquinas a mano, que no dependen de ningún modelo.
- **La policy no juzga el agarre**: en la ruta con ACT la pinza queda casi cerrada sobre la
  semilla, indistinguible de vacía, así que no hay reintento. Mitigación: el brazo suelta
  igualmente sobre la celda y la web avisa de que parecía vacía.
- **Zona de trabajo**: "cualquier sitio" significa dentro de la zona donde llega el brazo
  y que ve la cámara cenital. Se marca en la mesa. Si la bandeja queda fuera, el backend
  rechaza el plan con `code: "unreachable"` y la lista de alveolos, y la web lo explica.
- **Tiempo**: instalar, calibrar y ajustar cuesta medio sábado. Es el mayor riesgo técnico
  del proyecto.

### Plan B del semillero
Si el **sábado a mediodía** la prueba de 10 alveolos no acierta de forma fiable, se dibuja
en la mesa el contorno de la bandeja y se sueltan las pelotas con **4 esquinas enseñadas
con el leader** e interpolación. La cámara sigue detectando la rejilla para la web y
comprueba que la bandeja está en su sitio.

## Ejecutor del robot (`backend/smartseed_robot/`)

Por defecto el robot es **falso** (`SMARTSEED_ROBOT=fake`): no abre ningún puerto serie. Con
el brazo real: `SMARTSEED_ROBOT=real SMARTSEED_ROBOT_PORT=/dev/tty.usbmodem5B8E1124861 ./run.sh`
(follower `follower_01`, grados, `max_relative_target` 8). Los datos enseñados se guardan en
`backend/data/` (`poses.json`, `calibration.json`, fuera de git; `SMARTSEED_DATA_DIR` lo cambia).

Módulos:

| Fichero | De qué responde |
|---|---|
| `robot.py` | `RobotPort` (leer y mandar articulaciones, par, observación), `FakeRobot` y el adaptador `LeRobotFollower` |
| `kinematics.py` | cinemática directa e inversa sobre el URDF del SO-101 (placo), con la inclinación preferida hacia abajo |
| `calibration.py` | homografía píxel → mesa, su error en mm y su persistencia |
| `poses.py` | poses enseñadas con nombre (`home`, `act_start`, `above_box_<color>`, `grasp_<color>`) |
| `motion.py` | interpolación del movimiento, cancelable |
| `act.py` | policies ACT por color, cargadas en el primer uso, y su lazo cerrado |
| `executor.py` | validación del plan, modos, secuencia de cada celda y soltado corregido |
| `api.py` | endpoints HTTP y el WebSocket de progreso |

Puesta a punto con el brazo (todo en `http://127.0.0.1:8000`, mueve el brazo a mano con el par
desactivado: `POST /robot/torque-off`):

1. **Comprobar la cinemática directa**: `GET /robot/joints` devuelve ángulos y `tool` (x, y, z
   en metros respecto a la base). Mide con una regla la punta de la pinza y compara.
2. **Enseñar poses** (`home`, `above_box_<color>` —por defecto `red|yellow|green|purple`, y cualquier
   otro color que añadas en la web— y opcional `grasp_<color>`
   que baja a coger): coloca el brazo y `POST /robot/poses/{nombre}`.
   `POST /robot/goto/{nombre}` comprueba que vuelve a ella, **después** de volver a activar
   el par con `POST /robot/torque-on` (fija destino = posición actual, sin saltos). Con el
   par quitado, `goto` y `/plan` responden `409 torque_off`.
3. **Calibrar cámara-robot**: con la punta sobre un punto visible de la bandeja,
   `POST /robot/calibration/points {"u":..,"v":..,"image_size":[w,h]}` (x, y salen de la
   cinemática directa). Al menos 4 puntos repartidos y `POST /robot/calibration/fit`
   (devuelve el error en mm).
4. **Sembrar**: `POST /plan {"image_size":[w,h],"cells":[{"cell_index","row","col","color","u","v"}]}`
   y seguir el progreso por `WS /robot/progress`. Opcionales: `mode` (`"full"` por defecto,
   `"grasp"` solo coger, `"place"` solo dejar; son las pruebas del panel **Ajustes**) y
   `drop_z` (m, 0.02–0.25) para la altura de la punta al soltar.
5. **Parar**: `POST /stop` (el brazo se queda en su sitio con par). `POST /robot/torque-off`
   solo cuando el brazo esté en un lugar seguro; `POST /robot/torque-on` para recuperarlo.

En la ruta de poses enseñadas, un agarre vacío (pinza cerrada del todo) se reintenta una
vez; con policy no se juzga. En los dos casos el brazo **suelta igualmente sobre la celda**
y la celda se cuenta como hecha, con el aviso de que la pinza parecía vacía. Con la pinza
vertical el alcance a altura de bandeja es de unos 28 cm desde la base; inclinándola hacia
fuera se llega algo más lejos.

## Escena y objetos

Las semillas se representan con **pelotas** u objetos parecidos: coger una semilla real
con la pinza del SO-101 fallaría demasiado para aguantar 5 demos seguidas.

- **Tamaño**: más o menos el 60-70 % de la boca del alveolo, para que entre aunque el
  robot suelte un poco desviado. Por ejemplo, unos 2,5 cm para alveolos de 4 cm.
- **Que no reboten ni rueden**: bolas de madera, de goma maciza, canicas grandes o
  pompones. Nada de pelotas de ping-pong.
- **Color**: cada pelota del color de su caja. Se entiende al momento en la demo y en
  el vídeo.
- **Cajas**: bajas, de 3 a 5 cm de borde, para que la pinza llegue al fondo, y con pocas
  pelotas dentro para que no coja dos a la vez.
- **Mesa**: de un color que contraste con las pelotas y las cajas y sin reflejos, con la
  luz lo más constante posible.

### Formato del plan

Al pulsar **Sembrar**, la web manda `POST /plan` con una entrada por alveolo que lleva
semilla (los vacíos no se mandan). `u` y `v` son el centro del alveolo en **píxeles** del
fotograma de la cámara, que es lo que el backend convierte a coordenadas de mesa con la
homografía:

```json
{
  "image_size": [1280, 720],
  "cells": [
    { "cell_index": 0, "row": 0, "col": 0, "color": "red",    "u": 412, "v": 233 },
    { "cell_index": 5, "row": 1, "col": 1, "color": "green",  "u": 498, "v": 301 },
    { "cell_index": 9, "row": 2, "col": 1, "color": "purple", "u": 499, "v": 370 }
  ]
}
```

`color` es el id del color de la **caja** de la que hay que coger, no el nombre de la variedad.
Lo elige el usuario al crear la semilla (`red`, `orange`, `yellow`, `green`, `blue`, `purple`,
`pink`, `white`; el backend acepta cualquier id `^[a-z][a-z_-]{0,19}$`). Por defecto:
tomate → `black`, pimiento → `white`, limón → `yellow`, berenjena → `purple`. Un color sin
pose enseñada responde `409 missing_pose`. `cell_index`
es el índice de la casilla en el mapa (`fila * columnas + columna`) y vuelve tal cual en
los eventos de progreso, así que la web sabe qué casilla pintar.

Campos opcionales del cuerpo, usados por los botones de depuración de **Ajustes**:
`mode` (`"full"` por defecto; `"grasp"` va a `act_start`, ejecuta la policy y se queda con la
semilla, o en una ruta sin policy sube de la caja enseñada; `"place"` va encima de la celda con
la pinza como esté, abre y vuelve a `act_start`, sin policy ni cajas) y `drop_z` (m,
0.02–0.25, sustituye la altura por defecto de 6 cm solo en ese plan). `grasp` no necesita
calibración; `place` sí. `plan_started` repite el `mode` en el evento.

Respuesta: `202 {"plan_id", "cells"}` si lo acepta. Si no, `4xx {"detail", "code"}`:

| `code` | Cuándo |
|---|---|
| `invalid` (422) | faltan campos, el id de color no vale, o `mode`/`drop_z` fuera de rango |
| `no_calibration` (409) | la homografía no está ajustada (no aplica en `mode: "grasp"`) |
| `missing_pose` (409) | falta `home` o la pose de algún color sin policy (no aplica en `mode: "place"`) |
| `unreachable` (422) | la cinemática inversa no llega a una o varias celdas, que van en el `detail` |
| `torque_off` (409) | el par está quitado |
| `busy` (409) | ya hay un plan corriendo |

La web enseña ese `detail` y **no** arranca ninguna animación: un plan rechazado nunca debe
parecer una siembra correcta.

Progreso por `WS /robot/progress`, un JSON por evento:

| `type` | Campos | Qué hace la web |
|---|---|---|
| `plan_started` | `total` | Muestra el panel de siembra |
| `cell_started` | `cell_index`, `row`, `col`, `color` | La casilla parpadea |
| `drop_pose` | `cell_index`, `target`, `reached`, `error_mm`, `corrections` | Antes de abrir la pinza: enseña "Soltado a N mm del hueco" (la web ignora los tipos que no conoce) |
| `cell_done` | `cell_index`, `message`, `empty` | Marca ✓ y avanza la barra; con `empty` avisa de que la pinza parecía vacía |
| `cell_failed` | `cell_index`, `message` | Marca ✕ en rojo y lo cuenta aparte. El ejecutor ya no lo emite (una celda con la pinza vacía se completa igual); la web lo sigue entendiendo |
| `finished` | `message` | Cierra la siembra como terminada |
| `stopped` | `message` | Cierra la siembra como detenida |
| `error` | `cell_index`, `message` | Enseña el error del robot |

Un cliente que se conecta a mitad de un plan lo recibe desde el principio, así que
recargar la web durante una siembra no pierde el progreso.

**Sin backend** (la web publicada en GitHub Pages) el `POST` falla por red y la interfaz
simula la siembra con la etiqueta **MODO DEMO** bien visible. Si el backend sí responde
pero el semillero no se ha escaneado, la web se niega a sembrar y pide escanear: sin
píxeles no hay posición a la que llevar el brazo.

## Pasos a seguir

### 1. Hardware y escena (viernes)
- [x] Montar el leader y el follower y calibrarlos (hecho el viernes 23).
- [ ] Comprobar que la teleoperación va bien, pinza incluida.
- [ ] Conseguir las pelotas y un cuenco por color de semilla que vayas a usar (ver [Escena y objetos](#escena-y-objetos)).
- [ ] Marcar en la mesa la **zona de trabajo** del semillero y la zona de cada cuenco: se
      pueden mover dentro de su zona.
- [ ] Colocar la cámara cenital (`top`), que vea toda la zona de trabajo y las zonas de
      las cajas, y la del brazo (`wrist`). **Las cámaras y el robot no se mueven más.**
- [ ] Probar con la teleoperación que se coge una pelota de cada caja y se suelta en un
      alveolo.

### 2. Interfaz (viernes-sábado)
- [x] Rejilla de alveolos tipo cine, con tamaño configurable.
- [x] Semillas propias (nombre + emoji + color de caja, en `localStorage`) y botón de "rellenar todo de un color".
- [x] Guardar y cargar plantillas, y cargar automáticamente la última fórmula usada.
- [x] Botón **Sembrar** que envía el plan al backend, con vista de progreso y **Parar**.
- [x] Imagen de la cámara cenital con la rejilla **detectada** superpuesta.
- [x] Un plan rechazado enseña el motivo y no anima nada; sin backend, modo demo marcado.
- [x] Calibración cámara-robot desde el navegador y panel de **Ajustes** con altura de
      soltado y medias pruebas (**Probar coger** / **Probar dejar**).
- [x] Sin internet: tipografías y `js-aruco2` servidos desde `web/`, no desde un CDN.
- [x] Smoke test de la interfaz en jsdom, captura en Chromium y recorrido con cámara falsa.
- [ ] Aviso si la bandeja queda fuera de la zona de trabajo del brazo (hoy lo detecta el
      backend al recibir el plan, con `code: "unreachable"`, y la web enseña el motivo).

### 3. Backend y conexión con el robot (sábado)
- [x] Servidor local (FastAPI + WebSocket) con los endpoints `POST /plan`, `POST /stop`,
      `WS /robot/progress`, poses, calibración, par y estado.
- [x] Detección del semillero sin marcadores → centros de los alveolos en píxeles, con los
      huecos ya ocupados marcados.
- [x] Cinemática con `lerobot[kinematics]` y el URDF del SO-101 vendorizado en el repo.
- [x] Ejecutor de la [secuencia de siembra](#secuencia-de-siembra): recogida con policy o
      con poses enseñadas, soltado corregido en lazo cerrado, movimiento interpolado,
      validación del plan completo antes de moverse y parada segura (**Stop** mantiene el
      par).
- [x] Modos `grasp` / `place` y `drop_z` por plan para depurar media secuencia.
- [ ] Comprobar que la cinemática directa coincide con la posición real del brazo.
- [ ] Enseñar con el leader `act_start`, `home` y la posición encima de cada cuenco sin
      policy.
- [ ] Calibración cámara-robot (homografía píxel → x, y del robot).
- [ ] Soltar por cinemática inversa y **medir el error** con una prueba de 10 alveolos.
- [ ] Ajustar la detección con más fotogramas de la bandeja real.
- [ ] Sábado a mediodía: decidir entre semillero libre o plan B (esquinas enseñadas).

### 4. Datos y policy (viernes noche-sábado)
- [x] Tanda de prueba: unos 10 episodios, entrenar pocos pasos y comprobar que aprende
      antes de grabar todo.
- [x] Policy del primer cuenco entrenada y publicada en el Hub, enchufada en el ejecutor
      (`SMARTSEED_ACT_POLICIES`).
- [ ] Grabar **~50 episodios de 20 s por color** con `lerobot-record`: cada episodio va de
      `home` al cuenco de ese color, coge una semilla y vuelve. **Los dos cuencos en la
      mesa y cambiados de sitio** entre episodios, y algo de variación de luz.
- [ ] Subir los datasets al Hub de Hugging Face con las etiquetas del equipo.
- [ ] Entrenar la ACT del segundo color (≈ 1 h en la nube, ~4 h en el Mac) y probarla.
- [ ] Enseñar `act_start` con el brazo real y comprobar el ciclo entero celda a celda.
- [ ] Apuntar los fallos de cada iteración y cómo se arreglaron en `odd/tasks/`.

### 5. Demo y entrega (domingo antes de las 13:00)
- [ ] Fijar la **tarea de la demo** y ensayarla hasta que salga 5 veces seguidas sin tocar
      el robot.
- [ ] Grabar el **vídeo de 1 minuto como máximo**: problema → interfaz → robot sembrando →
      resultado, y subirlo a la [carpeta de Drive](https://drive.google.com/drive/folders/1uDB6e2SAj96LFbZUaVXhP8_1dHKJPw7n).
- [ ] Publicar los datasets en Hugging Face (+3) con la etiqueta `BraboRobots` y enlazarlos aquí.
- [ ] Dejar el repositorio reproducible (+2): comandos de grabación, entrenamiento y
      rollout, y la configuración usada.
- [ ] Preparar la presentación y las respuestas a las preguntas más probables del jurado
      (datos, fallos e iteraciones, utilidad).

## Estructura del repositorio

```
web/                        interfaz (la raíz del sitio de Pages redirige aquí)
  index.html                marcado: pantalla de escaneo, mapa, panel de siembra y ajustes
  app.css                   todos los estilos
  app.js                    semillas propias, mapa, plantillas y siembra contra el backend
  scanner.js                cámara en directo, rejilla y localización de la bandeja
  calibrate.js              calibración cámara-robot desde el navegador
  vendor/                   js-aruco2 (cv.js, aruco.js) servido desde el repo
  fonts/                    DM Sans y Manrope en local, sin Google Fonts
  README.md                 notas de la interfaz
tests/web/                  smoke test de la interfaz (jsdom), captura y cámara en Chromium
backend/                    servicio local (FastAPI): visión y control del robot
  smartseed_vision/         geometry.py, detector.py, depth.py, occupancy.py, app.py
  smartseed_robot/          robot.py, kinematics.py, calibration.py, poses.py,
                            motion.py, act.py, executor.py, api.py
  assets/so101/             URDF y mallas del SO-101 para la cinemática (+ SOURCE.md)
  tests/                    pytest con bandejas y profundidad sintéticas, fotos de la bandeja
                            real en fixtures/ y robot falso
  run.sh                    arranca en http://localhost:8000
  pyproject.toml            dependencias (lerobot fijado al commit e595b79)
scripts/stack.sh            backend real + web en una orden, para la demo
odd/tasks/                  documentos de tareas por funcionalidad, con la evidencia de cada iteración
.github/workflows/pages.yml despliegue antiguo de web/ (ver CLAUDE.md, «GitHub Pages»)
index.html                  redirección de la raíz de Pages a web/
README.md                   criterios resueltos y pasos para reproducir el resultado
guide.md                    este documento: idea, arquitectura y plan
CLAUDE.md                   guía para agentes y colaboradores
```

## Pruebas automáticas

Todo corre **sin brazo y sin cámaras**: el robot falso, las imágenes sintéticas y las
policies simuladas sustituyen al hardware, así que cualquiera puede clonar el repo y
comprobar que funciona.

**Backend** (`cd backend && uv run pytest`): 147 funciones de test en 13 ficheros.

| Fichero | Qué comprueba |
|---|---|
| `test_geometry.py` | esquinas y recuento de filas × columnas en bandejas sintéticas, giradas, oscuras, claras y de cartón |
| `test_depth.py` | huecos como cuencas: una por compartimento, orden por filas, huecos fuera de la bandeja descartados, una depresión abierta al borde no es un hueco |
| `test_occupancy.py` | huecos ocupados contra el borde de la bandeja, con las fotos reales (vacía y con piedras) |
| `test_detector.py` | selección de la mejor caja de OWLv2 y recorte al tamaño de la imagen |
| `test_app.py` | `/health`, `/vision/tray`, CORS y Private Network, y que los modelos nunca corran a la vez en la GPU |
| `test_robot.py` | `FakeRobot`: par, comandos parciales, historial, agarre lleno o vacío |
| `test_kinematics.py` | cinemática directa contra el URDF, ida y vuelta IK, y que la pinza apunta lo más abajo posible |
| `test_calibration.py` | ajuste de la homografía, error, reescalado de píxeles y persistencia |
| `test_poses.py` | nombres válidos (colores propios incluidos), poses que faltan, persistencia y fichero corrupto |
| `test_motion.py` | interpolación con límite de velocidad y parada dentro de un paso de control |
| `test_act.py` | configuración desde el entorno, carga perezosa por color y lazo cerrado cancelable |
| `test_executor.py` | las dos rutas de recogida, modos `grasp`/`place`, soltado con corrección, celda vacía que se completa igual, `busy` y `stop` |
| `test_robot_api.py` | contrato de la API: estado, poses, calibración, planes rechazados con su `code`, eventos del WebSocket |

**Interfaz** (`cd tests/web && npm test`): el smoke carga `web/index.html` de verdad en
jsdom y la maneja, en dos pasadas:

- **sin backend**: la siembra se simula y se marca **MODO DEMO**, y no se envía nada.
- **con el robot simulado**: el plan que sale tiene exactamente la forma de
  `smartseed_robot`, el progreso llega por WebSocket y pinta cada casilla, y un plan
  rechazado (`unreachable`, `torque_off`, `busy`) enseña el motivo sin animar nada.

Además: `npm run render` abre la página en un Chromium real a tamaño escritorio y móvil,
guarda capturas en `tests/web/shots/` y falla si hay errores de consola o desbordamiento
horizontal; `npm run camera` recorre el escaneo entero con la cámara sintética de Chromium.
Los dos necesitan `CHROME_PATH` apuntando a un Chromium instalado.

## Probar la web

Abre `web/index.html` en el navegador. No necesita compilación ni servidor, y funciona
sin internet: la tipografía y `js-aruco2` están dentro de `web/`.
Se publica en GitHub Pages: <https://alvaromoli13.github.io/Robotluces/> (la raíz redirige a
`web/`). Pages está en modo *deploy from branch* (`main`, carpeta raíz), así que **cada push a
`main` publica todo el repositorio**, no solo `web/`: no subas nada privado.

Hay un smoke test que carga la página de verdad y la maneja:

```bash
cd tests/web
npm install     # la primera vez (jsdom y puppeteer-core, solo para los tests)
npm test        # 2 pasadas: sin backend (modo demo) y con el robot simulado
CHROME_PATH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" npm run render
CHROME_PATH="..." npm run camera   # cámara falsa de Chromium: escaneo y mapa sobre el vídeo
```

`npm test` comprueba el comportamiento: mapa, plantillas, redimensionado, el plan que se
envía (su forma exacta, la de `smartseed_robot`), el progreso por WebSocket, el plan
rechazado y el modo demo. `npm run render` abre la página en un Chromium real a tamaño
escritorio y móvil, guarda capturas en `tests/web/shots/` y falla si hay errores de
consola o desbordamiento horizontal. `npm run camera` recorre el escaneo entero con la
cámara sintética de Chromium.

## Seguridad

La web publicada no controla el robot. Solo el backend local, en la red del evento, puede
mover el brazo. Ten siempre a mano el cable de alimentación del follower la primera vez
que pruebes cada cambio.
