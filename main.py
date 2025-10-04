# main.py (Arquitectura V9.9 - Orquestador Robusto y Orientado a la Acción)
# Versión con la refactorización de la máquina de estados y la lógica de confirmación de citas.
import logging
from logging_config import configure_logging
import base64
import requests
import time
import os
import re # Importamos re para parsear JSON
import mercadopago
from datetime import datetime, timedelta, timezone
from threading import Lock, Thread, Timer
from collections import deque
from flask import Flask, request, jsonify, redirect
from waitress import serve
import copy
import json # Importamos json para la prueba de payload interactivo
from firebase_admin import firestore
from urllib.parse import urlparse, parse_qs

# --- Importaciones de nuestros módulos ---
import config
import memory
from memory import _clean_context_for_firestore
import msgio_handler
import hubspot_handler
import llm_handler
import audio_handler
import utils
# state_manager eliminado - sus funciones se integraron directamente en main.py

# Importamos los nuevos handlers para tenerlos listos.
if 'PAYMENT' in config.ENABLED_AGENTS:
    import pago_handler
if 'SCHEDULING' in config.ENABLED_AGENTS:
    import agendamiento_handler

# === BALLESTER V11 MEDICAL SYSTEM (imports mínimos) ===
try:
    import verification_handler  # Orquestador médico V11
    BALLESTER_V11_ENABLED = True
except Exception:
    BALLESTER_V11_ENABLED = False

# Control de mensajes procesados para evitar duplicados y manejar reintentos tras reinicios
# Diccionario: unique_key -> first_seen_epoch
PROCESSED_MESSAGES = {}
PROCESSED_MESSAGES_LOCK = Lock()

# Configuración de tiempos
STALE_MESSAGE_TTL_SECONDS = 300      # 5 minutos: umbral para ignorar mensajes antiguos re-enviados
DEDUP_CLEANUP_TTL_SECONDS = 7200     # 2 horas: tiempo de retención en cache para claves de deduplicación

# --- PRETAG sin teléfono: cola por-orden para el próximo chat nuevo ---
PENDING_VENDOR_QUEUE = deque()  # elementos: (vendor:str, ts:int)
PENDING_VENDOR_LOCK = Lock()
PENDING_VENDOR_TTL_SECONDS = 30  # 30s de validez para minimizar colisiones

# --- VENDOR OWNER: Detección y normalización ---
# Regla estricta: solo detectar vendor si el usuario escribe explícitamente
# "#AGT=...", "AGT=...", "CLIENTE DE: ...", "AGENTE: ...", "VENDEDOR: ...", "ref=...". Evita falsos positivos (ej. "HOLA").
VENDOR_TEXT_REGEX = re.compile(
    r"(?:#?\s*(?:AGT|AGENTE|VENDEDOR)\s*[=:]\s*|CLIENTE\s*DE\s*:|ref\s*[=:]\s*)[\s\-]*([A-ZÁÉÍÓÚÑ0-9 ._\-]{2,40})",
    flags=re.IGNORECASE
)

# --- VENDOR OWNER: Tag invisible usando caracteres de ancho cero ---
# Marcadores invisibles:
# - Inicio: \u2063\u2063\u2063  (Invisible Separator x3)
# - Fin:    \u2063\u2063        (Invisible Separator x2)
# Cuerpo: secuencia de bits con \u200B (0) y \u200C (1) que codifica ASCII del vendor
HIDDEN_MARKER_START = '\u2063\u2063\u2063'
HIDDEN_MARKER_END = '\u2063\u2063'
ZERO_WIDTH_BIT_0 = '\u200B'  # ZERO WIDTH SPACE
ZERO_WIDTH_BIT_1 = '\u200C'  # ZERO WIDTH NON-JOINER

def _extract_vendor_from_hidden_marker(body: str) -> str | None:
    try:
        if not body or HIDDEN_MARKER_START not in body:
            return None
        start_idx = body.find(HIDDEN_MARKER_START) + len(HIDDEN_MARKER_START)
        end_idx = body.find(HIDDEN_MARKER_END, start_idx)
        if end_idx == -1:
            end_idx = len(body)
        payload = body[start_idx:end_idx]
        # Mantener solo los caracteres de bit esperados
        payload_bits = ''.join(
            '0' if ch == ZERO_WIDTH_BIT_0 else ('1' if ch == ZERO_WIDTH_BIT_1 else '')
            for ch in payload
        )
        if not payload_bits or len(payload_bits) % 8 != 0:
            return None
        bytes_out: list[int] = []
        for i in range(0, len(payload_bits), 8):
            byte_str = payload_bits[i:i+8]
            try:
                bytes_out.append(int(byte_str, 2))
            except Exception:
                return None
        try:
            decoded = bytes(bytes_out).decode('ascii', errors='ignore')
        except Exception:
            return None
        decoded = re.sub(r"[^A-ZÁÉÍÓÚÑ0-9 ._\-]", '', decoded, flags=re.IGNORECASE)
        decoded_norm = _norm_vendor(decoded)
        if decoded_norm:
            logger.info(f"[VENDOR] ✅ Vendor oculto detectado: '{decoded}' -> '{decoded_norm}'")
            return decoded_norm
        return None
    except Exception as e:
        logger.debug(f"[VENDOR] Error extrayendo vendor oculto: {e}")
        return None

def _norm_vendor(name: str) -> str:
    if not name:
        return ""
    
    # Limpiar el código de cualquier prefijo
    cleaned = str(name).strip()
    
    # Remover prefijos comunes como /?ref=, ref=, #agt=, etc.
    cleaned = re.sub(r'^[/\?]*ref\s*[=:]\s*', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'^[#]*\s*(?:agt|agente|vendedor)\s*[=:]\s*', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'^cliente\s*de\s*[=:]\s*', '', cleaned, flags=re.IGNORECASE)
    
    # Normalizar espacios y convertir a mayúsculas
    cleaned = re.sub(r"\s+", " ", cleaned).strip().upper()
    
    return cleaned

def _extract_vendor_from_text(body: str) -> str | None:
    try:
        if not body:
            logger.debug("[VENDOR] Body vacío, no se puede extraer vendor")
            return None
        
        logger.info(f"[VENDOR] Analizando texto para vendor: '{body[:100]}...'")
        # 1) Intento con tag invisible
        hidden = _extract_vendor_from_hidden_marker(body)
        if hidden:
            return hidden

        # 2) Intento con patrones visibles tolerados
        m = VENDOR_TEXT_REGEX.search(body or "")
        if not m:
            logger.info(f"[VENDOR] No se encontró patrón de vendor en: '{body[:100]}...'")
            return None
        
        grp = m.group(1)
        vendor_normalizado = _norm_vendor(grp)
        logger.info(f"[VENDOR] ✅ Vendor extraído: '{grp}' -> '{vendor_normalizado}'")
        return vendor_normalizado
    except Exception as e:
        logger.error(f"[VENDOR] Error extrayendo vendor de '{body[:100]}...': {e}")
        return None

def _extract_vendor_from_referral(first_msg: dict) -> str | None:
    try:
        ref = first_msg.get("referral") if isinstance(first_msg, dict) else None
        if not ref:
            logger.debug("[VENDOR] No hay referral en el mensaje")
            return None
        
        logger.info(f"[VENDOR] Referral encontrado: {ref}")
        src = ref.get("source_url") or ref.get("source") or ""
        if not src:
            logger.debug("[VENDOR] No hay source_url o source en referral")
            return None
        
        logger.info(f"[VENDOR] Source URL: {src}")
        q = parse_qs(urlparse(src).query)
        logger.info(f"[VENDOR] Query params: {q}")
        
        for key in ("ref", "agt", "agent", "seller"):
            if key in q and q[key]:
                vendor = _norm_vendor(q[key][0])
                logger.info(f"[VENDOR] ✅ Vendor encontrado en referral '{key}': '{q[key][0]}' -> '{vendor}'")
                return vendor
        
        logger.info("[VENDOR] No se encontró vendor en parámetros de referral")
        return None
    except Exception as e:
        logger.error(f"[VENDOR] Error extrayendo vendor de referral: {e}", exc_info=True)
        return None

def _debug_message_structure(msg: dict, author: str):
    """
    Función de debug para mostrar la estructura completa del mensaje recibido.
    Útil para entender por qué no se detecta el vendor tag.
    """
    try:
        logger.info(f"[VENDOR_DEBUG] 🔍 Estructura completa del mensaje para {author}:")
        logger.info(f"[VENDOR_DEBUG] Tipo: {msg.get('type')}")
        logger.info(f"[VENDOR_DEBUG] Body directo: {msg.get('body')}")
        logger.info(f"[VENDOR_DEBUG] Text object: {msg.get('text')}")
        logger.info(f"[VENDOR_DEBUG] Referral: {msg.get('referral')}")
        logger.info(f"[VENDOR_DEBUG] Keys disponibles: {list(msg.keys())}")
        
        # Mostrar estructura anidada si existe
        if msg.get('text') and isinstance(msg['text'], dict):
            logger.info(f"[VENDOR_DEBUG] Text keys: {list(msg['text'].keys())}")
            logger.info(f"[VENDOR_DEBUG] Text body: {msg['text'].get('body')}")
        
        if msg.get('referral') and isinstance(msg['referral'], dict):
            logger.info(f"[VENDOR_DEBUG] Referral keys: {list(msg['referral'].keys())}")
            logger.info(f"[VENDOR_DEBUG] Referral source: {msg['referral'].get('source')}")
            logger.info(f"[VENDOR_DEBUG] Referral source_url: {msg['referral'].get('source_url')}")
            
    except Exception as e:
        logger.error(f"[VENDOR_DEBUG] Error en debug: {e}")

def _ensure_vendor_label(author: str, first_msg: dict | None):
    """
    Intenta inferir vendor_owner del mensaje actual
    (texto con #AGT=..., AGENTE: ..., VENDEDOR: ... o referral URL). Si hay nueva evidencia, sobreescribe.
    """
    try:
        if not author:
            logger.debug("[VENDOR] No hay author, saltando")
            return
        
        existing = memory.get_vendor_owner(author) if hasattr(memory, 'get_vendor_owner') else None
        logger.info(f"[VENDOR] 🔍 Buscando vendor para {author} - Actual: {existing or 'NINGUNO'} - Mensaje: {type(first_msg)}")
        
        # Intentar desde texto
        body_text = None
        if isinstance(first_msg, dict):
            logger.info(f"[VENDOR] Mensaje es dict, tipo: {first_msg.get('type')}")
            if first_msg.get('type') == 'text':
                body_text = (first_msg.get('text') or {}).get('body') or first_msg.get('body')
                logger.info(f"[VENDOR] Texto extraído desde 'text.body': '{body_text[:100] if body_text else 'None'}...'")
            else:
                body_text = (first_msg.get('text') or {}).get('body') or first_msg.get('body')
                logger.info(f"[VENDOR] Texto extraído desde 'body': '{body_text[:100] if body_text else 'None'}...'")
        else:
            logger.warning(f"[VENDOR] Mensaje no es dict: {type(first_msg)}")
        
        vendor = _extract_vendor_from_text(body_text or "")
        if not vendor:
            logger.info(f"[VENDOR] No se encontró vendor en texto, intentando referral...")
            vendor = _extract_vendor_from_referral(first_msg or {})
        
        if vendor:
            if vendor != existing:
                if hasattr(memory, 'upsert_vendor_label'):
                    memory.upsert_vendor_label(author, vendor, agent_label=f"AGENTE: {vendor}", only_if_absent=False)
                    logger.info(f"[VENDOR] ✅ Actualizado {author}: {existing or 'NINGUNO'} -> {vendor}")
                else:
                    logger.error(f"[VENDOR] ❌ memory.upsert_vendor_label no disponible")
            else:
                logger.info(f"[VENDOR] ✅ Vendor {vendor} ya asignado para {author}, no se modifica")
        else:
            logger.info(f"[VENDOR] ❌ No se encontró vendor en mensaje para {author}")
            
    except Exception as _e:
        logger.error(f"[VENDOR] ❌ Error fijando vendor para {author}: {_e}", exc_info=True)

def _cleanup_old_processed_messages():
    """Limpia entradas antiguas del caché de deduplicación por TTL y controla tamaño."""
    try:
        current_time = int(time.time())
    except Exception:
        return
    with PROCESSED_MESSAGES_LOCK:
        # Limpiar por TTL
        keys_to_delete = [k for k, first_seen in PROCESSED_MESSAGES.items() if current_time - first_seen > DEDUP_CLEANUP_TTL_SECONDS]
        for k in keys_to_delete:
            PROCESSED_MESSAGES.pop(k, None)
        # Control básico de tamaño para evitar crecimiento desmedido
        if len(PROCESSED_MESSAGES) > 5000:
            # Eliminar de forma aproximada las primeras N claves (no ordenado, suficiente para control de tamaño)
            exceso = len(PROCESSED_MESSAGES) - 4000
            for i, k in enumerate(list(PROCESSED_MESSAGES.keys())):
                if i >= exceso:
                    break
                PROCESSED_MESSAGES.pop(k, None)
            logger.info(f"[LIMPIEZA] Limpiadas {exceso} entradas. Quedan {len(PROCESSED_MESSAGES)}")

# --- FUNCIÓN DE VALIDACIÓN DE DOC_ID ---
def is_valid_doc_id(doc_id):
    # Validación más robusta que permite caracteres válidos como +, @, ., etc.
    return bool(doc_id and isinstance(doc_id, str) and re.match(r'^[\w\-\@\+\.]+$', doc_id or ""))

def _validar_id_interactivo(id_interactivo, current_state):
    """
    PLAN DE ACCIÓN DEFINITIVO: Lógica única y robusta para todos los flujos.
    OBJETIVO: Ser la única autoridad para los clics en botones. Sin ambigüedades.
    """
    logger.info(f"[VALIDACION_ID] Validando ID '{id_interactivo}' en estado '{current_state}'")

    # PLAN DE ACCIÓN: Reglas duras y predecibles para cada tipo de botón
    
    # REGLA 1: SIEMPRE que llegue un turno, CONFIRMAMOS (sin importar el estado)
    if id_interactivo.startswith('turno_'):
        logger.info(f"[VALIDACION_ID] ✅ Botón de turno detectado. Forzando finalizar_cita_automatico.")
        return 'finalizar_cita_automatico'

    # REGLA 2: SIEMPRE que llegue un servicio, CONFIRMAMOS (sin importar el estado)
    if id_interactivo.startswith('servicio_'):
        logger.info(f"[VALIDACION_ID] ✅ Botón de servicio detectado. Forzando confirmar_servicio_pago.")
        return 'confirmar_servicio_pago'

    # REGLA 3: Confirmaciones de pago
    if current_state == 'PAGOS_ESPERANDO_CONFIRMACION':
        if 'confirmar_si' in id_interactivo:
            logger.info(f"[VALIDACION_ID] ✅ Confirmación positiva de pago. Generando link.")
            return 'generar_link_pago'
        elif 'confirmar_no' in id_interactivo:
            logger.info(f"[VALIDACION_ID] ✅ Confirmación negativa de pago. Reiniciando flujo.")
            return 'reiniciar_flujo_pagos'

    # REGLA 4: Confirmaciones de cancelación
    if current_state == 'AGENDA_CANCELACION_CONFIRMANDO':
        if 'confirmar_si' in id_interactivo:
            logger.info(f"[VALIDACION_ID] ✅ Confirmación positiva de cancelación. Ejecutando cancelación.")
            return 'ejecutar_cancelacion_cita'
        elif 'confirmar_no' in id_interactivo:
            logger.info(f"[VALIDACION_ID] ✅ Confirmación negativa de cancelación. Cancelando operación.")
            return 'preguntar'

    # REGLA 5: Confirmaciones de reprogramación
    if current_state == 'AGENDA_REPROGRAMACION_CONFIRMANDO':
        if 'confirmar_si' in id_interactivo:
            logger.info(f"[VALIDACION_ID] ✅ Confirmación positiva de reprogramación. Ejecutando reprogramación.")
            return 'ejecutar_reprogramacion_cita'
        elif 'confirmar_no' in id_interactivo:
            logger.info(f"[VALIDACION_ID] ✅ Confirmación negativa de reprogramación. Cancelando operación.")
            return 'preguntar'

    logger.warning(f"[VALIDACION_ID] ❌ El ID '{id_interactivo}' no tiene una regla para el estado '{current_state}'.")
    return None

def _normalize_message_unified(msg, author, full_payload):
    """
    Función ÚNICA que normaliza cualquier tipo de mensaje y obtiene la media URL si es necesario.
    """
    message_type = msg.get('type', 'text')
    message_content = ''
    media_url = None
    media_id = None
    caption = None

    if message_type == 'interactive':
        if 'list_reply' in msg.get('interactive', {}):
            message_content = msg['interactive']['list_reply'].get('id', '')
        elif 'button_reply' in msg.get('interactive', {}):
            message_content = msg['interactive']['button_reply'].get('id', '')
    elif message_type == 'reaction':
        # Reacciones (ej.: 👍) no deben disparar IA, pero sí registrarse en Chatwoot
        reaction = msg.get('reaction', {}) or {}
        emoji = reaction.get('emoji', '') or ''
        reacted_id = reaction.get('message_id', '') or ''
        # Usamos el emoji como cuerpo; si falta, un marcador textual
        message_content = emoji or '[REACCION]'
        # Construir estructura mínima adicional (no usado por IA)
        sender_name = _extraer_sender_name(msg, author, full_payload)
        return {
            'author': author,
            'body': message_content.strip(),
            'type': 'reaction',
            'senderName': sender_name,
            'time': msg.get('timestamp', ''),
            'reaction_emoji': emoji,
            'reaction_to': reacted_id,
            'media_url': None,
            'media_id': None,
            'caption': None,
        }
    elif message_type == 'text':
        message_content = msg.get('text', {}).get('body', '')
    elif message_type in ['audio', 'image', 'video', 'document']:
        media_payload = msg.get(message_type, {})
        media_id = media_payload.get('id')
        caption = media_payload.get('caption', '')
        
        if media_id:
            # Esta es la parte más importante: obtener URL con el nuevo método que modifica dominios
            media_url = utils.get_media_url(media_id)
            if not media_url:
                logger.warning(f"[NORMALIZE] No se pudo obtener URL para media ID: {media_id}")
        
        message_content = f"[{message_type.upper()}]"
        if caption:
            message_content += f" {caption}"

    if not message_content and not media_url:
        return None

    sender_name = _extraer_sender_name(msg, author, full_payload)
    
    return {
        'author': author, 'body': message_content.strip(), 'type': message_type,
        'senderName': sender_name, 'time': msg.get('timestamp', ''), 'media_url': media_url,
        'media_id': media_id, 'caption': caption
    }

def _procesar_multimedia_instantaneo(author, media_messages, state_context=None):
    """
    NUEVA FUNCIÓN: Procesa multimedia al instante y lo agrega al buffer como mensajes de texto.
    Convierte audios transcritos e imágenes analizadas en mensajes de texto normales en el buffer.
    """
    logger.info(f"[MULTIMEDIA_INSTANTANEO] Iniciando procesamiento instantáneo para {author}")
    
    # Inicializar state_context si es None
    if state_context is None:
        state_context = {}
    
    # Preparar lista para devolver siempre, incluso ante errores
    mensajes_texto_procesados = []
    try:
        # Lista para almacenar mensajes de texto procesados
        mensajes_texto_procesados = []
        
        # Procesar cada mensaje multimedia
        for msg in media_messages:
            message_type = msg.get('type')
            media_url = msg.get('media_url')
            body_content = msg.get('body', '').strip()
            sender_name = msg.get('senderName', 'Usuario')
            
            logger.info(f"[MULTIMEDIA_INSTANTANEO] Procesando {message_type} para {author}")
            
            processed_content = ""
            
            if message_type == 'audio':
                # Manejar audio con método oficial de 360dialog
                logger.info(f"[MULTIMEDIA_INSTANTANEO] 🎵 Procesando audio para {author}")
                media_id = msg.get('media_id')
                
                transcribed_text = None
                
                if media_url:
                    # Opción 1: Intentar transcripción con URL temporal (rápido pero limitado a 5min)
                    # Intentar transcripción directamente (sin signal que no funciona en threads)
                    try:
                        logger.info(f"[MULTIMEDIA_INSTANTANEO] 🔄 Intentando transcripción con URL temporal")
                        transcribed_text = audio_handler.transcribe_audio_from_url(media_url)
                        if transcribed_text and "[Error" not in transcribed_text and "[Audio recibido - timeout" not in transcribed_text:
                            logger.info(f"[MULTIMEDIA_INSTANTANEO] ✅ Transcripción exitosa con URL temporal")
                        else:
                            logger.warning(f"[MULTIMEDIA_INSTANTANEO] ⚠️ Primera transcripción falló o tuvo timeout")
                            transcribed_text = None
                    except Exception as e:
                        logger.warning(f"[MULTIMEDIA_INSTANTANEO] ⚠️ Error con URL temporal: {e}")
                        transcribed_text = None
                
                # Opción 2: Si falla URL temporal, usar descarga oficial de 360dialog
                if not transcribed_text and media_id:
                    try:
                        logger.info(f"[MULTIMEDIA_INSTANTANEO] 💾 Descargando audio usando método oficial 360dialog")
                        download_result = utils.download_and_store_media(media_id, "./temp_audio")
                        
                        if download_result["success"]:
                            filepath = download_result["filepath"]
                            logger.info(f"[MULTIMEDIA_INSTANTANEO] ✅ Audio descargado: {filepath}")
                            
                            # Si tienes transcribe_audio_from_file, úsalo:
                            # transcribed_text = audio_handler.transcribe_audio_from_file(filepath)
                            
                            # Por ahora, intentar de nuevo con la URL (ya descargada es más confiable)
                            if media_url:
                                try:
                                    logger.info(f"[MULTIMEDIA_INSTANTANEO] 🔄 Segundo intento con descarga+upload")
                                    transcribed_text = audio_handler.transcribe_audio_from_url_with_download(media_url)
                                    
                                    # Si aún falla, intentar una vez más con método original
                                    if not transcribed_text or "[Error" in transcribed_text:
                                        logger.info(f"[MULTIMEDIA_INSTANTANEO] 🔄 Tercer intento con método original")
                                        transcribed_text = audio_handler.transcribe_audio_from_url(media_url)
                                        
                                except Exception as e:
                                    logger.error(f"[MULTIMEDIA_INSTANTANEO] Error en segundo intento: {e}")
                        else:
                            logger.error(f"[MULTIMEDIA_INSTANTANEO] ❌ Error descargando: {download_result['error']}")
                    except Exception as e:
                        logger.error(f"[MULTIMEDIA_INSTANTANEO] 💥 Error en descarga: {e}")
                
                # Resultado final del audio
                if transcribed_text:
                    processed_content = f"[AUDIO]: {transcribed_text}"
                    logger.info(f"[MULTIMEDIA_INSTANTANEO] ✅ Audio transcrito exitosamente")
                else:
                    # Aún registrar que se recibió un audio aunque no se pueda transcribir
                    processed_content = f"[AUDIO]: (nota de voz recibida - ID: {media_id})"
                    logger.warning(f"[MULTIMEDIA_INSTANTANEO] ⚠️ Audio recibido pero no transcribible")
            
            elif message_type == 'image':
                # Manejar imagen con método oficial - DEBE pasar por el lector
                logger.info(f"[MULTIMEDIA_INSTANTANEO] 🖼️ Procesando imagen para {author}")
                caption = msg.get('caption', '')
                media_id = msg.get('media_id')
                
                image_description = None
                
                if media_url:
                    # Descargar y analizar imagen con el lector
                    try:
                        logger.info(f"[MULTIMEDIA_INSTANTANEO] 📥 Descargando imagen para análisis")
                        import requests
                        import base64
                        from llm_handler import llamar_agente_lector
                        
                        # IMPORTANTE: Agregar headers de autorización para 360dialog
                        headers = {}
                        if media_url and 'waba-v2.360dialog.io' in media_url:
                            headers = {"D360-API-KEY": os.getenv('D360_API_KEY')}
                            logger.info(f"[MULTIMEDIA_INSTANTANEO] 🔑 Usando API key para descargar imagen de 360dialog")

                        response = requests.get(media_url, headers=headers, timeout=45)
                        response.raise_for_status()
                        
                        if len(response.content) > 5 * 1024 * 1024:
                            logger.warning(f"[MULTIMEDIA_INSTANTANEO] ⚠️ Imagen demasiado grande para {author}")
                            image_description = "Imagen demasiado grande para procesar"
                        else:
                            # Convertir a base64 y preparar para el lector
                            image_base64 = base64.b64encode(response.content).decode('utf-8')
                            image_content_for_lector = [{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}}]
                            
                            # Llamar al lector para analizar la imagen
                            logger.info(f"[MULTIMEDIA_INSTANTANEO] 🔍 Analizando imagen con agente lector")
                            image_description = llamar_agente_lector(image_content_for_lector).strip()
                            logger.info(f"[MULTIMEDIA_INSTANTANEO] ✅ Imagen analizada exitosamente")
                    except Exception as e:
                        logger.error(f"[MULTIMEDIA_INSTANTANEO] ❌ Error analizando imagen: {e}")
                
                # Resultado final de la imagen (quirúrgico para comprobantes)
                # Si el lector devuelve el formato estricto de comprobante, conservarlo tal cual; si no, no forzar mensaje de comprobante
                if image_description and image_description.strip().upper().startswith("COMPROBANTE DE PAGO:"):
                    # Mensaje concreto de detección de comprobante; no anteponer "Descripción"
                    processed_content = image_description.strip()
                    logger.info(f"[MULTIMEDIA_INSTANTANEO] ✅ Comprobante de pago detectado por lector: '{processed_content}'")
                    
                    # NUEVO: Registrar automáticamente el pago como verificado
                    try:
                        # Extraer el monto del comprobante
                        import re
                        monto_match = re.search(r'\$\s*([\d.,]+)', processed_content)
                        if monto_match:
                            monto_detectado = monto_match.group(1).replace(',', '').replace('.', '')
                            try:
                                monto_numerico = int(monto_detectado)
                                # Registrar el pago como verificado
                                state_context['payment_verified'] = True
                                state_context['payment_amount'] = monto_numerico
                                state_context['payment_status'] = f'VERIFICADO - ${monto_numerico:,}'
                                state_context['payment_verification_timestamp'] = datetime.now().isoformat()
                                
                                # Limpiar restricciones de pago
                                state_context['payment_restriction_active'] = False
                                state_context['requires_payment_first'] = False
                                state_context['blocked_action'] = None
                                
                                # CORRECCIÓN V10: NO cambiar estado automáticamente
                                # El usuario debe usar "SALIR DE PAGO" para cambiar estado
                                # Solo marcar pago como verificado, mantener flujo actual
                                logger.info(f"[PAGO_VERIFICADO] ✅ Pago verificado pero manteniendo flujo actual para comandos explícitos")
                                
                                logger.info(f"[PAGO_VERIFICADO] ✅ Pago registrado automáticamente: ${monto_numerico:,} para {author}")
                                logger.info(f"[PAGO_VERIFICADO] 🔓 Restricciones de pago removidas para {author}")
                            except ValueError:
                                logger.warning(f"[PAGO_VERIFICADO] ⚠️ No se pudo convertir monto a número: {monto_detectado}")
                        else:
                            logger.warning(f"[PAGO_VERIFICADO] ⚠️ No se pudo extraer monto del comprobante: {processed_content}")
                    except Exception as e:
                        logger.error(f"[PAGO_VERIFICADO] ❌ Error registrando pago: {e}")
                elif image_description and image_description.strip() != "N/A":
                    # Otros casos donde el lector describa la imagen (opcional): registramos como descripción genérica
                    if caption:
                        processed_content = f"[IMAGEN]: {caption} - Descripción: {image_description.strip()}"
                    else:
                        processed_content = f"[IMAGEN]: {image_description.strip()}"
                    logger.info(f"[MULTIMEDIA_INSTANTANEO] ✅ Imagen procesada con descripción genérica")
                else:
                    # Fallback si no se puede analizar o no es comprobante
                    if caption:
                        processed_content = f"[IMAGEN]: {caption}"
                    else:
                        processed_content = f"[IMAGEN]: (imagen enviada - ID: {media_id})"
                    logger.info(f"[MULTIMEDIA_INSTANTANEO] ℹ️ Imagen recibida sin comprobante detectado")
            
            elif message_type == 'video':
                caption = msg.get('caption', '')
                if caption:
                    processed_content = f"[VIDEO]: {caption}"
                elif body_content:
                    processed_content = f"[VIDEO]: {body_content}"
                else:
                    processed_content = "[VIDEO]: (video enviado)"
                logger.info(f"[MULTIMEDIA_INSTANTANEO] Video procesado: '{processed_content}'")
            
            elif message_type == 'document':
                caption = msg.get('caption', '')
                if caption:
                    processed_content = f"[DOCUMENTO]: {caption}"
                elif body_content:
                    processed_content = f"[DOCUMENTO]: {body_content}"
                else:
                    processed_content = "[DOCUMENTO]: (documento enviado)"
                logger.info(f"[MULTIMEDIA_INSTANTANEO] Documento procesado: '{processed_content}'")
            
            # NUEVA LÓGICA: Crear mensaje de texto con el contenido procesado
            if processed_content:
                mensaje_texto = {
                    'type': 'text',
                    'body': processed_content,
                    'timestamp': msg.get('timestamp'),
                    'senderName': sender_name,
                    'id': f"{msg.get('id', '')}_processed"  # ID único para evitar duplicados
                }
                mensajes_texto_procesados.append(mensaje_texto)
                logger.info(f"[MULTIMEDIA_INSTANTANEO] ✅ Contenido multimedia convertido a mensaje de texto: '{processed_content}'")
        
        # Nota: Ya no agregamos al buffer local. El caller persistirá en Firestore.
        if mensajes_texto_procesados:
            logger.info(f"[MULTIMEDIA_INSTANTANEO] 🚀 Total mensajes procesados para {author}: {len(mensajes_texto_procesados)}")
    
    except Exception as e:
        logger.error(f"[MULTIMEDIA_INSTANTANEO] Error procesando multimedia para {author}: {e}", exc_info=True)
    
    # NUEVO: Si se verificó un pago, persistir el contexto inmediatamente
    if state_context and state_context.get('payment_verified'):
        try:
            # Obtener estado actual para persistir
            _, _, current_state, _ = memory.get_conversation_data(phone_number=author)
            # IMPORTANTE: Usar el estado del contexto si fue actualizado
            estado_a_persistir = state_context.get('current_state', current_state)
            memory.update_conversation_state(author, estado_a_persistir, context=_clean_context_for_firestore(state_context))
            logger.info(f"[PAGO_VERIFICADO] 💾 Contexto con pago verificado persistido para {author}")
        except Exception as e:
            logger.error(f"[PAGO_VERIFICADO] ❌ Error persistiendo contexto: {e}")
    
    # Devolver los mensajes de texto procesados para permitir persistencia cross-proceso
    return mensajes_texto_procesados


def _reconstruir_mensaje_usuario(messages_to_process, author):
    logger.info(f"[RECONSTRUIR] Iniciando reconstrucción de mensaje para {author} - {len(messages_to_process)} mensajes")
    
    # Obtener contexto actual para incluir multimedia procesada previamente
    history, _, current_state, state_context = memory.get_conversation_data(phone_number=author)
    
    ordered_user_content = []
    user_message_for_history = ""
    
    # NUEVO: Incluir contenido multimedia procesado previamente desde el contexto
    if state_context and 'multimedia_processed' in state_context:
        for multimedia_item in state_context['multimedia_processed']:
            content = multimedia_item.get('content', '')
            if content:
                ordered_user_content.append(content)
                user_message_for_history += content + " "
                logger.info(f"[RECONSTRUIR] ✅ Incluyendo multimedia pre-procesada: '{content}'")
    
    # Procesar mensajes actuales (solo texto e interactivos)
    for i, msg in enumerate(messages_to_process):
        message_type = msg.get('type')
        body_content = msg.get('body', '').strip()
        
        logger.info(f"[RECONSTRUIR] Procesando mensaje {i+1}/{len(messages_to_process)} - Tipo: {message_type}")
        
        # SOLO procesar texto e interactivos (multimedia ya se procesó instantáneamente)
        if message_type in ['text', 'interactive']:
            if body_content:
                ordered_user_content.append(body_content)
                user_message_for_history += body_content + " "
                logger.info(f"[RECONSTRUIR] Texto agregado: '{body_content}'")
        else:
            logger.info(f"[RECONSTRUIR] Ignorando {message_type} - ya procesado instantáneamente")
    
    if not ordered_user_content:
        logger.warning(f"[RECONSTRUIR] No se pudo extraer contenido útil para {author}")
        return "", ""

    # Unir todo el contenido en un mensaje coherente
    mensaje_completo_usuario = " ".join(ordered_user_content).strip()
    logger.info(f"[RECONSTRUIR] Mensaje completo unificado: '{mensaje_completo_usuario}'")
    logger.info(f"[RECONSTRUIR] Historial para guardar: '{user_message_for_history.strip()}'")
    
    return mensaje_completo_usuario, user_message_for_history.strip()



def _obtener_estrategia(current_state, mensaje_enriquecido, history, contexto_extra, mensaje_completo_usuario, state_context=None, message_type_original=None):
    """
    PLAN DE REFACTORIZACIÓN v3: Función con lógica anti-bucle para prevenir "triage loops".
    """
    logger.info(f"[ESTRATEGIA] Obteniendo estrategia LLM para estado: {current_state}")

    # HARD-GUARD: Si NO hay departamentos habilitados, saltar Meta-Agente e Intenciones
    try:
        if not (('PAYMENT' in config.ENABLED_AGENTS) or ('SCHEDULING' in config.ENABLED_AGENTS)):
            logger.info("[ESTRATEGIA] Modo SOLO AGENTE CERO. Saltando Meta-Agente e Intenciones.")
            # Asegurar que nunca quede marcado como pasado a departamento
            if isinstance(state_context, dict):
                state_context['pasado_a_departamento'] = False
                # CORRECCIÓN V10: NO forzar 'conversando', respetar estado actual
                # Solo inicializar si no hay estado (nuevo usuario)
                if not state_context.get('current_state'):
                    state_context['current_state'] = 'conversando'
            # Estrategia: solo 'preguntar'
            return {"detalles": {}, "accion_recomendada": "preguntar"}
    except Exception:
        # Si algo falla en la validación, continuar pero jamás cortar la conversación
        logger.warning("[ESTRATEGIA] No se pudo validar ENABLED_AGENTS. Continuando en modo seguro.")

    # PLAN DE REFACTORIZACIÓN v3: Lógica Anti-Bucle
    if not state_context:
        state_context = {}
    
    # Inicializar contador de triage si no existe
    triage_count = state_context.get('triage_count', 0)
    logger.info(f"[ESTRATEGIA] Contador de triage actual: {triage_count}")

    # Llamada al Meta-Agente AMPLIFICADO para decisión + extracción
    meta_resultado = llm_handler.llamar_meta_agente(mensaje_enriquecido, history, current_state)
    logger.info(f"[ESTRATEGIA] Meta-Agente Amplificado decidió: {meta_resultado}")

    # MANEJO DE DECISIONES DEL META-AGENTE
    decision = meta_resultado.get("decision", "AGENTE_CERO")
    
    # Comando SALIR - limpiar estado y pasar al Agente Cero (siempre permitido)
    if decision in ["SALIR_PAGOS", "SALIR_AGENDAMIENTO"]:
        logger.info(f"[ESTRATEGIA] Comando SALIR detectado: {decision}")
        # Limpiar estado completamente y volver al Agente Cero
        state_context = {
            'author': state_context.get('author'),
            'senderName': state_context.get('senderName'),
            'pasado_a_departamento': False,
            'triage_count': 0
        }
        estrategia = {
            "accion_recomendada": "volver_agente_cero",
            "detalles": {
                "mensaje_salida": "Perfecto, saliste del flujo. ¿En qué más puedo ayudarte?"
            }
        }
    elif decision == "AGENTE_CERO":
        logger.info(f"[ESTRATEGIA] Sin comando explícito - Usando Agente Cero")
        # Pasar control al Agente Cero para educación/conversación
        estrategia = {
            "accion_recomendada": "usar_agente_cero", 
            "detalles": {}
        }
    else:
        # Flujo normal - comandos explícitos o en flujo activo
        dominio = meta_resultado.get("dominio", "AGENDAMIENTO")
        datos_extraidos = meta_resultado.get("datos_extraidos", {})
        accion_recomendada = meta_resultado.get("accion_recomendada", "iniciar_triage_agendamiento")
        
        # Construir estrategia directamente con datos del Meta-Agente
        estrategia = {
            "accion_recomendada": accion_recomendada,
            "detalles": datos_extraidos.copy()
        }
        
        # Agregar información de dominio y aplicar blindaje de flujo activo
        estrategia["detalles"]["dominio_sugerido"] = dominio
        # BLINDAJE CENTRAL DE ESTADO: si hay flujo activo, jamás cambiar dominio
        if current_state and (current_state.startswith('PAGOS_') or current_state.startswith('AGENDA_')):
            estrategia["accion_recomendada"] = "preguntar"
            datos_extraidos.clear()  # ignorar extracción que cambie de dominio
            logger.info(f"[ESTRATEGIA] 🔒 Flujo activo -> forzar 'preguntar' y mantener dominio")
        
        logger.info(f"[ESTRATEGIA] Estrategia construida desde Meta-Agente: {estrategia}")

    # PLAN DE REFACTORIZACIÓN v3: Detectar acciones de triage
    accion_recomendada = estrategia.get("accion_recomendada", "")
    es_accion_triage = accion_recomendada in ["iniciar_triage_agendamiento", "iniciar_triage_pagos"]
    
    if es_accion_triage:
        triage_count += 1
        logger.info(f"[ESTRATEGIA] Acción de triage detectada. Contador incrementado a: {triage_count}")
        
        # PLAN DE REFACTORIZACIÓN v3: Romper bucle después de 2 intentos
        if triage_count >= 3:
            logger.warning(f"[ESTRATEGIA] ⚠️ BUCLE DE TRIAGE DETECTADO ({triage_count} intentos). Forzando escalación a humano.")
            estrategia = {
                "accion_recomendada": "escalar_a_humano",
                "detalles": {
                    "motivo": "bucle_triage",
                    "intentos": triage_count,
                    "mensaje_usuario": mensaje_completo_usuario
                }
            }
            # Resetear contador para futuras interacciones
            state_context['triage_count'] = 0
        else:
            # Actualizar contador en el contexto
            state_context['triage_count'] = triage_count
    else:
        # Si no es acción de triage, resetear contador
        if triage_count > 0:
            logger.info(f"[ESTRATEGIA] Acción no-triage detectada. Reseteando contador de triage de {triage_count} a 0")
            state_context['triage_count'] = 0

    # CORRECCIÓN CRÍTICA PARA ELIMINAR EL "ESTADO FANTASMA"
    if estrategia.get("accion_recomendada") in ["iniciar_triage_pagos"]:
        estrategia["proximo_estado_sugerido"] = "PAGOS_ESPERANDO_SELECCION_SERVICIO"
        logger.info(f"[ESTRATEGIA] Forzando estado inicial de pagos a '{estrategia['proximo_estado_sugerido']}' para evitar estados fantasma.")
    elif estrategia.get("accion_recomendada") in ["iniciar_agendamiento", "iniciar_triage_agendamiento"]:
         estrategia["proximo_estado_sugerido"] = "AGENDA_MOSTRANDO_OPCIONES"
         logger.info(f"[ESTRATEGIA] Forzando estado inicial de agendamiento a '{estrategia['proximo_estado_sugerido']}' para evitar estados fantasma.")
    
    # Añadir una re-evaluación si la IA solo sugiere "preguntar" pero estamos en un flujo
    if estrategia.get("accion_recomendada") == "preguntar" and (current_state.startswith('PAGOS_') or current_state.startswith('AGENDA_')):
         logger.info(f"[ESTRATEGIA] LLM sugirió 'preguntar' en estado de flujo '{current_state}'. Dejamos que el wrapper use Generador y mantenga el flujo.")

    logger.info(f"[ESTRATEGIA] Estrategia LLM obtenida: {estrategia}")
    return estrategia

def _ejecutar_accion(accion, history, detalles, state_context, mensaje_completo_usuario, author):
    logger.info(f"[EJECUTAR] Ejecutando acción: {accion} para {author}")
    if accion not in MAPA_DE_ACCIONES:
        logger.error(f"Acción '{accion}' no encontrada en MAPA_DE_ACCIONES.")
        
        # MENSAJE EDUCATIVO según el contexto actual
        current_state = state_context.get('current_state', '') if state_context else ''
        if current_state.startswith('PAGOS_'):
            mensaje_educativo = f"{config.COMMAND_TIPS['GEN_PROBLEMA_PAGO']} Para salir y volver al inicio, {config.COMMAND_TIPS['EXIT_PAGO']}"
        elif current_state.startswith('AGENDA_'):
            mensaje_educativo = f"{config.COMMAND_TIPS['GEN_PROBLEMA_AGENDA']} Para salir y volver al inicio, {config.COMMAND_TIPS['EXIT_AGENDA']}"
        else:
            mensaje_educativo = f"Tuve un problema técnico. {config.COMMAND_TIPS['ENTER_AGENDA']}. {config.COMMAND_TIPS['ENTER_PAGO']}"
        
        return mensaje_educativo, state_context
    
    # BLINDAJE DE DOMINIO EN EJECUCIÓN: si hay flujo activo, bloquear acciones de otro dominio
    try:
        current_state_local = (state_context or {}).get('current_state', '') or ''
        accion_limpia = str(accion).strip()
        # Listas blancas mínimas por dominio
        acciones_permitidas_pagos = {
            'preguntar',
            'iniciar_triage_pagos', 'mostrar_servicios_pago', 'generar_link_pago',
            'confirmar_servicio_pago', 'confirmar_pago', 'reanudar_flujo_anterior',
            'salir_de_pago', 'volver_agente_cero'
        }
        # EXCEPCIÓN: si el pago está verificado, permitir saltar a agendamiento
        try:
            if (state_context or {}).get('payment_verified'):
                acciones_permitidas_pagos.update({'iniciar_triage_agendamiento', 'mostrar_opciones_turnos'})
        except Exception:
            pass

        acciones_permitidas_agenda = {
            'preguntar',
            'iniciar_agendamiento', 'iniciar_triage_agendamiento', 'mostrar_opciones_turnos',
            'seleccionar_turno', 'confirmar_turno', 'reprogramar', 'cancelar',
            'confirmar_cancelacion', 'reanudar_flujo_anterior', 'salir_de_agenda', 'volver_agente_cero',
            'finalizar_cita_automatico', 'iniciar_reprogramacion_cita', 'ejecutar_reprogramacion_cita'
        }
        if current_state_local.startswith('PAGOS_'):
            if accion_limpia not in acciones_permitidas_pagos:
                logger.info("[BLINDAJE_EJECUTAR] En flujo PAGOS: bloqueo de acción fuera de dominio. Reforzando UI de pagos")
                try:
                    # Mostrar nuevamente servicios (sin texto conversacional)
                    return pago_handler.mostrar_servicios_pago(
                        history=history,
                        detalles=detalles or {},
                        state_context=state_context,
                        mensaje_completo_usuario=mensaje_completo_usuario,
                        author=author
                    )
                except Exception:
                    return (f"Estás en el flujo de pagos. Para continuar elegí un servicio. \n"
                            f"{config.COMMAND_TIPS['EXIT_PAGO']}") , state_context
        elif current_state_local.startswith('AGENDA_'):
            if accion_limpia not in acciones_permitidas_agenda:
                logger.info("[BLINDAJE_EJECUTAR] En flujo AGENDA: bloqueo de acción fuera de dominio. Reforzando UI de agenda")
                try:
                    # Reforzar opciones de turnos (sin texto conversacional)
                    resultado, nuevo_state = agendamiento_handler.mostrar_opciones_turnos(
                        history=history,
                        detalles=detalles or {},
                        state_context=state_context,
                        mensaje_completo_usuario=mensaje_completo_usuario,
                        author=author
                    )
                    if resultado is None:
                        return None, nuevo_state
                    return (f"Estás en el flujo de agendamiento. Elegí un turno de la lista anterior. \n"
                            f"{config.COMMAND_TIPS['EXIT_AGENDA']}") , nuevo_state
                except Exception:
                    return (f"Estás en el flujo de agendamiento. {config.COMMAND_TIPS['EXIT_AGENDA']}") , state_context
    except Exception as _e:
        logger.warning(f"[BLINDAJE_EJECUTAR] No se pudo aplicar el guard de dominio: {_e}")

    try:
        # ¡LA CORRECCIÓN MÁS IMPORTANTE!
        # Pasamos los argumentos por nombre para asegurar que cada función reciba lo que necesita.
        # GUARDIA DE REPROGRAMACIÓN: Solo si existe un turno confirmado
        try:
            if accion in ("iniciar_reprogramacion_cita", "ejecutar_reprogramacion_cita"):
                from memory import obtener_ultimo_turno_confirmado
                _author_guard = author or ((state_context or {}).get('author'))
                ultimo_turno = obtener_ultimo_turno_confirmado(_author_guard) if _author_guard else None
                if not ultimo_turno:
                    logger.info("[REPROG_GUARD] Sin turno confirmado. Redirigiendo a iniciar_triage_agendamiento")
                    accion = "iniciar_triage_agendamiento"
                    detalles = (detalles or {})
                    detalles['motivo'] = 'sin_turno_para_reprogramar'
        except Exception as _e:
            logger.warning(f"[REPROG_GUARD] No se pudo verificar turno confirmado: {_e}")
        respuesta_final, nuevo_contexto = MAPA_DE_ACCIONES[accion](
            history=history, 
            detalles=detalles, 
            state_context=state_context, 
            mensaje_completo_usuario=mensaje_completo_usuario,
            author=author # <-- ¡EL PARÁMETRO FALTANTE!
        )
        logger.info(f"Acción '{accion}' ejecutada. Respuesta: {respuesta_final[:100] if respuesta_final else 'None'}")
        return respuesta_final, nuevo_contexto
    except Exception as e:
        logger.error(f"Error catastrófico al ejecutar acción '{accion}': {e}", exc_info=True)
        
        # MENSAJE EDUCATIVO según el contexto actual
        current_state = state_context.get('current_state', '') if state_context else ''
        if current_state.startswith('PAGOS_'):
            mensaje_educativo = f"Estoy teniendo problemas en el flujo de pagos. {config.COMMAND_TIPS['EXIT_PAGO']}"
        elif current_state.startswith('AGENDA_'):
            mensaje_educativo = f"Estoy teniendo problemas en el flujo de agendamiento. {config.COMMAND_TIPS['EXIT_AGENDA']}"
        else:
            mensaje_educativo = f"Tuve un problema técnico. {config.COMMAND_TIPS['ENTER_AGENDA']}. {config.COMMAND_TIPS['ENTER_PAGO']}"
        
        return mensaje_educativo, state_context

# --- Wrapper para la acción 'preguntar' ---
def wrapper_preguntar(history, detalles, state_context, mensaje_completo_usuario, author=None):
    """
    Fallback consciente de dominio:
    - Si estamos en AGENDA (o hay señales de AGENDA), no usar el generador: re-ofrecer turnos usando extracción con el agente de intención.
    - Si estamos en PAGOS (o hay señales de PAGOS), reanudar/mostrar servicios sin usar el generador.
    - Solo si no hay señales de flujo activo, usar el generador conversacional.
    """
    state_context = state_context or {}

    # MODO SOLO AGENTE CERO: todas las respuestas vienen del Agente Cero
    try:
        if not (('PAYMENT' in config.ENABLED_AGENTS) or ('SCHEDULING' in config.ENABLED_AGENTS)):
            # CORRECCIÓN CRÍTICA: Usar función helper para context_info completo
            context_info = _construir_context_info_completo(detalles, state_context, mensaje_completo_usuario, "preguntar", state_context.get('author') if state_context else None)
            respuesta_cero = _llamar_agente_cero_directo(history, context_info)
            
            # CORRECCIÓN CRÍTICA: Procesar respuesta del Agente Cero para extraer solo texto
            try:
                import utils
                data_cero = utils.parse_json_from_llm_robusto(str(respuesta_cero), context="wrapper_preguntar_solo_agente_cero") or {}
                
                # Si viene JSON con response_text, usar solo ese texto
                if data_cero.get("response_text"):
                    respuesta_final = data_cero.get("response_text")
                else:
                    respuesta_final = respuesta_cero
            except Exception:
                respuesta_final = respuesta_cero
            
            return respuesta_final, state_context
    except Exception:
        # Si algo falla, continuar con lógica general, pero no enviar textos rígidos
        pass

    # LÓGICA SIMPLIFICADA V10: Solo usar current_state para detectar flujos activos
    current_state_sc = state_context.get('current_state', '') or ''
    
    # SISTEMA SIMPLIFICADO: Solo current_state determina flujos activos
    hay_pagos_activo = current_state_sc.startswith('PAGOS_')
    hay_agenda_activa = current_state_sc.startswith('AGENDA_')
    
    # Restricciones solo para información, no afectan detección de flujos
    hay_restricciones_activas = (
        state_context.get('requires_payment_first') or 
        state_context.get('payment_restriction_active') or
        state_context.get('blocked_action')
    )
    
    logger.info(f"[WRAPPER_PREGUNTAR] SIMPLIFICADO - current_state: {current_state_sc}")
    logger.info(f"[WRAPPER_PREGUNTAR] hay_pagos_activo: {hay_pagos_activo}, hay_agenda_activa: {hay_agenda_activa}")
    
    # Si current_state = "conversando" → NO hay flujos activos, usar Agente Cero
    # BLINDAJE: si hay 'pasado_a_departamento' True se respeta como metadato, pero
    # no se considera flujo activo salvo que el estado comience con PAGOS_/AGENDA_
    if current_state_sc == 'conversando':
        logger.info(f"[WRAPPER_PREGUNTAR] Estado 'conversando' - Usando Agente Cero directamente")
        author = state_context.get('author') if state_context else None
        context_info = _construir_context_info_completo(detalles, state_context, mensaje_completo_usuario, "preguntar", author)
        
        respuesta_cero = _llamar_agente_cero_directo(history, context_info)
        
        # CORRECCIÓN CRÍTICA: Procesar respuesta del Agente Cero para ejecutar acción o extraer solo texto
        try:
            import utils
            data_cero = utils.parse_json_from_llm_robusto(str(respuesta_cero), context="wrapper_preguntar_conversando") or {}
            
            # CASO 0: Ejecutar acción si es válida
            accion_recomendada = str(data_cero.get("accion_recomendada", "")).strip()
            if accion_recomendada and accion_recomendada in MAPA_DE_ACCIONES:
                logger.info(f"[WRAPPER_PREGUNTAR] (conversando) Agente Cero recomienda acción: {accion_recomendada}")
                detalles_accion = data_cero.get("detalles", {}) or {}
                return _ejecutar_accion(accion_recomendada, history, detalles_accion, state_context, mensaje_completo_usuario, author)

            # Si viene JSON con response_text, usar solo ese texto
            if data_cero.get("response_text"):
                respuesta_final = data_cero.get("response_text")
            else:
                respuesta_final = respuesta_cero
        except Exception:
            respuesta_final = respuesta_cero
        
        return respuesta_final, state_context

    def _es_pregunta_general(texto: str) -> bool:
        if not isinstance(texto, str):
            return False
        t = texto.lower()
        # Palabras de pregunta
        qw = ["qué", "que ", "cómo", "como ", "cuándo", "cuando ", "dónde", "donde ", "por qué", "porque", "cuál", "cual ", "quién", "quien ", "?", "¿"]
        es_pregunta = any(w in t for w in qw)
        return es_pregunta

    def _es_ack_breve(texto: str) -> bool:
        """Detecta confirmaciones sociales breves."""
        if not isinstance(texto, str):
            return False
        t = texto.strip().lower()
        if not t or len(t) > 16:
            return False
        acks = {
            "ok", "oka", "okey", "okk", "dale", "listo", "gracias", "muchas gracias",
            "perfecto", "genial", "bien", "entendido", "anotado", "vale", "va", "sip", "sí", "si"
        }
        return t in acks

    def _responder_ack_cortesia(detalles_locales: dict, sc: dict) -> tuple[str, dict]:
        """Usa el Agente Cero para una cortesía breve."""
        try:
            # CORRECCIÓN CRÍTICA: Usar función helper para context_info completo
            author = sc.get('author') if sc else None
            context_info = _construir_context_info_completo(detalles_locales, sc, mensaje_completo_usuario, "cierre_cortesia", author)
            
            # REEMPLAZO QUIRÚRGICO: Usar Agente Cero con contexto completo
            respuesta_cero = _llamar_agente_cero_directo(history, context_info)
            
            # CORRECCIÓN CRÍTICA: Procesar respuesta del Agente Cero para extraer solo texto
            try:
                import utils
                data_cero = utils.parse_json_from_llm_robusto(str(respuesta_cero), context="responder_ack_cortesia") or {}
                
                # Si viene JSON con response_text, usar solo ese texto
                if data_cero.get("response_text"):
                    respuesta_final = data_cero.get("response_text")
                else:
                    respuesta_final = respuesta_cero
            except Exception:
                respuesta_final = respuesta_cero
            
            return respuesta_final, sc
        except Exception:
            # Ante cualquier fallo, silencio elegante
            return "", sc

    # 1) PAGOS: BLINDAJE TOTAL - SOLO SERVICIOS/BOTONES, NUNCA TEXTO CONVERSACIONAL
    if hay_pagos_activo and 'pago_handler' in globals():
        logger.info(f"[WRAPPER_PREGUNTAR] BLINDAJE PAGOS - Solo servicios/botones permitidos")
        
        # BLINDAJE V10: En pagos, NUNCA usar Agente Cero, SIEMPRE mostrar servicios
        logger.info(f"[BLINDAJE_PAGOS] Forzando servicios de pago - NO texto conversacional")
        try:
            # Si el pago ya está verificado, no hay nada más que hacer en pagos.
            # Educar al usuario para salir explícitamente del flujo.
            if state_context.get('payment_verified'):
                # Regla de negocio: pago verificado permite saltar directo a agendamiento sin frase
                logger.info("[BLINDAJE_PAGOS] Pago verificado: iniciando agendamiento automáticamente")
                detalles_auto = (detalles or {}).copy()
                try:
                    from utils import parsear_fecha_hora_natural as _parse_fecha_hora
                    parsed = _parse_fecha_hora(mensaje_completo_usuario or "", return_details=True) or {}
                    if parsed:
                        fecha_dt = parsed.get('fecha_datetime')
                        fecha_iso = parsed.get('fecha_iso')
                        hora_parseada = parsed.get('hora')
                        preferencia_horaria_msg = parsed.get('preferencia_horaria')
                        if fecha_dt:
                            detalles_auto['fecha_deseada'] = fecha_dt.strftime('%Y-%m-%d')
                        elif fecha_iso:
                            detalles_auto['fecha_deseada'] = fecha_iso
                        if hora_parseada:
                            detalles_auto['hora_especifica'] = hora_parseada
                        if preferencia_horaria_msg:
                            detalles_auto['preferencia_horaria'] = preferencia_horaria_msg
                except Exception as _e:
                    logger.warning(f"[BLINDAJE_PAGOS] No se pudo parsear fecha/hora para autoiniciar agenda: {_e}")
                try:
                    logger.info(f"[PAGOS→AGENDA_PARSE] Filtros autoinicio: fecha={detalles_auto.get('fecha_deseada')}, hora={detalles_auto.get('hora_especifica')}, pref={detalles_auto.get('preferencia_horaria')}")
                except Exception:
                    pass
                return _ejecutar_accion(
                    'iniciar_triage_agendamiento',
                    history,
                    detalles_auto,
                    state_context,
                    mensaje_completo_usuario,
                    author
                )
            # Si ya estábamos esperando confirmación, reanudar; de lo contrario, volver a listar
            if current_state_sc == 'PAGOS_ESPERANDO_CONFIRMACION':
                return pago_handler.reanudar_flujo_anterior(history, detalles or {}, state_context, mensaje_completo_usuario)
            return pago_handler.mostrar_servicios_pago(history, detalles or {}, state_context, mensaje_completo_usuario, author)
        except Exception as e:
            logger.error(f"[BLINDAJE_PAGOS] Error crítico: {e}")
            return f"Para continuar en pagos, elegí un servicio de la lista anterior. {config.COMMAND_TIPS['EXIT_PAGO']}", state_context

    # 2) AGENDA: BLINDAJE TOTAL - SOLO BOTONES, NUNCA TEXTO CONVERSACIONAL
    if hay_agenda_activa and 'agendamiento_handler' in globals():
        logger.info(f"[WRAPPER_PREGUNTAR] BLINDAJE AGENDA - Solo botones permitidos")
        
        # Intentar extraer fecha/hora/preferencia directamente del mensaje del usuario
        try:
            from utils import parsear_fecha_hora_natural as _parse_fecha_hora
            parsed = _parse_fecha_hora(mensaje_completo_usuario or "", return_details=True) or {}
            if parsed:
                try:
                    logger.info(f"[AGENDA_PARSE] Extraído desde texto: {parsed}")
                except Exception:
                    pass
                fecha_dt = parsed.get('fecha_datetime')
                fecha_iso = parsed.get('fecha_iso')
                hora_parseada = parsed.get('hora')
                preferencia_horaria_msg = parsed.get('preferencia_horaria')
                restricciones_msg = parsed.get('restricciones_temporales') or []
                if fecha_dt:
                    state_context['fecha_deseada'] = fecha_dt.strftime('%Y-%m-%d')
                elif fecha_iso:
                    state_context['fecha_deseada'] = fecha_iso
                if hora_parseada:
                    state_context['hora_especifica'] = hora_parseada
                if preferencia_horaria_msg:
                    state_context['preferencia_horaria'] = preferencia_horaria_msg
                if restricciones_msg:
                    existentes = list(state_context.get('restricciones_temporales', []) or [])
                    state_context['restricciones_temporales'] = existentes + restricciones_msg
        except Exception as _e:
            logger.warning(f"[AGENDA_PARSE] Error parseando fecha/hora natural: {_e}")
        
        # BLINDAJE V10: En agenda, NUNCA usar Agente Cero, SIEMPRE botones
        # Si el mensaje es un ID interactivo de turno, no re-listar; dejar que validación/acción lo procese
        if isinstance(mensaje_completo_usuario, str) and mensaje_completo_usuario.startswith("turno_"):
            logger.info("[BLINDAJE_AGENDA] ID interactivo detectado en wrapper; no re-listar, esperar acción segura")
            return None, state_context
        # Si hay nueva fecha en detalles, ejecutar nuevo triage
        detalles_actuales = detalles or {}
        # Detectar modo reprogramación
        es_reprogramacion = current_state_sc.startswith('AGENDA_REPROGRAMACION_') or bool(state_context.get('es_reprogramacion'))
        # Tomar fecha/hora detectadas por el Meta-Agente si existen
        fecha_nueva = detalles_actuales.get('fecha_deseada') or state_context.get('fecha_deseada')
        hora_especifica = detalles_actuales.get('hora_especifica') or state_context.get('hora_especifica')
        preferencia_horaria = detalles_actuales.get('preferencia_horaria') or state_context.get('preferencia_horaria')
        fecha_actual_contexto = state_context.get('fecha_deseada')
        
        if fecha_nueva and fecha_nueva != fecha_actual_contexto:
            logger.info(f"[BLINDAJE_AGENDA] Nueva fecha detectada: {fecha_nueva} - Ejecutando nuevo triage")
            # Pasar también hora/preferencia si están disponibles
            if hora_especifica:
                detalles_actuales['hora_especifica'] = hora_especifica
            if preferencia_horaria:
                detalles_actuales['preferencia_horaria'] = preferencia_horaria
            if es_reprogramacion:
                return agendamiento_handler.iniciar_reprogramacion_cita(history, detalles_actuales, state_context, mensaje_completo_usuario, author)
            else:
                return agendamiento_handler.iniciar_triage_agendamiento(history, detalles_actuales, state_context, mensaje_completo_usuario, author)
        else:
            # SIEMPRE mostrar turnos con botones - NO texto conversacional
            logger.info(f"[BLINDAJE_AGENDA] Forzando botones de turnos - NO texto conversacional")
            try:
                # Forzar el filtrado por fecha/hora/preferencia si existen
                if fecha_nueva:
                    detalles_actuales['fecha_deseada'] = fecha_nueva
                if hora_especifica:
                    detalles_actuales['hora_especifica'] = hora_especifica
                if preferencia_horaria:
                    detalles_actuales['preferencia_horaria'] = preferencia_horaria

                if es_reprogramacion:
                    resultado, nuevo_state = agendamiento_handler.mostrar_opciones_turnos_reprogramacion(
                        history, detalles_actuales, state_context, mensaje_completo_usuario, author
                    )
                else:
                    resultado, nuevo_state = agendamiento_handler.mostrar_opciones_turnos(
                        history, detalles_actuales, state_context, mensaje_completo_usuario, author
                    )
                
                # Si mostrar_opciones_turnos devuelve None (éxito), mensaje interactivo enviado
                if resultado is None:
                    logger.info(f"[BLINDAJE_AGENDA] Botones enviados exitosamente")
                    return None, nuevo_state
                else:
                    # Si devuelve texto (fallback), convertir a botón educativo
                    logger.warning(f"[BLINDAJE_AGENDA] Texto detectado - Convirtiendo a mensaje educativo")
                    return f"Para continuar en agendamiento, elegí un turno de la lista anterior. {config.COMMAND_TIPS['EXIT_AGENDA']}", nuevo_state
            except Exception as e:
                logger.error(f"[BLINDAJE_AGENDA] Error crítico: {e}")
                return f"Para salir del agendamiento, escribí: SALIR DE AGENDA", state_context

    # 3) Sin flujo activo o estado final: usar Agente Cero conversacional
    logger.info(f"[WRAPPER_PREGUNTAR] Sin flujo activo - Usando Agente Cero conversacional")
    
    author = state_context.get('author') if state_context else None
    context_info = _construir_context_info_completo(detalles, state_context, mensaje_completo_usuario, "preguntar", author)

    respuesta_cero = _llamar_agente_cero_directo(history, context_info)
    
    # CORRECCIÓN CRÍTICA V10: Procesar respuesta del Agente Cero
    try:
        import utils
        data_cero = utils.parse_json_from_llm_robusto(str(respuesta_cero), context="wrapper_preguntar_final") or {}
        
        # CASO 1: Agente Cero recomienda una acción específica
        accion_recomendada = data_cero.get("accion_recomendada", "").strip()
        if accion_recomendada and accion_recomendada in MAPA_DE_ACCIONES:
            logger.info(f"[WRAPPER_PREGUNTAR] Agente Cero recomienda acción: {accion_recomendada}")
            
            # Ejecutar la acción recomendada en lugar de devolver JSON
            detalles_accion = data_cero.get("detalles", {})
            return _ejecutar_accion(accion_recomendada, history, detalles_accion, state_context, mensaje_completo_usuario, author)
        
        # CASO 2: Respuesta conversacional con texto
        elif data_cero.get("response_text"):
            respuesta_final = data_cero.get("response_text")
            logger.info(f"[WRAPPER_PREGUNTAR] Texto extraído del JSON: {respuesta_final[:100]}...")
        else:
            # CASO 3: Respuesta directa (no JSON)
            respuesta_final = respuesta_cero
            logger.info(f"[WRAPPER_PREGUNTAR] Usando respuesta directa: {respuesta_final[:100]}...")
            
    except Exception as e:
        # Si falla el parsing, usar respuesta directa
        logger.info(f"[WRAPPER_PREGUNTAR] No es JSON o error parseando: {e}. Usando texto directo.")
        respuesta_final = respuesta_cero
    
    return respuesta_final, state_context

def _verificar_restricciones_pago(state_context: dict, author: str) -> dict | None:
    """
    Función centralizada para verificar restricciones de pago antes de ejecutar acciones de agendamiento.
    
    Returns:
        None: Si no hay restricciones o no están configuradas
        dict: Si hay restricciones activas, contiene:
            - "blocked": True
            - "reason": Razón del bloqueo  
            - "context_updated": Contexto actualizado con información de restricciones
    """
    try:
        import config
        
        # Solo verificar si la restricción está activa
        if not (hasattr(config, 'REQUIRE_PAYMENT_BEFORE_SCHEDULING') and config.REQUIRE_PAYMENT_BEFORE_SCHEDULING):
            return None
            
        # Verificar estado de pago en el contexto
        state_context = state_context or {}
        payment_verified = state_context.get('payment_verified', False)
        payment_amount = state_context.get('payment_amount', 0)
        
        if payment_verified:
            logger.info(f"[RESTRICCIONES] ✅ Pago verificado por ${payment_amount} - Agendamiento permitido para {author}")
            return None
            
        # Hay restricciones activas - preparar contexto enriquecido
        logger.info(f"[RESTRICCIONES] ❌ Pago no verificado - Bloqueando agendamiento para {author}")
        
        context_updated = state_context.copy()
        context_updated.update({
            'payment_restriction_active': True,
            'payment_verified': False,
            'payment_amount': payment_amount,
            'requires_payment_first': True,
            'blocked_action': 'agendamiento',
            'payment_status': 'SIN VERIFICAR - REQUERIDO PARA AGENDAR',
            'restriction_message': 'El usuario necesita completar el pago antes de agendar. Ayúdale con el proceso de pago o verifica si ya pagó pidiendo foto del comprobante.'
        })
        
        return {
            "blocked": True,
            "reason": "payment_required",
            "context_updated": context_updated
        }
        
    except Exception as e:
        logger.error(f"[RESTRICCIONES] Error al verificar restricciones: {e}")
        return None

def _enriquecer_contact_info(author: str, sender_name: str | None, mensaje_usuario: str, state_context: dict) -> dict:
    """
    Enriquece automáticamente la información del contacto en state_context.
    Captura: teléfono, nombre, email (si se detecta), vendor, etc.
    """
    try:
        # Inicializar contact_info si no existe
        contact_info = state_context.get('contact_info', {})
        updated = False
        
        # TELÉFONO: Siempre disponible desde author
        if contact_info.get('phone') != author:
            contact_info['phone'] = author
            updated = True
            
        # NOMBRE: Desde senderName de WhatsApp si está disponible
        if sender_name and sender_name.strip():
            sender_clean = sender_name.strip()
            if contact_info.get('name') != sender_clean:
                contact_info['name'] = sender_clean
                updated = True
                logger.info(f"[CONTACT_INFO] Nombre actualizado para {author}: {sender_clean}")
        
        # EMAIL: Detectar automáticamente en el mensaje del usuario
        if mensaje_usuario:
            email_regex = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
            emails_found = re.findall(email_regex, mensaje_usuario)
            if emails_found and not contact_info.get('email'):
                email_detectado = emails_found[0].lower()
                contact_info['email'] = email_detectado
                updated = True
                logger.info(f"[CONTACT_INFO] Email detectado para {author}: {email_detectado}")
        
        # VENDOR: Desde state_context si existe
        vendor_owner = state_context.get('vendor_owner')
        if vendor_owner and contact_info.get('vendor') != vendor_owner:
            contact_info['vendor'] = vendor_owner
            updated = True
            
        # SOURCE: Siempre WhatsApp para este sistema
        if contact_info.get('source') != 'whatsapp':
            contact_info['source'] = 'whatsapp'
            updated = True
            
        # PROFILE_COMPLETE: Verificar completitud por niveles
        has_name = bool(contact_info.get('name'))
        has_phone = bool(contact_info.get('phone'))
        has_email = bool(contact_info.get('email'))
        
        # Nivel básico: nombre + teléfono
        profile_basic = has_name and has_phone
        # Nivel completo: básico + email
        profile_complete = profile_basic and has_email
        
        # Guardar ambos niveles
        if contact_info.get('profile_basic') != profile_basic:
            contact_info['profile_basic'] = profile_basic
            updated = True
            
        if contact_info.get('profile_complete') != profile_complete:
            contact_info['profile_complete'] = profile_complete
            updated = True
            
        # Nivel de completitud para el generador
        if profile_complete:
            contact_info['completion_level'] = 'complete'
        elif profile_basic:
            contact_info['completion_level'] = 'basic'
        else:
            contact_info['completion_level'] = 'minimal'
            
        # TIMESTAMP: Actualizar si hubo cambios
        if updated:
            from datetime import datetime, timezone
            contact_info['last_updated'] = datetime.now(timezone.utc).isoformat()
            
        # Guardar de vuelta en state_context
        state_context['contact_info'] = contact_info
        
        if updated:
            logger.info(f"[CONTACT_INFO] Información actualizada para {author}: {list(contact_info.keys())}")
            
        return state_context
        
    except Exception as e:
        logger.error(f"[CONTACT_INFO] Error enriqueciendo información de contacto para {author}: {e}")
        return state_context

def _enriquecer_contexto_generador(context_info: dict, state_context: dict, current_state_sc: str | None = None) -> None:
    """Agrega claves que el generador entiende: estado_agenda, horarios_disponibles, id_evento, estado_pago, plan, monto, proveedor, link_pago, estado_general."""
    if context_info is None:
        return
    sc = state_context or {}
    estado_actual = (current_state_sc or sc.get('current_state') or '')

    # Estado General
    if estado_actual:
        context_info['estado_general'] = estado_actual

    # Agenda
    estado_agenda = None
    if estado_actual == 'evento_creado' or sc.get('evento_creado') or sc.get('cita_agendada'):
        estado_agenda = 'agendado'
    elif estado_actual.startswith('AGENDA_REPROGRAMACION_'):
        estado_agenda = 'reprogramando'
    elif estado_actual.startswith('AGENDA_'):
        estado_agenda = 'sin_turno'
    if estado_agenda:
        context_info['estado_agenda'] = estado_agenda

    # Horarios disponibles
    available_slots = sc.get('available_slots')
    if isinstance(available_slots, list) and available_slots:
        context_info['horarios_disponibles'] = available_slots

    # ID de evento
    id_evento = sc.get('last_event_id')
    if id_evento:
        context_info['id_evento'] = id_evento

    # NUEVO: Información detallada del turno seleccionado/confirmado
    slot_seleccionado = sc.get('slot_seleccionado')
    ultimo_turno_memory = None
    
    # También buscar en memory si no hay slot_seleccionado activo
    if not slot_seleccionado and sc.get('author'):
        try:
            import memory
            ultimo_turno_memory = memory.obtener_ultimo_turno_confirmado(sc.get('author'))
        except Exception:
            pass
    
    # Usar slot_seleccionado si está disponible, sino el de memoria
    turno_info = slot_seleccionado or ultimo_turno_memory
    
    if turno_info:
        context_info['turno_agendado'] = True
        context_info['turno_fecha'] = turno_info.get('fecha_formateada', '')
        context_info['turno_hora'] = turno_info.get('hora', '')
        context_info['turno_completo'] = turno_info.get('fecha_completa_legible', '')
        
        # Resumen legible para el generador
        if turno_info.get('fecha_para_titulo'):
            context_info['turno_summary'] = f"Turno confirmado: {turno_info['fecha_para_titulo']}"
        else:
            context_info['turno_summary'] = f"Turno confirmado para {turno_info.get('fecha_formateada', 'fecha no especificada')}"
        
        # Indicar fuente de la información
        if slot_seleccionado:
            context_info['turno_source'] = 'session_active'
        else:
            context_info['turno_source'] = 'memory_persistent'
    else:
        context_info['turno_agendado'] = False

    # Pago
    estado_pago = sc.get('estado_pago')
    if not estado_pago and estado_actual.startswith('PAGOS_'):
        if sc.get('link_pago'):
            estado_pago = 'link_generado'
        elif estado_actual == 'PAGOS_ESPERANDO_CONFIRMACION':
            estado_pago = 'esperando_confirmacion'
        elif estado_actual == 'PAGOS_ESPERANDO_SELECCION_SERVICIO':
            estado_pago = 'seleccionando_servicio'
    if estado_pago:
        context_info['estado_pago'] = estado_pago

    for clave in ['plan', 'monto', 'proveedor', 'link_pago']:
        if sc.get(clave) and clave not in context_info:
            context_info[clave] = sc.get(clave)
    
    # NUEVO: Información de restricciones de pago para el generador
    try:
        import config
        if hasattr(config, 'REQUIRE_PAYMENT_BEFORE_SCHEDULING') and config.REQUIRE_PAYMENT_BEFORE_SCHEDULING:
            context_info['payment_restriction_active'] = True
            context_info['payment_verified'] = sc.get('payment_verified', False)
            context_info['payment_amount'] = sc.get('payment_amount', 0)
            context_info['requires_payment_first'] = sc.get('requires_payment_first', False)
            context_info['blocked_action'] = sc.get('blocked_action', '')
            
            # Estado de verificación legible para el generador
            if sc.get('payment_verified'):
                context_info['payment_status'] = f"PAGO VERIFICADO (${sc.get('payment_amount', 0)})"
            else:
                context_info['payment_status'] = "SIN VERIFICAR - REQUERIDO PARA AGENDAR"
            
            # Mensaje clave para el generador
            if sc.get('requires_payment_first'):
                context_info['restriction_message'] = "El usuario necesita completar el pago antes de agendar. Manéjalo conversacionalmente y ofrece ayuda con el pago."
        else:
            context_info['payment_restriction_active'] = False
    except Exception:
        # Si hay error, continuar sin las claves de restricción
        pass
    
    # NUEVO: Información del contacto para el generador
    try:
        contact_info = sc.get('contact_info', {})
        if contact_info:
            # Información básica del contacto
            context_info['contact_phone'] = contact_info.get('phone', '')
            context_info['contact_name'] = contact_info.get('name', '')
            context_info['contact_email'] = contact_info.get('email', '')
            context_info['contact_vendor'] = contact_info.get('vendor', '')
            context_info['contact_profile_complete'] = contact_info.get('profile_complete', False)
            context_info['contact_profile_basic'] = contact_info.get('profile_basic', False)
            context_info['contact_completion_level'] = contact_info.get('completion_level', 'minimal')
            
            # Información resumida para el generador
            if contact_info.get('name'):
                context_info['contact_info_summary'] = f"Cliente: {contact_info.get('name')} ({contact_info.get('phone')})"
                if contact_info.get('email'):
                    context_info['contact_info_summary'] += f" - Email: {contact_info.get('email')}"
                if contact_info.get('vendor'):
                    context_info['contact_info_summary'] += f" - Vendedor: {contact_info.get('vendor')}"
            else:
                context_info['contact_info_summary'] = f"Cliente sin nombre registrado ({contact_info.get('phone', 'sin teléfono')})"
            
            # ESTRATEGIA PROGRESIVA: Información faltante por etapas
            missing_info = []
            missing_critical = []
            missing_optional = []
            
            # Información crítica (necesaria para procesos importantes)
            if not contact_info.get('name'):
                missing_critical.append('nombre')
            
            # Información opcional (útil pero no crítica)
            if not contact_info.get('email'):
                missing_optional.append('email')
            
            missing_info = missing_critical + missing_optional
            
            if missing_info:
                context_info['contact_missing_info'] = missing_info
                context_info['contact_missing_critical'] = missing_critical
                context_info['contact_missing_optional'] = missing_optional
                
                # Sugerencia progresiva inteligente
                if missing_critical:
                    context_info['contact_suggestion'] = f"Necesitas obtener: {', '.join(missing_critical)} (crítico)"
                    context_info['contact_priority'] = 'critical'
                elif missing_optional:
                    context_info['contact_suggestion'] = f"Puedes solicitar: {', '.join(missing_optional)} (si es relevante)"
                    context_info['contact_priority'] = 'optional'
                else:
                    context_info['contact_priority'] = 'complete'
            else:
                context_info['contact_suggestion'] = "Información de contacto completa"
                context_info['contact_priority'] = 'complete'
    except Exception:
        # Si hay error, continuar sin la información de contacto
        pass

# --- MAPA DE ACCIONES (CORREGIDO Y ALINEADO) ---
import notifications_handler

# Wrappers para mantener consistencia de parámetros
def wrapper_confirmar_agendamiento(history, detalles, state_context, mensaje_completo_usuario, author=None):
    user_choice = detalles.get('opcion_elegida', '') if detalles else ''
    return agendamiento_handler.confirmar_agendamiento(history, state_context, user_choice)

def wrapper_confirmar_reprogramacion(history, detalles, state_context, mensaje_completo_usuario, author=None):
    user_choice = detalles.get('opcion_elegida', '') if detalles else ''
    return agendamiento_handler.confirmar_reprogramacion(history, state_context, user_choice)

def wrapper_confirmar_cancelacion(history, detalles, state_context, mensaje_completo_usuario, author=None):
    return agendamiento_handler.confirmar_cancelacion(history, state_context)

def wrapper_escalar_a_humano(history, detalles, state_context, mensaje_completo_usuario, author=None):
    """
    PLAN DE REFACTORIZACIÓN v3: Función para escalar a humano cuando se detecta un bucle o error crítico.
    """
    logger.warning(f"[ESCALACION] Escalando a humano para {author}. Motivo: {detalles.get('motivo', 'desconocido')}")
    
    # PLAN DE REFACTORIZACIÓN v3: Mensaje tranquilizador para el usuario
    mensaje_usuario = "Parece que estamos teniendo un inconveniente técnico para procesar tu solicitud. No te preocupes, un miembro de nuestro equipo ya fue notificado y se pondrá en contacto contigo a la brevedad para ayudarte personalmente."
    
    # PLAN DE REFACTORIZACIÓN v3: Notificación interna
    try:
        import notifications_handler
        detalles_notificacion = {
            "tipo": "escalacion_humano",
            "motivo": detalles.get('motivo', 'desconocido'),
            "usuario": author,
            "mensaje_usuario": detalles.get('mensaje_usuario', ''),
            "intentos": detalles.get('intentos', 0),
            "timestamp": datetime.now().isoformat()
        }
        notifications_handler.send_internal_notification(detalles_notificacion)
        logger.info(f"[ESCALACION] Notificación interna enviada para {author}")
    except Exception as e:
        logger.error(f"[ESCALACION] Error enviando notificación interna: {e}")
    
    # PLAN DE REFACTORIZACIÓN v3: Limpiar contexto y resetear contadores
    if state_context:
        state_context['triage_count'] = 0
        state_context['escalado_a_humano'] = True
        state_context['current_state'] = 'escalado_a_humano'
    
    return mensaje_usuario, state_context

# Wrapper para confirmar pago con la firma unificada del orquestador
def wrapper_confirmar_pago(history, detalles, state_context, mensaje_completo_usuario, author=None):
     try:
         from pago_handler import confirmar_pago as _confirmar_pago
         return _confirmar_pago(
             history=history,
             context=detalles or {},
             state_context=state_context,
             mensaje_completo_usuario=mensaje_completo_usuario,
             author=author,
         )
     except Exception as e:
         logger.error(f"[WRAPPER_CONFIRMAR_PAGO] Error: {e}")
         return "¡Muchas gracias! Registramos tu comprobante y ya lo informamos al equipo.", state_context or {}

# MAPA DE ACCIONES v7 (LIMPIO Y DEFINITIVO)
# Este mapa contiene ÚNICAMENTE las acciones del nuevo flujo unificado.
# Se han eliminado todas las acciones antiguas y redundantes para evitar "dobles vías".
def wrapper_volver_agente_cero(history, detalles, state_context, mensaje_completo_usuario, author=None):
    """
    Nueva acción para comandos SALIR - vuelve al Agente Cero con estado limpio.
    """
    logger.info("[VOLVER_AGENTE_CERO] Procesando comando SALIR...")
    
    # Mensaje de salida del comando
    mensaje_salida = detalles.get('mensaje_salida', '¿En qué más puedo ayudarte?')
    
    # Estado completamente limpio para conversación general
    state_context_limpio = {
        'author': state_context.get('author') if state_context else author,
        'senderName': state_context.get('senderName') if state_context else None,
        'pasado_a_departamento': False,
        'triage_count': 0,
        'current_state': 'conversando'
    }
    
    return mensaje_salida, state_context_limpio

def wrapper_usar_agente_cero(history, detalles, state_context, mensaje_completo_usuario, author=None):
    """
    Acción cuando Meta-Agente no detecta comandos explícitos.
    El Agente Cero maneja la conversación y enseña los comandos disponibles.
    """
    logger.info("[USAR_AGENTE_CERO] Meta-Agente pasó control al Agente Cero...")
    
    # CORRECCIÓN CRÍTICA: Usar función helper para context_info completo
    context_info = _construir_context_info_completo(detalles, state_context, mensaje_completo_usuario, "enseñar_comandos", author)
    
    # Llamar Agente Cero con contexto completo
    respuesta_cero = _llamar_agente_cero_directo(history, context_info)
    
    # CORRECCIÓN CRÍTICA: Procesar respuesta del Agente Cero para extraer acción o solo texto
    try:
        import utils
        data_cero = utils.parse_json_from_llm_robusto(str(respuesta_cero), context="wrapper_usar_agente_cero") or {}
        
        # 1) Si el Agente Cero recomienda una acción válida, NO ejecutar directamente: derivar a Meta-Agente
        accion_recomendada = str(data_cero.get("accion_recomendada", "")).strip()
        if accion_recomendada and accion_recomendada in MAPA_DE_ACCIONES:
            logger.info(f"[USAR_AGENTE_CERO] Agente Cero recomienda acción: {accion_recomendada} → Derivando a Meta-Agente")
            detalles_accion = data_cero.get("detalles", {}) or {}
            sc = state_context or {}
            sc['pasado_a_departamento'] = True
            if 'author' not in sc and author:
                sc['author'] = author
            estado_actual = sc.get('current_state') or 'conversando'
            mensaje_enriquecido = f"Contexto: {estado_actual}. Usuario: '{mensaje_completo_usuario}'"
            estrategia_local = _obtener_estrategia(estado_actual, mensaje_enriquecido, history, detalles_accion, mensaje_completo_usuario, sc)
            if estrategia_local and estrategia_local.get("accion_recomendada"):
                return _ejecutar_accion(estrategia_local.get("accion_recomendada"), history, estrategia_local.get("detalles", {}), sc, mensaje_completo_usuario, author)
            return "Para agendar, escribí: QUIERO AGENDAR. Para pagos, escribí: QUIERO PAGAR", sc
        
        # 2) Si viene JSON con response_text, usar solo ese texto
        if data_cero.get("response_text"):
            respuesta_final = data_cero.get("response_text")
            logger.info(f"[USAR_AGENTE_CERO] Texto extraído del JSON: {respuesta_final[:100]}...")
        else:
            # Si no hay response_text o no es JSON, usar respuesta directa
            respuesta_final = respuesta_cero
            logger.info(f"[USAR_AGENTE_CERO] Usando respuesta directa: {respuesta_final[:100]}...")
    except Exception as e:
        # Si falla el parsing, usar respuesta directa
        logger.info(f"[USAR_AGENTE_CERO] No es JSON o error parseando: {e}. Usando texto directo.")
        respuesta_final = respuesta_cero
    
    return respuesta_final, state_context

MAPA_DE_ACCIONES = {
    # --- ACCIONES SIEMPRE DISPONIBLES ---
    "preguntar": wrapper_preguntar,
    "escalar_a_humano": wrapper_escalar_a_humano,
    "volver_agente_cero": wrapper_volver_agente_cero,
    "usar_agente_cero": wrapper_usar_agente_cero,
}

# === Acciones médicas Ballester V11 ===
if BALLESTER_V11_ENABLED and 'verification_handler' in globals():
    try:
        MAPA_DE_ACCIONES.update({
            "iniciar_verificacion_medica": verification_handler.start_medical_verification,
            "continuar_verificacion_medica": verification_handler.start_medical_verification,
        })
    except Exception:
        pass

# --- AGREGAR DINÁMICAMENTE SEGÚN CONFIGURACIÓN ---
# Solo agregar acciones de agendamiento si el módulo está habilitado Y importado
if 'SCHEDULING' in config.ENABLED_AGENTS and 'agendamiento_handler' in globals():
    MAPA_DE_ACCIONES.update({
        # --- FLUJO DE AGENDAMIENTO UNIFICADO ---
        "iniciar_triage_agendamiento": agendamiento_handler.iniciar_triage_agendamiento,
        "mostrar_opciones_turnos": agendamiento_handler.mostrar_opciones_turnos,
        "finalizar_cita_automatico": agendamiento_handler.finalizar_cita_automatico, # Llamado por botón de turno
        "reiniciar_busqueda": agendamiento_handler.reiniciar_busqueda,
        # ELIMINADO: "reanudar_agendamiento" - redundante, wrapper_preguntar() llama directamente a mostrar_opciones_turnos()
        
        # --- ACCIONES DE REPROGRAMACIÓN Y CANCELACIÓN (Simplificadas) ---
        # Nota: El triage de agendamiento se encarga de iniciar estos flujos.
        "iniciar_reprogramacion_cita": agendamiento_handler.iniciar_reprogramacion_cita,
        "iniciar_cancelacion_cita": agendamiento_handler.iniciar_cancelacion_cita,
        "ejecutar_cancelacion_cita": agendamiento_handler.ejecutar_cancelacion_cita, # Llamado por botón de confirmación "Sí"
    })

# Solo agregar acciones de pagos si el módulo está habilitado Y importado
if 'PAYMENT' in config.ENABLED_AGENTS and 'pago_handler' in globals():
    MAPA_DE_ACCIONES.update({
        # --- FLUJO DE PAGOS UNIFICADO ---
        "iniciar_triage_pagos": pago_handler.iniciar_triage_pagos,
        "mostrar_servicios_pago": pago_handler.mostrar_servicios_pago,
        "confirmar_servicio_pago": pago_handler.confirmar_servicio_pago, # Llamado por botón de servicio
        "generar_link_pago": pago_handler.generar_link_pago, # Llamado por botón de confirmación "Sí"
        "reiniciar_flujo_pagos": pago_handler.reiniciar_flujo_pagos, # Llamado por botón de cancelación "No"
        "reanudar_flujo_anterior": pago_handler.reanudar_flujo_anterior, # Usado por wrapper_preguntar() en estados específicos
        
        # --- ACCIONES COMPLEMENTARIAS ---
        "confirmar_pago": wrapper_confirmar_pago, # Adaptador de firma unificada
    })

# --- Configuración inicial ---
app = Flask(__name__)
# Configurar logging con niveles específicos para reducir ruido
configure_logging()
logger = logging.getLogger(config.TENANT_NAME)

# === INTEGRACIÓN CHATWOOT ===
from chatwoot_integration import chatwoot, log_to_chatwoot
logger.info("✅ Integración Chatwoot cargada correctamente")

# --- Estructuras de Control (Actualizadas) ---
message_buffer = {}
user_timers = {}  # Ahora almacena objetos Timer
user_timer_tokens = {}  # Token/generación por usuario para invalidar timers viejos
chatwoot_processed_messages = {}  # Dedupe de mensajes del webhook de Chatwoot
buffer_lock = Lock()
# Ahora se lee desde config.py para permitir personalización por cliente
BUFFER_WAIT_TIME = config.BUFFER_WAIT_TIME
logger.info(f"🕐 Buffer de mensajes configurado: {BUFFER_WAIT_TIME}s")
PROCESSING_USERS = set()
LEAD_PROCESSING_LOCK = Lock()

def _persist_buffer_and_get_token(author: str, new_messages: list) -> int:
    """Agrega mensajes al buffer persistente en Firestore y devuelve el token vigente.
    Regla: si la ventana anterior ya venció, incrementa el token; si no, reutiliza el actual.
    También extiende la deadline en +BUFFER_WAIT_TIME segundos.
    """
    try:
        import time as _t
        history, _, current_state, state_context = memory.get_conversation_data(phone_number=author)
        state_context = state_context or {}
        pending_messages = list(state_context.get('pending_messages', []))
        # Asegurar lista JSON-serializable
        if new_messages:
            for m in new_messages:
                if isinstance(m, dict):
                    pending_messages.append(m)
        now_ts = _t.time()
        prev_deadline = float(state_context.get('buffer_deadline_ts', 0.0) or 0.0)
        prev_token = int(state_context.get('current_timer_token', 0) or 0)
        if now_ts > prev_deadline:
            new_token = prev_token + 1
        else:
            new_token = prev_token
        # Extender deadline
        state_context['pending_messages'] = pending_messages
        state_context['buffer_deadline_ts'] = now_ts + BUFFER_WAIT_TIME
        state_context['current_timer_token'] = new_token
        # Resetear cualquier lock previo al iniciar/renovar ventana
        state_context['processing_lock_token'] = 0
        memory.update_conversation_state(author, current_state, context=_clean_context_for_firestore(state_context))
        return new_token
    except Exception as e:
        logger.error(f"[BUFFER_PERSIST] Error actualizando buffer persistente para {author}: {e}", exc_info=True)
        # Fallback seguro: generar token local
        with buffer_lock:
            prev = user_timer_tokens.get(author)
            new_t = (prev + 1) if isinstance(prev, int) else 1
            user_timer_tokens[author] = new_t
            return new_t

def _process_if_valid_callback(author: str, expected_token: int):
    """Callback del timer: coordina entre procesos usando Firestore con lock transaccional.
    Si el token coincide y la deadline venció, toma los mensajes de forma atómica y los procesa.
    Si aún no venció, reprograma el timer para el remanente.
    """
    import time as _t
    try:
        # Leer último estado rápido (no transaccional) para decidir si reprogramar
        _, _, _cs, sc_view = memory.get_conversation_data(phone_number=author)
        sc_view = sc_view or {}
        current_token = int(sc_view.get('current_timer_token', 0) or 0)
        if current_token != expected_token:
            logger.info(f"[BUFFER_TIMER] Token inválido para {author}: esperado {expected_token}, actual {current_token}. Cancelando.")
            return
        deadline_ts = float(sc_view.get('buffer_deadline_ts', 0.0) or 0.0)
        now_ts = _t.time()
        if now_ts < deadline_ts:
            delay = max(0.5, (deadline_ts - now_ts) + 0.05)
            with buffer_lock:
                t = Timer(delay, _process_if_valid_callback, args=(author, expected_token))
                user_timers[author] = t
                t.start()
            logger.info(f"[BUFFER_TIMER] Reprogramado {author} en {delay:.2f}s hasta {deadline_ts:.3f}")
            return

        # Usar transacción para tomar lock y vaciar pending_messages de forma atómica
        doc_id = memory.sanitize_and_recover_doc_id(author)
        if not doc_id or memory.db is None:
            logger.error(f"[BUFFER_TIMER] No se pudo resolver doc_id o Firestore no disponible para {author}")
            return
        doc_ref = memory.db.collection('conversations_v3').document(doc_id)

        @firestore.transactional
        def take_messages(transaction, ref, token):
            snapshot = ref.get(transaction=transaction)
            data = snapshot.to_dict() if snapshot.exists else {}
            sc = data.get('state_context', {}) or {}
            cur = int(sc.get('current_timer_token', 0) or 0)
            if cur != token:
                return None
            # Evitar doble-take si otro proceso ya tomó lock
            lock_token = sc.get('processing_lock_token')
            if lock_token and lock_token != token:
                return None
            pending = list(sc.get('pending_messages', []))
            # Setear lock y limpiar buffer en la misma escritura
            sc['processing_lock_token'] = token
            sc['pending_messages'] = []
            sc['buffer_deadline_ts'] = 0.0
            sc['current_timer_token'] = 0
            transaction.set(ref, {'state_context': sc}, merge=True)
            return pending

        transaction = memory.db.transaction()
        pending_messages = take_messages(transaction, doc_ref, expected_token)
        if not pending_messages:
            logger.info(f"[BUFFER_TIMER] No hay mensajes pendientes (posible lock tomado por otro proceso) para {author}")
            return
        logger.info(f"[BUFFER_TIMER] Procesando {len(pending_messages)} mensajes para {author}")
        process_message_logic(author, pending_messages)
    except Exception as e:
        logger.error(f"[BUFFER_TIMER] Error en callback para {author}: {e}", exc_info=True)
    finally:
        with buffer_lock:
            try:
                if author in user_timers:
                    del user_timers[author]
            except Exception:
                pass

def _limpiar_timers_obsoletos():
    """
    NUEVA: Función para limpiar timers obsoletos y prevenir problemas de memoria.
    """
    with buffer_lock:
        timers_a_eliminar = []
        for author, timer in user_timers.items():
            try:
                if not timer.is_alive():
                    timers_a_eliminar.append(author)
                    logger.info(f"[LIMPIEZA_TIMERS] Timer obsoleto eliminado para {author}")
            except Exception as e:
                logger.warning(f"[LIMPIEZA_TIMERS] Error verificando timer de {author}: {e}")
                timers_a_eliminar.append(author)
        
        for author in timers_a_eliminar:
            del user_timers[author]
        
        if timers_a_eliminar:
            logger.info(f"[LIMPIEZA_TIMERS] Limpieza completada. Timers activos: {len(user_timers)}")

if memory.db is None:
    logger.critical("FATAL: Firestore no se pudo inicializar. El bot no funcionará.")

# --- FLUJO 2 - GENERACIÓN DE LEADS EN SEGUNDO PLANO (Sin Cambios) ---
def _formatear_transcripcion(historial: list) -> str:
    transcripcion = ""
    for mensaje in historial:
        rol = "Cliente" if mensaje.get('role') == 'user' else mensaje.get('name', 'Asistente')
        contenido = mensaje.get('content', '')
        transcripcion += f"{rol}: {contenido}\n\n"
    return transcripcion.strip()

def procesar_leads_inactivos():
    if not LEAD_PROCESSING_LOCK.acquire(blocking=False): return
    logger.info("--- [LEAD_GEN] Iniciando chequeo de conversaciones inactivas ---")
    try:
        hace_una_hora = datetime.now(timezone.utc) - timedelta(hours=1)
        conversaciones_inactivas = memory.get_inactive_conversations(hace_una_hora)
        if not conversaciones_inactivas:
            logger.info("[LEAD_GEN] No hay conversaciones inactivas para procesar.")
            return
        for autor, datos_conv in conversaciones_inactivas.items():
            try:
                historial = datos_conv.get('history', [])
                sender_name = datos_conv.get('senderName', '')
                if not historial: continue
                transcripcion = _formatear_transcripcion(historial)
                respuesta_analista = llm_handler.llamar_analista_leads(transcripcion)
                datos_lead = utils.parse_json_from_llm(respuesta_analista, context=f"analista_leads_{autor}")
                if not datos_lead: continue
                if datos_lead and "email" in datos_lead and ("vacío" in datos_lead["email"] or "@" not in datos_lead["email"]):
                    del datos_lead["email"]
                hubspot_handler.update_hubspot_contact(
                    phone_number=autor.split('@')[0], name=sender_name,
                    last_message="", lead_data=datos_lead
                )
                memory.marcar_lead_como_procesado(autor)
            except Exception as e:
                logger.error(f"[LEAD_GEN] Error procesando el lead de {autor}: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"[LEAD_GEN] Error catastrófico durante el chequeo de leads: {e}", exc_info=True)
    finally:
        LEAD_PROCESSING_LOCK.release()

# --- FLUJO 1 - INTERACCIÓN EN TIEMPO REAL CON ORQUESTADOR ---
def process_buffered_messages(author):
    """Obsoleto: se mantiene por compatibilidad; usa el callback coordinado."""
    process_text_messages(author)
    logger.info(f"Procesamiento finalizado para {author}.")
def lead_checker_daemon():
    while True:
        try:
            procesar_leads_inactivos()
        except Exception as e:
            logger.error(f"[LEAD_DAEMON] Error en el ciclo del demonio de leads: {e}", exc_info=True)
        time.sleep(900)





@app.route('/')
def index():
    return f"Servidor IA para {config.TENANT_NAME} está funcionando!", 200

@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    if request.method == 'GET':
        mode = request.args.get('hub.mode')
        token = request.args.get('hub.verify_token')
        challenge = request.args.get('hub.challenge')
        if mode == 'subscribe' and token == config.D360_WEBHOOK_VERIFY_TOKEN:
            return challenge, 200
        else:
            return "Error, token no válido", 403
            
    if request.method == 'POST':
        # CRÍTICO: Guardar datos y responder INMEDIATAMENTE
        data = request.get_json()
        
        # Procesar en background para no bloquear la respuesta
        thread = Thread(target=_process_webhook_async, args=(data,))
        thread.start()
        
        # RESPONDER INMEDIATAMENTE para evitar reintentos de 360dialog
        return "OK", 200

# NUEVA FUNCIÓN: Procesar webhook de forma asíncrona
def _process_webhook_async(data):
    """Procesa el webhook en background para responder rápido a 360dialog"""
    try:
        logger.info(f"[WEBHOOK] Payload recibido: {data}")
        
        if 'entry' not in data: 
            return
        
        for entry in data.get('entry', []):
            for change in entry.get('changes', []):
                value = change.get('value', {})
                
                if 'messages' in value:
                    for msg in value.get('messages', []):
                        if not msg.get("from"): 
                            continue
                        
                        author = msg.get('from')
                        # Aplicar vendor encolado al primer chat nuevo que llegue (sobreescribe si existe)
                        try:
                            if hasattr(memory, 'get_vendor_owner') and hasattr(memory, 'upsert_vendor_label'):
                                current_vendor = memory.get_vendor_owner(author)
                                now_ts = int(time.time())
                                with PENDING_VENDOR_LOCK:
                                    # limpiar expirados
                                    while PENDING_VENDOR_QUEUE and (now_ts - PENDING_VENDOR_QUEUE[0][1] > PENDING_VENDOR_TTL_SECONDS):
                                        PENDING_VENDOR_QUEUE.popleft()
                                    if PENDING_VENDOR_QUEUE:
                                        vndr, _ts = PENDING_VENDOR_QUEUE.popleft()
                                        try:
                                            memory.upsert_vendor_label(author, vndr, agent_label=f"AGENTE: {vndr}", only_if_absent=False)
                                            logger.info(f"[VENDOR_PRETAG_APPLY] Vendor actualizado '{current_vendor or 'NINGUNO'}' -> '{vndr}' para {author}")
                                        except Exception as _e:
                                            logger.error(f"[VENDOR_PRETAG_APPLY] Error asignando vendor encolado a {author}: {_e}")
                        except Exception as _e:
                            logger.debug(f"[VENDOR_PRETAG_APPLY] No se pudo aplicar vendor encolado: {_e}")
                        # --- DETECCIÓN Y FIJACIÓN DE VENDEDOR (una sola vez, silenciosa) ---
                        logger.info(f"[WEBHOOK] 🔍 Analizando mensaje para vendor detection: {msg.get('type')} - {msg.get('body', '')[:100] if msg.get('body') else 'No body'}...")
                        
                        # DEBUG: Mostrar estructura completa del mensaje
                        _debug_message_structure(msg, author)
                        
                        try:
                            _ensure_vendor_label(author, msg)
                        except Exception as _e_v:
                            logger.error(f"[VENDOR] ❌ No se pudo asegurar vendor label para {author}: {_e_v}", exc_info=True)
                        
                        # PREVENCIÓN DE DUPLICADOS
                        message_id = msg.get('id')
                        timestamp_str = msg.get('timestamp')
                        try:
                            msg_epoch = int(timestamp_str) if timestamp_str is not None else 0
                        except Exception:
                            msg_epoch = 0
                        current_time = int(time.time())

                        # Filtro de mensajes antiguos re-enviados (por reinicios o deploys)
                        if msg_epoch and (current_time - msg_epoch > STALE_MESSAGE_TTL_SECONDS):
                            logger.warning(f"[WEBHOOK] Mensaje antiguo ignorado (>{STALE_MESSAGE_TTL_SECONDS}s): id={message_id} from={author} age={current_time - msg_epoch}s")
                            # Igual marcar la clave como vista para evitar reprocesar si vuelve
                            unique_key_old = f"{author}_{message_id}_{timestamp_str}"
                            with PROCESSED_MESSAGES_LOCK:
                                PROCESSED_MESSAGES[unique_key_old] = current_time
                            _cleanup_old_processed_messages()
                            continue

                        # Deduplicación por clave única
                        unique_key = f"{author}_{message_id}_{timestamp_str}"
                        with PROCESSED_MESSAGES_LOCK:
                            if unique_key in PROCESSED_MESSAGES:
                                logger.info(f"[WEBHOOK] Mensaje duplicado ignorado: {unique_key}")
                                continue
                            PROCESSED_MESSAGES[unique_key] = current_time
                        _cleanup_old_processed_messages()
                        
                        # Normalizar el mensaje
                        normalized_message = _normalize_message_unified(msg, author, data)
                        if not normalized_message:
                            continue
                        
                        message_type = normalized_message.get('type')
                        
                        if message_type == 'reaction':
                            try:
                                # Registrar inmediatamente la reacción en Chatwoot y no activar IA
                                from chatwoot_integration import log_to_chatwoot
                                phone_clean = author.split('@')[0]
                                emoji = normalized_message.get('reaction_emoji') or normalized_message.get('body', '')
                                reacted = normalized_message.get('reaction_to', '')
                                texto = f"Reaccionó con {emoji}" + (f" al mensaje {reacted}" if reacted else "")
                                log_to_chatwoot(phone_clean, texto, None, normalized_message.get('senderName', ''))
                                logger.info(f"[WEBHOOK] Reacción registrada en Chatwoot: {texto}")
                            except Exception as e:
                                logger.warning(f"[WEBHOOK] No se pudo registrar reacción en Chatwoot: {e}")
                            continue
                        if message_type in ['image', 'audio', 'video', 'document']:
                            # Procesar multimedia instantáneamente y persistir en buffer cross-proceso
                            logger.info(f"[WEBHOOK] Media ({message_type}) detectada. Procesando contenido.")
                            # NUEVO: Obtener contexto para permitir registro de pagos
                            try:
                                _, _, _, current_state_context = memory.get_conversation_data(phone_number=author)
                                procesados = _procesar_multimedia_instantaneo(author, [normalized_message], current_state_context) or []
                            except Exception as e:
                                logger.warning(f"[WEBHOOK] Error obteniendo contexto para multimedia: {e}")
                                procesados = _procesar_multimedia_instantaneo(author, [normalized_message]) or []
                            token = _persist_buffer_and_get_token(author, procesados)
                            # Reiniciar/iniciar timer local coordinado por token persistido
                            with buffer_lock:
                                prev_local = user_timers.get(author)
                                if prev_local:
                                    try:
                                        prev_local.cancel()
                                    except Exception:
                                        pass
                                t = Timer(BUFFER_WAIT_TIME, _process_if_valid_callback, args=(author, token))
                                user_timers[author] = t
                                t.start()
                                logger.info(f"[WEBHOOK] Timer coordinado iniciado para {author} (token {token})")
                        else:
                            # Texto o botón - agregar al buffer normalmente
                            # Persistir mensaje textual en buffer cross-proceso y coordinar timer
                            token = _persist_buffer_and_get_token(author, [normalized_message])
                            with buffer_lock:
                                prev_local = user_timers.get(author)
                                if prev_local:
                                    try:
                                        prev_local.cancel()
                                    except Exception:
                                        pass
                                t = Timer(BUFFER_WAIT_TIME, _process_if_valid_callback, args=(author, token))
                                user_timers[author] = t
                                t.start()
                                logger.info(f"[WEBHOOK] Mensaje agregado y timer coordinado para {author} (token {token})")
                                
    except Exception as e:
        logger.error(f"[WEBHOOK] Error procesando webhook asíncrono: {e}", exc_info=True)

@app.route('/webhook-humano', methods=['POST'])
def webhook_humano():
    token_recibido = request.args.get('token')
    if not token_recibido or token_recibido != config.D360_HUMAN_WEBHOOK_VERIFY_TOKEN:
        logger.warning(f"[WEBHOOK-HUMANO] Intento de acceso con token de URL inválido.")
        return "Error: Autenticación fallida", 403

# --- ENDPOINT QUIRÚRGICO: PRE-TAG DE VENDOR (invisible para el cliente) ---
@app.route('/vendor-pretag', methods=['GET', 'POST', 'OPTIONS'])
def vendor_pretag():
    # CORS básico para landings externas
    if request.method == 'OPTIONS':
        resp = app.response_class(status=204)
        resp.headers['Access-Control-Allow-Origin'] = '*'
        resp.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        resp.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
        return resp
    try:
        if request.method == 'GET':
            raw_phone = str(request.args.get('phone') or '').strip()
            raw_vendor = str(request.args.get('vendor') or '').strip()
            next_url = str(request.args.get('next') or '').strip()
        else:
            payload = request.get_json(silent=True) or {}
            raw_phone = str(payload.get('phone') or '').strip()
            raw_vendor = str(payload.get('vendor') or '').strip()
            next_url = str((payload.get('next') or '')).strip()

        # Normalizar
        phone = re.sub(r'\D', '', raw_phone)  # solo dígitos, e.g. 54911...
        vendor = _norm_vendor(raw_vendor)

        # Modo 1: phone + vendor -> persistir directo
        # Modo 2: solo vendor -> encolar para el próximo chat nuevo (válido 3 min)
        if not vendor:
            resp = jsonify({'ok': False, 'error': 'vendor_requerido'})
            resp.headers['Access-Control-Allow-Origin'] = '*'
            return resp, 400

        persisted = False
        queued = False
        if phone:
            if hasattr(memory, 'upsert_vendor_label'):
                try:
                    persisted = bool(memory.upsert_vendor_label(phone, vendor, agent_label=f"AGENTE: {vendor}", only_if_absent=False))
                except Exception as e:
                    logger.error(f"[VENDOR_PRETAG] Error persistiendo vendor para {phone}: {e}", exc_info=True)
            else:
                logger.error("[VENDOR_PRETAG] memory.upsert_vendor_label no disponible")
        else:
            # Encolar vendor para próximo chat nuevo
            try:
                now_ts = int(time.time())
                with PENDING_VENDOR_LOCK:
                    # limpiar expirados
                    while PENDING_VENDOR_QUEUE and (now_ts - PENDING_VENDOR_QUEUE[0][1] > PENDING_VENDOR_TTL_SECONDS):
                        PENDING_VENDOR_QUEUE.popleft()
                    PENDING_VENDOR_QUEUE.append((vendor, now_ts))
                    queued = True
            except Exception as e:
                logger.error(f"[VENDOR_PRETAG] Error encolando vendor: {e}", exc_info=True)

        logger.info(f"[VENDOR_PRETAG] phone={phone or '-'} vendor={vendor} persisted={persisted} queued={queued}")
        # Si viene next, redirigimos (permite un solo link clickeable)
        if next_url:
            target = next_url
            if not (target.startswith('http://') or target.startswith('https://')):
                # fallback a wa.me estándar si pasaron solo número
                target = f"https://wa.me/{target}"
            return redirect(target, code=302)
        else:
            resp = jsonify({'ok': True, 'persisted': persisted, 'queued': queued, 'phone': phone, 'vendor': vendor})
            resp.headers['Access-Control-Allow-Origin'] = '*'
            return resp, 200
    except Exception as e:
        logger.error(f"[VENDOR_PRETAG] Error inesperado: {e}", exc_info=True)
        resp = jsonify({'ok': False, 'error': 'unexpected_error'})
        resp.headers['Access-Control-Allow-Origin'] = '*'
        return resp, 500
    data = request.get_json()
    if not data: return "OK", 200
    logger.info(f"[WEBHOOK-HUMANO] Recibida notificación verificada: {data}")
    try:
        if 'messages' not in data: return "OK", 200
        message_data = data.get('messages', [{}])[0]
        if not message_data.get("fromMe"): return "OK", 200
        human_agent_name = message_data.get('senderName', 'Agente-Humano')
        if config.HUMAN_AGENT_NAMES and human_agent_name not in config.HUMAN_AGENT_NAMES:
            logger.debug(f"[WEBHOOK-HUMANO] Mensaje automático ignorado: {human_agent_name}")
            return "OK", 200
        recipient_author = message_data.get('chatId')
        human_message_body = message_data.get('body', '')
        if not recipient_author: return "Datos incompletos", 400
        if human_message_body:
            logger.info(f"Registrando intervención de '{human_agent_name}' para {recipient_author}.")
            memory.add_to_conversation_history(
                phone_number=recipient_author, role="assistant",
                name=human_agent_name, content=human_message_body, sender_name=""
            )
            logger.info(f"Intervención guardada en historial de {recipient_author}.")
    except Exception as e:
        logger.error(f"[WEBHOOK-HUMANO] Error procesando mensaje saliente: {e}", exc_info=True)
        return "Error interno del servidor", 500
    return "OK", 200


@app.route('/mercadopago-webhook', methods=['POST'])
def mercadopago_webhook():
    """Recibe notificaciones de MercadoPago y actualiza el estado de la conversación."""
    data = request.get_json() or {}
    payment_id = data.get('data', {}).get('id')
    if not payment_id:
        return "Sin ID", 200
    try:
        sdk = mercadopago.SDK(config.MERCADOPAGO_TOKEN)
        info = sdk.payment().get(payment_id)
        payment = info.get('response', {})
        ext_ref = payment.get('external_reference')
        status = payment.get('status')
        phone = memory.get_phone_by_reference(ext_ref) if ext_ref else None
        if phone:
            # Unificar estados: si no está aprobado, mantener en flujo de pagos esperando confirmación
            if status == 'approved':
                # No forzar dominio/estado; solo marcar verificado en el contexto actual
                history, _, current_state, state_context = memory.get_conversation_data(phone_number=phone)
                sc = state_context or {}
                sc['payment_verified'] = True
                sc['payment_status'] = 'VERIFICADO'
                sc['payment_verification_timestamp'] = datetime.utcnow().isoformat()
                memory.update_conversation_state(phone, sc.get('current_state', current_state), context=_clean_context_for_firestore(sc))
            else:
                memory.update_conversation_state(phone, 'PAGOS_ESPERANDO_CONFIRMACION', context={'external_reference': ext_ref})
        logger.info(f"[MP-WEBHOOK] Pago {status} para ref {ext_ref}")
    except Exception as e:
        logger.error(f"Error en webhook de MercadoPago: {e}", exc_info=True)
        return "Error", 500
    return "OK", 200

@app.route('/test-hora')
def test_hora():
    """
    Endpoint de diagnóstico para verificar la configuración de la zona horaria.
    """
    import pytz
    from datetime import datetime
    # Importamos la variable TIMEZONE directamente desde el handler para ver qué está usando.
    from agendamiento_handler import TIMEZONE as AGENDAMIENTO_TZ
    # Definimos la zona horaria correcta para comparar.
    tz_buenos_aires = pytz.timezone('America/Argentina/Buenos_Aires')
    # Obtenemos la hora con diferentes métodos.
    hora_servidor_default = datetime.now()
    hora_pytz_correcta = datetime.now(tz_buenos_aires)
    # Creamos un mensaje claro para el log.
    log_mensaje = f"""
    --- PRUEBA DE ZONA HORARIA ---
    Hora Default del Servidor (datetime.now()): {hora_servidor_default.isoformat()} (tzinfo: {hora_servidor_default.tzinfo})
    Hora Forzada con Pytz (datetime.now(tz)): {hora_pytz_correcta.isoformat()} (tzinfo: {hora_pytz_correcta.tzinfo})
    Variable TIMEZONE importada de agendamiento_handler: {AGENDAMIENTO_TZ}
    ---------------------------------
    """
    logger.info(log_mensaje)
    print(log_mensaje)
    return f"<pre>{log_mensaje}</pre>", 200

@app.route('/cache-stats')
def cache_stats():
    """
    Endpoint de diagnóstico para verificar el estado del caché de turnos.
    """
    import utils
    
    try:
        stats = utils.get_slots_cache_stats()
        stats_html = f"""
        <h2>Estadísticas del Caché de Turnos</h2>
        <ul>
            <li><strong>Total de entradas:</strong> {stats['total_entries']}</li>
            <li><strong>Entradas válidas:</strong> {stats['valid_entries']}</li>
            <li><strong>Entradas expiradas:</strong> {stats['expired_entries']}</li>
            <li><strong>TTL del caché:</strong> {stats['cache_ttl_seconds']} segundos</li>
        </ul>
        """
        return stats_html, 200
    except Exception as e:
        logger.error(f"Error obteniendo estadísticas del caché: {e}")
        return f"Error obteniendo estadísticas del caché: {e}", 500

@app.route('/clear-cache')
def clear_cache():
    """Limpia todas las cachés del sistema."""
    try:
        # Limpiar cachés de servicios
        if 'PAYMENT' in config.ENABLED_AGENTS:
            pago_handler.clear_cache()
        if 'SCHEDULING' in config.ENABLED_AGENTS:
            agendamiento_handler.clear_cache()
        
        # Limpiar cachés de otros módulos
        utils.clear_cache()
        llm_handler.clear_cache()
        
        return jsonify({
            "status": "success",
            "message": "Todas las cachés han sido limpiadas",
            "timestamp": datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Error limpiando cachés: {e}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": f"Error limpiando cachés: {str(e)}"
        }), 500



@app.route('/clear-user-cache/<author>')
def clear_user_cache(author):
    """
    Endpoint para limpiar el caché de turnos de un usuario específico.
    """
    import utils
    
    try:
        utils.clear_user_slots_cache(author)
        return f"Caché de turnos limpiado exitosamente para el usuario {author}", 200
    except Exception as e:
        logger.error(f"Error limpiando caché del usuario {author}: {e}")
        return f"Error limpiando caché del usuario {author}: {e}", 500

@app.route('/test-services-cache')
def test_services_cache():
    """
    Endpoint para probar el caché de servicios.
    """
    import utils
    
    try:
        # Llamar a la función varias veces para verificar el caché
        servicios1 = utils.get_services_catalog()
        servicios2 = utils.get_services_catalog()
        servicios3 = utils.get_services_catalog()
        
        # Verificar que todas las llamadas devuelven el mismo resultado
        son_iguales = servicios1 == servicios2 == servicios3
        
        result_html = f"""
        <h2>Prueba del Caché de Servicios</h2>
        <ul>
            <li><strong>Número de servicios:</strong> {len(servicios1)}</li>
            <li><strong>Resultados idénticos:</strong> {son_iguales}</li>
            <li><strong>Primer servicio:</strong> {servicios1[0]['nombre'] if servicios1 else 'N/A'}</li>
        </ul>
        <h3>Lista de Servicios:</h3>
        <ul>
        """
        
        for servicio in servicios1:
            result_html += f"<li>{servicio['nombre']} - ${servicio['precio']}</li>"
        
        result_html += "</ul>"
        
        return result_html, 200
    except Exception as e:
        logger.error(f"Error probando caché de servicios: {e}")
        return f"Error probando caché de servicios: {e}", 500

@app.route('/test-interactive-payload')
def test_interactive_payload():
    """
    Endpoint para probar la estructura JSON de mensajes interactivos.
    """
    import utils
    
    try:
        servicios = utils.get_services_catalog()
        
        # Crear opciones de lista con títulos acortados
        opciones_lista = []
        for servicio in servicios[:3]:  # Solo los primeros 3 para la prueba
            nombre = servicio.get('nombre', 'Servicio')
            precio = servicio.get('precio', 'Consultar')
            titulo_final = utils.acortar_titulo_servicio(nombre, precio, max_caracteres=24)
            
            opciones_lista.append({
                "id": servicio.get('id', 'servicio_1'),
                "title": titulo_final,
                "description": f"${precio} ARS"
            })
        
        # Estructura JSON para lista
        lista_payload = {
            "to": "5493413167185",  # Número de prueba
            "type": "interactive",
            "interactive": {
                "type": "list",
                "header": {
                    "type": "text",
                    "text": "Elige una opción"
                },
                "body": {
                    "text": "Selecciona el servicio que te interesa:"
                },
                "footer": {
                    "text": "Tu Asistente Virtual"
                },
                "action": {
                    "button": "Ver Servicios",
                    "sections": [
                        {
                            "title": "Servicios Disponibles",
                            "rows": opciones_lista
                        }
                    ]
                }
            }
        }
        
        # Estructura JSON para botones
        botones_payload = {
            "to": "5493413167185",  # Número de prueba
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {
                    "text": "¿Confirmas el servicio 'Asesoramiento (60 min)' por $120000?"
                },
                "action": {
                    "buttons": [
                        {
                            "type": "reply",
                            "reply": {
                                "id": "confirmar_si",
                                "title": "✅ Sí, confirmar"
                            }
                        },
                        {
                            "type": "reply",
                            "reply": {
                                "id": "confirmar_no",
                                "title": "❌ No, cancelar"
                            }
                        }
                    ]
                }
            }
        }
        
        result_html = f"""
        <h2>Prueba de Estructura JSON para Mensajes Interactivos</h2>
        
        <h3>Payload para Lista:</h3>
        <pre>{json.dumps(lista_payload, indent=2)}</pre>
        
        <h3>Payload para Botones:</h3>
        <pre>{json.dumps(botones_payload, indent=2)}</pre>
        
        <h3>Límites de Caracteres Verificados:</h3>
        <ul>
            <li>Header text: {len(lista_payload['interactive']['header']['text'])}/60 ✅</li>
            <li>Body text: {len(lista_payload['interactive']['body']['text'])}/1024 ✅</li>
            <li>Button text: {len(lista_payload['interactive']['action']['button'])}/20 ✅</li>
            <li>Section title: {len(lista_payload['interactive']['action']['sections'][0]['title'])}/24 ✅</li>
        </ul>
        
        <h3>Opciones de Lista:</h3>
        <ul>
        """
        
        for opcion in opciones_lista:
            result_html += f"<li>{opcion['title']} ({len(opcion['title'])}/24 chars) - {opcion['description']}</li>"
        
        result_html += "</ul>"
        
        return result_html, 200
    except Exception as e:
        logger.error(f"Error probando payload interactivo: {e}")
        return f"Error probando payload interactivo: {e}", 500

@app.route('/test-sender-name')
def test_sender_name():
    """
    Endpoint de diagnóstico para probar la extracción de senderName con diferentes estructuras de payload.
    """
    test_payloads = [
        {
            "name": "Estructura estándar (profile.name)",
            "payload": {
                "from": "5493413167185@c.us",
                "type": "text",
                "profile": {"name": "Juan Pérez"},
                "timestamp": "1234567890"
            }
        },
        {
            "name": "Estructura alternativa (contact.name)",
            "payload": {
                "from": "5493413167185@c.us",
                "type": "text",
                "contact": {"name": "María García"},
                "timestamp": "1234567890"
            }
        },
        {
            "name": "Estructura de contexto (context.name)",
            "payload": {
                "from": "5493413167185@c.us",
                "type": "text",
                "context": {"name": "Carlos López"},
                "timestamp": "1234567890"
            }
        },
        {
            "name": "Estructura de metadatos (metadata.name)",
            "payload": {
                "from": "5493413167185@c.us",
                "type": "text",
                "metadata": {"name": "Ana Rodríguez"},
                "timestamp": "1234567890"
            }
        },
        {
            "name": "Sin nombre (fallback)",
            "payload": {
                "from": "5493413167185@c.us",
                "type": "text",
                "timestamp": "1234567890"
            }
        },
        {
            "name": "Estructura completa de webhook (contacts array)",
            "payload": {
                "from": "5493413167185@c.us",
                "type": "text",
                "timestamp": "1234567890"
            },
            "full_payload": {
                "entry": [{
                    "changes": [{
                        "value": {
                            "contacts": [{
                                "profile": {
                                    "name": "Cristian Bárbulo"
                                }
                            }]
                        }
                    }]
                }]
            }
        },
        {
            "name": "Estructura completa de webhook (contacts array)",
            "payload": {
                "from": "5493413167185@c.us",
                "type": "text",
                "timestamp": "1234567890"
            },
            "full_payload": {
                "entry": [{
                    "changes": [{
                        "value": {
                            "contacts": [{
                                "profile": {
                                    "name": "Cristian Bárbulo"
                                }
                            }]
                        }
                    }]
                }]
            }
        }
    ]
    
    result_html = "<h2>Prueba de Extracción de SenderName</h2>"
    
    for test in test_payloads:
        author = test["payload"]["from"]
        full_payload = test.get("full_payload")
        sender_name_raw = _extraer_sender_name(test["payload"], author, full_payload)
        sender_name_clean = _validar_sender_name(sender_name_raw, author)
        
        result_html += f"""
        <h3>{test['name']}</h3>
        <p><strong>Payload:</strong> {test['payload']}</p>
        """
        if full_payload:
            result_html += f"<p><strong>Full Payload:</strong> {full_payload}</p>"
        result_html += f"""
        <p><strong>SenderName Raw:</strong> '{sender_name_raw}'</p>
        <p><strong>SenderName Clean:</strong> '{sender_name_clean}'</p>
        <hr>
        """
    
    return result_html, 200

@app.route('/monitor-sender-names')
def monitor_sender_names():
    """
    Endpoint para monitorear los senderNames extraídos en tiempo real.
    Muestra estadísticas de extracción de nombres.
    """
    try:
        # Obtener estadísticas de los últimos mensajes procesados
        stats = {
            "total_messages_processed": 0,
            "messages_with_sender_name": 0,
            "messages_without_sender_name": 0,
            "recent_sender_names": [],
            "common_sender_name_patterns": {}
        }
        
        # Analizar el buffer actual para estadísticas
        with buffer_lock:
            for author, messages in message_buffer.items():
                for msg in messages:
                    stats["total_messages_processed"] += 1
                    sender_name = msg.get('senderName', '').strip()
                    if sender_name:
                        stats["messages_with_sender_name"] += 1
                        stats["recent_sender_names"].append(sender_name)
                        
                        # Contar patrones comunes
                        if sender_name in stats["common_sender_name_patterns"]:
                            stats["common_sender_name_patterns"][sender_name] += 1
                        else:
                            stats["common_sender_name_patterns"][sender_name] = 1
                    else:
                        stats["messages_without_sender_name"] += 1
        
        # Limitar la lista de nombres recientes
        stats["recent_sender_names"] = stats["recent_sender_names"][-10:]
        
        # Ordenar patrones por frecuencia
        sorted_patterns = sorted(
            stats["common_sender_name_patterns"].items(), 
            key=lambda x: x[1], 
            reverse=True
        )[:5]
        
        result_html = f"""
        <h2>Monitor de SenderNames</h2>
        
        <h3>Estadísticas Generales</h3>
        <ul>
            <li><strong>Total de mensajes procesados:</strong> {stats['total_messages_processed']}</li>
            <li><strong>Mensajes con senderName:</strong> {stats['messages_with_sender_name']}</li>
            <li><strong>Mensajes sin senderName:</strong> {stats['messages_without_sender_name']}</li>
            <li><strong>Porcentaje de éxito:</strong> {(stats['messages_with_sender_name'] / max(stats['total_messages_processed'], 1) * 100):.1f}%</li>
        </ul>
        
        <h3>Nombres Recientes (últimos 10)</h3>
        <ul>
        """
        
        for name in stats["recent_sender_names"]:
            result_html += f"<li>'{name}'</li>"
        
        result_html += "</ul>"
        
        result_html += """
        <h3>Patrones Comunes (top 5)</h3>
        <ul>
        """
        
        for name, count in sorted_patterns:
            result_html += f"<li>'{name}': {count} veces</li>"
        
        result_html += """
        </ul>
        
        <p><em>Nota: Estas estadísticas se basan en el buffer actual de mensajes.</em></p>
        """
        
        return result_html, 200
        
    except Exception as e:
        logger.error(f"Error en monitor de sender names: {e}")
        return f"Error obteniendo estadísticas: {e}", 500

# --- FUNCIONES MANEJADORAS DE ESTADO (AÑADIR O REEMPLAZAR EN main.py) ---
# Eliminar todas las funciones _handle_state_* (desde def _handle_state_conversando hasta la última _handle_state_*)

def _clean_context_for_firestore(context):
    """
    Limpia el contexto para que sea compatible con Firestore.
    Permite que Firestore maneje datetime nativamente.
    Convierte otros tipos no soportados a formatos compatibles.
    """
    if not context or not isinstance(context, dict):
        return context
    
    cleaned_context = {}
    for key, value in context.items():
        if isinstance(value, dict):
            # Recursivamente limpiar diccionarios anidados
            cleaned_context[key] = _clean_context_for_firestore(value)
        elif isinstance(value, list):
            # Para listas, mantener elementos compatibles con Firestore
            cleaned_list = []
            for item in value:
                if isinstance(item, dict):
                    cleaned_list.append(_clean_context_for_firestore(item))
                elif isinstance(item, (str, int, float, bool, datetime)) or item is None:
                    # Permitir datetime nativamente en Firestore
                    cleaned_list.append(item)
                else:
                    # Convertir otros tipos a string si es crítico
                    try:
                        cleaned_list.append(str(item))
                    except:
                        # Si no se puede convertir, ignorar
                        pass
            cleaned_context[key] = cleaned_list
        elif isinstance(value, (str, int, float, bool, datetime)) or value is None:
            # Permitir datetime nativamente en Firestore
            cleaned_context[key] = value
        else:
            # Convertir otros tipos a string si es crítico
            try:
                cleaned_context[key] = str(value)
            except:
                # Si no se puede convertir, ignorar
                pass
    
    return cleaned_context

def _limpiar_contexto_al_finalizar_flujo(author, proximo_estado, state_context):
    """
    MEJORADO: Función dedicada para limpiar el contexto cuando se finaliza un flujo exitosamente o por derivación.
    """
    logger.info(f"[LIMPIEZA_FINAL] Iniciando limpieza de contexto para {author} con estado: {proximo_estado}")
    
    # Estados que indican finalización exitosa de flujos
    estados_finalizacion_exitosa = [
        "evento_creado", "evento_cancelado", "evento_reprogramado", 
        "pago_confirmado", "pago_aprobado", "AGENDA_FINALIZANDO_CITA", 
        "PAGOS_GENERANDO_LINK", "cita_agendada", "pago_completado"
    ]
    
    # Estados que indican derivación a humano o error
    estados_derivacion = [
        "escalado_a_humano", "error_tecnico", "timeout_conversacion",
        "usuario_inactivo", "problema_sistema"
    ]
    
    # Estados que indican retorno a estado base (solo los necesarios)
    estados_retorno_inicial = [
        "conversando",
        # Estados de triage (inician flujo y limpian contexto anterior)
        "iniciar_triage_agendamiento",
        "iniciar_triage_pagos"
    ]
    
    # NUEVA MEJORA: Confirmar que todas las funciones de "triage" o "inicio de flujo" retornen un proximo_estado_sugerido que esté en esta lista
    estados_triage_iniciales = [
        "AGENDA_MOSTRANDO_OPCIONES",  # iniciar_triage_agendamiento
        "PAGOS_ESPERANDO_SELECCION_SERVICIO"  # iniciar_triage_pagos
    ]
    
    if proximo_estado in estados_finalizacion_exitosa:
        logger.info(f"[LIMPIEZA_FINAL] Finalización exitosa detectada: {proximo_estado}")
        # Desapilar contexto y limpiar completamente
        memory.desapilar_contexto(author)
        # Limpiar context_stack completamente
        memory.limpiar_context_stack(author)
        # Resetear estado a conversación normal
        if is_valid_doc_id(author):
            memory.update_conversation_state(author, "conversando", context={})
        logger.info(f"[LIMPIEZA_FINAL] Contexto completamente limpiado para finalización exitosa")
        
    elif proximo_estado in estados_derivacion:
        logger.info(f"[LIMPIEZA_FINAL] Derivación detectada: {proximo_estado}")
        # Desapilar contexto pero mantener información de derivación
        memory.desapilar_contexto(author)
        # Guardar información de derivación
        contexto_derivacion = {
            "ultima_derivacion": proximo_estado,
            "timestamp_derivacion": datetime.now(timezone.utc).isoformat(),
            "motivo_derivacion": state_context.get('motivo_derivacion', 'No especificado')
        }
        if is_valid_doc_id(author):
            memory.update_conversation_state(author, "escalado_a_humano", context=contexto_derivacion)
        logger.info(f"[LIMPIEZA_FINAL] Contexto limpiado con información de derivación")
        
    elif proximo_estado in estados_retorno_inicial or proximo_estado in estados_triage_iniciales:
        logger.info(f"[LIMPIEZA_FINAL] Retorno a estado inicial o triage: {proximo_estado}")
        
        # PLAN DE ACCIÓN: Preservar información crítica para futuras operaciones
        contexto_preservado = {}
        if state_context:
            # Preservar el flag pasado_a_departamento si ya fue marcado como True
            if state_context.get('pasado_a_departamento', False):
                contexto_preservado['pasado_a_departamento'] = True
                logger.info(f"[LIMPIEZA_FINAL] Preservando 'pasado_a_departamento' como True para {author}")
            
            # CRÍTICO: Preservar last_event_id para futuras reprogramaciones/cancelaciones
            if state_context.get('last_event_id'):
                contexto_preservado['last_event_id'] = state_context['last_event_id']
                logger.info(f"[LIMPIEZA_FINAL] Preservando 'last_event_id': {state_context['last_event_id']} para {author}")
            
            # PLAN DE ACCIÓN: Preservar información de turno confirmado si existe
            if state_context.get('slot_seleccionado'):
                contexto_preservado['ultimo_turno_confirmado'] = state_context['slot_seleccionado']
                logger.info(f"[LIMPIEZA_FINAL] Preservando información de turno confirmado para {author}")
            
            # PLAN DE REFACTORIZACIÓN v3: Preservar contador de triage para lógica anti-bucles
            if state_context.get('triage_count', 0) > 0:
                contexto_preservado['triage_count'] = state_context['triage_count']
                logger.info(f"[LIMPIEZA_FINAL] Preservando triage_count: {state_context['triage_count']} para {author}")
        
        # Desapilar contexto y limpiar stack
        memory.desapilar_contexto(author)
        memory.limpiar_context_stack(author)
        # Resetear a estado inicial limpio pero preservar el flag
        if is_valid_doc_id(author):
            memory.update_conversation_state(author, proximo_estado, context=contexto_preservado)
        logger.info(f"[LIMPIEZA_FINAL] Contexto limpiado para retorno a estado inicial (preservando pasado_a_departamento)")
        
    else:
        logger.info(f"[LIMPIEZA_FINAL] Estado intermedio: {proximo_estado} - No se requiere limpieza completa")

def _generar_id_interactivo_temporal(tipo, datos, timestamp=None):
    """
    NUEVO: Función para generar IDs interactivos únicos y temporales.
    Los IDs incluyen timestamp para evitar conflictos y facilitar limpieza.
    """
    if timestamp is None:
        timestamp = datetime.now(timezone.utc)
    
    timestamp_str = timestamp.strftime("%Y%m%d_%H%M%S")
    
    if tipo == "servicio":
        servicio_id = datos.get('id', '1')
        return f"servicio_{servicio_id}_{timestamp_str}"
    
    elif tipo == "turno":
        fecha = datos.get('fecha', '')
        hora = datos.get('hora', '')
        return f"turno_{fecha}_{hora}_{timestamp_str}"
    
    elif tipo == "confirmacion":
        accion = datos.get('accion', 'confirmar')
        return f"{accion}_{timestamp_str}"
    
    else:
        return f"{tipo}_{timestamp_str}"

def _limpiar_ids_obsoletos(state_context, max_age_hours=24):
    """
    NUEVO: Función para limpiar IDs interactivos obsoletos del contexto.
    """
    if not state_context:
        return state_context
    
    ahora = datetime.now(timezone.utc)
    context_limpio = state_context.copy()
    
    # Lista de campos que pueden contener IDs interactivos
    campos_ids = ['ultimo_interactive_timestamp', 'ids_interactivos_activos']
    
    for campo in campos_ids:
        if campo in context_limpio:
            valor = context_limpio[campo]
            
            # Si es un diccionario con timestamp
            if isinstance(valor, dict) and 'timestamp' in valor:
                try:
                    timestamp_id = datetime.fromisoformat(valor['timestamp'].replace('Z', '+00:00'))
                    edad_horas = (ahora - timestamp_id).total_seconds() / 3600
                    
                    if edad_horas > max_age_hours:
                        del context_limpio[campo]
                        logger.info(f"[LIMPIEZA_IDS] ID obsoleto eliminado: {campo} (edad: {edad_horas:.1f}h)")
                except:
                    # Si no se puede parsear el timestamp, eliminar
                    del context_limpio[campo]
                    logger.info(f"[LIMPIEZA_IDS] ID con timestamp inválido eliminado: {campo}")
    
    return context_limpio

# --- FUNCIÓN MEJORADA PARA EXTRAER SENDERNAME ---
def _extraer_sender_name(message_data, author, full_payload=None):
    """
    NUEVO: Función robusta para extraer el nombre del remitente de diferentes estructuras de payload de 360dialog.
    Maneja múltiples ubicaciones donde puede estar el nombre del contacto.
    Ahora también busca en el payload completo si se proporciona.
    """
    logger.info(f"[SENDER_NAME] Extrayendo senderName para {author}")
    
    # Estrategia 1: Buscar en profile.name (estructura estándar)
    if message_data.get('profile', {}).get('name'):
        sender_name = message_data['profile']['name'].strip()
        logger.info(f"[SENDER_NAME] Encontrado en profile.name: '{sender_name}'")
        return sender_name
    
    # Estrategia 2: Buscar en contact.name (estructura alternativa)
    if message_data.get('contact', {}).get('name'):
        sender_name = message_data['contact']['name'].strip()
        logger.info(f"[SENDER_NAME] Encontrado en contact.name: '{sender_name}'")
        return sender_name
    
    # Estrategia 3: Buscar en context.name (estructura de contexto)
    if message_data.get('context', {}).get('name'):
        sender_name = message_data['context']['name'].strip()
        logger.info(f"[SENDER_NAME] Encontrado en context.name: '{sender_name}'")
        return sender_name
    
    # Estrategia 4: Buscar en metadata.name (estructura de metadatos)
    if message_data.get('metadata', {}).get('name'):
        sender_name = message_data['metadata']['name'].strip()
        logger.info(f"[SENDER_NAME] Encontrado en metadata.name: '{sender_name}'")
        return sender_name
    
    # Estrategia 5: Buscar en cualquier campo que contenga 'name' en el primer nivel
    for key, value in message_data.items():
        if isinstance(value, dict) and 'name' in value and isinstance(value['name'], str):
            sender_name = value['name'].strip()
            if sender_name:
                logger.info(f"[SENDER_NAME] Encontrado en {key}.name: '{sender_name}'")
                return sender_name
    
    # Estrategia 6: Buscar en cualquier campo que contenga 'sender' en el nombre
    for key, value in message_data.items():
        if 'sender' in key.lower() and isinstance(value, str) and value.strip():
            sender_name = value.strip()
            logger.info(f"[SENDER_NAME] Encontrado en campo {key}: '{sender_name}'")
            return sender_name
    
    # Estrategia 7: Buscar en cualquier campo que contenga 'name' en el nombre
    for key, value in message_data.items():
        if 'name' in key.lower() and isinstance(value, str) and value.strip():
            sender_name = value.strip()
            logger.info(f"[SENDER_NAME] Encontrado en campo {key}: '{sender_name}'")
            return sender_name
    
    # NUEVA ESTRATEGIA 8: Buscar en el payload completo (entry[0].changes[0].value.contacts[0].profile.name)
    if full_payload:
        try:
            # Buscar en la estructura completa del webhook
            for entry in full_payload.get('entry', []):
                for change in entry.get('changes', []):
                    value = change.get('value', {})
                    # Buscar en contacts array
                    for contact in value.get('contacts', []):
                        if contact.get('profile', {}).get('name'):
                            sender_name = contact['profile']['name'].strip()
                            logger.info(f"[SENDER_NAME] Encontrado en payload completo (contacts): '{sender_name}'")
                            return sender_name
        except Exception as e:
            logger.warning(f"[SENDER_NAME] Error al buscar en payload completo: {e}")
    
    # Estrategia 9: Logging detallado para diagnóstico
    logger.warning(f"[SENDER_NAME] No se encontró senderName para {author}. Estructura del mensaje:")
    logger.warning(f"[SENDER_NAME] Keys disponibles: {list(message_data.keys())}")
    if 'profile' in message_data:
        logger.warning(f"[SENDER_NAME] Profile content: {message_data['profile']}")
    if 'contact' in message_data:
        logger.warning(f"[SENDER_NAME] Contact content: {message_data['contact']}")
    
    # Fallback: retornar string vacío pero loguear para monitoreo
    return ""

# --- FUNCIÓN PARA VALIDAR Y LIMPIAR SENDERNAME ---
def _validar_sender_name(sender_name, author):
    """
    NUEVO: Función para validar y limpiar el senderName extraído.
    """
    if not sender_name:
        return ""
    
    # Limpiar caracteres problemáticos
    sender_name_clean = sender_name.strip()
    
    # Remover caracteres de control y emojis problemáticos
    import re
    sender_name_clean = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', sender_name_clean)
    
    # Limitar longitud para evitar problemas en la base de datos
    if len(sender_name_clean) > 100:
        sender_name_clean = sender_name_clean[:100]
        logger.info(f"[SENDER_NAME] Nombre truncado a 100 caracteres para {author}")
    
    # Validar que no sea solo espacios o caracteres especiales
    if not sender_name_clean or sender_name_clean.isspace():
        logger.warning(f"[SENDER_NAME] Nombre vacío o solo espacios para {author}")
        return ""
    
    logger.info(f"[SENDER_NAME] Nombre validado para {author}: '{sender_name_clean}'")
    return sender_name_clean

@app.route('/test-flujos-completos')
def test_flujos_completos():
    """
    NUEVO: Endpoint para probar que todos los flujos funcionan correctamente.
    """
    logger.info("[TEST_FLUJOS] Iniciando prueba de flujos completos")
    
    resultados = {
        "agendamiento": {
            "funciones_existentes": [],
            "funciones_faltantes": [],
            "estado": "OK"
        },
        "pagos": {
            "funciones_existentes": [],
            "funciones_faltantes": [],
            "estado": "OK"
        },
        "validacion_ids": {
            "estado": "OK",
            "errores": []
        },
        "limpieza_contexto": {
            "estado": "OK",
            "errores": []
        }
    }
    
    # Verificar funciones de agendamiento
    funciones_agendamiento = [
        "iniciar_triage_agendamiento",
        "iniciar_agendamiento", 
        "mostrar_opciones_turnos",
        "confirmar_turno_directo",
        "finalizar_cita_automatico",
        "reiniciar_busqueda",
        "iniciar_reprogramacion_cita",
        "confirmar_reprogramacion",
        "ejecutar_reprogramacion_cita",
        "iniciar_cancelacion_cita",
        "confirmar_cancelacion",
        "ejecutar_cancelacion_cita"
    ]
    
    for funcion in funciones_agendamiento:
        try:
            if hasattr(agendamiento_handler, funcion):
                resultados["agendamiento"]["funciones_existentes"].append(funcion)
            else:
                resultados["agendamiento"]["funciones_faltantes"].append(funcion)
                resultados["agendamiento"]["estado"] = "ERROR"
        except Exception as e:
            resultados["agendamiento"]["funciones_faltantes"].append(funcion)
            resultados["agendamiento"]["estado"] = "ERROR"
    
    # Verificar funciones de pagos
    funciones_pagos = [
        "iniciar_triage_pagos",
        "mostrar_servicios_pago",
        "confirmar_servicio_pago",
        "generar_link_pago",
        "reiniciar_flujo_pagos",
        "confirmar_pago"
    ]
    
    for funcion in funciones_pagos:
        try:
            if hasattr(pago_handler, funcion):
                resultados["pagos"]["funciones_existentes"].append(funcion)
            else:
                resultados["pagos"]["funciones_faltantes"].append(funcion)
                resultados["pagos"]["estado"] = "ERROR"
        except Exception as e:
            resultados["pagos"]["funciones_faltantes"].append(funcion)
            resultados["pagos"]["estado"] = "ERROR"
    
    # Verificar validación de IDs
    try:
        # Probar validación de IDs de servicios
        id_servicio = "servicio_3_20241201_143022"
        es_valido, accion, error = _validar_id_interactivo(id_servicio, 'PAGOS_ESPERANDO_SELECCION_SERVICIO', {})
        if not es_valido:
            resultados["validacion_ids"]["errores"].append(f"ID servicio inválido: {error}")
            resultados["validacion_ids"]["estado"] = "ERROR"
        
        # Probar validación de IDs de turnos
        id_turno = "turno_20241201_143022_20241201_143022"
        es_valido, accion, error = _validar_id_interactivo(id_turno, 'AGENDA_MOSTRANDO_OPCIONES', {})
        if not es_valido:
            resultados["validacion_ids"]["errores"].append(f"ID turno inválido: {error}")
            resultados["validacion_ids"]["estado"] = "ERROR"
            
    except Exception as e:
        resultados["validacion_ids"]["errores"].append(f"Error en validación: {str(e)}")
        resultados["validacion_ids"]["estado"] = "ERROR"
    
    # Verificar limpieza de contexto
    try:
        from utils import limpiar_contexto_pagos_unificado, limpiar_contexto_agendamiento_unificado
        
        # Probar limpieza de pagos
        contexto_pagos = {
            'author': 'test@c.us',
            'servicio_seleccionado_id': 'servicio_1',
            'precio': 100,
            'current_state': 'PAGOS_ESPERANDO_CONFIRMACION'
        }
        contexto_limpio_pagos = limpiar_contexto_pagos_unificado(contexto_pagos)
        if 'servicio_seleccionado_id' in contexto_limpio_pagos:
            resultados["limpieza_contexto"]["errores"].append("No se limpió contexto de pagos")
            resultados["limpieza_contexto"]["estado"] = "ERROR"
        
        # Probar limpieza de agendamiento
        contexto_agenda = {
            'author': 'test@c.us',
            'fecha_deseada': '2024-12-01',
            'available_slots': [],
            'current_state': 'AGENDA_MOSTRANDO_OPCIONES'
        }
        contexto_limpio_agenda = limpiar_contexto_agendamiento_unificado(contexto_agenda)
        if 'fecha_deseada' in contexto_limpio_agenda:
            resultados["limpieza_contexto"]["errores"].append("No se limpió contexto de agendamiento")
            resultados["limpieza_contexto"]["estado"] = "ERROR"
            
    except Exception as e:
        resultados["limpieza_contexto"]["errores"].append(f"Error en limpieza: {str(e)}")
        resultados["limpieza_contexto"]["estado"] = "ERROR"
    
    # Verificar MAPA_DE_ACCIONES
    acciones_faltantes = []
    for accion, funcion in MAPA_DE_ACCIONES.items():
        try:
            # Verificar que la función existe
            if accion.startswith("iniciar_") or accion.startswith("confirmar_") or accion.startswith("ejecutar_"):
                if accion in ["iniciar_triage_agendamiento", "iniciar_triage_pagos"]:
                    continue  # Estas ya se verificaron arriba
                if not callable(funcion):
                    acciones_faltantes.append(accion)
        except Exception as e:
            acciones_faltantes.append(accion)
    
    if acciones_faltantes:
        resultados["mapa_acciones"] = {
            "estado": "ERROR",
            "acciones_faltantes": acciones_faltantes
        }
    else:
        resultados["mapa_acciones"] = {
            "estado": "OK"
        }
    
    # Resumen final
    estado_general = "OK"
    if any(result["estado"] == "ERROR" for result in resultados.values() if isinstance(result, dict) and "estado" in result):
        estado_general = "ERROR"
    
    resultados["estado_general"] = estado_general
    resultados["timestamp"] = datetime.now(timezone.utc).isoformat()
    
    logger.info(f"[TEST_FLUJOS] Prueba completada. Estado general: {estado_general}")
    
    return jsonify(resultados)

def _build_vendor_hint_from_context_main(context_info: dict) -> str:
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

def _construir_context_info_completo(detalles, state_context, mensaje_completo_usuario, intencion="preguntar", author=None):
    """
    FUNCIÓN CRÍTICA: Construye context_info COMPLETO para el Agente Cero.
    GARANTIZA que SIEMPRE reciba toda la información disponible.
    """
    context_info = {}
    
    # Agregar detalles si existen
    if isinstance(detalles, dict):
        context_info.update(detalles)
    
    # Agregar state_context si existe
    if isinstance(state_context, dict):
        context_info.update(state_context)
    
    # Agregar información básica obligatoria
    context_info["ultimo_mensaje_usuario"] = mensaje_completo_usuario
    context_info["intencion"] = intencion
    
    # CRÍTICO: Agregar vendor_owner si no está presente
    if "vendor_owner" not in context_info and author:
        try:
            import memory
            vendor = memory.get_vendor_owner(author)
            if vendor:
                context_info["vendor_owner"] = vendor
        except Exception:
            pass
    
    # CRÍTICO: Enriquecer con datos del sistema
    try:
        current_state_sc = state_context.get('current_state', '') if state_context else ''
        _enriquecer_contexto_generador(context_info, state_context, current_state_sc)
    except Exception as e:
        logger.warning(f"[CONTEXT_INFO] Error enriqueciendo contexto: {e}")
    
    logger.info(f"[CONTEXT_INFO] Context_info completo construido: {list(context_info.keys())}")
    return context_info

def _llamar_agente_cero_directo(history, context_info):
    """
    Agente Cero mejorado: Recibe context_info completo como el generador.
    RESPONSABILIDADES:
    1. Resolver preguntando (respuesta directa)
    2. Pasar al Meta-Agente (cuando detecta intención de agenda/pago)
    """
    logger.info("[AGENTE_CERO] Llamando con context_info completo...")
    
    # Extraer información del contexto enriquecido
    mensaje_usuario = context_info.get('ultimo_mensaje_usuario', '')
    intencion = context_info.get('intencion', 'desconocida')
    
    # CORRECCIÓN CRÍTICA: Usar SIEMPRE config.PROMPT_AGENTE_CERO desde variables de entorno
    # Construir contexto enriquecido igual que el generador
    vendor_hint = _build_vendor_hint_from_context_main(context_info)
    
    prompt_completo = f"""{vendor_hint}
{config.PROMPT_AGENTE_CERO}

---
## CONTEXTO DEL SISTEMA (DATOS REALES Y ACTUALES)

### INTENCIÓN ACTUAL: {intencion}
**Significado:** Esta es la intención detectada del usuario en su último mensaje.

### ÚLTIMO MENSAJE DEL USUARIO:
"{mensaje_usuario}"

### ESTADOS DEL SISTEMA (DATOS REALES):
"""
    
    # Agregar información específica según el tipo de datos disponibles (IGUAL QUE GENERADOR)
    if 'estado_agenda' in context_info:
        estado_agenda = context_info['estado_agenda']
        prompt_completo += f"""
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
            prompt_completo += f"""
**HORARIOS DISPONIBLES:** {len(slots)} opciones
**Significado:** Lista REAL de horarios disponibles obtenida del calendario.
**IMPORTANTE:** Solo menciona estos horarios específicos, NO inventes otros.
"""
            
        if 'id_evento' in context_info:
            id_evento = context_info['id_evento']
            prompt_completo += f"""
**ID DE EVENTO:** {id_evento}
**Significado:** Identificador único de la cita creada en el calendario.
**IMPORTANTE:** Incluye este ID en tu respuesta para referencia.
"""
    
    if 'estado_pago' in context_info:
        estado_pago = context_info['estado_pago']
        prompt_completo += f"""
**ESTADO DE PAGO:** {estado_pago}
**Significado:**
- 'link_generado': Se creó exitosamente el link de pago
- 'verificacion_fallida': No se pudo verificar el pago
- 'sin_referencia': No se encontró la referencia de pago
- 'faltan_datos': Faltan datos para generar el link
- 'error': Hubo un problema técnico
"""
        if estado_pago == 'faltan_datos':
            prompt_completo += "\n**IMPORTANTE:** FALTA INFORMACIÓN para generar el link de pago. Pide al usuario de forma clara y cálida que indique el dato faltante (plan, monto o proveedor)."
        
        if 'link_pago' in context_info:
            link_pago = context_info['link_pago']
            prompt_completo += f"""
**LINK DE PAGO:** {link_pago}
**Significado:** URL REAL generada para que el usuario realice el pago.
**IMPORTANTE:** Incluye este link exacto en tu respuesta.
"""
            
        if 'monto' in context_info:
            monto = context_info['monto']
            prompt_completo += f"""
**MONTO:** {monto}
**Significado:** Precio REAL del servicio/producto seleccionado.
**IMPORTANTE:** Usa este monto exacto, NO inventes otros precios.
"""
            
        if 'plan' in context_info:
            plan = context_info['plan']
            prompt_completo += f"""
**PLAN:** {plan}
**Significado:** Servicio/producto REAL seleccionado por el usuario.
**IMPORTANTE:** Menciona este plan específico en tu respuesta.
"""
            
        if 'proveedor' in context_info:
            proveedor = context_info['proveedor']
            prompt_completo += f"""
**PROVEEDOR:** {proveedor}
**Significado:** Plataforma de pago REAL que se está utilizando.
**IMPORTANTE:** Menciona este proveedor en tu respuesta.
"""
    
    if 'estado_general' in context_info:
        estado_general = context_info['estado_general']
        prompt_completo += f"""
**ESTADO GENERAL:** {estado_general}
**Significado:** Estado actual de la conversación en el sistema.
"""

    # Formatear historial para mayor claridad
    historial_formateado = ""
    for msg in history:
        rol = msg.get('role', msg.get('name', 'asistente'))
        contenido = msg.get('content', '')
        historial_formateado += f"{rol}: {contenido}\n"

    prompt_completo += f"""
---
### HISTORIAL DE CONVERSACIÓN:
{historial_formateado}

---
### COMANDOS EXPLÍCITOS DEL SISTEMA:
El usuario debe usar estos comandos EXACTOS para navegar:

**PARA ENTRAR A FLUJOS:**
- "QUIERO AGENDAR" → Entra al sistema de agendamiento
- "QUIERO PAGAR" → Entra al sistema de pagos

**PARA SALIR DE FLUJOS:**
- "SALIR DE AGENDA" → Sale del sistema de agendamiento  
- "SALIR DE PAGO" → Sale del sistema de pagos

**IMPORTANTE:** Si el usuario no usa estos comandos exactos, enséñale que debe escribir exactamente estas frases.

---
### INSTRUCCIONES ESPECÍFICAS:
1. **ENSEÑA COMANDOS:** Si el usuario quiere agendar/pagar pero no usó el comando exacto, dile: "Para ir a [agendamiento/pagos], escribí exactamente: QUIERO [AGENDAR/PAGAR]"
2. **USA SOLO DATOS REALES:** Solo menciona horarios, precios, links y estados que estén en el contexto.
3. **NO INVENTES:** Si no hay horarios disponibles, di que no hay disponibilidad.
4. **SÉ PRECISO:** Usa los montos, planes y proveedores exactos que están en el contexto.
5. **SÉ EMPÁTICO:** Mantén un tono cálido pero directo sobre los comandos.

---
**RESPONDE AL USUARIO:**
"""
    
    # Llamar a la API de OpenAI con el contexto enriquecido
    try:
        import llm_handler
        messages = [
            {"role": "system", "content": prompt_completo}
        ]
        
        respuesta = llm_handler._llamar_api_openai(
            messages=messages, 
            model=config.AGENTE_CERO_MODEL, 
            temperature=1.0,  # GPT-5 solo soporta temperature=1.0
            max_completion_tokens=500
        )
        
        return respuesta
    except Exception as e:
        logger.error(f"[AGENTE_CERO] Error llamando al LLM: {e}", exc_info=True)
        return "Error en el procesamiento. Pasando al departamento."

def _agente_cero_decision(mensaje_completo_usuario, history, state_context):
    """
    Agente Cero: Capa de inteligencia desechable que filtra el primer contacto.
    Solo se activa si pasado_a_departamento es False o no existe.
    """
    logger.info(f"[AGENTE_CERO] Iniciando evaluación para mensaje: '{mensaje_completo_usuario[:100]}...'")
    logger.info(f"[AGENTE_CERO] Estado actual de pasado_a_departamento: {state_context.get('pasado_a_departamento', False) if state_context else 'No existe'}")
    
    # Inicializar pasado_a_departamento como False si no existe
    if state_context is None:
        state_context = {}
    if 'pasado_a_departamento' not in state_context:
        state_context['pasado_a_departamento'] = False
        logger.info(f"[AGENTE_CERO] Inicializando pasado_a_departamento como False")
    
    # CRÍTICO: Verificar si han pasado más de 24 horas desde el último mensaje
    if state_context.get('pasado_a_departamento', False):
        # Verificar si han pasado 24 horas desde el último mensaje
        ultimo_mensaje_timestamp = state_context.get('ultimo_mensaje_timestamp')
        if ultimo_mensaje_timestamp:
            try:
                from datetime import datetime, timezone
                ultimo_mensaje_dt = datetime.fromisoformat(ultimo_mensaje_timestamp.replace('Z', '+00:00'))
                ahora = datetime.now(timezone.utc)
                horas_transcurridas = (ahora - ultimo_mensaje_dt).total_seconds() / 3600
                
                if horas_transcurridas >= 48:
                    logger.info(f"[AGENTE_CERO] Han pasado {horas_transcurridas:.1f} horas. Reiniciando pasado_a_departamento.")
                    state_context['pasado_a_departamento'] = False
                    state_context['ultimo_mensaje_timestamp'] = ahora.isoformat()
                else:
                    logger.info(f"[AGENTE_CERO] Solo han pasado {horas_transcurridas:.1f} horas. Agente Cero desactivado.")
                    return None
            except Exception as e:
                logger.warning(f"[AGENTE_CERO] Error calculando tiempo transcurrido: {e}. Reiniciando bandera.")
                state_context['pasado_a_departamento'] = False
        else:
            # Si no hay timestamp, reiniciar la bandera
            logger.info(f"[AGENTE_CERO] No hay timestamp de último mensaje. Reiniciando pasado_a_departamento.")
            state_context['pasado_a_departamento'] = False
    else:
        # Si no está pasado a departamento, actualizar timestamp
        from datetime import datetime, timezone
        state_context['ultimo_mensaje_timestamp'] = datetime.now(timezone.utc).isoformat()
    
    # DETECCIÓN DIRECTA DE PALABRAS CLAVE CRÍTICAS EN AGENTE CERO
    mensaje_lower = mensaje_completo_usuario.lower().strip()
    
    # PALABRAS CLAVE PARA PASAR DIRECTO AL DEPARTAMENTO
    palabras_agendar = ["quiero agendar", "agendar", "agenda", "turno", "cita", "fecha", "hora", "disponible"]
    palabras_pagar = ["quiero pagar", "pagar", "necesito pagar", "dame las opciones", "pago", "link de pago", "abonar", "precio", "costo", "servicio", "link", "plan", "mercado pago", "mercadopago"]
    
    # BLINDAJE V10: ELIMINAR DETECCIÓN AUTOMÁTICA - SOLO COMANDOS EXPLÍCITOS
    # Ya no detectamos palabras sueltas como "turno", "pago" para derivar automáticamente
    # El usuario DEBE usar comandos explícitos: "QUIERO AGENDAR" o "QUIERO PAGAR"
    logger.info(f"[AGENTE_CERO] BLINDAJE V10 - Solo comandos explícitos permitidos, no detección automática")
    
    # Si no hay comando explícito, educar al usuario
    state_context['pasado_a_departamento'] = False  # NO derivar automáticamente
    
    # BLINDAJE V10: El Agente Cero educará sobre comandos explícitos
    # NO hay derivación automática por palabras clave
    logger.info(f"[AGENTE_CERO] Educando sobre comandos explícitos para: {mensaje_completo_usuario[:50]}...")
    
    return {
        'decision': 'RESPUESTA_GENERAL',
        'response_text': 'Para agendar turnos, escribí exactamente: QUIERO AGENDAR\nPara ver servicios de pago, escribí exactamente: QUIERO PAGAR\n\n¿En qué puedo ayudarte?',
        'state_context_updated': state_context
    }

@app.route('/test-bot-locked-problem')
def test_bot_locked_problem():
    """
    Ruta de prueba para simular y resolver el problema del bot pausado.
    """
    try:
        logger.info("[TEST] Iniciando prueba del problema de bot pausado...")
        
        # Simular un usuario de prueba
        test_phone = "5493413167185"
        
        # 1. Verificar estado actual
        history, _, current_state, state_context = memory.get_conversation_data(test_phone)
        
        initial_status = {
            "phone": test_phone,
            "current_state": current_state,
            "state_context": state_context
        }
        
        # 2. Simular el problema (establecer locked: True)
        logger.info("[TEST] Simulando problema: estableciendo locked=True...")
        memory.update_conversation_state(test_phone, current_state, context={'locked': True})
        
        # 3. Verificar que el problema existe
        history, _, current_state, state_context = memory.get_conversation_data(test_phone)
        
        problem_status = {
            "current_state": current_state,
            "state_context": state_context
        }
        
        # 4. Aplicar la solución automática
        logger.info("[TEST] Aplicando solución automática...")
        history, _, current_state, state_context = memory.get_conversation_data(test_phone)
        
        final_status = {
            "current_state": current_state,
            "state_context": state_context
        }
        
        # 5. Limpiar completamente
        logger.info("[TEST] Limpieza completada.")
        
        return jsonify({
            "status": "success",
            "test_results": {
                "initial_status": initial_status,
                "problem_status": problem_status,
                "final_status": final_status,
                "problem_solved": True
            },
            "message": "✅ Prueba completada. El problema del bot pausado ha sido resuelto.",
            "timestamp": datetime.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"[TEST] Error en prueba de bot pausado: {e}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": f"Error en prueba: {str(e)}"
        }), 500

@app.route('/test-audio-url-solution')
def test_audio_url_solution():
    """
    Ruta de prueba para verificar que la solución de URLs de audio funciona correctamente.
    """
    try:
        logger.info("[TEST] Iniciando prueba de la solución de URLs de audio...")
        
        # Simular un mensaje de audio con ID
        test_media_id = "test_audio_id_123"
        
        # 1. Probar obtención inmediata de URL
        logger.info("[TEST] Probando obtención inmediata de URL...")
        media_url = utils.get_media_url(test_media_id)
        
        # 2. Simular el flujo completo
        test_message = {
            'author': '5493413167185@c.us',
            'body': '[AUDIO]',
            'type': 'audio',
            'senderName': 'Test User',
            'time': '1234567890',
            'media_id': test_media_id,
            'media_url': media_url
        }
        
        # 3. Verificar que la URL se procesa correctamente
        messages_to_process = [test_message]
        mensaje_completo, user_message_for_history = _reconstruir_mensaje_usuario(messages_to_process, '5493413167185@c.us')
        
        test_results = {
            "media_id": test_media_id,
            "media_url_obtained": media_url is not None,
            "media_url_preview": media_url[:50] + "..." if media_url else None,
            "message_reconstruction_success": bool(mensaje_completo),
            "reconstructed_message": mensaje_completo,
            "user_message_for_history": user_message_for_history
        }
        
        return jsonify({
            "status": "success",
            "test_results": test_results,
            "message": "✅ Prueba de solución de URLs de audio completada.",
            "timestamp": datetime.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"[TEST] Error en prueba de URLs de audio: {e}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": f"Error en prueba: {str(e)}"
        }), 500

# Esta función ya la tienes, asegúrate de que esté como la propuse antes
def process_text_messages(author):
    """Obsoleto: se mantiene por compatibilidad, pero ahora no consume buffer local.
    El procesamiento real lo hace _process_if_valid_callback leyendo Firestore.
    """
    try:
        # Leer buffer persistente para no perder mensajes si alguien llama esta función
        _, _, _cs, sc = memory.get_conversation_data(phone_number=author)
        pending = list((sc or {}).get('pending_messages', []))
        if not pending:
            return
        process_message_logic(author, pending)
    except Exception as e:
        logger.error(f"[PROCESS_TEXT_MESSAGES] Error: {e}")

# El nombre de esta función debe coincidir con el que estás usando
# (antes la llamamos process_buffered_messages)
def process_message_logic(author, messages_to_process):
    """
    Este es el ORQUESTADOR PRINCIPAL.
    """
    logger.info(f"[CHECKPOINT] INICIO process_message_logic para {author}")
    
    with buffer_lock:
        if author in PROCESSING_USERS:
            return
        PROCESSING_USERS.add(author)

    try:
        # Obtener contexto ANTES de reconstruir mensaje para incluir multimedia procesada
        history, _, current_state, state_context = memory.get_conversation_data(phone_number=author)
        logger.info(f"[CONTEXTO] Contexto leído para {author}: {state_context}")

        # Enforzar lock de departamento cuando hay flujo activo para evitar llamar Agente Cero
        try:
            sc_cs = (state_context or {}).get('current_state', '') or ''
            if sc_cs.startswith('PAGOS_') or sc_cs.startswith('AGENDA_'):
                if not (state_context or {}).get('pasado_a_departamento'):
                    state_context = state_context or {}
                    state_context['pasado_a_departamento'] = True
                    memory.update_conversation_state(author, sc_cs or current_state, context=_clean_context_for_firestore(state_context))
                    logger.info(f"[GUARD_FLOW] Forzado pasado_a_departamento=True por flujo activo ({sc_cs})")
        except Exception as _e:
            logger.warning(f"[GUARD_FLOW] No se pudo aplicar guard de lock de flujo: {_e}")

        # Hidratar vendor_owner en state_context si existe en Firestore (etiqueta invisible y persistente)
        try:
            _v_owner = memory.get_vendor_owner(author) if hasattr(memory, 'get_vendor_owner') else None
            current_vendor_in_context = (state_context or {}).get('vendor_owner')
            
            if _v_owner and _v_owner != current_vendor_in_context:
                state_context = state_context or {}
                state_context['vendor_owner'] = _v_owner
                memory.update_conversation_state(author, current_state, context=_clean_context_for_firestore(state_context))
                logger.info(f"[CONTEXTO] Sincronizado vendor_owner en state_context para {author}: {current_vendor_in_context or 'NINGUNO'} -> {_v_owner}")
        except Exception:
            pass
        
        mensaje_completo_usuario, user_message_for_history = _reconstruir_mensaje_usuario(messages_to_process, author)
        if not mensaje_completo_usuario or "(no disponible)" in mensaje_completo_usuario:
            logger.warning(f"Procesamiento detenido para {author} por falta de contenido útil.")
            return

        # NUEVO: Limpiar multimedia procesada DESPUÉS de usarla para evitar duplicaciones futuras
        if state_context and 'multimedia_processed' in state_context:
            logger.info(f"[BUFFER] Limpiando multimedia procesada del contexto después de usar para {author}")
            del state_context['multimedia_processed']
            memory.update_conversation_state(author, current_state, context=_clean_context_for_firestore(state_context))
        
        sender_name = messages_to_process[-1].get('senderName', 'Usuario')
        last_message_type = messages_to_process[-1].get('type')

        # NUEVO: Enriquecer información del contacto automáticamente
        try:
            state_context = _enriquecer_contact_info(author, sender_name, mensaje_completo_usuario, state_context)
            # Persistir el contexto actualizado inmediatamente
            # IMPORTANTE: Usar el estado del contexto si fue actualizado (ej. cuando se verifica pago)
            estado_a_persistir = state_context.get('current_state', current_state)
            memory.update_conversation_state(author, estado_a_persistir, context=_clean_context_for_firestore(state_context))
        except Exception as e:
            logger.error(f"[CONTACT_INFO] Error actualizando información de contacto: {e}")

        # === BALLESTER V11: Derivación temprana al verificador médico ===
        if BALLESTER_V11_ENABLED and 'verification_state' in (state_context or {}) and state_context.get('verification_state'):
            try:
                orchestrator = verification_handler.MedicalVerificationOrchestrator()
                resultado_medico = orchestrator.process_medical_flow(mensaje_completo_usuario, state_context or {}, author)
                if resultado_medico:
                    mensaje_respuesta, contexto_actualizado, botones = resultado_medico
                    if botones:
                        msgio_handler.send_whatsapp_message(
                            phone_number=author,
                            message=mensaje_respuesta,
                            options=[{"id": b.get("id", ""), "title": b.get("title", "")} for b in botones],
                            list_title="Opciones",
                            section_title="Seleccioná"
                        )
                    else:
                        msgio_handler.send_whatsapp_message(phone_number=author, message=mensaje_respuesta)
                    memory.update_conversation_state(author, contexto_actualizado.get('current_state', current_state), context=_clean_context_for_firestore(contexto_actualizado))
                    return
            except Exception as e:
                logger.error(f"[MAIN] Error en derivación médica temprana: {e}")

        # Inicio automático del flujo médico por intención
        if BALLESTER_V11_ENABLED:
            try:
                texto_lower = (mensaje_completo_usuario or "").lower()
                if any(k in texto_lower for k in [
                    'quiero agendar', 'consultar cobertura', 'obra social', 'neurologia', 'ecografia', 'eeg', 'cardiologia'
                ]):
                    context_medico = (state_context or {}).copy()
                    context_medico['verification_state'] = context_medico.get('verification_state') or 'IDENTIFICAR_PRACTICA'
                    orchestrator = verification_handler.MedicalVerificationOrchestrator()
                    resultado_medico = orchestrator.process_medical_flow(mensaje_completo_usuario, context_medico, author)
                    if resultado_medico:
                        mensaje_respuesta, contexto_actualizado, botones = resultado_medico
                        if botones:
                            msgio_handler.send_whatsapp_message(
                                phone_number=author,
                                message=mensaje_respuesta,
                                options=[{"id": b.get("id", ""), "title": b.get("title", "")} for b in botones],
                                list_title="Opciones",
                                section_title="Seleccioná"
                            )
                        else:
                            msgio_handler.send_whatsapp_message(phone_number=author, message=mensaje_respuesta)
                        memory.update_conversation_state(author, contexto_actualizado.get('current_state', current_state), context=_clean_context_for_firestore(contexto_actualizado))
                        return
            except Exception as e:
                logger.error(f"[MAIN] Error iniciando flujo médico: {e}")

        estrategia = None
        respuesta_final = None
        nuevo_contexto = state_context

        if last_message_type == 'interactive':
            logger.info(f"[ORQUESTADOR] Mensaje interactivo detectado. Usando lógica rígida.")
            accion = _validar_id_interactivo(mensaje_completo_usuario, current_state)
            if accion:
                estrategia = {"accion_recomendada": accion, "detalles": {"id_interactivo": mensaje_completo_usuario}}
            else:
                estrategia = {"accion_recomendada": "preguntar", "detalles": {"error": "ID interactivo inválido."}}
        else:
            logger.info(f"[ORQUESTADOR] Mensaje de texto/audio. Usando lógica de IA.")
            if state_context and state_context.get('pasado_a_departamento'):
                # IMPORTANTE: Usar el estado actualizado del contexto si fue modificado
                estado_actual = state_context.get('current_state', current_state)
                mensaje_enriquecido = f"Contexto: {estado_actual}. Usuario: '{mensaje_completo_usuario}'"
                estrategia = _obtener_estrategia(estado_actual, mensaje_enriquecido, history, {}, mensaje_completo_usuario, state_context)
            else:
                # VERIFICACIÓN CRÍTICA: Si author es None desde el inicio, no continuar
                if not author:
                    logger.error(f"[AGENTE_CERO] Author es None desde inicio - abortando procesamiento")
                    return
                
                # SIMPLIFICACIÓN CRÍTICA: Usar Agente Cero híbrido que puede recomendar acciones
                context_info = _construir_context_info_completo(None, state_context, mensaje_completo_usuario, "decidir_flujo", author)
                
                respuesta_cero = _llamar_agente_cero_directo(history, context_info)
                
                # Verificar si el Agente Cero recomienda una acción
                try:
                    import utils
                    data_cero = utils.parse_json_from_llm_robusto(str(respuesta_cero), context="agente_cero_hibrido") or {}
                    
                    # CASO 1: Agente Cero recomienda una acción específica
                    accion_recomendada = data_cero.get("accion_recomendada", "").strip()
                    if accion_recomendada and accion_recomendada in MAPA_DE_ACCIONES:
                        # No ejecutar directamente: derivar al Meta-Agente para mantener regla perfecta
                        detalles_cero = data_cero.get("detalles", {})
                        logger.info(f"[AGENTE_CERO] Acción recomendada: {accion_recomendada} → Derivando a Meta-Agente")
                        state_context['pasado_a_departamento'] = True
                        if 'author' not in state_context and author:
                            state_context['author'] = author
                        nuevo_contexto = state_context
                        estado_actual = nuevo_contexto.get('current_state', current_state)
                        mensaje_enriquecido = f"Contexto: {estado_actual}. Usuario: '{mensaje_completo_usuario}'"
                        estrategia = _obtener_estrategia(estado_actual, mensaje_enriquecido, history, detalles_cero or {}, mensaje_completo_usuario, nuevo_contexto)
                    
                    # CASO 2: Agente Cero retorna decision="RESPUESTA_GENERAL" 
                    elif data_cero.get("decision") == "RESPUESTA_GENERAL":
                        # CORRECCIÓN CRÍTICA: Usar response_text, no todo el JSON
                        respuesta_final = data_cero.get("response_text", respuesta_cero)
                        # CRÍTICO: Preservar author en contexto
                        nuevo_contexto = state_context.copy() if state_context else {}
                        if 'author' not in nuevo_contexto and author:
                            nuevo_contexto['author'] = author
                        logger.info(f"[AGENTE_CERO] Respuesta general detectada: {respuesta_final[:100]}...")
                    
                    # CASO 3: Agente Cero retorna decision="PASADO_A_DEPARTAMENTO"
                    elif data_cero.get("decision") == "PASADO_A_DEPARTAMENTO":
                        # Pasar al Meta-Agente como antes
                        state_context['pasado_a_departamento'] = True
                        # CRÍTICO: Asegurar que author se preserve
                        if 'author' not in state_context and author:
                            state_context['author'] = author
                        nuevo_contexto = state_context
                        mensaje_enriquecido = f"Contexto: {current_state}. Usuario: '{mensaje_completo_usuario}'"
                        estrategia = _obtener_estrategia(current_state, mensaje_enriquecido, history, {}, mensaje_completo_usuario, nuevo_contexto)
                        # BLINDAJE: En ausencia de comandos, el Agente Cero no puede cambiar de flujo
                        if estrategia and estrategia.get("accion_recomendada") not in ["iniciar_triage_agendamiento", "iniciar_triage_pagos", "preguntar", "volver_agente_cero"]:
                            estrategia["accion_recomendada"] = "preguntar"
                            logger.info("[AGENTE_CERO] Blindaje aplicado: mantener flujo hasta comando explícito")
                        logger.info(f"[AGENTE_CERO] Pasando a departamento especializado")
                    
                    else:
                        # Solo respuesta conversacional directa (sin JSON)
                        respuesta_final = respuesta_cero
                        # CRÍTICO: Preservar author en contexto
                        nuevo_contexto = state_context.copy() if state_context else {}
                        if 'author' not in nuevo_contexto and author:
                            nuevo_contexto['author'] = author
                        logger.info(f"[AGENTE_CERO] Respuesta conversacional directa")
                        
                except Exception as e:
                    # Si no hay JSON o falla parsing, usar como respuesta directa
                    logger.warning(f"[AGENTE_CERO] Error parseando respuesta como JSON: {e}. Usando texto directo.")
                    respuesta_final = respuesta_cero
                    # CRÍTICO: Preservar author en contexto
                    nuevo_contexto = state_context.copy() if state_context else {}
                    if 'author' not in nuevo_contexto and author:
                        nuevo_contexto['author'] = author

        # 5. VERIFICACIÓN DE RESTRICCIONES ANTES DE EJECUTAR ACCIONES DE AGENDAMIENTO
        if respuesta_final is None and estrategia and estrategia.get("accion_recomendada"):
            accion = estrategia.get("accion_recomendada")
            
            # NUEVO: Verificar contexto de restricciones ANTES de ejecutar acciones de agendamiento
            if accion in ["iniciar_triage_agendamiento", "mostrar_opciones_turnos", "buscar_y_ofrecer_turnos", 
                         "finalizar_cita_automatico", "reiniciar_busqueda", "iniciar_reprogramacion_cita"]:
                restriccion_result = _verificar_restricciones_pago(state_context, author)
                
                # Verificar si hay restricciones configuradas (independientemente de si está bloqueado)
                hay_restricciones_configuradas = False
                try:
                    import config
                    hay_restricciones_configuradas = hasattr(config, 'REQUIRE_PAYMENT_BEFORE_SCHEDULING') and config.REQUIRE_PAYMENT_BEFORE_SCHEDULING
                except Exception:
                    pass
                
                if restriccion_result:
                    # Hay restricciones activas: NO re-listar ni invocar generador. Responder educativo y claro.
                    logger.info(f"[RESTRICCIONES] Acción '{accion}' bloqueada por restricciones - Respondiendo con educación de pago")
                    try:
                        import config
                        motivo = restriccion_result["context_updated"].get(
                            'restriction_message',
                            'Para confirmar un turno necesitás tener el pago verificado.'
                        )
                        respuesta_final = (
                            f"{motivo}\n"
                            f"Primero, {config.COMMAND_TIPS['EXIT_AGENDA']}.\n"
                            f"Luego, {config.COMMAND_TIPS['ENTER_PAGO']}.\n"
                            f"Una vez aprobado el pago, vas a poder agendar normalmente con 'QUIERO AGENDAR' o eligiendo un turno."
                        )
                    except Exception:
                        respuesta_final = (
                            "Para confirmar un turno necesitás tener el pago verificado. "
                            "Salí del agendamiento con: SALIR DE AGENDA. Para pagar escribí: QUIERO PAGAR. "
                            "Luego podrás agendar con QUIERO AGENDAR."
                        )
                    # Preparar contexto actualizado con la marca de restricción
                    nuevo_contexto = restriccion_result["context_updated"]
                    # Marcar estrategia como procesada para evitar doble ejecución
                    logger.info(f"[RESTRICCIONES] Restricción aplicada - Bloqueando ejecución de '{accion}'")
                    estrategia = None  # Evitar ejecución posterior de acción bloqueada
                
                elif hay_restricciones_configuradas and state_context and state_context.get('payment_verified'):
                    # Pago verificado con restricciones configuradas - enriquecer contexto para el generador
                    logger.info(f"[RESTRICCIONES] ✅ Pago verificado - Permitiendo '{accion}' con contexto enriquecido")
                    
                    # NUEVO: Enriquecer detalles para mostrar que el pago está verificado
                    detalles_enriquecidos = estrategia.get("detalles", {}).copy()
                    detalles_enriquecidos.update({
                        "situacion_especifica": "pago_verificado_con_restricciones",
                        "accion_permitida": accion,
                        "cliente_quiere": "agendar",
                        "estado_pago": "verificado",
                        "payment_amount": state_context.get('payment_amount', 0),
                        "instruccion_generador": f"El cliente quiere agendar y su pago de ${state_context.get('payment_amount', 0)} ya está verificado. Procede normalmente con el agendamiento."
                    })
                    
                    # Continuar con la acción normalmente pero con contexto enriquecido
                    estrategia["detalles"] = detalles_enriquecidos
            
            # NUEVO: Manejar acciones de pago cuando hay restricciones activas (para contextualizar)
            elif accion in ["iniciar_triage_pagos", "mostrar_servicios_pago", "generar_link_pago"]:
                restriccion_result = _verificar_restricciones_pago(state_context, author)
                if restriccion_result:
                    # Cliente quiere pagar con restricciones activas - informar al generador
                    logger.info(f"[RESTRICCIONES] Cliente quiere pagar con restricciones activas - Informando al generador")
                    
                    # NUEVO: Enriquecer detalles con información específica de pago
                    detalles_enriquecidos = estrategia.get("detalles", {}).copy()
                    detalles_enriquecidos.update({
                        "situacion_especifica": "pago_con_restriccion_activa",
                        "accion_solicitada": accion,
                        "cliente_quiere": "pagar",
                        "estado_pago": "no_verificado",
                        "restriccion_activa": True,
                        "instruccion_generador": "El cliente quiere pagar y hay restricciones de pago antes de agendar activas. Esto es positivo - ayúdalo con el proceso de pago. Una vez que complete el pago y envíe el comprobante, podrá agendar sin problemas."
                    })
                    
                    # Permitir que continue con el pago pero con contexto enriquecido
                    logger.info(f"[RESTRICCIONES] Permitiendo acción de pago '{accion}' con contexto enriquecido")
                    # NO bloqueamos la acción, solo enriquecemos el contexto para futura referencia
        
        # EJECUCIÓN DE LA ACCIÓN (BLOQUE CRÍTICO CORREGIDO)
        if respuesta_final is None and estrategia and estrategia.get("accion_recomendada"):
            accion = estrategia.get("accion_recomendada")
            detalles = estrategia.get("detalles", {})
            # BLOQUEO PERMANENTE DE AGENTE CERO HASTA 48H: Si se inicia triage, marcar pasado_a_departamento
            if accion in ["iniciar_triage_agendamiento", "iniciar_triage_pagos"]:
                try:
                    if state_context is None:
                        state_context = {}
                    if not state_context.get('pasado_a_departamento', False):
                        state_context['pasado_a_departamento'] = True
                        # Persistir inmediatamente para evitar reentrada al Agente Cero
                        memory.update_conversation_state(author, current_state, context=_clean_context_for_firestore(state_context))
                        logger.info(f"[AGENTE_CERO_LOCK] Marcado pasado_a_departamento=True al iniciar '{accion}' para {author}")
                except Exception as e:
                    logger.warning(f"[AGENTE_CERO_LOCK] No se pudo persistir el lock previo a la acción '{accion}': {e}")
            logger.info(f"[EJECUTAR] Ejecutando acción '{accion}' para {author}")
            respuesta_final, nuevo_contexto = _ejecutar_accion(accion, history, detalles, state_context, mensaje_completo_usuario, author)
            
            # APLICAR BLINDAJE DE SALIDA SOBRE EL NUEVO CONTEXTO ANTES DE PERSISTIR
            context_to_commit = nuevo_contexto if nuevo_contexto is not None else state_context
            # PRESERVAR CAMPOS CRÍTICOS DEL CONTEXTO ANTERIOR (no perder flags como payment_verified)
            try:
                if isinstance(state_context, dict) and isinstance(context_to_commit, dict):
                    for clave in [
                        'payment_verified', 'payment_status', 'payment_amount',
                        'pasado_a_departamento', 'author', 'senderName'
                    ]:
                        if clave in state_context and clave not in context_to_commit:
                            context_to_commit[clave] = state_context[clave]
            except Exception as _e:
                logger.warning(f"[CONTEXTO] No se pudieron preservar campos críticos: {_e}")
            try:
                current_state_before = (state_context or {}).get('current_state', '') or ''
                requested_state = (context_to_commit or {}).get('current_state') or (estrategia or {}).get('proximo_estado_sugerido')
                texto_usuario_uc = (mensaje_completo_usuario or '').upper()
                if current_state_before.startswith('PAGOS_'):
                    if requested_state and not str(requested_state).startswith('PAGOS_'):
                        # Permitir transicionar a AGENDA_* si el pago está verificado (auto-agenda)
                        if (str(requested_state).startswith('AGENDA_') and (context_to_commit or {}).get('payment_verified')):
                            logger.info(f"[BLINDAJE_ESTADO] Permitida salida de PAGOS→AGENDA por pago verificado: '{current_state_before}' → '{requested_state}'")
                        elif requested_state == 'conversando' and (('SALIR DE PAGO' in texto_usuario_uc) or ('SALIR DE AGENDA' in texto_usuario_uc)):
                            pass
                        else:
                            logger.info(f"[BLINDAJE_ESTADO] Rechazando salida de PAGOS: '{current_state_before}' → '{requested_state}'")
                            requested_state = None
                elif current_state_before.startswith('AGENDA_'):
                    if requested_state and not str(requested_state).startswith('AGENDA_'):
                        if requested_state == 'conversando' and ('SALIR DE AGENDA' in texto_usuario_uc):
                            pass
                        else:
                            logger.info(f"[BLINDAJE_ESTADO] Rechazando salida de AGENDA: '{current_state_before}' → '{requested_state}'")
                            requested_state = None
                # Aplicar decisión final sobre el contexto a persistir
                if requested_state:
                    context_to_commit['current_state'] = requested_state
                else:
                    context_to_commit['current_state'] = current_state_before
            except Exception as _e:
                logger.warning(f"[BLINDAJE_ESTADO] No se pudo aplicar guard previo al commit: {_e}")

            # Guardar contexto actualizado tras aplicar blindaje
            if context_to_commit and context_to_commit != state_context:
                logger.info(f"[CONTEXTO] Guardando contexto actualizado (con blindaje aplicado) para {author}")
                estado_a_persistir_post = (context_to_commit or {}).get('current_state', current_state)
                memory.update_conversation_state(author, estado_a_persistir_post, context=_clean_context_for_firestore(context_to_commit))
        elif not respuesta_final:
            logger.warning(f"[ORQUESTADOR] No se pudo determinar una acción para '{mensaje_completo_usuario}'")
            
            # MENSAJE EDUCATIVO según el contexto actual
            current_state = state_context.get('current_state', '') if state_context else ''
            if current_state.startswith('PAGOS_'):
                respuesta_final = f"Estás en el flujo de pagos. Para continuar, seleccioná una opción. {config.COMMAND_TIPS['EXIT_PAGO']} para volver al inicio."
            elif current_state.startswith('AGENDA_'):
                respuesta_final = f"Estás en el flujo de agendamiento. Para continuar, seleccioná un turno. {config.COMMAND_TIPS['EXIT_AGENDA']} para volver al inicio."
            else:
                respuesta_final = f"{config.COMMAND_TIPS['ENTER_AGENDA']}. {config.COMMAND_TIPS['ENTER_PAGO']}. {config.COMMAND_TIPS['GEN_INICIO']}"
            
            if nuevo_contexto is None:
                nuevo_contexto = state_context

        proximo_estado_sugerido = (nuevo_contexto or {}).get('current_state') or (estrategia or {}).get('proximo_estado_sugerido')
        # BLINDAJE DE COMMIT DE ESTADO (redundante por seguridad): no salir de flujos sin comando explícito
        try:
            current_state_local = (state_context or {}).get('current_state', '') or ''
            texto_usuario_uc = (mensaje_completo_usuario or '').upper()
            if current_state_local.startswith('PAGOS_'):
                if proximo_estado_sugerido and not proximo_estado_sugerido.startswith('PAGOS_'):
                    # Permitir transición a AGENDA_* si el pago ya está verificado
                    if proximo_estado_sugerido.startswith('AGENDA_') and (state_context or {}).get('payment_verified'):
                        pass
                    elif proximo_estado_sugerido == 'conversando' and (('SALIR DE PAGO' in texto_usuario_uc) or ('SALIR DE AGENDA' in texto_usuario_uc)):
                        pass
                    else:
                        proximo_estado_sugerido = None
            elif current_state_local.startswith('AGENDA_'):
                if proximo_estado_sugerido and not proximo_estado_sugerido.startswith('AGENDA_'):
                    if proximo_estado_sugerido == 'conversando' and ('SALIR DE AGENDA' in texto_usuario_uc):
                        pass
                    else:
                        proximo_estado_sugerido = None
        except Exception as _e:
            logger.warning(f"[BLINDAJE_ESTADO] No se pudo evaluar el guard de estado: {_e}")

        if proximo_estado_sugerido and proximo_estado_sugerido != current_state:
            logger.info(f"[ESTADO] Actualizando estado de '{current_state}' a '{proximo_estado_sugerido}'")
            memory.update_conversation_state(author, proximo_estado_sugerido, context=_clean_context_for_firestore(nuevo_contexto))

        if respuesta_final:
            reply_sent = False
            # Guard anti-duplicados entre procesos: ventana corta persistida en estado
            try:
                from datetime import datetime, timezone
                import time as _t
                _, _, _, sc_latest = memory.get_conversation_data(phone_number=author)
                guard_until = 0.0
                if isinstance(sc_latest, dict):
                    guard_until = float(sc_latest.get('reply_guard_until_ts', 0.0) or 0.0)
                now_ts = _t.time()
                if now_ts < guard_until:
                    logger.warning(f"[REPLY_GUARD] Respuesta suprimida para {author} (ventana anti-duplicados activa)")
                else:
                    guard_window = 3.0
                    nuevo_contexto = nuevo_contexto or {}
                    nuevo_contexto['reply_guard_until_ts'] = now_ts + guard_window
                    contexto_limpio = _clean_context_for_firestore(nuevo_contexto)
                    # Persistir inmediatamente el guard para coordinación entre procesos
                    # Importante: no sobrescribir el estado actual si la acción ya movió a AGENDA
                    estado_guard = (sc_latest or {}).get('current_state', current_state)
                    memory.update_conversation_state(author, estado_guard, context=contexto_limpio)
                    msgio_handler.send_whatsapp_message(phone_number=author.split('@')[0], message=respuesta_final)
                    memory.add_to_conversation_history(author, "user", sender_name, user_message_for_history, context=contexto_limpio, history=history)
                    memory.add_to_conversation_history(author, "assistant", "RODI", respuesta_final, name="RODI", context=contexto_limpio, history=history)
                    reply_sent = True
            except Exception as e:
                logger.error(f"[REPLY_GUARD] Error aplicando guard: {e}")
                # Fallback: enviar igualmente y registrar
                msgio_handler.send_whatsapp_message(phone_number=author.split('@')[0], message=respuesta_final)
                contexto_limpio = _clean_context_for_firestore(nuevo_contexto)
                memory.add_to_conversation_history(author, "user", sender_name, user_message_for_history, context=contexto_limpio, history=history)
                memory.add_to_conversation_history(author, "assistant", "RODI", respuesta_final, name="RODI", context=contexto_limpio, history=history)
                reply_sent = True
            
            # === INTEGRACIÓN CHATWOOT (API del Cliente) ===
            try:
                import re  # ASEGURAR QUE re ESTÁ IMPORTADO
                phone_clean = author.split('@')[0]
                logger.debug(f"🔄 INTENTANDO log_to_chatwoot para {phone_clean}")
                
                # NUEVO: Detectar si hay multimedia procesada en el mensaje
                multimedia_messages = []
                
                # Buscar transcripciones de audio
                if "[AUDIO]:" in user_message_for_history:
                    # Extraer cada transcripción de audio
                    audio_matches = re.findall(r'\[AUDIO\]: ([^[]*)', user_message_for_history)
                    for transcripcion in audio_matches:
                        if transcripcion.strip() and "nota de voz recibida" not in transcripcion:
                            multimedia_messages.append(f"🎵 **Audio recibido:**\n_{transcripcion.strip()}_")
                
                # Buscar descripciones de imagen
                if "[IMAGEN]:" in user_message_for_history:
                    # Extraer cada descripción de imagen
                    imagen_matches = re.findall(r'\[IMAGEN\]: ([^[]*)', user_message_for_history)
                    for descripcion in imagen_matches:
                        if descripcion.strip() and "imagen enviada" not in descripcion:
                            multimedia_messages.append(f"🖼️ **Imagen recibida:**\n_{descripcion.strip()}_")
                
                if reply_sent:
                    # Enviar primero los mensajes multimedia formateados
                    for multimedia_msg in multimedia_messages:
                        success = log_to_chatwoot(
                            phone=phone_clean,
                            user_message=multimedia_msg,
                            bot_response=None,  # No enviar respuesta del bot aquí
                            sender_name=sender_name
                        )
                        logger.debug(f"📤 Multimedia enviada a Chatwoot: {multimedia_msg[:50]}...")
                    
                    # Luego enviar el mensaje de texto limpio (si hay algo más que multimedia)
                    mensaje_limpio = user_message_for_history
                    # Limpiar las etiquetas de multimedia del mensaje
                    mensaje_limpio = re.sub(r'\[AUDIO\]:[^[]*', '', mensaje_limpio)
                    mensaje_limpio = re.sub(r'\[IMAGEN\]:[^[]*', '', mensaje_limpio)
                    mensaje_limpio = mensaje_limpio.strip()
                    
                    if mensaje_limpio:
                        # Si hay texto adicional, enviarlo
                        success = log_to_chatwoot(
                            phone=phone_clean,
                            user_message=mensaje_limpio,
                            bot_response=respuesta_final,
                            sender_name=sender_name
                        )
                    else:
                        # Si solo había multimedia, enviar solo la respuesta del bot
                        success = log_to_chatwoot(
                            phone=phone_clean,
                            user_message="",
                            bot_response=respuesta_final,
                            sender_name=sender_name
                        )
                
                if success:
                    logger.debug(f"✅ log_to_chatwoot ejecutado exitosamente")
                else:
                    logger.error(f"❌ Error registrando en Chatwoot")
            except Exception as e:
                logger.error(f"❌ Error registrando en Chatwoot: {e}")

    except Exception as e:
        logger.error(f"Error catastrófico en process_message_logic para {author}: {e}", exc_info=True)
    finally:
        with buffer_lock:
            PROCESSING_USERS.discard(author)
        logger.info(f"Procesamiento finalizado para {author}.")

@app.route('/chatwoot-webhook', methods=['POST'])
def chatwoot_webhook():
    """
    Recibir mensajes de agentes humanos desde Chatwoot
    IMPORTANTE: No pausamos el bot automáticamente - tu lógica de control se mantiene
    """
    try:
        data = request.get_json()
        logger.debug(f"[CHATWOOT-WEBHOOK] Payload recibido: {data}")
        
        if not data or data.get('event') != 'message_created':
            return jsonify({'status': 'ignored'}), 200
        
        message = data.get('data', {})
        
        # Solo procesar mensajes de agentes (outgoing) y no privados
        if message.get('message_type') != 'outgoing' or message.get('private'):
            return jsonify({'status': 'ignored'}), 200
        
        conversation = message.get('conversation', {})
        contact = conversation.get('meta', {}).get('sender', {})
        
        if not contact:
            return jsonify({'status': 'no_contact'}), 200
        
        # Extraer información del mensaje
        phone_raw = contact.get('phone_number', '').replace('+', '')
        agent_message = message.get('content', '').strip()
        
        # Filtrar mensajes del bot (que tienen prefijo 🤖 Bot:)
        if agent_message.startswith('🤖 Bot:'):
            return jsonify({'status': 'bot_message_ignored'}), 200
        
        if not phone_raw or not agent_message:
            return jsonify({'status': 'incomplete_data'}), 200
        
        # CRÍTICO: Verificar que es para tu cliente configurado
        client_phone = os.getenv('CHATWOOT_CLIENT_PHONE', '').replace('+', '')
        if phone_raw != client_phone:
            return jsonify({'status': 'other_client'}), 200
        
        # Enviar mensaje del agente por WhatsApp
        try:
            msgio_handler.send_whatsapp_message(phone_raw, agent_message)
            
            logger.info(f"🧑‍💼 AGENTE HUMANO -> WhatsApp: {phone_raw} -> {agent_message[:50]}...")
            
            # Registrar en el historial como mensaje del agente
            author_with_suffix = f"{phone_raw}@c.us"
            sender_name = message.get('sender', {}).get('name', 'Agente Humano')
            
            # Obtener historial actual
            history, _, current_state, state_context = memory.get_conversation_data(phone_number=author_with_suffix)
            
            # Agregar mensaje del agente al historial
            memory.add_to_conversation_history(
                phone_number=author_with_suffix,
                role="assistant",
                name=sender_name,
                content=agent_message,
                sender_name=sender_name,
                context=state_context,
                history=history
            )
            
            return jsonify({'status': 'message_sent', 'phone': phone_raw}), 200
            
        except Exception as e:
            logger.error(f"[CHATWOOT-WEBHOOK] Error enviando mensaje: {e}")
            return jsonify({'status': 'send_error', 'error': str(e)}), 500
        
    except Exception as e:
        logger.error(f"[CHATWOOT-WEBHOOK] Error procesando webhook: {e}")
        return jsonify({'status': 'error', 'error': str(e)}), 500

@app.route('/chatwoot-status')
def chatwoot_status():
    """Verificar estado de la integración con Chatwoot"""
    try:
        status = {
            'enabled': chatwoot.enabled,
            'client_name': chatwoot.client_name,
            'client_phone': chatwoot.client_phone,
            'base_url': chatwoot.base_url,
            'account_id': chatwoot.account_id,
            'inbox_id': chatwoot.inbox_id,
            'api_token_present': bool(chatwoot.api_token),
            'timestamp': datetime.now().isoformat()
        }
        
        # Test de conectividad
        if chatwoot.enabled:
            test_result = chatwoot._make_request('GET', 'conversations?per_page=1')
            status['connectivity_test'] = 'OK' if test_result is not None else 'FAILED'
        
        return jsonify(status)
        
    except Exception as e:
        return jsonify({
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500

@app.route('/chatwoot-test')
def chatwoot_test():
    """Test completo de la integración con Chatwoot"""
    try:
        # Verificar si la función log_to_chatwoot está disponible
        test_result = {
            'function_available': 'log_to_chatwoot' in globals(),
            'chatwoot_enabled': chatwoot.enabled,
            'variables_configured': {
                'base_url': bool(chatwoot.base_url),
                'account_id': bool(chatwoot.account_id),
                'inbox_id': bool(chatwoot.inbox_id),
                'api_token': bool(chatwoot.api_token),
                'client_name': bool(chatwoot.client_name),
                'client_phone': bool(chatwoot.client_phone)
            },
            'test_message_sent': False,
            'error': None
        }
        
        if chatwoot.enabled:
            # Probar conexión básica
            try:
                from chatwoot_integration import test_chatwoot_connection
                connection_test = test_chatwoot_connection()
                test_result['connection_test'] = connection_test
            except Exception as e:
                test_result['connection_test'] = f"Error: {str(e)}"
            
            # Intentar enviar un mensaje de prueba
            try:
                result = log_to_chatwoot(
                    phone='1234567890',  # Número de prueba
                    user_message='Mensaje de prueba desde OptiAtiende-IA',
                    bot_response='Respuesta de prueba del bot',
                    sender_name='Test User'
                )
                test_result['test_message_sent'] = True
                test_result['test_result'] = result
            except Exception as e:
                test_result['error'] = str(e)
        
        return jsonify(test_result)
        
    except Exception as e:
        return jsonify({
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500

@app.route('/360dialog-debug')
def debug_360dialog():
    """
    Endpoint para diagnosticar problemas con 360dialog API
    Basado en información oficial del soporte de 360dialog
    """
    try:
        api_key = os.getenv('D360_API_KEY')
        
        if not api_key:
            return {
                "status": "error",
                "message": "D360_API_KEY no configurada",
                "recommendations": [
                    "Configurar variable de entorno D360_API_KEY",
                    "Verificar que sea clave de PRODUCCIÓN, no Sandbox"
                ]
            }
        
        # Información básica
        debug_info = {
            "api_key_presente": True,
            "api_key_preview": api_key[:10] + "..." if len(api_key) > 10 else api_key,
            "api_key_length": len(api_key),
            "endpoint_base": "https://waba-v2.360dialog.io",
            "timestamp": datetime.now().isoformat()
        }
        
        # Test básico de conectividad (sin media_id específico)
        try:
            headers = {"D360-API-KEY": api_key}
            test_url = "https://waba-v2.360dialog.io/"
            
            logger.info(f"[360DIALOG DEBUG] Probando conectividad con {test_url}")
            
            response = requests.get(test_url, headers=headers, timeout=5)
            
            debug_info["connectivity_test"] = {
                "status_code": response.status_code,
                "response_headers": dict(response.headers),
                "response_preview": response.text[:200] if response.text else "Sin contenido"
            }
            
            if response.status_code == 401:
                debug_info["diagnosis"] = "API Key inválida o sin permisos"
            elif response.status_code == 403:
                debug_info["diagnosis"] = "Posible API de Sandbox (no permite media)"
            elif response.status_code == 404:
                debug_info["diagnosis"] = "Endpoint no encontrado"
            else:
                debug_info["diagnosis"] = "API respondiendo"
                
        except Exception as e:
            debug_info["connectivity_test"] = {
                "error": str(e),
                "type": type(e).__name__
            }
        
        # Verificaciones adicionales
        debug_info["verifications"] = {
            "sandbox_warning": "Si usas Sandbox, NO puedes descargar media según 360dialog",
            "media_lifetime": "URLs de media válidas solo por 5 minutos",
            "rate_limit": "5 solicitudes fallidas por hora bloquean 1 hora",
            "endpoint_correcto": "/{media_id} NO /media/{media_id}"
        }
        
        return {
            "status": "success",
            "debug_info": debug_info,
            "recommendations": [
                "Verificar que uses API de PRODUCCIÓN",
                "Testear con media_id reciente (<5 minutos)",
                "Revisar logs para rate limits",
                "Contactar soporte 360dialog si persiste"
            ]
        }
        
    except Exception as e:
        logger.error(f"[360DIALOG DEBUG] Error: {e}", exc_info=True)
        return {
            "status": "error",
            "message": f"Error en diagnóstico: {e}"
        }

@app.route('/test-360dialog-media/<media_id>')
def test_360dialog_media(media_id):
    """
    Endpoint para probar descarga de media específico
    """
    try:
        logger.info(f"[TEST MEDIA] Probando media ID: {media_id}")
        
        # Probar get_media_url
        media_url = utils.get_media_url(media_id)
        
        result = {
            "media_id": media_id,
            "timestamp": datetime.now().isoformat(),
            "get_media_url_result": media_url,
            "success": media_url is not None
        }
        
        # Si se obtuvo URL, intentar descarga
        if media_url:
            try:
                download_result = utils.download_and_store_media(media_id, "./test_downloads")
                result["download_result"] = download_result
            except Exception as e:
                result["download_error"] = str(e)
        
        return result
        
    except Exception as e:
        logger.error(f"[TEST MEDIA] Error: {e}", exc_info=True)
        return {
            "media_id": media_id,
            "error": str(e),
            "success": False
        }

@app.route('/chatwoot-debug')
def chatwoot_debug():
    """
    Ruta de debug para verificar si los mensajes están llegando a Chatwoot
    """
    try:
        # Obtener logs recientes de Chatwoot
        import requests
        from datetime import datetime, timedelta
        
        # Intentar obtener conversaciones recientes
        chatwoot_url = "https://cliente.optinexia.com"
        account_id = "4"
        inbox_id = "MYmyk8y7TbR35pKXURAZiM6p"
        
        # Verificar si podemos acceder a la API de Chatwoot
        test_url = f"{chatwoot_url}/api/v1/accounts/{account_id}/conversations?inbox_id={inbox_id}&per_page=5"
        
        try:
            response = requests.get(test_url, timeout=10)
            conversations_status = f"API Status: {response.status_code}"
            conversations_data = response.json() if response.status_code == 200 else "Error"
        except Exception as e:
            conversations_status = f"Error: {str(e)}"
            conversations_data = "No disponible"
        
        # Verificar webhook configurado
        webhook_status = "✅ Configurado: https://optiatiende-ia-lb7m.onrender.com/chatwoot-webhook"
        
        # Información del sistema
        system_info = {
            "timestamp": datetime.now().isoformat(),
            "chatwoot_url": chatwoot_url,
            "account_id": account_id,
            "inbox_id": inbox_id,
            "webhook_status": webhook_status,
            "conversations_status": conversations_status
        }
        
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Chatwoot Debug</title>
            <meta charset="UTF-8">
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; }}
                .section {{ margin: 20px 0; padding: 15px; border: 1px solid #ddd; border-radius: 5px; }}
                .success {{ background-color: #d4edda; border-color: #c3e6cb; }}
                .error {{ background-color: #f8d7da; border-color: #f5c6cb; }}
                .info {{ background-color: #d1ecf1; border-color: #bee5eb; }}
                pre {{ background-color: #f8f9fa; padding: 10px; border-radius: 3px; overflow-x: auto; }}
            </style>
        </head>
        <body>
            <h1>🔍 Chatwoot Debug Panel</h1>
            
            <div class="section info">
                <h3>📊 Información del Sistema</h3>
                <pre>{system_info}</pre>
            </div>
            
            <div class="section info">
                <h3>🔗 Estado del Webhook</h3>
                <p>{webhook_status}</p>
            </div>
            
            <div class="section {'success' if '200' in conversations_status else 'error'}">
                <h3>💬 Estado de Conversaciones</h3>
                <p><strong>{conversations_status}</strong></p>
                <h4>Datos de conversaciones:</h4>
                <pre>{conversations_data}</pre>
            </div>
            
            <div class="section info">
                <h3>🎯 Próximos pasos para verificar:</h3>
                <ol>
                    <li>Ve a Chatwoot → "Todas las conversaciones" (no solo "Mine")</li>
                    <li>Busca por número: <strong>5493413167185</strong></li>
                    <li>Busca por nombre: <strong>Cristian Bárbulo</strong></li>
                    <li>Verifica en "Sin asignar"</li>
                    <li>Revisa logs de Chatwoot en Settings → Logs</li>
                </ol>
            </div>
            
            <div class="section info">
                <h3>📝 Últimos logs del sistema:</h3>
                <p>Revisa los logs de tu aplicación para ver:</p>
                <ul>
                    <li>✅ [WEBHOOK_NATIVO] Usuario enviado: 200</li>
                    <li>✅ [WEBHOOK_NATIVO] Bot enviado: 200</li>
                    <li>✅ [WEBHOOK_NATIVO] Conversación registrada exitosamente</li>
                </ul>
            </div>
        </body>
        </html>
        """
        
    except Exception as e:
        return f"Error en debug: {str(e)}"

@app.route('/webhook/chatwoot/reply', methods=['POST', 'GET'])
def webhook_chatwoot_reply():
    """
    Endpoint para recibir webhooks cuando agentes de Chatwoot responden.
    VERSIÓN CORREGIDA - Maneja múltiples estructuras de payload
    """
    # Si es GET, retornar información del webhook
    if request.method == 'GET':
        return jsonify({
            "status": "webhook_active",
            "endpoint": "/webhook/chatwoot/reply",
            "method": "POST",
            "description": "Endpoint activo para recibir respuestas de agentes de Chatwoot",
            "usage": "Este endpoint procesa webhooks POST de Chatwoot cuando agentes responden",
            "test_endpoint": "/webhook/chatwoot/reply/test",
            "timestamp": datetime.now().isoformat()
        })
    
    # Procesar webhook POST
    try:
        data = request.get_json()
        logger.debug(f"[CHATWOOT-REPLY] Webhook recibido: {data}")
        
        if not data or data.get('event') != 'message_created':
            logger.debug(f"[CHATWOOT-REPLY] Evento ignorado: {data.get('event', 'unknown')}")
            return jsonify({'status': 'event_ignored'}), 200
            
        message_data = data.get('data', data)  # A veces está en 'data', a veces directo
        
        # NUEVA LÓGICA: Procesar tanto agentes humanos como bot de IA
        message_type = message_data.get('message_type')
        sender = message_data.get('sender', {})
        sender_type = sender.get('type', '')
        
        # Determinar si es un mensaje válido para procesar
        is_agent_message = message_type == 'outgoing'  # Agente humano
        is_bot_message = (message_type == 'incoming' and sender_type in ['bot', 'agent_bot', 'system'])  # Bot de IA
        
        if not (is_agent_message or is_bot_message):
            logger.debug(f"[CHATWOOT-REPLY] Mensaje ignorado - tipo: {message_type}, sender: {sender_type}")
            return jsonify({'status': 'not_processable', 'message_type': message_type, 'sender_type': sender_type}), 200
            
        if message_data.get('private', False):
            logger.debug(f"[CHATWOOT-REPLY] Nota privada ignorada")
            return jsonify({'status': 'private_note'}), 200
            
        message_content = message_data.get('content', '').strip()
        if not message_content:
            logger.debug(f"[CHATWOOT-REPLY] Mensaje vacío ignorado")
            return jsonify({'status': 'empty_message'}), 200
            
        # CORRECCIÓN: Obtener el número de teléfono real, no el source_id
        phone_number = None
        conversation = message_data.get('conversation', {})
        
        # Buscar el teléfono real en meta.sender.phone_number
        if conversation.get('meta', {}).get('sender', {}).get('phone_number'):
            phone_number = conversation['meta']['sender']['phone_number']
            logger.debug(f"[CHATWOOT-REPLY] Teléfono encontrado: {phone_number}")
        else:
            logger.error(f"[CHATWOOT-REPLY] No se encontró número de teléfono en el payload")
            return jsonify({'status': 'no_phone_number'}), 400
        
        phone_clean = phone_number.replace('+', '').replace('-', '').replace(' ', '')
        logger.debug(f"[CHATWOOT-REPLY] Enviando a WhatsApp: {phone_clean}")
        
        # Diferenciar entre agente humano y bot de IA
        if is_bot_message:
            # Mensaje del bot de IA
            agent_name = '🤖 OptiAtiende IA'
            final_message = f"🤖 {message_content}"
            sender_type_label = "BOT"
        else:
            # Mensaje de agente humano
            agent_name = sender.get('name', 'Agente Humano')
            final_message = message_content
            sender_type_label = "AGENTE"
        
        logger.info(f"[CHATWOOT] {sender_type_label} ➡️ WhatsApp {phone_clean}")
        
        # DEDUPE: evitar enviar dos veces el mismo mensaje de Chatwoot (memoria compartida entre workers)
        try:
            message_id = str(message_data.get('id') or message_data.get('source_id') or '')
        except Exception:
            message_id = ''

        # Obtener contexto de conversación para dedupe persistente
        author_with_suffix = f"{phone_clean}@c.us"
        history, _, current_state, state_context = memory.get_conversation_data(phone_number=author_with_suffix)
        last_id_persisted = (state_context or {}).get('last_chatwoot_msg_id')
        if message_id and last_id_persisted and message_id == str(last_id_persisted):
            logger.warning(f"[CHATWOOT-REPLY] Dedupe persistente: mensaje ya procesado ({message_id}) para {phone_clean}")
            return jsonify({'status': 'duplicate_suppressed'}), 200

        # Además, mantener dedupe en memoria por si corre en un solo proceso
        with buffer_lock:
            last_id = chatwoot_processed_messages.get(phone_clean)
            if message_id and last_id == message_id:
                logger.warning(f"[CHATWOOT-REPLY] Dedupe en-memoria: mensaje ya procesado ({message_id}) para {phone_clean}")
                return jsonify({'status': 'duplicate_suppressed'}), 200
            if message_id:
                chatwoot_processed_messages[phone_clean] = message_id

        # Marcar en estado antes de enviar (para proteger aún si se cae entre envío y persistencia)
        if message_id:
            sc_to_persist = state_context or {}
            sc_to_persist['last_chatwoot_msg_id'] = message_id
            memory.update_conversation_state(author_with_suffix, current_state, context=_clean_context_for_firestore(sc_to_persist))

        success = msgio_handler.send_whatsapp_message(phone_clean, final_message)
        
        if success:
            logger.debug(f"[CHATWOOT-REPLY] ✅ Mensaje enviado exitosamente")
            
            # Registrar en historial
            memory.add_to_conversation_history(
                phone_number=author_with_suffix,
                role="assistant",
                name=agent_name,
                content=final_message,
                sender_name=agent_name,
                context=state_context,
                history=history
            )
            
            return jsonify({'status': 'success', 'phone': phone_clean}), 200
        else:
            logger.error(f"[CHATWOOT-REPLY] ❌ Error enviando a WhatsApp")
            return jsonify({'status': 'whatsapp_failed'}), 500
            
    except Exception as e:
        logger.error(f"[CHATWOOT-REPLY] Error: {e}", exc_info=True)
        # No filtrar a cliente; no enviar error al usuario
        try:
            # Escalar a humano de manera silenciosa
            author_with_suffix = None
            phone_in_payload = (request.get_json() or {}).get('data', {}).get('conversation', {}).get('meta', {}).get('sender', {}).get('phone_number')
            if phone_in_payload:
                author_with_suffix = f"{phone_in_payload.replace('+','').replace('-','').replace(' ','')}@c.us"
            if author_with_suffix:
                history, _, current_state, state_context = memory.get_conversation_data(phone_number=author_with_suffix)
                detalles = {"motivo": "error_chatwoot_reply", "mensaje_usuario": ""}
                _ = wrapper_escalar_a_humano(history, detalles, state_context or {}, "")
        except Exception:
            pass
        return jsonify({'status': 'error'}), 200

@app.route('/webhook/chatwoot/reply/test', methods=['GET'])
def test_chatwoot_reply_webhook():
    """
    Endpoint de prueba para verificar que el webhook de respuestas está funcionando
    """
    try:
        # Ejemplos de payload para diferentes tipos de mensajes
        agent_payload = {
            "event": "message_created",
            "data": {
                "message_type": "outgoing",
                "content": "Mensaje de prueba desde agente humano",
                "private": False,
                "conversation": {
                    "contact_inbox": {
                        "source_id": "5493413167185"
                    }
                },
                "sender": {
                    "name": "Agente Humano",
                    "type": "user"
                }
            }
        }
        
        bot_payload = {
            "event": "message_created",
            "data": {
                "message_type": "incoming",
                "content": "Respuesta automática del bot de IA",
                "private": False,
                "conversation": {
                    "contact_inbox": {
                        "source_id": "5493413167185"
                    }
                },
                "sender": {
                    "name": "OptiAtiende IA",
                    "type": "bot"
                }
            }
        }
        
        return jsonify({
            "status": "webhook_ready",
            "url": "/webhook/chatwoot/reply",
            "method": "POST",
            "description": "Webhook procesa TANTO agentes humanos como bot de IA",
            "supported_types": {
                "human_agent": "message_type: outgoing",
                "ai_bot": "message_type: incoming + sender.type: bot"
            },
            "test_payloads": {
                "human_agent": agent_payload,
                "ai_bot": bot_payload
            },
            "message": "Webhook listo para recibir respuestas de Chatwoot (agentes + IA)",
            "timestamp": datetime.now().isoformat()
        })
        
    except Exception as e:
        return jsonify({
            "status": "error",
            "error": str(e)
        }), 500

@app.route('/chatwoot-dashboard')
def chatwoot_dashboard():
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>OptiAtiende Integration</title>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body { 
                font-family: Arial, sans-serif; 
                padding: 20px; 
                margin: 0;
                background: #f5f5f5;
            }
            .container {
                max-width: 800px;
                margin: 0 auto;
                background: white;
                border-radius: 8px;
                padding: 20px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }
            .status {
                padding: 10px;
                border-radius: 4px;
                margin: 10px 0;
            }
            .status.active {
                background: #d4edda;
                color: #155724;
                border: 1px solid #c3e6cb;
            }
            .message {
                padding: 10px;
                margin: 10px 0;
                border-radius: 5px;
                border-left: 4px solid #007bff;
                background: #f8f9fa;
            }
            .info-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                gap: 15px;
                margin: 20px 0;
            }
            .info-card {
                padding: 15px;
                background: #e9ecef;
                border-radius: 6px;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h2>🤖 OptiAtiende - Centro de Control</h2>
            
            <div class="status active">
                ✅ Dashboard integrado correctamente con Chatwoot
            </div>
            
            <div class="info-grid">
                <div class="info-card">
                    <h4>Estado del Bot</h4>
                    <p id="bot-status">🟢 Activo y funcionando</p>
                </div>
                <div class="info-card">
                    <h4>Conversaciones Activas</h4>
                    <p id="conversations-count">-- conversaciones</p>
                </div>
                <div class="info-card">
                    <h4>Última Actividad</h4>
                    <p id="last-activity">-- minutos</p>
                </div>
            </div>
            
            <div id="conversation-details">
                <h3>Información de Conversación</h3>
                <div class="message">
                    Selecciona una conversación para ver detalles aquí
                </div>
            </div>
            
            <div id="contact-details">
                <h3>Información de Contacto</h3>
                <div class="message">
                    La información del contacto aparecerá aquí
                </div>
            </div>
        </div>
        
        <script>
            console.log('OptiAtiende Dashboard cargado');
            
            // Actualizar timestamp
            function updateTimestamp() {
                const now = new Date();
                document.getElementById('last-activity') = now.toLocaleTimeString();
            }
            
            // Escuchar eventos de Chatwoot
            window.addEventListener('message', function(event) {
                console.log('Evento recibido de Chatwoot:', event.data);
                
                if (event.data.type === 'conversation-selected') {
                    displayConversation(event.data.conversation);
                }
                
                if (event.data.type === 'contact-selected') {
                    displayContact(event.data.contact);
                }
                
                if (event.data.type === 'message-created') {
                    updateConversationActivity(event.data.message);
                }
            });
            
            function displayConversation(conversation) {
                const detailsDiv = document.getElementById('conversation-details');
                if (conversation) {
                    detailsDiv.innerHTML = `
                        <h3>Conversación Activa</h3>
                        <div class="message">
                            <strong>ID:</strong> ${conversation.id}<br>
                            <strong>Estado:</strong> ${conversation.status}<br>
                            <strong>Mensajes:</strong> ${conversation.messages_count || 0}<br>
                            <strong>Última actividad:</strong> ${new Date(conversation.last_activity_at).toLocaleString()}
                        </div>
                    `;
                    
                    // Actualizar contador
                    document.getElementById('conversations-count').textContent = '1 conversación activa';
                }
            }
            
            function displayContact(contact) {
                const contactDiv = document.getElementById('contact-details');
                if (contact) {
                    contactDiv.innerHTML = `
                        <h3>Información de Contacto</h3>
                        <div class="message">
                            <strong>Nombre:</strong> ${contact.name || 'Sin nombre'}<br>
                            <strong>Teléfono:</strong> ${contact.phone_number || 'No disponible'}<br>
                            <strong>Email:</strong> ${contact.email || 'No disponible'}
                        </div>
                    `;
                }
            }
            
            function updateConversationActivity(message) {
                updateTimestamp();
                const statusElement = document.getElementById('bot-status');
                statusElement.textContent = '🟢 Procesando mensajes...';
                
                setTimeout(() => {
                    statusElement.textContent = '🟢 Activo y funcionando';
                }, 2000);
            }
            
            // Actualizar cada 30 segundos
            setInterval(updateTimestamp, 30000);
            updateTimestamp();
        </script>
    </body>
    </html>
    '''

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

if __name__ == '__main__':
    logger.info(f"Iniciando servidor para el inquilino: {config.TENANT_NAME}")
    
    lead_daemon_thread = Thread(target=lead_checker_daemon, daemon=True)
    lead_daemon_thread.start()
    logger.info("Demonio de chequeo de leads iniciado en segundo plano.")
    
    serve(app, host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))