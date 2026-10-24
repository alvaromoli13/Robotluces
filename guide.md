# SmartSeed 🌱 — Siembra asistida con un brazo SO-101

Guía del proyecto: idea, arquitectura y plan de trabajo. Para los criterios
resueltos y los pasos de reproducción, ver [README.md](README.md).

Proyecto para el **Hackathon Robotekin LeRobot** (Vitoria-Gasteiz, 23-25 octubre 2026).
Entrega: **domingo 13:00**. Presentaciones: 14:15.

## La idea

Un brazo robótico **SO-101** (LeRobot) siembra un semillero alveolado siguiendo el
diseño que el cliente elige en una interfaz gráfica.

- Hay **4 tipos de semilla**, cada uno en una **caja de un color**.
- El semillero es una bandeja de alveolos en rejilla (filas × columnas).
- La interfaz funciona como el **selector de asientos de un cine o de un estadio**: cada
  alveolo es una casilla y se pinta del color de la semilla que llevará.
- Cuando el cliente pulsa **Listo**, el robot coge las semillas de las cajas de colores y
  va sembrando cada alveolo según el plan.

## Entregables y evaluación

**Entregables** (antes del domingo a las 13:00):
1. **Demo en vivo** ante el jurado.
2. **Vídeo de 1 minuto como máximo.**
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
  arreglaron (ver `docs/iteraciones.md` cuando exista), porque es lo que se cuenta al
  jurado.
- **Dificultad (15)**: la tarea es de varios pasos (elegir caja → coger → llevar →
  soltar en el alveolo correcto), lo que ya es ambicioso. Hay que demostrar que aguanta
  cambios de posición o de luz.
- **Utilidad (15)**: siembra a medida para viveros y huertos; el cliente diseña su
  semillero sin trabajo manual repetitivo.
- **Innovación (10)**: la interfaz tipo butacas de cine con la cámara en directo y las
  plantillas reutilizables.
- **Bonus (+5)**: subir los datasets al Hub en cuanto se graben y dejar en el repo los
  comandos exactos para grabar, entrenar y ejecutar.

## Flujo de uso

0. **Colocar el semillero**: el agricultor deja la bandeja **en cualquier sitio de la zona
   de trabajo** de la mesa. La cámara cenital la detecta y la web muestra la rejilla real
   (número de alveolos y su posición) sobre la imagen en directo.
1. **Elegir plantilla**: al abrir la app se carga la **última fórmula usada**. También se
   puede escoger una **plantilla guardada**.
2. **Editar**: el cliente toca alveolos para cambiar su semilla (cada alveolo puede llevar
   una semilla distinta), o usa los botones de
   **rellenar todo de un color**. Los alveolos vacíos se quedan sin sembrar.
3. **Guardar (opcional)**: el diseño se puede guardar como plantilla con nombre.
4. **Listo**: se envía el plan al robot. La interfaz muestra en directo qué alveolo se
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

## Enfoque del robot: híbrido

Cada alveolo del plan se siembra en dos fases:

| Fase | Cómo se hace | Qué se mueve en la escena |
|---|---|---|
| 1. **Coger** la "semilla" de la caja del color X | Movimiento programado hasta encima de la caja X y después **policy aprendida** (ACT) que hace el agarre final con la cámara de la muñeca | Las **cajas pueden moverse** unos centímetros dentro de su zona: la policy corrige la diferencia |
| 2. **Soltarla** en el alveolo (fila, columna) | **Visión + cinemática inversa**: la cámara localiza el alveolo y el brazo calcula cómo llegar encima | El **semillero va donde lo deje el agricultor**, dentro de la zona de trabajo |

- **Policy: una sola ACT de agarre, igual para todos los colores.** El brazo llega por
  movimiento programado a una posición enseñada encima de la caja que toca, y desde ahí la
  ACT hace solo "coge la semilla que tienes debajo", guiándose sobre todo por la cámara de
  la muñeca. Es la misma habilidad para las 4 cajas, así que basta **un modelo y unos
  60-80 episodios** mezclando los 4 colores, y se entrena en una noche.
- **Por qué no 4 ACT, una por color**: en el Mac cada entrenamiento de 20 000 pasos tarda
  unas 4 horas (medido antes del evento), unas 17 horas para las 4. No cabe en el tiempo
  del hackathon.
- Alternativa descartada por tiempo: una SmolVLA que reciba el color como texto.
- **Por qué no se aprende todo**: ACT no recibe "a qué alveolo voy". Aprender
  "caja X → alveolo (fila, columna)" exigiría demostraciones para 4 colores × 40 alveolos,
  cientos de combinaciones, y no cabe en 48 horas. La parte geométrica (dónde está cada
  alveolo) es un cálculo exacto; la parte difícil de percepción (coger de una caja que se
  ha movido) es la que se aprende.
- **Lo que suma puntos**: la variación de las cajas en las demostraciones es lo que
  demuestra el criterio de dificultad ("aguanta cambios de posición o de luz") y el de
  datos y entrenamiento.
- **Plan B de la recogida**: si la policy no es fiable a tiempo, las cajas también se fijan
  y la recogida se hace con posiciones enseñadas. La demo sale igual y la policy queda
  como mejora.

## Secuencia de siembra

El ejecutor del backend recorre el plan celda a celda. Cada siembra es una secuencia fija:

```
inicio → encima de la caja X (posición enseñada) → ACT coge la semilla
→ subir → encima de la celda (cinemática inversa) → abrir pinza → inicio
```

1. **Encima de la caja X**: una posición articular enseñada con el leader para cada zona
   de caja, guardada una vez.
2. **Agarre**: se ejecuta la ACT durante unos segundos, como máximo, hasta que cierra la
   pinza.
3. **¿Ha cogido algo?** Se mira la posición de la pinza (`gripper.pos`, de 0 a 100): si se
   ha cerrado del todo, no hay nada dentro. Si falla, se reintenta una vez y, si vuelve a
   fallar, se marca la celda como fallida y se pasa a la siguiente.
4. **Subir** unos centímetros en vertical para no arrastrar la caja.
5. **Encima de la celda**: el centro de la celda en píxeles pasa a (x, y) del robot con la
   homografía, se le suma una altura fija de unos 5 cm sobre la bandeja y la cinemática
   inversa da los ángulos (ver la sección siguiente).
6. **Abrir pinza**, volver a inicio y avisar a la web del progreso.

**Cómo se mueve el brazo.** El SO-101 recibe ángulos de articulación en grados:
`robot.send_action({"shoulder_pan.pos": …, "shoulder_lift.pos": …, "elbow_flex.pos": …,
"wrist_flex.pos": …, "wrist_roll.pos": …, "gripper.pos": 0-100})`. El destino no se manda
de golpe: se interpola entre la posición actual y la final a unos 30 Hz, y
`max_relative_target` en la configuración del follower limita cuánto puede moverse en
cada paso, por seguridad.

**Stop**: corta la secuencia y desactiva el par de los motores. Tiene que funcionar desde
la web y desde el teclado del portátil.

## Semillero libre: detección y cinemática inversa

### 1. Detectar el semillero
- Se pegan **4 marcadores ArUco** del diccionario `ARUCO_MIP_36h12` en las esquinas de la
  bandeja: id 0 arriba a la izquierda, 1 arriba a la derecha, 2 abajo a la derecha y 3 abajo
  a la izquierda ([generador para imprimirlos](https://damianofalcioni.github.io/js-aruco2/samples/marker-creator/marker-creator.html?dictionary=ARUCO_MIP_36h12)).
  La web (`web/scanner.js`) los detecta en directo con `js-aruco2`. OpenCV (`cv2.aruco`, ya
  instalado) los encuentra con cualquier luz, mucho mejor que intentar detectar una
  bandeja negra con alveolos negros.
- Con las 4 esquinas y el número de filas × columnas se calcula el centro de cada alveolo
  en píxeles, aunque la bandeja esté girada. Eso es lo que la web pinta sobre la imagen.
- **Sin marcadores: modelo de visión local** (`backend/`). Funciona sin internet una vez
  descargado el modelo:
  - **OWLv2** (`google/owlv2-base-patch16-ensemble`), un detector abierto que busca
    objetos a partir de texto ("a black plastic seed tray"), localiza la bandeja en la
    imagen.
  - **OpenCV** saca dentro de esa zona las 4 esquinas exactas, endereza la bandeja y
    **cuenta filas y columnas** por la repetición de los bordes de los alveolos.
  - La web le manda un fotograma por segundo y pinta el resultado en directo, con la
    rejilla en azul. En el Mac (MPS) tarda unos 0,7 s por fotograma; la primera vez,
    unos 12 s más mientras carga el modelo.
- **Huecos por profundidad, sin esquinas.** **Depth Anything V2 Small**
  (`depth-anything/Depth-Anything-V2-Small-hf`) estima la profundidad relativa de cada
  píxel (unos 130 ms por fotograma en MPS). La mesa alrededor de la caja está tan baja
  como el fondo de un compartimento, así que «hondo» no basta: un hueco es una **cuenca
  rodeada de paredes**, una zona de la que el agua no podría salir hasta el borde de la
  imagen sin pasar por encima de una pared. Cada cuenca da el centro de un hueco y la web
  pone una casilla encima, sea cual sea la forma de la bandeja. Con la caja de cartón de
  2 compartimentos detecta los 2 huecos con la cámara real.
- **Prioridad** en la web: ArUco (rejilla verde) > huecos por profundidad (círculos azules)
  > rejilla del modelo de visión (azul) > esquinas arrastradas a mano (amarilla). Si el
  usuario escribe filas o columnas a mano, se vuelve a la rejilla y el modelo ya no las
  sobrescribe.
- Sin backend la web funciona igual, con marcadores o esquinas a mano.

Arrancar el backend (en el portátil del robot):

```bash
cd backend
uv sync          # la primera vez; instala torch, transformers y OpenCV en backend/.venv
./run.sh         # http://localhost:8000 · GET /health · POST /vision/tray
```

Después abre la web (publicada o `web/index.html`) y pulsa **Escanear con cámara**. Si
el backend está en otra dirección, ejecuta esto en la consola del navegador:
`localStorage.setItem('smartseed.backendUrl', 'http://IP:8000')`.

Limitaciones conocidas: está ajustado con imágenes sintéticas. Con la bandeja real hay
que comprobar los brillos sobre el plástico negro, una mesa oscura que se confunda con la
bandeja y si cuenta bien los huecos (puede contar la mitad o el doble si las sombras
marcan otro patrón). Tests: `cd backend && uv run pytest`.

### 2. Calibrar la cámara con el robot (una vez)
- Se lleva la punta de la pinza a 4-6 marcas de la mesa. En cada una se guarda el píxel
  donde la ve la cámara y la posición de la punta que da la cinemática directa.
- `cv2.findHomography` convierte esas parejas en una transformación **píxel de la mesa →
  coordenadas (x, y) del robot**. Como esas posiciones salen del mismo modelo del brazo que
  luego usa la cinemática inversa, buena parte de los errores del modelo se compensan.
- Unos 15 minutos. Solo se repite si se mueve la cámara cenital o el robot.

### 3. Soltar en el alveolo
- Para cada alveolo: píxel → (x, y) del robot → **cinemática inversa** a una altura fija
  unos centímetros por encima del alveolo → abrir la pinza.
- LeRobot trae la cinemática: `lerobot.model.kinematics.RobotKinematics`
  (`forward_kinematics` / `inverse_kinematics`). Requisitos:
  - `uv pip install -e "vendor/lerobot[kinematics]"`, que instala `placo`.
  - El URDF del SO-101, `so101_new_calib.urdf`, del repositorio
    [SO-ARM100](https://github.com/TheRobotStudio/SO-ARM100/tree/main/Simulation/SO101).

### Riesgos y cómo mitigarlos
- **El URDF tiene que coincidir con nuestra calibración**: `so101_new_calib` está pensado
  para la calibración de LeRobot, pero hay que comprobarlo en 10 minutos. Se mueve el brazo
  a mano y se mira que la posición que da `forward_kinematics` coincida con la real.
- **Precisión**: entre la calibración y la cinemática se puede acumular alrededor de 1 cm
  de error (estimación, **hay que medirlo**). Con alveolos de 4 cm y pelotas de 2,5 cm el
  margen es justo. Mitigación: soltar desde un poco más arriba, pelotas algo más pequeñas o
  una bandeja con alveolos más grandes, y medir el error real con una prueba de
  10 alveolos.
- **Zona de trabajo**: "cualquier sitio" significa dentro de la zona donde llega el brazo
  y que ve la cámara cenital. Se marca en la mesa. Si la bandeja queda fuera, la web avisa
  y no arranca.
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

Puesta a punto con el brazo (todo en `http://127.0.0.1:8000`, mueve el brazo a mano con el par
desactivado: `POST /robot/torque-off`):

1. **Comprobar la cinemática directa**: `GET /robot/joints` devuelve ángulos y `tool` (x, y, z
   en metros respecto a la base). Mide con una regla la punta de la pinza y compara.
2. **Enseñar poses** (`home`, `above_box_red|yellow|green|purple`, y opcional `grasp_<color>`
   que baja a coger): coloca el brazo y `POST /robot/poses/{nombre}`.
   `POST /robot/goto/{nombre}` comprueba que vuelve a ella, **después** de volver a activar
   el par con `POST /robot/torque-on` (fija destino = posición actual, sin saltos). Con el
   par quitado, `goto` y `/plan` responden `409 torque_off`.
3. **Calibrar cámara-robot**: con la punta sobre un punto visible de la bandeja,
   `POST /robot/calibration/points {"u":..,"v":..,"image_size":[w,h]}` (x, y salen de la
   cinemática directa). Al menos 4 puntos repartidos y `POST /robot/calibration/fit`
   (devuelve el error en mm).
4. **Sembrar**: `POST /plan {"image_size":[w,h],"cells":[{"cell_index","row","col","color","u","v"}]}`
   y seguir el progreso por `WS /robot/progress`.
5. **Parar**: `POST /stop` (el brazo se queda en su sitio con par). `POST /robot/torque-off`
   solo cuando el brazo esté en un lugar seguro; `POST /robot/torque-on` para recuperarlo.

Un agarre vacío (pinza cerrada del todo) se reintenta una vez; si falla otra vez la celda
se marca como fallida y se sigue. Con la aproximación en vertical el alcance a altura de
bandeja es de unos 28 cm desde la base.

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

`color` es el color de la **caja** de la que hay que coger, no el nombre de la variedad:
tomate → `red`, pimiento → `green`, limón → `yellow`, berenjena → `purple`. `cell_index`
es el índice de la casilla en el mapa (`fila * columnas + columna`) y vuelve tal cual en
los eventos de progreso, así que la web sabe qué casilla pintar.

Respuestas: `202 {"plan_id", "cells"}` si lo acepta; `4xx {"detail", "code"}` si no
(`busy`, calibración sin ajustar, `unreachable` con la lista de alveolos fuera de
alcance). La web enseña ese `detail` y **no** arranca ninguna animación: un plan
rechazado nunca debe parecer una siembra correcta.

Progreso por `WS /robot/progress`, un JSON por evento:

| `type` | Campos | Qué hace la web |
|---|---|---|
| `plan_started` | `total` | Muestra el panel de siembra |
| `cell_started` | `cell_index`, `row`, `col`, `color` | La casilla parpadea |
| `cell_done` | `cell_index` | Marca ✓ y avanza la barra |
| `cell_failed` | `cell_index`, `message` | Marca ✕ en rojo y lo cuenta aparte |
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
- [ ] Conseguir las pelotas y las 4 cajas de colores (ver [Escena y objetos](#escena-y-objetos)).
- [ ] Marcar en la mesa la **zona de trabajo** del semillero y la zona de cada caja: se
      pueden mover dentro de su zona.
- [ ] Pegar los 4 marcadores ArUco en las esquinas de la bandeja.
- [ ] Colocar la cámara cenital (`top`), que vea toda la zona de trabajo y las zonas de
      las cajas, y la del brazo (`wrist`). **Las cámaras y el robot no se mueven más.**
- [ ] Probar con la teleoperación que se coge una pelota de cada caja y se suelta en un
      alveolo.

### 2. Interfaz (viernes-sábado)
- [x] Rejilla de alveolos tipo cine, con tamaño configurable.
- [x] Selector de las 4 semillas/colores y botón de "rellenar todo de un color".
- [x] Guardar y cargar plantillas, y cargar automáticamente la última fórmula usada.
- [x] Botón **Sembrar** que envía el plan al backend, con vista de progreso y **Parar**.
- [x] Imagen de la cámara cenital con la rejilla **detectada** superpuesta.
- [x] Sin internet: tipografías y `js-aruco2` servidos desde `web/`, no desde un CDN.
- [ ] Aviso si la bandeja queda fuera de la zona de trabajo del brazo (hoy lo detecta el
      backend al recibir el plan, con `code: "unreachable"`, y la web enseña el motivo).

### 3. Backend y conexión con el robot (sábado)
- [x] Servidor local (FastAPI + WebSocket) con los endpoints `POST /plan`, `POST /stop`
      y `WS /robot/progress`.
- [ ] Detección del semillero con ArUco → centros de los alveolos en píxeles.
- [ ] Instalar `lerobot[kinematics]` y descargar el URDF del SO-101. Comprobar que la
      cinemática directa coincide con la posición real del brazo.
- [ ] Enseñar con el leader la posición encima de cada zona de caja y la posición de
      inicio.
- [ ] Calibración cámara-robot (homografía píxel → x, y del robot).
- [ ] Soltar por cinemática inversa y **medir el error** con una prueba de 10 alveolos.
- [ ] Sábado a mediodía: decidir entre semillero libre o plan B (esquinas enseñadas).
- [ ] Ejecutor de la [secuencia de siembra](#secuencia-de-siembra): agarre con la ACT,
      comprobación de la pinza con un reintento, movimiento interpolado y parada segura
      (**Stop** desactiva el par de los motores).

### 4. Datos y policy (viernes noche-sábado)
- [ ] Tanda de prueba: unos 10 episodios, entrenar pocos pasos y comprobar que aprende
      antes de grabar todo.
- [ ] Grabar **60-80 episodios de agarre** con `lerobot-record` (tarea: *"grasp the seed
      below the gripper"*). Cada episodio empieza en la posición enseñada encima de una
      caja y acaba con la semilla cogida y levantada. Mezclar los 4 colores, **mover un
      poco la caja dentro de su zona** y cambiar algo la luz entre episodios.
- [ ] Subir los datasets al Hub de Hugging Face.
- [ ] Entrenar **una ACT** en el Mac durante la noche (unas 4 h para 20 000 pasos), o en
      GPU cloud, y probar con rollout.
- [ ] Apuntar los fallos de cada iteración y cómo se arreglaron.

### 5. Demo y entrega (domingo antes de las 13:00)
- [ ] Fijar la **tarea de la demo** y ensayarla hasta que salga 5 veces seguidas sin tocar
      el robot.
- [ ] Grabar el **vídeo de 1 minuto como máximo**: problema → interfaz → robot sembrando →
      resultado.
- [ ] Publicar los datasets en Hugging Face (+3) y enlazarlos aquí.
- [ ] Dejar el repositorio reproducible (+2): comandos de grabación, entrenamiento y
      rollout, y la configuración usada.
- [ ] Preparar la presentación y las respuestas a las preguntas más probables del jurado
      (datos, fallos e iteraciones, utilidad).

## Estructura del repositorio

```
web/                        interfaz (la raíz del sitio de Pages redirige aquí)
  index.html                marcado: pantalla de escaneo, mapa y panel de siembra
  app.css                   todos los estilos
  app.js                    paleta, mapa, plantillas y siembra contra el backend
  scanner.js                cámara en directo, rejilla, ArUco y modelo de visión
  vendor/                   js-aruco2 (cv.js, aruco.js) servido desde el repo
  fonts/                    DM Sans y Manrope en local, sin Google Fonts
  README.md                 notas de la interfaz
tests/web/                  smoke test de la interfaz (jsdom) y captura en navegador
backend/                    servicio local (FastAPI): visión y control del robot
  smartseed_vision/         geometry.py, detector.py, depth.py, app.py
  smartseed_robot/          robot.py, kinematics.py, calibration.py, poses.py,
                            motion.py, executor.py, api.py
  assets/so101/             URDF y mallas del SO-101 para la cinemática
  tests/                    pytest con bandejas sintéticas y robot falso
  run.sh                    arranca en http://localhost:8000
odd/tasks/                  documentos de tareas por funcionalidad
.github/workflows/pages.yml despliegue antiguo de web/ (ver CLAUDE.md, «GitHub Pages»)
index.html                  redirección de la raíz de Pages a web/
README.md                   criterios resueltos y pasos para reproducir el resultado
guide.md                    este documento: idea, arquitectura y plan
CLAUDE.md                   guía para agentes y colaboradores
```

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
