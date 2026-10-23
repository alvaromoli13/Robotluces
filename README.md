# SmartSeed 🌱 — Siembra asistida con un brazo SO-101

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
| 1. **Coger** la "semilla" de la caja del color X | **Policy aprendida** de LeRobot, entrenada con demostraciones teleoperadas | Las **cajas pueden moverse** unos centímetros: la policy las encuentra con la cámara |
| 2. **Soltarla** en el alveolo (fila, columna) | **Visión + cinemática inversa**: la cámara localiza el alveolo y el brazo calcula cómo llegar encima | El **semillero va donde lo deje el agricultor**, dentro de la zona de trabajo |

- **Policy**: 4 ACT, una por color, con unos 50 episodios cada una. Es lo más seguro.
  Alternativa: una sola SmolVLA que reciba el color como texto (*"pick the ball from the
  red box"*); da más que contar al jurado pero va más justa de tiempo en el Mac.
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
- **Prioridad** en la web: ArUco (rejilla verde) > modelo de visión (azul) > esquinas
  arrastradas a mano (amarilla). Si el usuario cambia filas o columnas a mano, el modelo
  ya no las sobrescribe.
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
  coordenadas (x, y) del robot**.
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

```json
{
  "tray": { "rows": 5, "cols": 8 },
  "seeds": {
    "red":    "tomate",
    "green":  "lechuga",
    "yellow": "girasol",
    "blue":   "albahaca"
  },
  "cells": [["red", "red", null, "green", "..."], "..."]
}
```

`null` = alveolo vacío. El tamaño de la bandeja es configurable.

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
- [ ] Rejilla de alveolos tipo cine, con tamaño configurable.
- [ ] Selector de las 4 semillas/colores y botones de "rellenar todo de un color".
- [ ] Guardar y cargar plantillas, y cargar automáticamente la última fórmula usada.
- [ ] Botón **Listo** que envía el plan al backend, con vista de progreso.
- [ ] Imagen de la cámara cenital con la rejilla **detectada** superpuesta, y aviso si la
      bandeja está fuera de la zona de trabajo.

### 3. Backend y conexión con el robot (sábado)
- [ ] Servidor local (FastAPI + WebSocket) con los endpoints `POST /plan`, `POST /stop`
      y `WS /progress`, y streaming de la cámara.
- [ ] Detección del semillero con ArUco → centros de los alveolos en píxeles.
- [ ] Instalar `lerobot[kinematics]` y descargar el URDF del SO-101.
- [ ] Calibración cámara-robot (homografía píxel → x, y del robot).
- [ ] Soltar por cinemática inversa y **medir el error** con una prueba de 10 alveolos.
- [ ] Sábado a mediodía: decidir entre semillero libre o plan B (esquinas enseñadas).
- [ ] Ejecutor de la cola con parada segura: **Stop** desactiva el par de los motores.

### 4. Datos y policy (viernes noche-sábado)
- [ ] Tanda de prueba: unos 10 episodios de un color, entrenar pocos pasos y comprobar
      que aprende antes de grabar todo.
- [ ] Grabar unos 50 episodios por color de "coger la pelota de la caja X" con
      `lerobot-record`, **moviendo un poco la caja entre episodios**.
- [ ] Subir los datasets al Hub de Hugging Face.
- [ ] Entrenar (ACT en el Mac durante la noche, o en GPU cloud) y probar con rollout.
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
web/                        interfaz (se publica en GitHub Pages)
  index.html
  scanner.js                cámara en directo, rejilla, ArUco y llamada al backend
  README.md                 notas del prototipo de la interfaz
backend/                    servicio local de visión (FastAPI + OWLv2 + OpenCV)
  smartseed_vision/         geometry.py, detector.py, app.py
  tests/                    pytest con bandejas sintéticas
  run.sh                    arranca en http://localhost:8000
odd/tasks/                  documentos de tareas por funcionalidad
.github/workflows/pages.yml despliega web/ en GitHub Pages
CLAUDE.md                   guía para agentes y colaboradores
```

## Probar la web

Abre `web/index.html` en el navegador. No necesita compilación.
También se publica en GitHub Pages cada vez que hay un push a `main` que cambia `web/`.

## Seguridad

La web publicada no controla el robot. Solo el backend local, en la red del evento, puede
mover el brazo. Ten siempre a mano el cable de alimentación del follower la primera vez
que pruebes cada cambio.
