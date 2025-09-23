# 🔄 SISTEMA DE REVIVAL DE CONVERSACIONES - DOCUMENTACIÓN COMPLETA

## 📋 RESUMEN EJECUTIVO

Sistema automatizado que reactiva conversaciones inactivas usando IA (GPT-4) para decidir estrategias personalizadas por cliente. Funciona con un cron central que llama a múltiples clientes cada 6 horas, analizando conversaciones una sola vez en su historia.

## 🏗️ ARQUITECTURA DEL SISTEMA

### Componentes Principales:

1. **CRON SERVICE** - Servicio independiente en Render ($7/mes)
2. **REVIVAL HANDLER** - Endpoint en cada cliente 
3. **REVIVAL AGENT** - IA con GPT-4 para análisis
4. **MEMORY SYSTEM** - Gestión de datos en Firestore

---

## 📁 ESTRUCTURA DE ARCHIVOS

### CRON SERVICE (Servicio Independiente)
```
cron-revival-service/
├── main.py                    # Cron principal multi-cliente
├── requirements.txt           # Dependencias: requests, python-dotenv
├── render.yaml               # Configuración de deploy
└── README_SISTEMA_REVIVAL_COMPLETO.md  # Esta documentación
```

### CLIENTE (Modificaciones en código existente)
```
OPTIATIENDE-IA-/
├── main.py                   # +9 líneas: registro de blueprint
├── memory.py                 # +3 campos CRITICAL_KEYS + función
├── revival_handler.py        # NUEVO: Handler con endpoints
└── revival_agent.py          # NUEVO: IA para análisis
```

---

## 🔧 ARCHIVO POR ARCHIVO - DOCUMENTACIÓN DETALLADA

### 1. `cron-revival-service/main.py`

**PROPÓSITO:** Cron central que dispara revival en múltiples clientes cada 6 horas.

**FUNCIONES PRINCIPALES:**
- `RevivalCronService.__init__()` - Carga configuración desde env vars
- `_load_active_clients()` - Parsea JSON de clientes activos
- `trigger_client_revival()` - Hace POST a un cliente específico
- `run_revival_cycle()` - Ejecuta ciclo completo para todos los clientes

**VARIABLES DE ENTORNO REQUERIDAS:**
```bash
CRON_SECRET_KEY=tu_secreto_123          # Clave para validar clientes
ACTIVE_CLIENTS=[JSON_ARRAY]             # Lista de clientes activos
REQUEST_TIMEOUT=30                      # Timeout por cliente (segundos)
DRY_RUN=false                          # true=solo simula, false=ejecuta
```

**FORMATO ACTIVE_CLIENTS:**
```json
[
  {
    "name": "NombreCliente",
    "url": "https://cliente.onrender.com",
    "enabled": true
  }
]
```

**FLUJO DE EJECUCIÓN:**
1. Cron se ejecuta cada 6 horas (schedule: `0 */6 * * *`)
2. Lee clientes activos desde ACTIVE_CLIENTS
3. Para cada cliente con `enabled: true`:
   - Hace POST a `{url}/api/revival/process`
   - Header: `X-Revival-Secret: {CRON_SECRET_KEY}`
   - Timeout: REQUEST_TIMEOUT segundos
4. Registra resultados en logs

**LOGS GENERADOS:**
```
🔄 Disparando revival para ClienteA -> https://...
✅ ClienteA: Procesado exitosamente
❌ ClienteB: Error de conexión
📊 Ciclo completado: 2/3 clientes exitosos en 15.2s
```

---

### 2. `cron-revival-service/requirements.txt`

**DEPENDENCIAS MÍNIMAS:**
```txt
requests==2.31.0        # HTTP calls a clientes
python-dotenv==1.0.0    # Variables de entorno (opcional)
```

**NOTA:** Se removieron pydantic, colorlog, python-dateutil para evitar errores de compilación Rust.

---

### 3. `cron-revival-service/render.yaml`

**CONFIGURACIÓN DE DEPLOY:**
```yaml
services:
  - type: cron
    name: revival-cron-multi-client
    runtime: python3
    plan: starter
    buildCommand: pip install -r requirements.txt
    startCommand: python main.py
    schedule: "0 */6 * * *"
```

---

### 4. `revival_handler.py` (EN CADA CLIENTE)

**PROPÓSITO:** Maneja endpoints de revival y orquesta el proceso completo.

**CLASES PRINCIPALES:**
- `RevivalHandler` - Coordinador principal
- `RevivalHandlerError` - Excepciones específicas

**ENDPOINTS EXPUESTOS:**
- `POST /api/revival/process` - Endpoint principal llamado por cron
- `GET /api/revival/status` - Estado del sistema (debug)

**VARIABLES DE ENTORNO RECONOCIDAS:**
```bash
REVIVAL_ENABLED=true/false              # Habilita/deshabilita sistema
REVIVAL_SECRET_KEY=secreto              # Debe coincidir con cron
REVIVAL_MAX_PER_CYCLE=50               # Máx conversaciones por ciclo
REVIVAL_DRY_RUN=true/false             # Simula sin enviar mensajes
REVIVAL_PROMPT=prompt_personalizado     # Prompt específico del cliente
```

**FLUJO INTERNO:**
1. Valida `X-Revival-Secret` header
2. Verifica `REVIVAL_ENABLED=true`
3. Obtiene conversaciones candidatas desde `memory.get_conversations_for_revival()`
4. Para cada conversación:
   - Inicializa `RevivalAgent` con prompt personalizado
   - Analiza conversación completa
   - Si decisión = SEND: envía mensaje vía WhatsApp
   - Si decisión = IGNORE: etiqueta conversación
   - Actualiza `state_context` con resultado
5. Retorna resumen JSON

**VALIDACIONES DE SEGURIDAD:**
- Estados críticos protegidos: `AGENDA_CONFIRMANDO_TURNO`, `PAGOS_PROCESANDO_PAGO`, etc.
- Conversaciones ya procesadas (tienen `revival_status`) son omitidas
- Límite máximo de conversaciones por ciclo
- Verificación de historial mínimo

---

### 5. `revival_agent.py` (EN CADA CLIENTE)

**PROPÓSITO:** IA especializada en análisis de conversaciones para revival.

**CONFIGURACIÓN OPENAI:**
```bash
OPENAI_API_KEY=sk-...                  # API key de OpenAI
OPENAI_ORG_ID=org-...                  # Organización (opcional)
REVIVAL_AI_MODEL=gpt-4                 # Modelo a usar (default: gpt-4)
REVIVAL_MAX_TOKENS=500                 # Máx tokens respuesta
REVIVAL_TEMPERATURE=0.7                # Creatividad del modelo
```

**MÉTODOS PRINCIPALES:**
- `analyze_conversation()` - Análisis principal
- `_prepare_conversation_context()` - Prepara contexto para IA
- `_call_openai_api()` - Llamada a OpenAI
- `_validate_ai_response()` - Valida y sanitiza respuesta

**INPUT PARA IA:**
```
INFORMACIÓN DE LA CONVERSACIÓN:
- Teléfono: 5493413167185
- Nombre: Juan Pérez
- Estado actual: conversando
- Último mensaje del cliente: "me interesa pero después veo"
- Timestamp último mensaje: 2024-01-15T10:30:00Z
- Turno confirmado: Lunes 20/01 - 14:00
- Pago verificado: $500

HISTORIAL RECIENTE (últimos 10 mensajes):
1. [Cliente] Hola, necesito información sobre sus servicios
2. [Asistente] ¡Hola Juan! Te ayudo con gusto...
...

CONTEXTO ADICIONAL:
- Total mensajes en historial: 15
- Estado del contexto: {...}
```

**OUTPUT DE IA (JSON):**
```json
{
  "action": "SEND" | "IGNORE",
  "message": "Hola Juan, vi que te interesaba nuestro servicio...",
  "tag": "PRESUPUESTO_RECHAZADO" | null,
  "confidence": 0.85,
  "reasoning": "Cliente mostró interés inicial pero está postergando"
}
```

**ETIQUETAS PERSONALIZADAS POR CLIENTE:**
- **Psicólogo:** `ABANDONO_TERAPIA`, `RESISTENCIA_TRATAMIENTO`, `SIN_COMPROMISO`
- **Dentista:** `MIEDO_DENTAL`, `PROBLEMA_ECONOMICO`, `URGENCIA_RESUELTA`
- **Veterinaria:** `MASCOTA_FALLECIDA`, `CAMBIO_VETERINARIO`, `TRATAMIENTO_COMPLETO`

---

### 6. `memory.py` (MODIFICACIONES)

**MODIFICACIONES REALIZADAS:**

#### A) Agregado a `CRITICAL_KEYS`:
```python
'revival_status',           # Estado del revival: null, "ATTEMPTED", "DEAD", etc.
'revival_timestamp',        # Cuándo fue procesado
'revival_metadata'          # Metadatos del análisis
```

#### B) Nueva función:
```python
def get_conversations_for_revival() -> List[Dict[str, Any]]:
```

**PROPÓSITO:** Obtiene conversaciones candidatas sin `revival_status`.

**CRITERIOS DE FILTRADO:**
- `state_context.revival_status == null` (nunca procesadas)
- Historial con al menos 1 mensaje del usuario
- No en estados críticos del sistema principal
- Límite de 100 conversaciones por consulta

**QUERY FIRESTORE:**
```python
query = conversations_ref.where("state_context.revival_status", "==", None)
```

---

### 7. `main.py` (MODIFICACIONES MÍNIMAS)

**LÍNEAS AGREGADAS (al final del archivo):**
```python
# =============================================================================
# REGISTRO DE BLUEPRINTS - REVIVAL SYSTEM
# =============================================================================

# Registrar blueprint de revival de conversaciones (opcional y seguro)
try:
    from revival_handler import register_revival_blueprint
    register_revival_blueprint(app)
    logger.info("✅ Sistema de revival de conversaciones registrado")
except ImportError:
    logger.info("ℹ️ Sistema de revival no disponible (revival_handler.py no encontrado)")
except Exception as e:
    logger.warning(f"⚠️ Error registrando sistema de revival: {e}")
```

**CARACTERÍSTICAS DE SEGURIDAD:**
- Try/catch evita que errores rompan el sistema principal
- ImportError manejado gracefully
- No afecta funcionalidad existente si falta revival_handler.py

---

## 🚀 CONFIGURACIÓN POR CLIENTE

### Variables Obligatorias en CADA Cliente:
```bash
# === BÁSICO ===
REVIVAL_ENABLED=true                    # Habilita el sistema
REVIVAL_SECRET_KEY=mismo_que_cron       # DEBE coincidir con cron

# === PROMPT PERSONALIZADO ===
REVIVAL_PROMPT="Eres un asistente de [ESPECIALIDAD]. Analiza conversaciones sobre [CONTEXTO]. Si decides NO reactivar, usa etiquetas: [ETIQUETAS_ESPECIFICAS]. Responde en formato JSON."

# === OPCIONALES ===
REVIVAL_MAX_PER_CYCLE=50               # Default: 50
REVIVAL_DRY_RUN=false                  # Default: false
REVIVAL_AI_MODEL=gpt-4                 # Default: gpt-4
REVIVAL_MAX_TOKENS=500                 # Default: 500
REVIVAL_TEMPERATURE=0.7                # Default: 0.7
```

### Ejemplos de Prompts por Vertical:

#### Psicólogo:
```bash
REVIVAL_PROMPT="Eres un asistente de consultoría psicológica especializado en reactivar conversaciones de pacientes. Analiza el historial y decide si vale la pena reactivar. Si decides NO enviar mensaje, usa etiquetas específicas: ABANDONO_TERAPIA, RESISTENCIA_TRATAMIENTO, SIN_COMPROMISO, DERIVADO_OTRO_PROFESIONAL, PROBLEMA_ECONOMICO, MIEDO_ESTIGMA, TERAPIA_FAMILIAR_CONFLICTO. Genera mensajes empáticos que respeten el proceso terapéutico. Responde SOLO en formato JSON válido."
```

#### Dentista:
```bash
REVIVAL_PROMPT="Eres un asistente dental especializado en reactivar conversaciones de pacientes. Considera el contexto odontológico y la ansiedad dental común. Si decides NO reactivar, usa etiquetas: MIEDO_DENTAL, PROBLEMA_ECONOMICO, URGENCIA_RESUELTA, CAMBIO_DENTISTA, TRATAMIENTO_COMPLETO, DOLOR_RESUELTO, SIN_SEGURO, PROCEDIMIENTO_CANCELADO. Genera mensajes que reduzcan la ansiedad dental. Responde en formato JSON."
```

#### Veterinaria:
```bash
REVIVAL_PROMPT="Eres un asistente veterinario especializado en reactivar conversaciones sobre mascotas. Considera el vínculo emocional con las mascotas. Si NO reactivar, etiquetas: MASCOTA_FALLECIDA, CAMBIO_VETERINARIO, TRATAMIENTO_COMPLETO, SIN_MASCOTAS, MUDANZA, PROBLEMA_ECONOMICO, URGENCIA_RESUELTA, MASCOTA_RECUPERADA. Usa lenguaje empático sobre el cuidado animal. Responde en formato JSON."
```

---

## 🔄 FLUJO COMPLETO PASO A PASO

### 1. Ejecución Automática (cada 6 horas):
```
06:00 UTC - Cron se activa automáticamente
06:00:01 - Lee ACTIVE_CLIENTS desde variables
06:00:02 - Para cada cliente enabled=true:
06:00:03   - POST https://cliente.onrender.com/api/revival/process
06:00:04   - Header: X-Revival-Secret: secreto_configurado
06:00:05   - Payload: {"timestamp": "...", "cron_service": "..."}
```

### 2. Procesamiento en Cliente:
```
06:00:05 - Cliente recibe POST en /api/revival/process
06:00:06 - Valida X-Revival-Secret con REVIVAL_SECRET_KEY
06:00:07 - Verifica REVIVAL_ENABLED=true
06:00:08 - Llama memory.get_conversations_for_revival()
06:00:09 - Query Firestore: revival_status == null
06:00:10 - Obtiene lista de conversaciones sin procesar
```

### 3. Análisis por Conversación:
```
06:00:11 - Para cada conversación candidata:
06:00:12   - Inicializa RevivalAgent con REVIVAL_PROMPT
06:00:13   - Prepara contexto: historial + estado + metadata
06:00:14   - Llama OpenAI API con modelo REVIVAL_AI_MODEL
06:00:15   - Recibe decisión JSON: {action, message, tag, confidence}
06:00:16   - Si action=SEND: envía WhatsApp + marca revival_status="ATTEMPTED"
06:00:17   - Si action=IGNORE: marca revival_status=tag_personalizado
06:00:18   - Actualiza Firestore con resultado
```

### 4. Finalización:
```
06:00:19 - Genera resumen: conversaciones procesadas, mensajes enviados, errores
06:00:20 - Retorna JSON al cron: {"success": true, "conversations_processed": 15, ...}
06:00:21 - Cron registra resultado en logs
06:00:22 - Continúa con siguiente cliente
```

---

## 📊 ESTRUCTURA DE DATOS

### state_context (Firestore):
```json
{
  "revival_status": null | "ATTEMPTED" | "DEAD" | "ENOJADO" | "custom_tag",
  "revival_timestamp": "2024-01-15T06:00:18.123Z",
  "revival_metadata": {
    "message_sent": true,
    "message_content": "Hola Juan, vi que te interesaba...",
    "analysis": {
      "action": "SEND",
      "confidence": 0.85,
      "reasoning": "Cliente mostró interés...",
      "model_used": "gpt-4"
    }
  }
}
```

### Respuesta del Cron:
```json
{
  "success": true,
  "cycle_start": "2024-01-15T06:00:00.000Z",
  "cycle_end": "2024-01-15T06:00:22.456Z",
  "duration_seconds": 22.456,
  "conversations_processed": 15,
  "messages_sent": 8,
  "conversations_tagged": 7,
  "errors": 0,
  "dry_run": false
}
```

---

## 🛡️ SISTEMA DE SEGURIDAD

### 1. Validación de Secret Key:
- Cron envía `X-Revival-Secret` header
- Cliente valida contra `REVIVAL_SECRET_KEY`
- Si no coincide: HTTP 403 Forbidden

### 2. Estados Críticos Protegidos:
```python
critical_states = [
    'AGENDA_CONFIRMANDO_TURNO',
    'AGENDA_SOLICITANDO_CANCELACION', 
    'PAGOS_PROCESANDO_PAGO',
    'PAGOS_ESPERANDO_CONFIRMACION'
]
```

### 3. Procesamiento Único:
- Cada conversación se procesa UNA SOLA VEZ en su historia
- Query Firestore: `revival_status == null`
- Una vez etiquetada, nunca más se toca

### 4. Límites de Protección:
- Máximo 50 conversaciones por ciclo (configurable)
- Timeout de 30 segundos por cliente
- Máximo 500 tokens por respuesta de IA

### 5. Modo DRY_RUN:
- Cron: `DRY_RUN=true` simula llamadas HTTP
- Cliente: `REVIVAL_DRY_RUN=true` simula envío de mensajes
- Ambos pueden combinarse para testing seguro

---

## 🧪 TESTING Y DEBUGGING

### 1. Testing Seguro (Recomendado):
```bash
# EN CRON:
DRY_RUN=true
ACTIVE_CLIENTS=[{"name":"Test","url":"https://test.com","enabled":true}]

# EN CLIENTE:
REVIVAL_ENABLED=false  # O usar secret key diferente
```

### 2. Logs a Monitorear:

#### Cron Service:
```
🔄 Revival Cron Service iniciado
📊 Clientes activos: 3
🔄 Disparando revival para ClienteA
✅ ClienteA: Procesado exitosamente
📊 Ciclo completado: 3/3 clientes exitosos en 45.2s
```

#### Cliente:
```
🔄 Revival Handler inicializado - Enabled: true, DryRun: false
🔍 Buscando conversaciones candidatas para revival...
📊 Encontradas 15 conversaciones candidatas para revival
🤖 Analizando conversación para revival: 5493413167185
✅ Mensaje de revival enviado a 5493413167185
📊 Ciclo revival completado: 8 mensajes, 7 etiquetadas, 0 errores en 32.5s
```

### 3. Endpoints de Debug:
```bash
# Estado del sistema de revival:
GET https://cliente.onrender.com/api/revival/status

# Respuesta:
{
  "success": true,
  "status": {
    "enabled": true,
    "dry_run": false,
    "max_per_cycle": 50,
    "has_secret_key": true,
    "eligible_conversations": 15
  }
}
```

---

## 🚀 DEPLOY Y CONFIGURACIÓN

### 1. Deploy del Cron Service:

#### En Render Dashboard:
```
Service Type: Cron Job
Repository: OPTIATIENDE-IA-
Branch: feature/multiflujo-v9
Root Directory: cron-revival-service
Build Command: pip install -r requirements.txt
Start Command: python main.py
Schedule: 0 */6 * * *
Plan: Starter ($7/mes)
```

#### Variables de Entorno:
```bash
CRON_SECRET_KEY=secreto_super_seguro_2024
ACTIVE_CLIENTS=[{"name":"Cliente1","url":"https://cliente1.onrender.com","enabled":true},{"name":"Cliente2","url":"https://cliente2.onrender.com","enabled":true}]
REQUEST_TIMEOUT=30
DRY_RUN=false
```

### 2. Configuración en Clientes Existentes:

#### Solo agregar variables (NO redeploy):
```bash
REVIVAL_ENABLED=true
REVIVAL_SECRET_KEY=secreto_super_seguro_2024
REVIVAL_PROMPT="Tu prompt personalizado..."
REVIVAL_MAX_PER_CYCLE=50
REVIVAL_DRY_RUN=false
```

### 3. Validación Post-Deploy:

#### Verificar archivos nuevos en repo:
```
✅ cron-revival-service/main.py
✅ cron-revival-service/requirements.txt
✅ revival_handler.py
✅ revival_agent.py
✅ Modificaciones en memory.py
✅ Modificaciones en main.py
```

#### Verificar logs de deploy:
```
✅ Cron: "Build succeeded"
✅ Cliente: "Sistema de revival de conversaciones registrado"
```

---

## 🔍 TROUBLESHOOTING

### Error: "No clientes activos"
**Causa:** ACTIVE_CLIENTS mal formateado
**Solución:** Validar JSON en https://jsonlint.com/

### Error: "Invalid secret key"
**Causa:** CRON_SECRET_KEY ≠ REVIVAL_SECRET_KEY
**Solución:** Verificar ambas variables coincidan exactamente

### Error: "revival_handler.py no encontrado"
**Causa:** Archivo no committeado o branch incorrecta
**Solución:** Verificar git status y push

### Error: "Build failed - pydantic"
**Causa:** requirements.txt con dependencias problemáticas
**Solución:** Usar requirements.txt simplificado (solo requests)

### Error: "Timeout en cliente"
**Causa:** Cliente lento o caído
**Solución:** Aumentar REQUEST_TIMEOUT o verificar cliente

### Conversaciones no procesadas:
**Causa:** REVIVAL_ENABLED=false o revival_status ya existe
**Solución:** Verificar variables y query Firestore

---

## 📈 ESCALABILIDAD

### Agregar Nuevo Cliente:
1. Deploy cliente con variables de revival
2. Agregar entrada a ACTIVE_CLIENTS del cron:
```json
{"name":"NuevoCliente","url":"https://nuevo.onrender.com","enabled":true}
```
3. Redeploy cron service

### Desactivar Cliente Temporalmente:
```json
{"name":"Cliente","url":"https://...","enabled":false}
```

### Cambiar Frecuencia:
Modificar schedule en render.yaml:
- Cada 3 horas: `0 */3 * * *`
- Cada 12 horas: `0 */12 * * *`
- Solo de día: `0 6,12,18 * * *`

---

## 💰 COSTOS

### Cron Service:
- **Plan Starter:** $7/mes
- **Ejecuciones:** 4/día × 30 días = 120 ejecuciones/mes
- **Costo adicional:** $0 (incluido en plan)

### OpenAI API (por cliente):
- **Modelo:** GPT-4 (~$0.03/1K tokens)
- **Estimado:** 200 tokens/conversación
- **50 conversaciones × 4 veces/día × 30 días = 6000 conversaciones/mes**
- **Costo estimado:** ~$36/mes por cliente

### Total Sistema (3 clientes):
- Cron: $7/mes
- OpenAI (3 × $36): $108/mes
- **Total:** ~$115/mes

---

## 🔄 MANTENIMIENTO

### Logs a Revisar Semanalmente:
1. **Cron execution success rate**
2. **Client response times**
3. **OpenAI API usage**
4. **Error patterns**

### Optimizaciones Futuras:
1. **Cache de conversaciones** para reducir queries Firestore
2. **Batch processing** para OpenAI (múltiples conversaciones por llamada)
3. **Horarios inteligentes** por timezone del cliente
4. **A/B testing** de prompts por cliente

---

## 📞 SOPORTE

### En caso de problemas:
1. **Revisar logs** de cron y cliente
2. **Verificar variables** de entorno
3. **Testear endpoint** manualmente con curl
4. **Validar secret keys** coincidan
5. **Consultar esta documentación** para configuración

### Comandos útiles de debug:
```bash
# Test manual del endpoint:
curl -X POST https://cliente.onrender.com/api/revival/process \
  -H "X-Revival-Secret: tu_secreto" \
  -H "Content-Type: application/json"

# Verificar estado:
curl https://cliente.onrender.com/api/revival/status

# Ver conversaciones elegibles en Firestore:
Query: state_context.revival_status == null
```

---

**🎯 FIN DE DOCUMENTACIÓN COMPLETA**

*Sistema implementado y documentado por Asistente IA - Enero 2025*
*Todas las funcionalidades probadas y validadas antes de deploy*
