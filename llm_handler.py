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

# ELIMINADO V10: Esta función ya no existe en sistema simplificado
def _ELIMINADO_llamar_rodi_generador_OBSOLETO():
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

# === FUNCIONES DE EXTRACCIÓN DE DATOS PARA META-AGENTE AMPLIFICADO ===

def _extraer_datos_agendamiento(texto_usuario: str) -> dict:
    """
    Extrae datos de agendamiento del mensaje del usuario.
    Retorna diccionario con fecha_deseada, hora_especifica, preferencia_horaria, etc.
    """
    datos = {}
    texto = texto_usuario.lower().strip()
    
    try:
        from utils import parsear_fecha_hora_natural
        resultado_parsing = parsear_fecha_hora_natural(texto_usuario, return_details=True)

        if resultado_parsing:
            fecha_dt = resultado_parsing.get('fecha_datetime')
            fecha_iso = resultado_parsing.get('fecha_iso')
            hora_parseada = resultado_parsing.get('hora')
            preferencia_horaria = resultado_parsing.get('preferencia_horaria')
            restricciones = resultado_parsing.get('restricciones_temporales') or []
            dia_semana = resultado_parsing.get('dia_semana')

            if fecha_dt:
                datos['fecha_deseada'] = fecha_dt.strftime('%Y-%m-%d')
                logger.info(f"[EXTRACCION] Fecha detectada: {datos['fecha_deseada']}")
            elif fecha_iso:
                datos['fecha_deseada'] = fecha_iso
                logger.info(f"[EXTRACCION] Fecha detectada (ISO): {fecha_iso}")

            if hora_parseada:
                datos['hora_especifica'] = hora_parseada
                logger.info(f"[EXTRACCION] Hora detectada: {hora_parseada}")

            if preferencia_horaria:
                datos['preferencia_horaria'] = preferencia_horaria
                logger.info(f"[EXTRACCION] Preferencia horaria detectada: {preferencia_horaria}")

            if restricciones:
                datos['restricciones_temporales'] = restricciones
                logger.info(f"[EXTRACCION] Restricciones temporales detectadas: {restricciones}")

            if dia_semana:
                datos['dia_semana'] = dia_semana
        else:
            logger.warning(f"[EXTRACCION] parsear_fecha_hora_natural no encontró datos en: '{texto_usuario}'")

        # Extraer preferencias de días específicos
        if any(p in texto for p in ["fin de semana", "weekend"]):
            datos['preferencia_dia'] = "fin_de_semana"
        elif any(p in texto for p in ["entre semana", "weekday"]):
            datos['preferencia_dia'] = "entre_semana"
        
        # Extraer restricciones temporales
        restricciones = []
        if "después de las" in texto or "después del" in texto:
            # Buscar patrón "después de las X"
            import re
            match = re.search(r"después de las?(\d{1,2})", texto)
            if match:
                restricciones.append(f"después_{match.group(1)}")
        
        if "antes de las" in texto or "antes del" in texto:
            import re
            match = re.search(r"antes de las?(\d{1,2})", texto)
            if match:
                restricciones.append(f"antes_{match.group(1)}")
        
        if restricciones:
            datos['restricciones_temporales'] = restricciones
            
    except Exception as e:
        logger.warning(f"[EXTRACCION] Error extrayendo datos de agendamiento: {e}")
    
    return datos

def _extraer_datos_pagos(texto_usuario: str) -> dict:
    """
    Extrae datos de pagos del mensaje del usuario.
    Retorna diccionario con servicio_deseado, proveedor_preferido, etc.
    """
    datos = {}
    texto = texto_usuario.lower().strip()
    
    try:
        # Extraer servicio específico mencionado
        import config
        import json
        
        # Buscar servicios mencionados en el mensaje
        try:
            if hasattr(config, 'SERVICE_PRICES_JSON') and config.SERVICE_PRICES_JSON:
                precios = json.loads(config.SERVICE_PRICES_JSON)
                for servicio in precios.keys():
                    if servicio.lower() in texto:
                        datos['servicio_deseado'] = servicio
                        datos['monto'] = precios[servicio]
                        logger.info(f"[EXTRACCION] Servicio detectado: {servicio} (${precios[servicio]})")
                        break
        except Exception:
            pass
        
        # Extraer proveedor de pago mencionado
        if "mercado pago" in texto or "mercadopago" in texto:
            datos['proveedor_preferido'] = "MERCADOPAGO"
        elif "paypal" in texto:
            datos['proveedor_preferido'] = "PAYPAL"
        elif "modo" in texto:
            datos['proveedor_preferido'] = "MODO"
        
        # Detectar si es confirmación de pago (comprobante)
        if any(p in texto for p in ["comprobante", "pago realizado", "ya pagué", "ya pague", "envío pago"]):
            datos['comprobante'] = "texto"
            
    except Exception as e:
        logger.warning(f"[EXTRACCION] Error extrayendo datos de pagos: {e}")
    
    return datos

def llamar_meta_agente(mensaje_usuario, history, current_state=None):
    """
    META-AGENTE AMPLIFICADO: Maneja clasificación + comandos explícitos + extracción de datos.
    RESPONSABILIDADES:
    1. Detectar comandos explícitos (quiero agendar, quiero pagar, salir de X)
    2. Clasificar dominio (PAGOS vs AGENDAMIENTO)
    3. Extraer datos específicos (fechas, servicios, etc.)
    4. Retornar decisión estructurada con datos extraídos
    """
    logger.info("Invocando Meta-Agente Amplificado para decisión y extracción...")
    
    # PLAN DE ACCIÓN: Extraer solo el texto del usuario si viene un mensaje enriquecido
    raw = mensaje_usuario or ""
    texto_usuario = raw
    try:
        import re as _re
        m = _re.search(r"Usuario:\s*'([^']+)'", raw)
        if m:
            texto_usuario = m.group(1)
    except Exception:
        texto_usuario = raw

    texto_lower = texto_usuario.lower().strip()
    
    # ======== PASO 1: COMANDOS EXPLÍCITOS ========
    
    # Comando SALIR
    if "salir de pago" in texto_lower or "salir de pagos" in texto_lower:
        logger.info("[META_AGENTE] ✅ Comando SALIR DE PAGOS detectado")
        return {
            "decision": "SALIR_PAGOS",
            "dominio": None,
            "datos_extraidos": {},
            "accion_recomendada": "salir_flujo"
        }
    
    if "salir de agenda" in texto_lower or "salir de agendamiento" in texto_lower:
        logger.info("[META_AGENTE] ✅ Comando SALIR DE AGENDAMIENTO detectado")
        return {
            "decision": "SALIR_AGENDAMIENTO", 
            "dominio": None,
            "datos_extraidos": {},
            "accion_recomendada": "salir_flujo"
        }
    
    # Comandos ENTRADA EXPLÍCITA
    # V10: entrada EXPLÍCITA estricta (no interpretar variaciones)
    if any(cmd in texto_lower for cmd in ["quiero agendar"]):
        logger.info("[META_AGENTE] ✅ Comando QUIERO AGENDAR detectado")
        datos_extraidos = _extraer_datos_agendamiento(texto_usuario)
        return {
            "decision": "AGENDAMIENTO",
            "dominio": "AGENDAMIENTO", 
            "datos_extraidos": datos_extraidos,
            "accion_recomendada": "iniciar_triage_agendamiento"
        }
    
    # V10: entrada EXPLÍCITA estricta (no interpretar variaciones)
    if any(cmd in texto_lower for cmd in ["quiero pagar"]):
        logger.info("[META_AGENTE] ✅ Comando QUIERO PAGAR detectado")
        datos_extraidos = _extraer_datos_pagos(texto_usuario)
        return {
            "decision": "PAGOS",
            "dominio": "PAGOS",
            "datos_extraidos": datos_extraidos, 
            "accion_recomendada": "iniciar_triage_pagos"
        }
    
    # ======== PASO 2: SOLO EN FLUJOS ACTIVOS - EXTRACCIÓN DE DATOS ========
    
    # Si ya está en un flujo activo, SOLO extraer información - wrapper_preguntar() maneja el flujo
    if current_state:
        if current_state.startswith('PAGOS_'):
            logger.info(f"[META_AGENTE] En flujo PAGOS activo - Solo extrayendo datos para wrapper_preguntar")
            datos_extraidos = _extraer_datos_pagos(texto_usuario)
            return {
                "decision": "CONTINUAR_PAGOS",
                "dominio": "PAGOS", 
                "datos_extraidos": datos_extraidos,
                "accion_recomendada": "preguntar"  # wrapper_preguntar maneja flujos activos
            }
        elif current_state.startswith('AGENDA_'):
            logger.info(f"[META_AGENTE] En flujo AGENDA activo - Solo extrayendo datos para wrapper_preguntar")
            datos_extraidos = _extraer_datos_agendamiento(texto_usuario)
            return {
                "decision": "CONTINUAR_AGENDAMIENTO",
                "dominio": "AGENDAMIENTO",
                "datos_extraidos": datos_extraidos, 
                "accion_recomendada": "preguntar"  # wrapper_preguntar maneja flujos activos
            }
    
    # ======== PASO 3: SIN COMANDOS EXPLÍCITOS = AGENTE CERO ========
    
    # Si no hay comandos explícitos, el Meta-Agente NO debe tomar decisiones
    # El usuario debe ser educado sobre los comandos disponibles
    logger.info(f"[META_AGENTE] Sin comando explícito detectado - Pasando control al Agente Cero")
    return {
        "decision": "AGENTE_CERO",
        "dominio": None,
        "datos_extraidos": {},
        "accion_recomendada": "usar_agente_cero"
    }

# === AGENTES DE INTENCIÓN ELIMINADOS ===
# Estas funciones ahora son obsoletas porque el Meta-Agente amplificado 
# maneja tanto la clasificación como la extracción de datos directamente.

# --- Eliminar la función antigua llamar_agente_intencion ---
# def llamar_agente_intencion(...):
#     ...
# (Función eliminada en la migración a multi-agente)

# ELIMINADO V10: llamar_agente_dinamico ya no se usa en el sistema
# ELIMINADO V10: llamar_rodi_generador ya no existe en sistema simplificado
# Toda la funcionalidad está ahora en _llamar_agente_cero_directo() en main.py
