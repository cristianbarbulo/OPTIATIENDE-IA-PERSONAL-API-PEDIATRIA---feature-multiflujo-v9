## Arquitectura de Agentes y Flujos (Documento Maestro)

Este documento describe, de forma operativa y completa, cómo el sistema procesa los mensajes, qué agentes participan, qué datos reciben/devuelven, y qué decisiones toma en cada caso. Está alineado con el estado actual del código en `main.py`, `llm_handler.py`, `agendamiento_handler.py`, `pago_handler.py`, `memory.py` y utilidades relacionadas.

### 1. Objetivo del sistema
- Convertir cualquier mensaje entrante en una acción concreta (agendar, reprogramar, pagar, cancelar) con mínima fricción y sin “dar vueltas”.
- Mantener consistencia de estado, trazabilidad y una experiencia de lenguaje natural, breve y resolutiva.

### 2. Componentes principales
- **Orquestador** (`main.py`): coordina todo el flujo. Reconstruye mensajes, decide ruta, aplica blindaje de dominio y ejecuta acciones.
- **Meta-Agente** (`llm_handler.llamar_meta_agente`): clasifica por comandos explícitos (`QUIERO AGENDAR`, `QUIERO PAGAR`, `QUIERO REPROGRAMAR`, `SALIR DE AGENDA`, `SALIR DE PAGO`) y extrae datos (fecha, hora, servicio, preferencias).
- **Agente Cero Híbrido** (en `main.py`): fuera de flujo contesta con texto o recomienda acciones en JSON y educa los comandos explícitos.
- **Handlers de Dominio** (`agendamiento_handler.py`, `pago_handler.py`): implementan negocio (buscar turnos, crear/reprogramar evento, listar servicios, generar link, confirmar pago).
- **Persistencia** (`memory.py`): guarda y recupera `conversation_state`, `state_context` e historial en Firestore.
- **Interacciones/IO** (`msgio_handler.py`, `chatwoot_integration.py`): envío de mensajes, payloads interactivos, logging a Chatwoot.

### 3. Flujo de alto nivel (texto/audio)
1) Recepción webhook → reconstrucción del mensaje: `main._reconstruir_mensaje_usuario(...)` une el contenido útil y construye `mensaje_completo_usuario` e historial a guardar.
2) Determinación del camino:
   - Si hay flujo activo (`PAGOS_*` o `AGENDA_*`), `wrapper_preguntar` aplica blindaje y reofrece opciones del dominio con botones/listas (sin Agente Cero).
   - Si NO hay flujo activo, Agente Cero puede responder con texto o recomendar acción (JSON) y educa los comandos.
3) Meta-Agente decide y/o el Agente Cero recomienda acción. El orquestador ejecuta la acción mapeada (MAPA_DE_ACCIONES) y persiste contexto/estado.
4) En flujos activos, nunca se usa texto conversacional: siempre botones/listas. La selección de IDs temporales dispara acciones seguras.

### 4. Agente Cero (excepción controlada)
- Responde fuera de flujo con `RESPUESTA_GENERAL` o JSON con `accion_recomendada`.
- Educa comandos exactos. En flujo activo, no se usa; `wrapper_preguntar` reofrece opciones (turnos/servicios) con botones/listas.

### 5. Meta-Agente (clasificación y extracción)
- Función: `llamar_meta_agente(texto, history, current_state)`.
- Lógica: comandos explícitos → decisión directa; además extrae datos (fecha, hora, preferencias/servicio). Detección estricta de `QUIERO REPROGRAMAR`.

### 6. Extracción integrada (sin agentes de intención)
La extracción de entidades (fecha/hora/preferencias/servicio) ocurre dentro de `llm_handler.llamar_meta_agente`. No existen agentes de intención separados en V10.
Anti-bucle: `triage_count` controla reintentos y permite `escalar_a_humano` si aplica.

### 7. Handlers de dominio (acciones reales)

#### 7.1 Agendamiento (`agendamiento_handler.py`)
- `iniciar_triage_agendamiento(history, detalles, state_context, mensaje, author)`
  - Preserva `fecha_deseada`/`hora_especifica`/`preferencia_horaria` si llegan en `detalles`.
  - `current_state='AGENDA_MOSTRANDO_OPCIONES'` y llama a `mostrar_opciones_turnos`.
- `mostrar_opciones_turnos(...)`
  - Obtiene slots (caché/servicio), prioriza por `hora_especifica`/`preferencia_horaria`/restricciones.
  - Guarda `available_slots` y `available_slots_sent` y envía lista interactiva (IDs temporales `turno_...`).
- `confirmar_turno_directo(...)`
  - Acepta selección por número o ID temporal; llama directo a `finalizar_cita_automatico`.
- `finalizar_cita_automatico(...)`
  - Identifica el slot seleccionado (si no está, lo machea desde `available_slots_sent`).
  - Crea o reprograma evento (Google Calendar), guarda `last_event_id`, persiste `ultimo_turno_confirmado`.
  - `current_state='evento_creado'` y responde confirmación.
- Reprogramación (`iniciar_reprogramacion_cita`, `mostrar_opciones_turnos_reprogramacion`, `finalizar_cita_automatico`):
  - Activa SOLO con `QUIERO REPROGRAMAR` y si existe una cita confirmada (guard central en `main._ejecutar_accion`).
  - Establece `es_reprogramacion=True`, asegura `last_event_id` desde la cita previa y limpia `slot_seleccionado` viejo.
  - Lista opciones y, al elegir, reprograma el evento (mantiene `event_id`) y actualiza memoria.
- Cancelación (`iniciar_cancelacion_cita`, `confirmar_cancelacion`, `ejecutar_cancelacion_cita`):
  - Identifica cita y ejecuta cancelación con confirmación por botones.

#### 7.2 Pagos (`pago_handler.py`)
- `iniciar_triage_pagos(...)`
  - `current_state='PAGOS_ESPERANDO_SELECCION_SERVICIO'` y llama a `mostrar_servicios_pago` (catálogo central, IDs temporales `servicio_...`).
- `confirmar_servicio_pago(...)`
  - Acepta selección (número/ID temporal), pasa a `PAGOS_ESPERANDO_CONFIRMACION` con botones Sí/No.
- `generar_link_pago(...)`
  - Genera link (servicio de pago con retry/backoff), limpia contexto a mínimo y deja `current_state='conversando'` por diseño. El blindaje de estado permite seguir a agenda solo con pago verificado o comandos explícitos.
- `confirmar_pago(...)`
  - Detecta comprobante (imagen/texto) y marca verificación.
- `reanudar_flujo_anterior(...)`
  - Si `PAGOS_*` → reanuda servicios/confirmación; si `AGENDA_*` → reenvía opciones de turnos.

### 8. Interactivos (botones/listas): validación y atajos
- En `main.py`, la validación de IDs interactivos fuerza acciones seguras:
  - `turno_*` → `finalizar_cita_automatico` (agenda/reprogramación)
  - `servicio_*` → `confirmar_servicio_pago` (pagos)
- Justificación: IDs generados por el sistema llevan la info necesaria; evita ambigüedades.

### 9. Generador (ELIMINADO)
No hay generador conversacional separado. Agente Cero cubre conversación general y educación. En flujos activos, `wrapper_preguntar` evita texto y reofrece opciones con botones/listas.

### 10. Persistencia y estado (Firestore)
- `memory.get_conversation_data(author)` devuelve: `history`, `last_updated`, `conversation_state`, `state_context`.
- `memory.update_conversation_state(author, new_state, context=...)` guarda estado/contexto.
- Stack de contexto: `apilar_contexto` / `desapilar_contexto` prioriza contextos críticos.

### 11. Estados estándar
- Agendamiento: `AGENDA_MOSTRANDO_OPCIONES`, `AGENDA_REPROGRAMACION_ESPERANDO_CONFIRMACION_FINAL`, `evento_creado`.
- Pagos: `PAGOS_ESPERANDO_SELECCION_SERVICIO`, `PAGOS_ESPERANDO_CONFIRMACION`, `conversando`.
- Estado base: `conversando`.

### 12. Casos clave (cómo se resuelven)
- “Dale/ok/sí” tras oferta: se interpreta como aceptación; el sistema mantiene el dominio activo y ejecuta la acción segura.
- “Quiero miércoles 16hs” en medio de agenda: no se usa Agente Cero; `wrapper_preguntar` inyecta fecha/hora y reofrece turnos.
- Comprobante de pago (imagen/texto/URL): `confirmar_pago` responde automático y marca flags de verificación.
- “QUIERO REPROGRAMAR”: entra al flujo de reprogramación si y solo si hay cita confirmada; si no, educa “Para agendar, escribí: QUIERO AGENDAR”.

### 13. Principios y garantías
- Cero vueltas: en flujos activos no se usa texto conversacional; solo botones/listas.
- Consistencia de dominio: blindaje en `wrapper_preguntar`; transición `PAGOS_* → AGENDA_*` solo si `payment_verified=True`.
- Seguridad: IDs interactivos → acciones directas; guardia de reprogramación en `main._ejecutar_accion`.
- Observabilidad: logging detallado (filtros, slots, decisiones) y registro en Chatwoot.

### 14. Referencias útiles (rutas/funciones)
- Orquestador: `main.py` → `_obtener_estrategia`, `_ejecutar_accion`, `MAPA_DE_ACCIONES`, `wrapper_preguntar`.
- Agendamiento: `agendamiento_handler.py` → `iniciar_triage_agendamiento`, `mostrar_opciones_turnos`, `mostrar_opciones_turnos_reprogramacion`, `finalizar_cita_automatico`.
- Pagos: `pago_handler.py` → `iniciar_triage_pagos`, `mostrar_servicios_pago`, `confirmar_servicio_pago`, `generar_link_pago`, `confirmar_pago`.
- Agentes: `llm_handler.py` → `llamar_meta_agente` (comandos y extracción integrada).
- Persistencia: `memory.py` → `get_conversation_data`, `update_conversation_state`, `apilar_contexto`, `desapilar_contexto`.

---

Este documento refleja el contrato actual del sistema V10. Si se agrega o remueve alguna acción/estado, actualizar aquí para mantener el mapa operativo vivo y confiable.


