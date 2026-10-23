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

1. **Elegir plantilla**: al abrir la app se carga la **última fórmula usada**. También se
   puede escoger una **plantilla guardada**.
2. **Editar**: el cliente toca alveolos para cambiar su semilla, o usa los botones de
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
  la cámara y el progreso. Es el único sitio que habla con el hardware.
- **Ejecución en el robot**, enfoque híbrido:
  - **Coger la semilla** de la caja de un color: una policy de LeRobot entrenada con
    demostraciones teleoperadas (ACT, una por color, o una SmolVLA condicionada por texto
    del tipo *"pick a seed from the red box"*).
  - **Soltarla en el alveolo**: posiciones articulares enseñadas con el brazo leader.
    Se graban las 4 esquinas del semillero y el resto se interpola, o se graba cada
    alveolo si da tiempo.

Plan B: si la policy no es fiable a tiempo, la recogida también se hace con
posiciones enseñadas y la policy aprendida queda como mejora de la demo.

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
- [ ] Montar el leader y el follower, calibrarlos y comprobar que la teleoperación va bien.
- [ ] Fijar a la mesa el semillero y las 4 cajas de colores. **No se mueven más.**
- [ ] Colocar la cámara cenital (`top`), que vea el semillero y las cajas entero, y la del
      brazo (`wrist`).
- [ ] Elegir semillas que se puedan coger con la pinza, o usar sustitutos de prueba
      (bolitas, cuentas) para entrenar.

### 2. Interfaz (viernes-sábado)
- [ ] Rejilla de alveolos tipo cine, con tamaño configurable.
- [ ] Selector de las 4 semillas/colores y botones de "rellenar todo de un color".
- [ ] Guardar y cargar plantillas, y cargar automáticamente la última fórmula usada.
- [ ] Botón **Listo** que envía el plan al backend, con vista de progreso.
- [ ] Imagen de la cámara cenital con la rejilla superpuesta.

### 3. Backend y conexión con el robot (sábado)
- [ ] Servidor local (FastAPI + WebSocket) con los endpoints `POST /plan`, `POST /stop`
      y `WS /progress`, y streaming de la cámara.
- [ ] Mapa alveolo → posición articular: enseñar las 4 esquinas con el leader e
      interpolar.
- [ ] Ejecutor de la cola con parada segura: **Stop** desactiva el par de los motores.

### 4. Datos y policy (viernes noche-sábado)
- [ ] Grabar unos 50 episodios por color de "coger semilla de la caja X" con
      `lerobot-record`.
- [ ] Subir los datasets al Hub de Hugging Face.
- [ ] Entrenar (ACT en el Mac durante la noche, o en GPU cloud) y probar con rollout.

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
  README.md                 notas del prototipo de la interfaz
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
