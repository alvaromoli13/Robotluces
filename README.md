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
- **Ejecución en el robot**: enfoque híbrido, ver la sección siguiente.

## Enfoque del robot: híbrido

Cada alveolo del plan se siembra en dos fases:

| Fase | Cómo se hace | Qué se mueve en la escena |
|---|---|---|
| 1. **Coger** la "semilla" de la caja del color X | **Policy aprendida** de LeRobot, entrenada con demostraciones teleoperadas | Las **cajas pueden moverse** unos centímetros: la policy las encuentra con la cámara |
| 2. **Soltarla** en el alveolo (fila, columna) | **Posiciones enseñadas**: se graban las 4 esquinas del semillero con el leader y el resto se interpola | El **semillero va fijo** a la mesa, con topes o cinta |

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
- **Plan B**: si la policy no es fiable a tiempo, las cajas también se fijan y la recogida
  se hace con posiciones enseñadas. La demo sale igual y la policy queda como mejora.

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
- [ ] Montar el leader y el follower, calibrarlos y comprobar que la teleoperación va bien.
- [ ] Conseguir las pelotas y las 4 cajas de colores (ver [Escena y objetos](#escena-y-objetos)).
- [ ] **Fijar el semillero** a la mesa con topes o cinta. Marcar en la mesa la zona de
      cada caja: se pueden mover dentro de su zona.
- [ ] Colocar la cámara cenital (`top`), que vea el semillero y todas las zonas de las
      cajas, y la del brazo (`wrist`). Las cámaras no se mueven más.
- [ ] Probar con la teleoperación que se coge una pelota de cada caja y se suelta en un
      alveolo.

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
