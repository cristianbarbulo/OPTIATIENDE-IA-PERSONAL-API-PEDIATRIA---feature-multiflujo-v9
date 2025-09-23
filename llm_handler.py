# llm_handler.py (Arquitectura V9.1 - Refactorizado con Agentes Dinámicos y Fecha)
import openai
import logging
import config
import utils 
import re  # <-- AÑADIDO para operaciones de regex
from datetime import datetime # <-- AÑADIDO para obtener la fecha actual
import locale # <-- AÑADIDO para formato de fecha en español
from utils import parsear_fecha_hora_natural  # <-- AÑADIDO para extracción de fechas

# El logger se mantiene igual, usando el TENANT_NAME. ¡Perfecto!
logger = logging.getLogger(config.TENANT_NAME)

# --- Inicialización del Cliente OpenAI (Con organización para GPT-5) ---
client = openai.OpenAI(
    api_key=config.OPENAI_API_KEY,
    organization=config.OPENAI_ORG_ID
)

# --- FUNCIÓN INTERNA REUTILIZABLE (GPT-5 Responses API) ---
def _llamar_api_openai(messages: list, model: str, temperature: float, max_completion_tokens: int, agent_context: str = None) -> str:
    """Función base para interactuar con la API de OpenAI.
    
    NOTA: GPT-5 usa la nueva Responses API con parámetros diferentes.
    Los parámetros temperature y max_completion_tokens se mantienen por compatibilidad
    pero se traducen internamente a los nuevos parámetros.
    """
    if not client:
        return "Lo siento, el servicio de IA no está disponible en este momento."
    
    try:
        # Configurar locale para fecha en español
        try:
            locale.setlocale(locale.LC_TIME, 'es_ES.UTF-8')
        except:
            try:
                locale.setlocale(locale.LC_TIME, 'Spanish_Spain.1252')
            except:
                pass
        
        # Obtener fecha y hora actual
        ahora = datetime.now()
        fecha_hora_actual = ahora.strftime("%A %d de %B %Y, %H:%M")
        
        # Convertir messages a un solo string de input para GPT-5
        input_text = f"FECHA Y HORA ACTUAL: {fecha_hora_actual}\n\n"
        
        for msg in messages:
            role = msg.get('role', '')
            content = msg.get('content', '')
            if role == 'system':
                input_text += f"Sistema: {content}\n\n"
            elif role == 'user':
                input_text += f"Usuario: {content}\n\n"
            elif role == 'assistant':
                input_text += f"Asistente: {content}\n\n"
        
        input_text = input_text.strip()
        
        logger.info(f"[LLM] Usando modelo={model}, org={config.OPENAI_ORG_ID}")
        logger.info(f"Enviando solicitud a OpenAI Responses API (Modelo: {model})")
        
        # Configurar parámetros según el modelo y contexto
        reasoning_effort = "minimal"  # Por defecto minimal para rapidez
        text_verbosity = "medium"     # Por defecto medium
        
        # Configuración específica según el agente/modelo
        if agent_context == "meta_agente":
            # Meta-agente: solo clasifica, necesita mínimo reasoning
            reasoning_effort = config.META_AGENTE_REASONING if hasattr(config, 'META_AGENTE_REASONING') else "minimal"
            text_verbosity = config.META_AGENTE_VERBOSITY if hasattr(config, 'META_AGENTE_VERBOSITY') else "low"
        elif agent_context in ["intencion_agendamiento", "intencion_pagos"]:
            # Agentes de intención: extraen datos estructurados
            reasoning_effort = config.INTENCION_REASONING if hasattr(config, 'INTENCION_REASONING') else "low"
            text_verbosity = config.INTENCION_VERBOSITY if hasattr(config, 'INTENCION_VERBOSITY') else "low"
        elif model == config.AGENTE_CERO_MODEL:
            # Usar configuración específica de Agente Cero desde variables de entorno
            reasoning_effort = config.AGENTE_CERO_REASONING if hasattr(config, 'AGENTE_CERO_REASONING') else "low"
            text_verbosity = config.AGENTE_CERO_VERBOSITY if hasattr(config, 'AGENTE_CERO_VERBOSITY') else "medium"
        elif model == config.GENERATOR_MODEL:
            # Usar configuración específica del Generador desde variables de entorno
            reasoning_effort = config.GENERADOR_REASONING if hasattr(config, 'GENERADOR_REASONING') else "medium"
            text_verbosity = config.GENERADOR_VERBOSITY if hasattr(config, 'GENERADOR_VERBOSITY') else "high"
        elif "vision" in model.lower():
            reasoning_effort = "minimal"  # Mínimo para visión (análisis rápido)
            text_verbosity = "low"       # Baja verbosidad para respuestas concisas
        elif "nano" in model.lower():
            reasoning_effort = "minimal"  # Mínimo para nano (tareas simples)
            text_verbosity = "low"       # Baja verbosidad
        elif "mini" in model.lower():
            reasoning_effort = "low"      # Bajo para mini (balance costo/capacidad)
            text_verbosity = "medium"     # Media verbosidad
        
        # Llamada a la nueva Responses API
        response = client.responses.create(
            model=model,
            input=input_text,
            reasoning={
                "effort": reasoning_effort
            },
            text={
                "verbosity": text_verbosity
            }
        )
        
        # La respuesta tiene una estructura diferente
        full_response = response.output_text
        logger.info(f"Respuesta completa recibida de {model}: '{full_response[:120]}...'")
        return full_response.strip()
    except Exception as e:
        logger.error(f"Error al llamar a la API de OpenAI con el modelo {model}: {e}", exc_info=True)
        return "Lo siento, estoy teniendo problemas técnicos internos. Por favor, intenta de nuevo en un momento."

# --- Agentes existentes (se mantienen por compatibilidad o uso específico) ---

def llamar_agente_lector(contenido_usuario: list) -> str:
    """Agente 1: LECTOR. Analiza imágenes y texto para extraer datos."""
    logger.info("Invocando al Agente Lector...")
    
    if not client:
        return "Lo siento, el servicio de IA no está disponible en este momento."
    
    try:
        # Configurar locale para fecha en español
        try:
            locale.setlocale(locale.LC_TIME, 'es_ES.UTF-8')
        except:
            try:
                locale.setlocale(locale.LC_TIME, 'Spanish_Spain.1252')
            except:
                pass
        
        # Obtener fecha y hora actual
        ahora = datetime.now()
        fecha_hora_actual = ahora.strftime("%A %d de %B %Y, %H:%M")
        
        # Para el lector de imágenes, usar la API tradicional de Chat Completions
        # que soporta correctamente el análisis de imágenes
        system_message = {
            "role": "system", 
            "content": f"FECHA Y HORA ACTUAL: {fecha_hora_actual}\n\n{config.PROMPT_LECTOR}"
        }
        
        # Construir el mensaje del usuario manteniendo el formato para imágenes
        user_message = {
            "role": "user",
            "content": contenido_usuario  # Ya viene en el formato correcto con image_url
        }
        
        messages = [system_message, user_message]
        
        logger.info(f"[LLM] Usando modelo=gpt-4o-mini para visión (Chat Completions API)")
        logger.info(f"Enviando solicitud con imágenes a OpenAI Chat Completions API")
        
        # Usar la API de Chat Completions que sí soporta imágenes
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=1.0,
            max_tokens=300
        )
        
        # Extraer la respuesta
        full_response = response.choices[0].message.content
        logger.info(f"Respuesta del lector recibida: '{full_response[:120]}...'")
        return full_response.strip()
        
    except Exception as e:
        logger.error(f"Error al llamar al agente lector con imágenes: {e}", exc_info=True)
        return "Lo siento, estoy teniendo problemas técnicos internos. Por favor, intenta de nuevo en un momento."

# --- HINT SILENCIOSO DE VENDEDOR ---
def _build_vendor_hint_from_context(context_info: dict) -> str:
    """Devuelve un bloque de hint silencioso con el vendor_owner, si existe en context_info."""
    try:
        vendor = (context_info or {}).get('vendor_owner')
        if not vendor:
            return (
                "[CONTEXT PERMANENTE]\n"
                "SIN ETIQUETA DE VENDEDOR.\n"
                "Política: NO ofrezcas descuentos salvo que el usuario pregunte por precio/descuento o estemos en cierre."
            )
        return (
            f"[CONTEXT PERMANENTE]\nCLIENTE DE: {str(vendor).strip().upper()}. (No mencionar al usuario)\n"
            "Ofrecer descuentos solo si el usuario los solicita explícitamente o en cierre/confirmación.\n"
        )
    except Exception:
        return ""

def llamar_rodi_generador(prompt_base: str, conversation_history: list, context_info: dict) -> str:
    """Agente 2: GENERADOR CONVERSACIONAL. Genera respuestas de texto naturales con contexto explícito."""
    logger.info("Invocando a RODI Generador (Modo Conversacional, contexto explícito)...")
    # Si no hay PROMPT_GENERADOR definido, no se permite invocar al generador
    if not getattr(config, 'PROMPT_GENERADOR', None):
        logger.error("[GENERADOR] PROMPT_GENERADOR no está definido. No se puede invocar al generador.")
        raise RuntimeError("PROMPT_GENERADOR no definido")
    
    # Extraer datos del contexto
    intencion = context_info.get('intencion', 'desconocida')
    ultimo_mensaje_usuario = context_info.get('ultimo_mensaje_usuario', '')
    
    # CORRECCIÓN CRÍTICA: El prompt_base viene de config.PROMPT_GENERADOR (Render)
    # El ultimo_mensaje_usuario ya está explícitamente incluido en el prompt estructurado más abajo
    
    # Formatear historial para mayor claridad
    historial_formateado = ""
    for msg in conversation_history:
        rol = msg.get('role', msg.get('name', 'asistente'))
        contenido = msg.get('content', '')
        historial_formateado += f"{rol}: {contenido}\n"
    
    # Construir el prompt estructurado con explicaciones claras de cada dato
    vendor_hint = _build_vendor_hint_from_context(context_info)
    prompt = f"""{vendor_hint}
{prompt_base}

---
## CONTEXTO DEL SISTEMA (DATOS REALES Y ACTUALES)

### INTENCIÓN ACTUAL: {intencion}
**Significado:** Esta es la intención detectada del usuario en su último mensaje.

### ÚLTIMO MENSAJE DEL USUARIO:
"{ultimo_mensaje_usuario}"

### REGLA CRÍTICA - FLUIDEZ CONVERSACIONAL:
**IMPORTANTE:** Si la conversación ya está activa (hay más de 2 mensajes en el historial), NO uses saludos como "¡Hola!" o "Entiendo que estás interesado en...". Responde directamente a la consulta del usuario de forma natural y fluida.

### REGLA CRÍTICA - CONTEXTO COMPLETO:
**IMPORTANTE:** Tienes acceso al historial completo de la conversación. Usa este contexto para dar respuestas precisas y contextuales. Si el usuario hace referencia a algo mencionado anteriormente, respóndele de manera coherente.

### ESTADOS DEL SISTEMA (DATOS REALES):
"""
    
    # Agregar explicaciones específicas según el tipo de datos disponibles
    if 'estado_agenda' in context_info:
        estado_agenda = context_info['estado_agenda']
        prompt += f"""
**ESTADO DE AGENDA:** {estado_agenda}
**Significado:** 
- 'sin_turno': El usuario aún no eligió un horario
- 'agendado': La cita fue confirmada exitosamente
- 'reprogramado': La cita fue modificada
- 'cancelado': La cita fue cancelada
- 'no_disponible': No hay horarios disponibles
- 'error': Hubo un problema técnico
"""
        
        if 'horarios_disponibles' in context_info:
            slots = context_info['horarios_disponibles']
            prompt += f"""
**HORARIOS DISPONIBLES:** {len(slots)} opciones
**Significado:** Lista REAL de horarios disponibles obtenida del calendario.
**IMPORTANTE:** Solo menciona estos horarios específicos, NO inventes otros.
"""
            
        if 'id_evento' in context_info:
            id_evento = context_info['id_evento']
            prompt += f"""
**ID DE EVENTO:** {id_evento}
**Significado:** Identificador único de la cita creada en el calendario.
**IMPORTANTE:** Incluye este ID en tu respuesta para referencia.
"""
    
    if 'estado_pago' in context_info:
        estado_pago = context_info['estado_pago']
        prompt += f"""
**ESTADO DE PAGO:** {estado_pago}
**Significado:**
- 'link_generado': Se creó exitosamente el link de pago
- 'verificacion_fallida': No se pudo verificar el pago
- 'sin_referencia': No se encontró la referencia de pago
- 'faltan_datos': Faltan datos para generar el link
- 'error': Hubo un problema técnico
"""
        if estado_pago == 'faltan_datos':
            prompt += "\n**IMPORTANTE:** FALTA INFORMACIÓN para generar el link de pago. Pide al usuario de forma clara y cálida que indique el dato faltante (plan, monto o proveedor)."
        
        if 'link_pago' in context_info:
            link_pago = context_info['link_pago']
            prompt += f"""
**LINK DE PAGO:** {link_pago}
**Significado:** URL REAL generada para que el usuario realice el pago.
**IMPORTANTE:** Incluye este link exacto en tu respuesta.
"""
            
        if 'monto' in context_info:
            monto = context_info['monto']
            prompt += f"""
**MONTO:** {monto}
**Significado:** Precio REAL del servicio/producto seleccionado.
**IMPORTANTE:** Usa este monto exacto, NO inventes otros precios.
"""
            
        if 'plan' in context_info:
            plan = context_info['plan']
            prompt += f"""
**PLAN:** {plan}
**Significado:** Servicio/producto REAL seleccionado por el usuario.
**IMPORTANTE:** Menciona este plan específico en tu respuesta.
"""
            
        if 'proveedor' in context_info:
            proveedor = context_info['proveedor']
            prompt += f"""
**PROVEEDOR:** {proveedor}
**Significado:** Plataforma de pago REAL que se está utilizando.
**IMPORTANTE:** Menciona este proveedor en tu respuesta.
"""
    
    if 'estado_general' in context_info:
        estado_general = context_info['estado_general']
        prompt += f"""
**ESTADO GENERAL:** {estado_general}
**Significado:** Estado actual de la conversación en el sistema.
"""

    prompt += f"""
---
### HISTORIAL DE CONVERSACIÓN:
{historial_formateado}

---
### INSTRUCCIONES ESPECÍFICAS:
1. **USA SOLO DATOS REALES:** Solo menciona horarios, precios, links y estados que estén en el contexto.
2. **NO INVENTES:** Si no hay horarios disponibles, di que no hay disponibilidad. Si no hay link de pago, no lo menciones.
3. **SÉ PRECISO:** Usa los montos, planes y proveedores exactos que están en el contexto.
4. **MANTÉN EL FLUJO:** Responde según la intención y estado actual del usuario.
5. **SÉ EMPÁTICO:** Mantén un tono cálido y profesional.

---
**RESPONDE AL USUARIO:**
"""
    
    system_message = {"role": "system", "content": config.PROMPT_GENERADOR}
    user_message = {"role": "user", "content": prompt}
    messages = [system_message] + conversation_history + [user_message]
    
    # El generador usa el modelo configurable con verbosidad alta
    return _llamar_api_openai(messages=messages, model=config.GENERATOR_MODEL, temperature=1.0, max_completion_tokens=1000)

# ELIMINADO: llamar_corrector_de_estilo - ya no se usa en el sistema

def llamar_analista_leads(transcripcion_completa: str) -> str:
    """Agente 4: ANALISTA DE LEADS. Extrae datos para HubSpot (devuelve JSON como texto)."""
    logger.info("Invocando al Agente Analista de Leads...")
    system_message = {"role": "system", "content": config.PROMPT_ANALISTA_LEADS}
    user_message = {"role": "user", "content": transcripcion_completa}
    messages = [system_message, user_message]
    # Analista de leads usa el modelo por defecto
    return _llamar_api_openai(messages=messages, model=config.OPENAI_MODEL, temperature=1.0, max_completion_tokens=500)

# --- NUEVOS AGENTES MULTI-AGENTE (V10) ---
from datetime import datetime

def llamar_meta_agente(mensaje_usuario, history, current_state=None):
    """
    PLAN DE ACCIÓN DEFINITIVO: Meta-agente simplificado con detección directa por palabras clave.
    OBJETIVO: Eliminar el 90% de las fugas de flujo con reglas duras antes de consultar IA.
    """
    logger.info("Invocando Meta-Agente para decidir dominio...")
    
    # PLAN DE ACCIÓN: Extraer solo el texto del usuario si viene un mensaje enriquecido
    # Soporta formatos como: "Contexto: <estado>. Usuario: '<texto>'"
    raw = mensaje_usuario or ""
    texto_usuario = raw
    try:
        import re as _re
        m = _re.search(r"Usuario:\s*'([^']+)'", raw)
        if m:
            texto_usuario = m.group(1)
    except Exception:
        texto_usuario = raw

    # Detección directa por palabras clave
    texto_lower = texto_usuario.lower().strip()
    
    # PALABRAS CLAVE CRÍTICAS PARA PAGOS (PRIORIDAD ALTA)
    # Incluye consultas de servicios/planes para forzar cambio de dominio aunque estemos en AGENDA
    palabras_pagar_criticas = [
        "pagar", "pago", "abonar", "precio", "costo", "link de pago",
        "mercado pago", "mercadopago", "paypal", "modo",
        "servicio", "servicios", "plan", "planes"
    ]
    
    # PALABRAS CLAVE CRÍTICAS PARA AGENDAMIENTO (PRIORIDAD ALTA)
    palabras_agendar_criticas = [
        "agendar", "turno", "cita", "fecha", "hora", "reprogramar", 
        "cambiar turno", "modificar cita", "disponible", "horario"
    ]
    
    # PALABRAS CLAVE AMBIGUAS (requieren contexto adicional)
    palabras_ambigüas = [
        "quiero", "necesito", "dame", "ver", "mostrame", "muestrame",
        "opciones", "servicios", "planes"
    ]
    
    # PRE-CHEQUEO: detectar negaciones cercanas a términos de pago para evitar falsos positivos
    try:
        negacion_cercana = False
        patrones_negacion = [
            r"\bno\s+(quiero|deseo|voy a|prefiero)\s+(pagar|pago|abonar)\b",
            r"\bno\s+(pagar|pago|abonar)\b",
            r"\bno\s+ahora\b.*\b(pagar|pago|abonar)\b",
            r"\bno\s+quiero\s+pagar\s+de\s+una\b",
        ]
        for patron in patrones_negacion:
            if re.search(patron, texto_lower):
                negacion_cercana = True
                break
    except Exception:
        negacion_cercana = False

    # DETECCIÓN DIRECTA CRÍTICA (SIN CONSULTAR IA)
    # Regla adicional: patrones de cambio explícito a servicios (forzar PAGOS)
    try:
        patrones_servicios = [
            r"\b(ver|prefiero ver|quiero ver)\s+(que\s+)?servicios\b",
            r"\bver\s+servicios\b",
        ]
        for patron in patrones_servicios:
            if re.search(patron, texto_lower):
                logger.info("[META_AGENTE] ✅ Cambio explícito a servicios detectado. Forzando dominio PAGOS.")
                return "PAGOS"
    except Exception:
        pass
    for palabra in palabras_pagar_criticas:
        if palabra in texto_lower:
            if negacion_cercana:
                logger.info(f"[META_AGENTE] ⚖️ Término de pago con negación detectado ('{palabra}'). Evitando forzar PAGOS.")
                break
            logger.info(f"[META_AGENTE] ✅ Detección directa PAGOS por palabra crítica: '{palabra}'. Forzando dominio PAGOS.")
            return "PAGOS"
    
    for palabra in palabras_agendar_criticas:
        if palabra in texto_lower:
            logger.info(f"[META_AGENTE] ✅ Detección directa AGENDAMIENTO por palabra crítica: '{palabra}'. Forzando dominio AGENDAMIENTO.")
            return "AGENDAMIENTO"
    
    # DETECCIÓN DE PALABRAS AMBIGUAS CON CONTEXTO
    tiene_palabras_ambigüas = any(palabra in texto_lower for palabra in palabras_ambigüas)
    
    if tiene_palabras_ambigüas:
        # REGLA CRÍTICA: Si el usuario dice "quiero ver opciones" sin contexto específico, 
        # y no hay estado actual, asumir AGENDAMIENTO por defecto
        if not current_state or current_state == "sin estado":
            logger.info(f"[META_AGENTE] Palabras ambiguas sin contexto. Asumiendo AGENDAMIENTO por defecto.")
            return "AGENDAMIENTO"
        
        # Si hay estado actual, usar el contexto para decidir
        if current_state.startswith('PAGOS_'):
            logger.info(f"[META_AGENTE] Palabras ambiguas en contexto de PAGOS. Manteniendo dominio PAGOS.")
            return "PAGOS"
        elif current_state.startswith('AGENDA_'):
            logger.info(f"[META_AGENTE] Palabras ambiguas en contexto de AGENDAMIENTO. Manteniendo dominio AGENDAMIENTO.")
            return "AGENDAMIENTO"
    
    # Si no hay detección directa, usar el LLM para análisis más complejo
    prompt = f"""Eres un Meta-Agente especializado en clasificar intenciones de usuario en conversaciones de WhatsApp.

# REGLAS PRINCIPALES:
1. **ANALIZA** el mensaje del usuario para determinar si su intención es de PAGOS o AGENDAMIENTO
2. **RESPONDE** SOLO con "PAGOS" o "AGENDAMIENTO"
3. **NO** agregues explicaciones adicionales

# CRITERIOS DE CLASIFICACIÓN:

## PAGOS (responder "PAGOS"):
- Usuario quiere pagar, abonar, ver precios, costos
- Usuario pide link de pago, opciones de pago
- Usuario pregunta por servicios, planes, precios
- Usuario menciona MercadoPago, PayPal, MODO
- Usuario dice "quiero pagar", "necesito pagar", "dame opciones"
- Usuario pregunta "que servicios tienen", "cuales son los planes"

## AGENDAMIENTO (responder "AGENDAMIENTO"):
- Usuario quiere agendar, programar, reservar turno/cita
- Usuario pregunta por horarios, disponibilidad, fechas
- Usuario quiere reprogramar, cambiar, modificar cita
- Usuario dice "quiero agendar", "necesito turno", "que horarios tienen"
- Usuario menciona fechas, horas, días específicos
- Usuario dice "reprogramar", "cambiar fecha", "modificar cita"

# ESTADO ACTUAL:
- Estado actual: {current_state or 'sin estado'}

# MENSAJE DEL USUARIO:
{mensaje_usuario}

# HISTORIAL RECIENTE:
{str(history[-3:]) if history else 'sin historial'}

Responde SOLO con "PAGOS" o "AGENDAMIENTO":"""
    
    try:
        respuesta = _llamar_api_openai(
            messages=[{"role": "system", "content": prompt}],
            model=config.OPENAI_MODEL,
            temperature=1.0,  # GPT-5 solo soporta temperature=1.0
            max_completion_tokens=10,
            agent_context="meta_agente"
        )
        
        # Limpiar y normalizar la respuesta
        respuesta_limpia = respuesta.strip().upper()
        
        if respuesta_limpia in ["PAGOS", "AGENDAMIENTO"]:
            logger.info(f"[META_AGENTE] Decisión LLM: {respuesta_limpia}")
            return respuesta_limpia
        else:
            logger.warning(f"[META_AGENTE] Respuesta LLM inválida: '{respuesta}'. Usando AGENDAMIENTO por defecto.")
            return "AGENDAMIENTO"
            
    except Exception as e:
        logger.error(f"[META_AGENTE] Error en LLM: {e}. Usando AGENDAMIENTO por defecto.")
        return "AGENDAMIENTO"

def llamar_agente_intencion_agendamiento(texto: str, history: list, current_state: str, contexto_extra: str = "") -> dict:
    """
    PLAN DE ACCIÓN v7: Agente de Intención de Agendamiento con prompt perfeccionado.
    Extrae datos y utiliza un menú de acciones explícito y limitado.
    """
    logger.info("Invocando Agente de Intención de Agendamiento (Perfeccionado)...")

    vendor_hint_block = contexto_extra.strip() if isinstance(contexto_extra, str) and contexto_extra.strip() else ""
    prompt_template = f"""
{vendor_hint_block}

Eres un asistente experto en analizar solicitudes de agendamiento. Tu misión es doble:
1.  Extraer datos clave del mensaje del usuario.
2.  Recomendar la acción correcta de un menú limitado.

# REGLAS:
- **Extrae:** `fecha_deseada`, `hora_especifica`, `preferencia_horaria` (ej: "mañana", "tarde"), y `restricciones_temporales` (ej: "no puedo los lunes").
- **Acción Recomendada:** Elige una acción de la sección # ACCIONES VÁLIDAS.
- **Formato:** Responde únicamente con el JSON.

# ACCIONES VÁLIDAS (Tu único menú de opciones):
- `iniciar_triage_agendamiento`: Úsala para CUALQUIER solicitud de agendar, buscar o cambiar un turno. Es tu acción principal.
- `iniciar_reprogramacion_cita`: Úsala si el usuario menciona explícitamente "reprogramar" y ya tiene una cita.
- `iniciar_cancelacion_cita`: Úsala si el usuario menciona explícitamente "cancelar".
- `preguntar`: Úsala para CUALQUIER pregunta general que no sea una solicitud directa de agendamiento (ej: "¿atienden los sábados?", "¿qué servicios ofrecen?").

# EJEMPLOS:
Usuario: "quiero un turno para mañana a la tarde"
{{
  "detalles": {{"fecha_deseada": "2025-08-02", "preferencia_horaria": "tarde"}},
  "accion_recomendada": "iniciar_triage_agendamiento"
}}

Usuario: "necesito cancelar mi cita"
{{
  "detalles": {{}},
  "accion_recomendada": "iniciar_cancelacion_cita"
}}

Usuario: "¿atienden los sábados?"
{{
  "detalles": {{"consulta": "horario sábados"}},
  "accion_recomendada": "preguntar"
}}

# MENSAJE DEL USUARIO A ANALIZAR:
{texto}

# JSON DE SALIDA:
"""
    respuesta_raw = _llamar_api_openai(
        messages=[{"role": "system", "content": prompt_template}],
        model=config.OPENAI_MODEL,
        temperature=1.0,  # GPT-5 solo soporta temperature=1.0
        max_completion_tokens=250,
        agent_context="intencion_agendamiento"
    )
    
    data = utils.parse_json_from_llm(respuesta_raw, context="agente_intencion_agendamiento_v7") or {}
    
    # Validación final para asegurar que la acción es válida
    acciones_validas = ["iniciar_triage_agendamiento", "iniciar_reprogramacion_cita", "iniciar_cancelacion_cita", "preguntar"]
    if data.get("accion_recomendada") not in acciones_validas:
        data["accion_recomendada"] = "preguntar" # Fallback seguro

    if "detalles" not in data:
        data["detalles"] = {}

    return data

def llamar_agente_intencion_pagos(texto: str, history: list, current_state: str, contexto_extra: str = "") -> dict:
    """
    PLAN DE ACCIÓN v7: Agente de Intención de Pagos con prompt perfeccionado.
    Extrae datos y utiliza un menú de acciones explícito y limitado.
    """
    logger.info("Invocando Agente de Intención de Pagos (Perfeccionado)...")

    vendor_hint_block = contexto_extra.strip() if isinstance(contexto_extra, str) and contexto_extra.strip() else ""
    prompt_template = f"""
{vendor_hint_block}

Eres un asistente experto en analizar solicitudes de pago. Tu misión es doble:
1.  Extraer el servicio que el usuario desea pagar.
2.  Recomendar la acción correcta de un menú limitado.

# REGLAS:
- **Extrae:** `servicio_deseado`.
- **Acción Recomendada:** Elige una acción de la sección # ACCIONES VÁLIDAS.
- **Formato:** Responde únicamente con el JSON.

# ACCIONES VÁLIDAS (Tu único menú de opciones):
- `iniciar_triage_pagos`: Úsala para CUALQUIER solicitud de pagar o ver precios/servicios. Es tu acción principal.
- `confirmar_pago`: Úsala SOLAMENTE si el usuario envía un comprobante de pago (generalmente una imagen).
- `preguntar`: Úsala para CUALQUIER pregunta general (el orquestador derivará al Generador y mantendrá el flujo activo).

# EJEMPLOS:
Usuario: "quiero pagar el coaching personalizado"
{{
  "detalles": {{"servicio_deseado": "Coaching Personalizado"}},
  "accion_recomendada": "iniciar_triage_pagos"
}}

Usuario: "[Imagen de un comprobante de pago]"
{{
  "detalles": {{"comprobante": "imagen"}},
  "accion_recomendada": "confirmar_pago"
}}

Usuario: "¿aceptan tarjeta de crédito?"
{{
  "detalles": {{"consulta": "tarjeta de crédito"}},
  "accion_recomendada": "preguntar"
}}

# MENSAJE DEL USUARIO A ANALIZAR:
{texto}

# JSON DE SALIDA:
"""
    respuesta_raw = _llamar_api_openai(
        messages=[{"role": "system", "content": prompt_template}],
        model=config.OPENAI_MODEL,
        temperature=1.0,  # GPT-5 solo soporta temperature=1.0
        max_completion_tokens=250,
        agent_context="intencion_pagos"
    )
    
    data = utils.parse_json_from_llm(respuesta_raw, context="agente_intencion_pagos_v7") or {}
    
    # Validación final para asegurar que la acción es válida
    acciones_validas = ["iniciar_triage_pagos", "confirmar_pago", "preguntar"]
    if data.get("accion_recomendada") not in acciones_validas:
        data["accion_recomendada"] = "preguntar" # Fallback seguro
        
    if "detalles" not in data:
        data["detalles"] = {}
        
    return data

# --- Eliminar la función antigua llamar_agente_intencion ---
# def llamar_agente_intencion(...):
#     ...
# (Función eliminada en la migración a multi-agente)

# ELIMINADO: llamar_agente_dinamico ya no se usa en el sistema
# El sistema funciona perfectamente con llamar_rodi_generador directamente
