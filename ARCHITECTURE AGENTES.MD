## Arquitectura de Agentes y Flujos (Documento Maestro)

Este documento describe, de forma operativa y completa, cómo el sistema procesa los mensajes, qué agentes participan, qué datos reciben/devuelven, y qué decisiones toma en cada caso. Está alineado con el estado actual del código en `main.py`, `llm_handler.py`, `agendamiento_handler.py`, `pago_handler.py`, `memory.py` y utilidades relacionadas.

### 1. Objetivo del sistema
- Convertir cualquier mensaje entrante en una acción concreta (agendar, reprogramar, pagar, cancelar) con mínima fricción y sin “dar vueltas”.
- Mantener consistencia de estado, trazabilidad y una experiencia de lenguaje natural, breve y resolutiva.

### 2. Componentes principales
- **Orquestador** (`main.py`): coordina todo el flujo. Reconstruye mensajes, decide ruta, invoca meta-agente, agentes de intención y ejecuta acciones.
- **Meta-Agente** (`llm_handler.llamar_meta_agente`): clasifica el dominio del mensaje: `AGENDAMIENTO` o `PAGOS`.
- **Agentes de Intención** (`llm_handler.llamar_agente_intencion_agendamiento` / `llm_handler.llamar_agente_intencion_pagos`): extraen entidades y recomiendan una acción dentro de un menú limitado y seguro.
- **Handlers de Dominio** (`agendamiento_handler.py` y `pago_handler.py`): implementan la lógica real del negocio (buscar turnos, crear evento, listar servicios, generar link, etc.).
- **Generador** (`llm_handler.llamar_rodi_generador`): produce el copy conversacional cuando no hay flujo activo; nunca toma decisiones de negocio.
- **Persistencia** (`memory.py`): guarda y recupera `conversation_state`, `state_context` e historial en Firestore.
- **Interacciones/IO** (`msgio_handler.py`, `chatwoot_integration.py`): envío de mensajes, payloads interactivos, logging a Chatwoot.

### 3. Flujo de alto nivel (texto/audio)
1) Recepción webhook → reconstrucción del mensaje: `main._reconstruir_mensaje_usuario(...)` une el contenido útil y construye `mensaje_completo_usuario` e historial a guardar.
2) Determinación del camino:
   - Si hay flujo activo o señales (por ej. `current_state` empieza con `AGENDA_`/`PAGOS_`, o existen `available_slots`/`available_slots_sent`), ir directo a Meta-Agente + Agentes de Intención del dominio (omitir Agente Cero).
   - Si NO hay flujo activo y el lock lo permite, se puede usar Agente Cero (excepción conversacional) para una `RESPUESTA_GENERAL`.
3) Meta-Agente decide dominio (`AGENDAMIENTO`/`PAGOS`).
4) Agente de Intención del dominio extrae entidades y recomienda una `accion_recomendada`.
5) Orquestador ejecuta la acción mapeada a los handlers (MAPA_DE_ACCIONES) y persiste contexto/estado.
6) Si la acción fue “preguntar” y hay flujo activo, se reanuda el dominio sin usar generador; si no hay flujo activo, se usa el Generador con `context_info` enriquecido.

### 4. Agente Cero (excepción controlada)
- ÚNICO caso permitido de responder sin pasar por intenciones. Útil fuera de flujo para `RESPUESTA_GENERAL`.
- Lock: `state_context['pasado_a_departamento']=True` al iniciar triage; el Agente Cero queda bloqueado por 48h.
- `memory.update_conversation_state` ya no resetea `pasado_a_departamento` cuando guarda `INITIAL` (preserva el lock).
- Si retorna “PASADO_A_DEPARTAMENTO”, el orquestador arranca flujo normal (Meta-Agente + Intenciones + Acción).

### 5. Meta-Agente (clasificación de dominio)
- Función: `llamar_meta_agente(texto, history, current_state)`.
- Lógica: palabras clave fuertes → decisión directa; si ambiguo, mira `current_state` para mantener consistencia; si aún ambiguo, usa LLM para responder SOLO `PAGOS` o `AGENDAMIENTO`.

### 6. Agentes de Intención (qué reciben, qué devuelven, qué deciden)
- Entrada común: `texto`, `history`, `current_state`, `contexto_extra`.
- Salida común: `{"accion_recomendada": <string>, "detalles": <dict>}` (siempre dentro de acciones válidas).

#### 6.1 Agendamiento – `llamar_agente_intencion_agendamiento`
- Extrae: `fecha_deseada (YYYY-MM-DD)`, `hora_especifica (HH:MM)`, `preferencia_horaria` (mañana/tarde), `restricciones_temporales` (p.ej. `después_16`, `excluir_miércoles`).
- Acciones válidas:
  - `iniciar_triage_agendamiento` (principal para buscar/mostrar turnos).
  - `iniciar_reprogramacion_cita` (si el usuario cambia fecha/hora y ya tiene turno).
  - `iniciar_cancelacion_cita` (cancelar una cita).
  - `preguntar` (preguntas generales, no flujo).
- Notas:
  - Si devuelve una acción de triage/reprogramación, el handler usa entidades extraídas para priorizar slots.
  - Si devolviera `preguntar` con flujo activo, el orquestador reofrece turnos (no generador).

#### 6.2 Pagos – `llamar_agente_intencion_pagos`
- Extrae: `servicio_deseado`.
- Acciones válidas:
  - `iniciar_triage_pagos` (lista servicios → confirmación → link).
  - `confirmar_pago` (cuando el usuario envía comprobante/imagen).
  - `preguntar` (dudas generales).
- Notas:
  - Si `preguntar` con flujo activo, se reanuda pagos (lista/confirmación) sin generador.

#### 6.3 Anti-bucle
- `state_context['triage_count']` incrementa en cada triage consecutivo; al llegar a 3 → `escalar_a_humano`.

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
- Reprogramación (`iniciar_reprogramacion_cita`, `mostrar_opciones_turnos_reprogramacion`, `ejecutar_reprogramacion_cita`):
  - Usa `last_event_id`/cita previa; muestra opciones y reprograma directo.
- Cancelación (`iniciar_cancelacion_cita`, `confirmar_cancelacion`, `ejecutar_cancelacion_cita`):
  - Identifica cita (con ayuda del Agente de Intención de agendamiento si hace falta) y ejecuta cancelación.

#### 7.2 Pagos (`pago_handler.py`)
- `iniciar_triage_pagos(...)`
  - `current_state='PAGOS_ESPERANDO_SELECCION_SERVICIO'` y llama a `mostrar_servicios_pago` (catálogo central, IDs temporales `servicio_...`).
- `confirmar_servicio_pago(...)`
  - Acepta selección (número/ID temporal), pasa a `PAGOS_ESPERANDO_CONFIRMACION` con botones Sí/No.
- `generar_link_pago(...)`
  - Genera link (servicio de pago con retry/backoff), limpia contexto a mínimo y deja `current_state='conversando'`.
- `confirmar_pago(...)`
  - Detecta comprobante (imagen/texto) y marca verificación simple.
- `reanudar_flujo_anterior(...)`
  - Si `PAGOS_*` → reanuda servicios/confirmación; si `AGENDA_*` → reenvía opciones de turnos.

### 8. Interactivos (botones/listas): validación y atajos
- En `main.py`, `_validar_id_interactivo(...)` reconoce IDs y fuerza acciones seguras:
  - `turno_*` → `finalizar_cita_automatico` (agenda).
  - `servicio_*` → `confirmar_servicio_pago` (pagos).
- Justificación: IDs generados por el sistema llevan la info necesaria; evita ambigüedades.

### 9. Generador (copy conversacional)
- Función: `llamar_rodi_generador(prompt_base, history, context_info)`.
- Se usa cuando NO hay flujo activo o cuando `preguntar` no está en flujo.
- Enriquecimiento automático en `wrapper_preguntar` (main):
  - Mapea señales del sistema hacia claves que el prompt entiende: `estado_agenda`, `horarios_disponibles`, `id_evento`, `estado_pago`, `plan`, `monto`, `proveedor`, `link_pago`, `estado_general`.
- Reglas de estilo: 4–5 líneas, 0–1 emoji, sin JSON/código, sin inventar datos; derivación “en copy”, acciones las ejecuta el sistema.

### 10. Persistencia y estado (Firestore)
- `memory.get_conversation_data(author)` devuelve: `history`, `last_updated`, `conversation_state`, `state_context`.
- `memory.update_conversation_state(author, new_state, context=...)` guarda estado/contexto (sin forzar `pasado_a_departamento=False`).
- Limpieza de compatibilidad: `_clean_context_for_firestore` (en `main.py` y `memory.py`) permite `datetime`, listas/dicts compatibles.
- Stack de contexto: `apilar_contexto` / `desapilar_contexto` prioriza contextos críticos (evento creado, pago registrado). 

### 11. Estados estándar
- Agendamiento: `AGENDA_MOSTRANDO_OPCIONES`, `AGENDA_CONFIRMANDO_TURNO`, `AGENDA_REPROGRAMACION_*`, `evento_creado`.
- Pagos: `PAGOS_ESPERANDO_SELECCION_SERVICIO`, `PAGOS_ESPERANDO_CONFIRMACION`, `conversando`.
- Estado base: `conversando` (no se usa `preguntando`).
- Lock Agente Cero: `pasado_a_departamento=True` durante 48h tras iniciar triage.

### 12. Casos clave (cómo se resuelven)
- “Dale/ok/sí” tras oferta: se interpreta como aceptación → Meta-Agente + Intención → acción del dominio.
- “Quiero miércoles 16hs” en medio de agenda: no generador; extracción de fecha/hora con Agente de Intención de agenda y reofrecer turnos.
- Comprobante de pago (imagen/texto/URL): `confirmar_pago` responde automático y marca flags.
- Triages repetidos: a la 3ª vez → `escalar_a_humano`.

### 13. Principios y garantías
- Cero vueltas: si hay intención o flujo activo, actuar; Generador solo cuando no hay flujo.
- Consistencia de dominio: Meta-Agente mantiene el dominio cuando hay estado activo.
- Seguridad: IDs interactivos → acciones directas; lock 48h para evitar reentrar a Agente Cero; anti-bucle.
- Observabilidad: logging detallado y registro en Chatwoot.

### 14. Referencias útiles (rutas/funciones)
- Orquestador: `main.py` → `_obtener_estrategia`, `_ejecutar_accion`, `MAPA_DE_ACCIONES`, `wrapper_preguntar`.
- Agendamiento: `agendamiento_handler.py` → `iniciar_triage_agendamiento`, `mostrar_opciones_turnos`, `finalizar_cita_automatico`, reprogramación/cancelación.
- Pagos: `pago_handler.py` → `iniciar_triage_pagos`, `mostrar_servicios_pago`, `confirmar_servicio_pago`, `generar_link_pago`, `confirmar_pago`.
- Agentes: `llm_handler.py` → `llamar_meta_agente`, `llamar_agente_intencion_agendamiento`, `llamar_agente_intencion_pagos`, `llamar_rodi_generador`.
- Persistencia: `memory.py` → `get_conversation_data`, `update_conversation_state`, `apilar_contexto`, `desapilar_contexto`.

---

Este documento refleja el contrato actual del sistema. Si se agrega o remueve alguna acción/estado, actualizar aquí para mantener el mapa operativo vivo y confiable.


