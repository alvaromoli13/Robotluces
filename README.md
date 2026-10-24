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
| Demo en vivo | Cinco intentos seguidos de la tarea completa sin tocar el robot. Cada éxito suma 6 puntos. | 30 | Tarea de demo corta y fija: plantilla de 4 alveolos, uno por color. La secuencia es siempre la misma (posición enseñada sobre la caja → agarre con la policy → cinemática inversa al alveolo → soltar), con comprobación de la pinza y un reintento por celda, así que un fallo de agarre no rompe el intento. El semillero completo se reserva para el vídeo. |
| Datos y entrenamiento | Cantidad, variedad y consistencia de las demostraciones, cámaras y encuadre, y cómo habéis iterado sobre los fallos. | 20 | 60-80 episodios de agarre grabados con `lerobot-record`, mezclando los 4 colores, moviendo la caja dentro de su zona y cambiando la luz entre episodios. Dos cámaras fijas y siempre el mismo encuadre: cenital (`top`) para la escena y muñeca (`wrist`) para el agarre. Antes de grabar todo, tanda de prueba de ~10 episodios con pocos pasos de entrenamiento para validar el pipeline. Cada iteración, sus fallos y el arreglo quedan apuntados en [guide.md](guide.md). |
| Dificultad de la tarea | Ambición realista para 48 horas: desde coger un objeto hasta tareas de varios pasos que toleran cambios de posición o de luz. | 15 | Tarea de varios pasos y no de un solo agarre: elegir la caja del color correcto → coger → transportar → soltar en el alveolo (fila, columna) que pide el plan. Tolera cambios de posición por los dos lados: las **cajas se mueven** dentro de su zona y la policy corrige la diferencia; el **semillero va donde lo deje el agricultor** y se localiza por visión (ArUco, huecos por profundidad o detección con OWLv2), sin posiciones fijas. |
| Utilidad e impacto | Si la solución resuelve un problema real. | 15 | La siembra de semilleros alveolados en viveros y huertos es trabajo manual, repetitivo y a medida. SmartSeed deja que el cliente diseñe la mezcla de variedades alveolo a alveolo, guarde plantillas y repita la última fórmula, sin tocar código ni el robot. |
| Innovación e ingenio | Originalidad del enfoque y de la solución. | 10 | Interfaz de selector de butacas sobre la imagen en directo de la cámara cenital, con la rejilla **detectada** superpuesta y el progreso visible a simple vista. Enfoque **híbrido**: se aprende solo la parte difícil de percepción (una ACT de agarre, la misma para los 4 colores) y la geometría se calcula exacta con homografía y cinemática inversa. Detección del semillero sin marcadores: los alveolos se encuentran como **cuencas rodeadas de paredes** en un mapa de profundidad monocular, así que funciona con cualquier forma de bandeja. |
| Presentación y equipo | Cómo contáis lo que habéis hecho y respondéis a las preguntas del jurado. | 10 | Relato en cuatro pasos: problema → interfaz → robot sembrando → resultado, el mismo del vídeo de 1 minuto. Llevamos preparadas las respuestas a las preguntas probables (cuántos datos, qué fallaba y cómo se arregló, por qué híbrido y no todo aprendido, qué utilidad real tiene). |
| Bonus | Dataset publicado en Hugging Face (+3) y repositorio reproducible (+2). | +5 | Los datasets se suben al Hub en cuanto se graban y se enlazan aquí. El repositorio es reproducible: los comandos exactos de instalación, grabación, entrenamiento y ejecución están en la sección siguiente. |

## Estado

| Parte | Estado |
|---|---|
| Interfaz web (rejilla, 4 semillas, plantillas, última fórmula, progreso) | ✅ funcionando, publicada en GitHub Pages en modo demo |
| Visión: localizar el semillero y contar alveolos (ArUco · profundidad · OWLv2) | ✅ backend local con tests |
| Leader y follower montados y calibrados | ✅ viernes 23 |
| Ejecutor del robot: cinemática, homografía, poses, cola de siembra y Stop | ✅ en código, con robot falso y tests |
| Puesta a punto con el brazo real: poses enseñadas y calibración cámara-robot | 🔜 |
| Escena: pelotas, 4 cajas de colores, zonas marcadas, cámaras fijas | 🔜 |
| Dataset de agarre y policy ACT | 🔜 |
| Demo ensayada 5 veces seguidas, vídeo y dataset en el Hub | 🔜 |

Checklist detallada por día: [guide.md](guide.md).

## Pasos para repetir nuestro resultado

### 0. Requisitos

- Mac con Python 3.12 y [uv](https://docs.astral.sh/uv/).
- Un brazo **SO-101** (leader + follower) y dos cámaras USB: cenital (`top`) y muñeca (`wrist`).
- LeRobot (`lerobot[feetech,kinematics]`, fijado al commit `e595b79`) ya es dependencia del
  backend: lo instala `uv sync`. El URDF y las mallas del SO-101 están en el repositorio
  (`backend/assets/so101/`), no hay que descargarlos.

### 1. Interfaz

```bash
open web/index.html        # sin compilación ni dependencias
```

También se publica en GitHub Pages en cada push a `main` que toque `web/`.

### 2. Backend de visión

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

`SMARTSEED_DISABLE_MODEL=1` arranca sin OWLv2 (solo contornos), útil para probar rápido.

El mismo servicio expone el ejecutor del robot. Por defecto usa un **robot falso**
(`SMARTSEED_ROBOT=fake`) y no abre ningún puerto serie. Con el brazo real:

```bash
SMARTSEED_ROBOT=real SMARTSEED_ROBOT_PORT=/dev/tty.usbmodemXXXX ./run.sh
```

Las poses enseñadas y la calibración se guardan en `backend/data/` (fuera de git;
`SMARTSEED_DATA_DIR` cambia la ruta).

### 3. Escena y calibración

1. Marcar en la mesa la **zona de trabajo** del semillero y la zona de cada caja de color.
2. Pegar los 4 marcadores ArUco (`ARUCO_MIP_36h12`, ids 0-3 = arriba-izq, arriba-der,
   abajo-der, abajo-izq) en las esquinas de la bandeja.
3. Colocar las cámaras `top` y `wrist`. **A partir de aquí, cámaras y robot no se mueven.**

Con el backend arrancado en modo `real`, todo lo demás se hace por HTTP contra
`http://127.0.0.1:8000`. Para mover el brazo a mano, primero `POST /robot/torque-off`:

4. **Comprobar la cinemática directa**: `GET /robot/joints` devuelve los ángulos y `tool`
   (x, y, z en metros desde la base). Medir la punta con una regla y comparar.
5. **Enseñar poses**: colocar el brazo y `POST /robot/poses/{nombre}` para `home`,
   `above_box_red|yellow|green|purple` y, opcionalmente, `grasp_<color>`.
   `POST /robot/goto/{nombre}` comprueba que vuelve a ella.
6. **Calibrar cámara-robot**: con la punta sobre un punto visible de la bandeja,
   `POST /robot/calibration/points {"u":..,"v":..,"image_size":[w,h]}`. Al menos 4 puntos
   repartidos y `POST /robot/calibration/fit`, que devuelve el error en mm.
7. **Medir el error** con una prueba de 10 alveolos antes de seguir.

### 4. Datos

```bash
lerobot-record \
  --robot.type=so101_follower \
  --teleop.type=so101_leader \
  --dataset.repo_id=<usuario>/smartseed-grasp \
  --dataset.single_task="grasp the seed below the gripper" \
  --dataset.num_episodes=70
```

Cada episodio empieza en la posición enseñada encima de una caja y acaba con la semilla
cogida y levantada. Mezclar los 4 colores, mover un poco la caja dentro de su zona y
variar la luz entre episodios. Tanda de prueba de ~10 episodios antes de grabar las 70.

### 5. Entrenamiento

```bash
lerobot-train \
  --policy.type=act \
  --dataset.repo_id=<usuario>/smartseed-grasp \
  --steps=20000 \
  --output_dir=outputs/act-grasp
```

En el Mac son unas 4 h para 20 000 pasos: se lanza por la noche. Una sola ACT para los
4 colores, porque el agarre es la misma habilidad.

### 6. Ejecución

Con el backend y la web levantados: diseñar el plan en la interfaz y pulsar **Sembrar**.
El plan llega como `POST /plan` con `image_size` y una lista de celdas
(`cell_index`, `row`, `col`, `color`, `u`, `v`), se convierte en una cola de
`(color de caja → alveolo fila, columna)` y por cada celda se ejecuta:

```
inicio → encima de la caja X (pose enseñada) → coger la semilla
→ subir → encima de la celda (cinemática inversa) → abrir pinza → inicio
```

El progreso se sigue por `WS /robot/progress`. Un agarre vacío (pinza cerrada del todo) se
reintenta una vez; si vuelve a fallar, la celda se marca como fallida y se pasa a la
siguiente. **Stop** es `POST /stop`: corta la secuencia y el brazo se queda en su sitio con
par; `POST /robot/torque-off` solo cuando el brazo esté en un lugar seguro.

### Datasets y modelos

- Dataset de agarre: _pendiente de publicar en el Hub_.
- Policy ACT entrenada: _pendiente de publicar en el Hub_.

## Seguridad

La web publicada **no controla el robot**: funciona en modo demo. Solo el backend local
del portátil conectado al brazo manda acciones. Ten a mano el cable de alimentación del
follower la primera vez que pruebes cada cambio.
