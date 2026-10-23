# Brota 🌱 — Control de siembra con LeRobot

Prototipo responsive, mobile-first para una hackathon de LeRobot. Interfaz en español para seleccionar semillas, preparar órdenes de siembra y visualizar el estado del robot.

## Primera versión
- Dashboard con métricas del semillero.
- Selector de semillas (tomate, lechuga, zanahoria, albahaca, girasol y pimiento).
- Cantidad por orden y cola de siembra.
- Controles interactivos de iniciar, pausar y reanudar en **modo demo**.
- Progreso simulado y actividad reciente.
- Diseño adaptable a móvil, tablet y escritorio.

## Probar
Abre `index.html` directamente en el navegador. No necesita instalación ni dependencias de compilación.

## Importante: conexión con el robot
Esta versión es únicamente la interfaz visual: **no envía todavía comandos reales al robot**. Los estados, el progreso y las órdenes son simulados en el navegador. Para integrar el LeRobot físico habrá que definir el hardware y el entorno de ejecución, y añadir una API/backend seguro que traduzca las órdenes de la interfaz a acciones del robot. Los botones de pausa/reanudación deben conectarse a un mecanismo de parada seguro del controlador real antes de operar hardware.

## Próximos pasos sugeridos
1. Definir robot, actuadores, cámara/sensores y mecanismo de dosificación.
2. Acordar el protocolo entre frontend y backend (REST o WebSocket).
3. Modelar estados reales: desconectado, listo, sembrando, pausado, error y completado.
4. Añadir confirmación de órdenes, telemetría y tratamiento de errores.
5. Validar parada de emergencia y seguridad física.

## Tecnología
HTML, CSS y JavaScript sin framework; mobile-first y accesible con controles de teclado.
