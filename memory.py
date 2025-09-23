# memory.py (Versión V9 - Corregida con Máquina de Estados)
import logging
import os
import base64
import json
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any

# --- Importación de función crítica para validación de documentos ---
from pago_handler import is_valid_doc_id

# --- Configuración del Logger ---
logger = logging.getLogger(__name__)

# --- Constantes de Configuración ---
FIRESTORE_COLLECTION_NAME = "conversations_v3"
MAX_HISTORY_PAIRS = 10

# --- NUEVO: Configuración para gestión inteligente del context_stack ---
MAX_CONTEXT_STACK_SIZE = 5  # Máximo 5 contextos apilados
CRITICAL_KEYS = [
    'plan', 'monto', 'proveedor', 'link_pago', 'fecha_deseada', 
    'hora_especifica', 'servicio', 'available_slots', 'last_event_id',
    'pago_confirmado', 'cita_agendada', 'evento_creado',
    # NUEVOS campos críticos para persistir información del cliente
    'payment_verified', 'payment_amount', 'payment_status', 'payment_verification_timestamp',
    'contact_info', 'requires_payment_first', 'payment_restriction_active',
    # NUEVOS campos para sistema de revival de conversaciones
    'revival_status', 'revival_timestamp', 'revival_metadata'
]

def _is_critical_context(context: dict) -> bool:
    """
    Determina si un contexto contiene información crítica que debe persistir.
    """
    if not context or not isinstance(context, dict):
        return False
    
    # Verificar si contiene información crítica
    for key in CRITICAL_KEYS:
        if key in context and context[key]:
            return True
    
    # Verificar si contiene información de pago confirmado o cita agendada
    if any(key in context for key in ['pago_confirmado', 'cita_agendada', 'evento_creado']):
        return True
    
    return False

def _should_clean_stack(stack: list) -> bool:
    """
    Determina si el stack debe ser limpiado basado en su tamaño y contenido.
    """
    if len(stack) > MAX_CONTEXT_STACK_SIZE:
        return True
    
    # Si hay más de 3 contextos no críticos consecutivos, limpiar
    non_critical_count = 0
    for item in stack:
        if not _is_critical_context(item.get('contexto', {})):
            non_critical_count += 1
        else:
            non_critical_count = 0  # Reset counter
    
    return non_critical_count >= 3

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

# --- Inicialización de Firebase (Sin cambios) ---
db = None
def _init_firebase_client() -> firestore.Client | None:
    """Inicializa Firebase con múltiples estrategias robustas para Render.

    Orden de intento:
    1) GOOGLE_CREDENTIALS_JSON (raw o base64) → credentials.Certificate
    2) GOOGLE_APPLICATION_CREDENTIALS (ruta existente) → credentials.Certificate
    3) Application Default Credentials → credentials.ApplicationDefault
    """
    try:
        # 1) GOOGLE_CREDENTIALS_JSON: contenido inline del service account
        creds_json_env = os.getenv('GOOGLE_CREDENTIALS_JSON')
        if creds_json_env:
            try:
                # Detectar si es base64 o JSON raw
                if creds_json_env.strip().startswith('{'):
                    creds_dict = json.loads(creds_json_env)
                else:
                    decoded = base64.b64decode(creds_json_env).decode('utf-8')
                    creds_dict = json.loads(decoded)
                cred = credentials.Certificate(creds_dict)
                if not firebase_admin._apps:
                    firebase_admin.initialize_app(cred)
                client = firestore.client()
                logger.info("Firebase inicializado con GOOGLE_CREDENTIALS_JSON (inline).")
                return client
            except Exception as e:
                logger.warning(f"No se pudo inicializar con GOOGLE_CREDENTIALS_JSON: {e}")

        # 2) GOOGLE_APPLICATION_CREDENTIALS: ruta a archivo en disco
        creds_path = os.getenv('GOOGLE_APPLICATION_CREDENTIALS')
        if creds_path:
            try:
                # Permitir que el env var traiga JSON directamente por error de configuración
                if creds_path.strip().startswith('{'):
                    creds_dict = json.loads(creds_path)
                    cred = credentials.Certificate(creds_dict)
                else:
                    if not os.path.exists(creds_path):
                        # Intento alternativo: usar valor por defecto si existe en el repo
                        default_path = os.path.join(os.getcwd(), creds_path)
                        if os.path.exists(default_path):
                            creds_path = default_path
                    cred = credentials.Certificate(creds_path)
                if not firebase_admin._apps:
                    firebase_admin.initialize_app(cred)
                client = firestore.client()
                logger.info("Firebase inicializado con GOOGLE_APPLICATION_CREDENTIALS (ruta).")
                return client
            except Exception as e:
                logger.warning(f"No se pudo inicializar con GOOGLE_APPLICATION_CREDENTIALS: {e}")

        # 3) Application Default Credentials (ADC)
        if not firebase_admin._apps:
            cred = credentials.ApplicationDefault()
            firebase_admin.initialize_app(cred)
        client = firestore.client()
        logger.info("Firebase inicializado correctamente usando Application Default Credentials (ADC).")
        return client

    except Exception as e:
        logger.critical(f"FALLO CRÍTICO: No se pudo inicializar Firebase. Error: {e}")
        return None


db = _init_firebase_client()

# --- Funciones de Historial (Sin cambios) ---
def add_to_conversation_history(phone_number: str, role: str, sender_name: str, content: str, name: str = None, context: dict = None, history: list = None):
    if db is None:
        logger.error("Firestore no disponible. No se puede guardar el historial.")
        return
    doc_id = sanitize_and_recover_doc_id(phone_number, context, history)
    if not doc_id:
        logger.error("No se pudo guardar historial: phone_number inválido.")
        return
    try:
        doc_ref = db.collection(FIRESTORE_COLLECTION_NAME).document(doc_id)
        current_timestamp = datetime.now(timezone.utc)
        new_message = {'role': role, 'content': content, 'timestamp': current_timestamp}
        if role == 'assistant' and name:
            new_message['name'] = name

        @firestore.transactional
        def update_in_transaction(transaction, doc_ref, new_message):
            snapshot = doc_ref.get(transaction=transaction)
            data = snapshot.to_dict() if snapshot.exists else {}
            current_history = data.get('history', [])
            current_history.append(new_message)
            
            if len(current_history) > MAX_HISTORY_PAIRS * 2:
                current_history = current_history[-(MAX_HISTORY_PAIRS * 2):]

            data_to_set = {
                'history': current_history,
                'last_updated': current_timestamp,
                'lead_processed': False
            }
            if sender_name and data.get('senderName') != sender_name:
                data_to_set['senderName'] = sender_name
            
            transaction.set(doc_ref, data_to_set, merge=True)

        transaction = db.transaction()
        update_in_transaction(transaction, doc_ref, new_message)
        logger.info(f"Historial actualizado para {phone_number}.")
    except Exception as e:
        logger.error(f"Error al guardar historial para {phone_number}: {e}", exc_info=True)

# --- INICIO DE LA SECCIÓN CORREGIDA ---

# ¡NUEVA FUNCIÓN V9!
def update_conversation_state(phone_number: str, new_state: str, context: dict = None, context_extra: dict = None, history: list = None):
    """
    Actualiza el estado y el contexto de la conversación para la máquina de estados.
    """
    if db is None:
        logger.error("Firestore no está disponible. No se puede actualizar el estado de la conversación.")
        return
    doc_id = sanitize_and_recover_doc_id(phone_number, context_extra or context, history)
    if not doc_id:
        logger.error("No se pudo actualizar estado de conversación: phone_number inválido.")
        return
    try:
        doc_ref = db.collection(FIRESTORE_COLLECTION_NAME).document(doc_id)
        from datetime import datetime, timezone
        data_to_update = {
            'conversation_state': new_state,
            'last_updated': datetime.now(timezone.utc)
        }
        
        # AGENTE CERO: Reiniciar pasado_a_departamento si el estado final es INITIAL o ATENCION_GENERAL_ACTIVA
        if context is None:
            context = {}
        
        # IMPORTANTE: No forzar a False 'pasado_a_departamento' automáticamente al guardar INITIAL.
        # El lock/deslock del Agente Cero se gestiona en el orquestador (main.py) con TTL.
        # Aquí solo preservamos el valor provisto en 'context' sin modificarlo.
        
        if context is not None:
            if context:
                # Contexto no vacío, usarlo normalmente
                data_to_update['state_context'] = _clean_context_for_firestore(context)
            else:
                # Contexto vacío: preservar solo CRITICAL_KEYS del contexto existente
                try:
                    doc = doc_ref.get()
                    if doc.exists:
                        existing_context = doc.to_dict().get('state_context', {})
                        preserved_context = {k: v for k, v in existing_context.items() if k in CRITICAL_KEYS}
                        data_to_update['state_context'] = _clean_context_for_firestore(preserved_context) if preserved_context else firestore.DELETE_FIELD
                    else:
                        data_to_update['state_context'] = firestore.DELETE_FIELD
                except Exception as e:
                    logger.warning(f"Error preservando campos críticos para {phone_number}: {e}")
                    data_to_update['state_context'] = firestore.DELETE_FIELD
        
        doc_ref.set(data_to_update, merge=True)
        logger.info(f"Estado de conversación para {phone_number} actualizado a '{new_state}'.")
    except Exception as e:
        logger.error(f"Error al actualizar el estado de la conversación para {phone_number}: {e}", exc_info=True)

# ¡FUNCIÓN CRÍTICA MODIFICADA V9!
def get_conversation_data(phone_number: str, context: dict = None, history: list = None) -> tuple[list, datetime | None, str, dict]:
    """
    Obtiene los datos de conversación de Firestore.
    Retorna: (historial, timestamp_ultimo_mensaje, estado_actual, contexto_actual)
    """
    if db is None:
        logger.error("Firestore no disponible. No se puede obtener datos de conversación.")
        return [], None, "conversando", {}
    
    doc_id = sanitize_and_recover_doc_id(phone_number, context, history)
    if not doc_id:
        logger.error("No se pudo obtener datos: phone_number inválido.")
        return [], None, "conversando", {}
    
    try:
        logger.info(f"[CHECKPOINT] INICIO get_conversation_data para {phone_number}")
        doc_ref = db.collection(FIRESTORE_COLLECTION_NAME).document(doc_id)
        doc = doc_ref.get()
        
        if doc.exists:
            data = doc.to_dict()
            logger.info(f"[CHECKPOINT] Datos obtenidos para {phone_number}: {list(data.keys())}")
            

            
            # CRÍTICO: Usar .get() con valor por defecto para asegurar que siempre sea del tipo correcto
            current_state = data.get('conversation_state', 'INITIAL')
            state_context = data.get('state_context', {})
            history = data.get('history', []) # <-- Asegura que sea lista vacía si no existe

            # --- CRÍTICO: Manejo ROBUSTO de 'last_updated' (Timestamp de Firestore) ---
            last_updated_obj = data.get('last_updated')
            last_message_timestamp = None
            if hasattr(last_updated_obj, 'to_datetime'): # Es un objeto Timestamp de Firestore
                # Convertir a datetime y asegurarse de que tenga información de zona horaria si Firestore no la incluye.
                # Firestore Timestamps suelen ser UTC. Asegúrate de que tu aplicación maneje UTC o la TZ correcta.
                last_message_timestamp = last_updated_obj.to_datetime().replace(tzinfo=timezone.utc)
                logger.info(f"[MEMORY] 'last_updated' es Timestamp de Firestore. Convertido a: {last_message_timestamp} (TZ: {last_message_timestamp.tzinfo})")
            elif isinstance(last_updated_obj, datetime):
                # Incluye google.api_core.datetime_helpers.DatetimeWithNanoseconds, que hereda de datetime
                last_message_timestamp = last_updated_obj
                if last_message_timestamp.tzinfo is None:
                    last_message_timestamp = last_message_timestamp.replace(tzinfo=timezone.utc)
                logger.info(f"[MEMORY] 'last_updated' es datetime. Usando valor: {last_message_timestamp} (TZ: {last_message_timestamp.tzinfo})")
            elif isinstance(last_updated_obj, str): # Si es una cadena ISO (fallback)
                try:
                    last_message_timestamp = datetime.fromisoformat(last_updated_obj)
                    if last_message_timestamp.tzinfo is None: # Si no tiene tzinfo, asumir UTC
                        last_message_timestamp = last_message_timestamp.replace(tzinfo=timezone.utc)
                    logger.info(f"[MEMORY] 'last_updated' es string ISO. Convertido a: {last_message_timestamp} (TZ: {last_message_timestamp.tzinfo})")
                except ValueError:
                    logger.error(f"[MEMORY] Error parsing ISO string for last_updated: {last_updated_obj}. Setting to None.")
            elif last_updated_obj is not None: # Otro tipo inesperado
                logger.warning(f"[MEMORY] Tipo inesperado para 'last_updated': {type(last_updated_obj)}. No se pudo convertir a datetime. Setting to None.")
            # --- Fin manejo robusto de 'last_updated' ---



            # CRÍTICO: Asegura que 'pasado_a_departamento' siempre esté presente en state_context
            if 'pasado_a_departamento' not in state_context:
                state_context['pasado_a_departamento'] = False
                logger.info(f"[MEMORY] Agregando 'pasado_a_departamento' a False para {phone_number} (doc existente, campo faltante).")
            
            # Limpiar contexto para compatibilidad
            if state_context:
                state_context = _clean_context_for_firestore(state_context)
            
            logger.info(f"[CHECKPOINT] Datos parseados para {phone_number}")
            return history, last_message_timestamp, current_state, state_context
        else:
            # Documento no existe, es un usuario nuevo
            current_state = 'INITIAL'
            state_context = {
                'pasado_a_departamento': False,
                'revival_status': None  # NUEVO: Elegible para revival desde el inicio
            }
            history = []
            last_message_timestamp = None
            logger.info(f"[MEMORY] Creando nuevo contexto para {phone_number}. Inicializando 'pasado_a_departamento'=False y 'revival_status'=None (elegible para revival).")
            return history, last_message_timestamp, current_state, state_context
            
    except Exception as e:
        logger.error(f"Error al obtener datos de conversación para {phone_number}: {e}", exc_info=True)
        return [], None, "conversando", {}


def get_conversation_context(phone_number: str) -> dict:
    """
    Obtiene solo el contexto de una conversación.
    Retorna el contexto actual o un diccionario vacío si no existe.
    """
    if db is None:
        logger.error("Firestore no disponible. No se puede obtener contexto.")
        return {}
    
    doc_id = sanitize_and_recover_doc_id(phone_number)
    if not doc_id:
        logger.error("No se pudo obtener contexto: phone_number inválido.")
        return {}
    
    try:
        doc_ref = db.collection(FIRESTORE_COLLECTION_NAME).document(doc_id)
        doc = doc_ref.get()
        
        if doc.exists:
            data = doc.to_dict()
            state_context = data.get('state_context', {})
            
            # Limpiar contexto para compatibilidad
            if state_context:
                state_context = _clean_context_for_firestore(state_context)
            
            return state_context
        else:
            return {}
            
    except Exception as e:
        logger.error(f"Error al obtener contexto de conversación para {phone_number}: {e}", exc_info=True)
        return {}

# --- FIN DE LA SECCIÓN CORREGIDA ---

# --- NUEVA FUNCIÓN PARA LIMPIAR ESTADOS LOCKED ---


# --- Funciones de Leads (Sin cambios) ---
def get_inactive_conversations(timestamp_limite: datetime) -> dict:
    # ... (tu código existente aquí, no necesita cambios)
    if db is None: return {}
    try:
        conversations = {}
        docs_stream = db.collection(FIRESTORE_COLLECTION_NAME)\
                        .where(filter=firestore.FieldFilter('last_updated', '<=', timestamp_limite))\
                        .where(filter=firestore.FieldFilter('lead_processed', '==', False))\
                        .stream()
        for doc in docs_stream:
            conversations[doc.id] = doc.to_dict()
        return conversations
    except Exception as e:
        logger.error(f"Error al obtener conversaciones inactivas: {e}", exc_info=True)
        return {}


def marcar_lead_como_procesado(phone_number: str, context: dict = None, history: list = None):
    # ... (tu código existente aquí, no necesita cambios)
    if db is None: return
    doc_id = sanitize_and_recover_doc_id(phone_number, context, history)
    if not doc_id:
        logger.error("No se pudo marcar lead como procesado: phone_number inválido.")
        return
    try:
        doc_ref = db.collection(FIRESTORE_COLLECTION_NAME).document(doc_id)
        doc_ref.update({'lead_processed': True})
        logger.info(f"Lead para {phone_number} marcado como procesado.")
    except Exception as e:
        logger.error(f"Error al marcar lead como procesado para {phone_number}: {e}", exc_info=True)


def get_phone_by_reference(external_reference: str) -> str | None:
    """Devuelve el número telefónico asociado a un external_reference."""
    if db is None:
        return None
    try:
        docs = db.collection(FIRESTORE_COLLECTION_NAME).where(
            filter=firestore.FieldFilter('state_context.external_reference', '==', external_reference)
        ).stream()
        for doc in docs:
            return doc.id
    except Exception as e:
        logger.error(f"Error al buscar phone_number por reference {external_reference}: {e}", exc_info=True)
    return None

def apilar_contexto(phone_number: str, estado: str, contexto: dict, context_extra: dict = None, history: list = None):
    """Apila el contexto actual en una lista (stack) en Firestore para el usuario con gestión inteligente."""
    if db is None:
        logger.error("Firestore no disponible. No se puede apilar contexto.")
        return
    doc_id = sanitize_and_recover_doc_id(phone_number, context_extra or contexto, history)
    if not doc_id:
        logger.error("No se pudo apilar contexto: phone_number inválido.")
        return
    try:
        doc_ref = db.collection(FIRESTORE_COLLECTION_NAME).document(doc_id)
        doc = doc_ref.get()
        data = doc.to_dict() if doc.exists else {}
        stack = data.get('context_stack', [])
        
        # NUEVO: Gestión inteligente del stack
        is_critical = _is_critical_context(contexto)
        
        # Si el contexto no es crítico y el stack ya es grande, limpiar antes de apilar
        if not is_critical and _should_clean_stack(stack):
            logger.info(f"[CONTEXT] Limpiando stack no crítico para {phone_number}. Stack size antes: {len(stack)}")
            # Mantener solo los contextos críticos
            stack = [item for item in stack if _is_critical_context(item.get('contexto', {}))]
            logger.info(f"[CONTEXT] Stack limpiado para {phone_number}. Stack size después: {len(stack)}")
        
        # Limpiar contexto para Firestore antes de apilar
        contexto_limpio = _clean_context_for_firestore(contexto)
        stack.append({'estado': estado, 'contexto': contexto_limpio, 'critical': is_critical})
        
        # NUEVO: Limitar el tamaño máximo del stack
        if len(stack) > MAX_CONTEXT_STACK_SIZE:
            logger.warning(f"[CONTEXT] Stack demasiado grande para {phone_number}. Limpiando contextos no críticos.")
            # Mantener solo los contextos críticos más recientes
            critical_items = [item for item in stack if item.get('critical', False)]
            non_critical_items = [item for item in stack if not item.get('critical', False)]
            
            # Mantener todos los críticos + algunos no críticos recientes
            if len(critical_items) < MAX_CONTEXT_STACK_SIZE:
                remaining_slots = MAX_CONTEXT_STACK_SIZE - len(critical_items)
                stack = critical_items + non_critical_items[-remaining_slots:]
            else:
                stack = critical_items[-MAX_CONTEXT_STACK_SIZE:]
        
        doc_ref.set({'context_stack': stack}, merge=True)
        logger.info(f"[CONTEXT] Contexto apilado para {phone_number}. Stack size: {len(stack)}, Critical: {is_critical}")
    except Exception as e:
        logger.error(f"Error al apilar contexto para {phone_number}: {e}", exc_info=True)

def desapilar_contexto(phone_number: str, context: dict = None, history: list = None) -> dict:
    """Desapila el contexto más reciente del stack y lo retorna con gestión inteligente."""
    if db is None:
        logger.error("Firestore no disponible. No se puede desapilar contexto.")
        return {}
    doc_id = sanitize_and_recover_doc_id(phone_number, context, history)
    if not doc_id:
        logger.error("No se pudo desapilar contexto: phone_number inválido.")
        return {}
    try:
        doc_ref = db.collection(FIRESTORE_COLLECTION_NAME).document(doc_id)
        doc = doc_ref.get()
        data = doc.to_dict() if doc.exists else {}
        stack = data.get('context_stack', [])
        if not stack:
            logger.info(f"[CONTEXT] Stack de contexto vacío para {phone_number}.")
            return {}
        
        # NUEVO: Gestión inteligente al desapilar
        popped = stack.pop()
        is_critical = popped.get('critical', False)
        
        # Si el contexto desapilado no es crítico y el stack sigue siendo grande, limpiar
        if not is_critical and len(stack) > MAX_CONTEXT_STACK_SIZE // 2:
            logger.info(f"[CONTEXT] Limpiando stack después de desapilar contexto no crítico para {phone_number}")
            # Mantener solo contextos críticos
            stack = [item for item in stack if item.get('critical', False)]
        
        doc_ref.set({'context_stack': stack}, merge=True)
        logger.info(f"[CONTEXT] Contexto desapilado para {phone_number}. Stack size: {len(stack)}, Critical: {is_critical}")
        return popped.get('contexto', {})
    except Exception as e:
        logger.error(f"Error al desapilar contexto para {phone_number}: {e}", exc_info=True)
        return {}



def limpiar_context_stack(phone_number: str, context: dict = None, history: list = None):
    """Limpia el context_stack manteniendo solo información crítica."""
    if db is None:
        logger.error("Firestore no disponible. No se puede limpiar context_stack.")
        return
    doc_id = sanitize_and_recover_doc_id(phone_number, context, history)
    if not doc_id:
        logger.error("No se pudo limpiar context_stack: phone_number inválido.")
        return
    try:
        doc_ref = db.collection(FIRESTORE_COLLECTION_NAME).document(doc_id)
        doc = doc_ref.get()
        data = doc.to_dict() if doc.exists else {}
        stack = data.get('context_stack', [])
        
        if not stack:
            logger.info(f"[CONTEXT] Stack ya está vacío para {phone_number}.")
            return
        
        # Mantener solo contextos críticos
        critical_stack = [item for item in stack if _is_critical_context(item.get('contexto', {}))]
        
        doc_ref.set({'context_stack': critical_stack}, merge=True)
        logger.info(f"[CONTEXT] Stack limpiado para {phone_number}. Antes: {len(stack)}, Después: {len(critical_stack)}")
    except Exception as e:
        logger.error(f"Error al limpiar context_stack para {phone_number}: {e}", exc_info=True)

# --- Utilidad para sanitizar y recuperar IDs de documento ---
def sanitize_and_recover_doc_id(doc_id: str, context: dict = None, history: list = None) -> str:
    """
    Valida y recupera el ID de documento (phone_number) para Firestore.
    Si el ID es inválido, intenta recuperarlo del contexto, historial o stack de contexto.
    """
    if doc_id and doc_id.strip() and not doc_id.strip().endswith("/"):
        return doc_id.strip()
    # Intentar recuperar del contexto
    if context and isinstance(context, dict):
        if 'author' in context and context['author']:
            logging.warning(f"Recuperando phone_number desde contexto: {context['author']}")
            return context['author']
        if 'phone_number' in context and context['phone_number']:
            logging.warning(f"Recuperando phone_number desde contexto: {context['phone_number']}")
            return context['phone_number']
        # Buscar en stack de contexto si existe
        if 'context_stack' in context and isinstance(context['context_stack'], list):
            for stack_item in reversed(context['context_stack']):
                if isinstance(stack_item, dict):
                    if 'author' in stack_item and stack_item['author']:
                        logging.warning(f"Recuperando phone_number desde stack de contexto: {stack_item['author']}")
                        return stack_item['author']
                    if 'phone_number' in stack_item and stack_item['phone_number']:
                        logging.warning(f"Recuperando phone_number desde stack de contexto: {stack_item['phone_number']}")
                        return stack_item['phone_number']
    # Intentar recuperar del historial
    if history and isinstance(history, list):
        for msg in reversed(history):
            if isinstance(msg, dict):
                if 'author' in msg and msg['author']:
                    logging.warning(f"Recuperando phone_number desde historial: {msg['author']}")
                    return msg['author']
                if 'phone_number' in msg and msg['phone_number']:
                    logging.warning(f"Recuperando phone_number desde historial: {msg['phone_number']}")
                    return msg['phone_number']
    logging.critical("No se pudo recuperar un phone_number válido para Firestore. Operación abortada.")
    return None

def registrar_pago_enviado(phone_number: str, pago_data: dict):
    """
    Registra un pago enviado al usuario para verificación posterior.
    NUEVO: Compatible con el nuevo flujo de pagos.
    """
    try:
        if not is_valid_doc_id(phone_number):
            logger.error(f"[REGISTRAR_PAGO] Phone number inválido: {phone_number}")
            return False
        
        # Obtener el documento del usuario
        doc_ref = db.collection('conversations').document(phone_number)
        doc = doc_ref.get()
        
        if not doc.exists:
            logger.warning(f"[REGISTRAR_PAGO] Documento no encontrado para {phone_number}")
            return False
        
        # Obtener datos actuales
        data = doc.to_dict()
        pagos_registrados = data.get('pagos_registrados', [])
        
        # Agregar nuevo pago
        pagos_registrados.append(pago_data)
        
        # Actualizar documento
        doc_ref.update({
            'pagos_registrados': pagos_registrados,
            'last_updated': datetime.now(timezone.utc)
        })
        
        logger.info(f"[REGISTRAR_PAGO] Pago registrado para {phone_number}: {pago_data.get('external_reference')}")
        return True
        
    except Exception as e:
        logger.error(f"[REGISTRAR_PAGO] Error registrando pago: {e}", exc_info=True)
        return False

def get_pagos_registrados(phone_number: str) -> list:
    """
    Obtiene todos los pagos registrados para un usuario.
    NUEVO: Compatible con el nuevo flujo de pagos.
    """
    try:
        if not is_valid_doc_id(phone_number):
            logger.error(f"[GET_PAGOS] Phone number inválido: {phone_number}")
            return []
        
        # Obtener el documento del usuario
        doc_ref = db.collection('conversations').document(phone_number)
        doc = doc_ref.get()
        
        if not doc.exists:
            logger.info(f"[GET_PAGOS] Documento no encontrado para {phone_number}")
            return []
        
        # Obtener pagos registrados
        data = doc.to_dict()
        pagos_registrados = data.get('pagos_registrados', [])
        
        logger.info(f"[GET_PAGOS] Encontrados {len(pagos_registrados)} pagos para {phone_number}")
        return pagos_registrados
        
    except Exception as e:
        logger.error(f"[GET_PAGOS] Error obteniendo pagos: {e}", exc_info=True)
        return []

def marcar_pago_verificado(phone_number: str, external_reference: str):
    """
    Marca un pago como verificado.
    NUEVO: Compatible con el nuevo flujo de pagos.
    """
    try:
        if not is_valid_doc_id(phone_number):
            logger.error(f"[MARCAR_PAGO] Phone number inválido: {phone_number}")
            return False
        
        # Obtener el documento del usuario
        doc_ref = db.collection('conversations').document(phone_number)
        doc = doc_ref.get()
        
        if not doc.exists:
            logger.warning(f"[MARCAR_PAGO] Documento no encontrado para {phone_number}")
            return False
        
        # Obtener datos actuales
        data = doc.to_dict()
        pagos_registrados = data.get('pagos_registrados', [])
        
        # Buscar y actualizar el pago específico
        pago_encontrado = False
        for pago in pagos_registrados:
            if pago.get('external_reference') == external_reference:
                pago['estado'] = 'verificado'
                pago['fecha_verificacion'] = datetime.now(timezone.utc).isoformat()
                pago_encontrado = True
                break
        
        if not pago_encontrado:
            logger.warning(f"[MARCAR_PAGO] Pago no encontrado: {external_reference}")
            return False
        
        # Actualizar documento
        doc_ref.update({
            'pagos_registrados': pagos_registrados,
            'last_updated': datetime.now(timezone.utc)
        })
        
        logger.info(f"[MARCAR_PAGO] Pago marcado como verificado: {external_reference}")
        return True
        
    except Exception as e:
        logger.error(f"[MARCAR_PAGO] Error marcando pago como verificado: {e}", exc_info=True)
        return False

def guardar_ultimo_turno_confirmado(phone_number: str, datos_turno: dict):
    """
    PLAN DE ACCIÓN: Guarda el último turno confirmado en memoria a largo plazo.
    OBJETIVO: No olvidar jamás una cita confirmada.
    """
    try:
        # Sanitizar el phone_number para usar como doc_id
        doc_id = sanitize_and_recover_doc_id(phone_number)
        
        # Obtener referencia al documento
        doc_ref = db.collection(FIRESTORE_COLLECTION_NAME).document(doc_id)
        
        # Preparar datos del turno para persistencia
        turno_persistente = {
            'fecha_confirmacion': datetime.now(timezone.utc),
            'datos_turno': datos_turno,
            'estado': 'confirmado'
        }
        
        # Actualizar el documento con el último turno confirmado
        doc_ref.update({
            'ultimo_turno_confirmado': turno_persistente,
            'ultima_actualizacion': datetime.now(timezone.utc)
        })
        
        logger.info(f"✅ Último turno confirmado guardado para {phone_number}: {datos_turno.get('fecha_para_titulo', 'N/A')}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Error al guardar último turno confirmado para {phone_number}: {e}")
        return False

def obtener_ultimo_turno_confirmado(phone_number: str) -> dict:
    """
    PLAN DE ACCIÓN: Obtiene el último turno confirmado de memoria a largo plazo.
    OBJETIVO: Recuperar información de citas confirmadas para reprogramación/cancelación.
    """
    try:
        # Sanitizar el phone_number para usar como doc_id
        doc_id = sanitize_and_recover_doc_id(phone_number)
        
        # Obtener referencia al documento
        doc_ref = db.collection(FIRESTORE_COLLECTION_NAME).document(doc_id)
        
        # Obtener el documento
        doc = doc_ref.get()
        
        if doc.exists:
            ultimo_turno = doc.to_dict().get('ultimo_turno_confirmado')
            if ultimo_turno:
                logger.info(f"✅ Último turno confirmado recuperado para {phone_number}: {ultimo_turno.get('datos_turno', {}).get('fecha_para_titulo', 'N/A')}")
                return ultimo_turno
            else:
                logger.info(f"ℹ️ No hay turno confirmado previo para {phone_number}")
                return None
        else:
            logger.info(f"ℹ️ No existe documento para {phone_number}")
            return None
        
    except Exception as e:
        logger.error(f"❌ Error al obtener último turno confirmado para {phone_number}: {e}")
        return None

# --- VENDOR OWNER (Etiqueta persistente de vendedor) ---

def get_vendor_owner(phone_number: str) -> str | None:
    """Obtiene el vendor_owner persistido (si existe) para el contacto."""
    try:
        if db is None:
            return None
        doc_id = sanitize_and_recover_doc_id(phone_number)
        if not doc_id:
            return None
        doc_ref = db.collection(FIRESTORE_COLLECTION_NAME).document(doc_id)
        doc = doc_ref.get()
        if doc.exists:
            data = doc.to_dict() or {}
            return (data.get('vendor_owner') or '').strip() or None
        return None
    except Exception:
        return None

def upsert_vendor_label(phone_number: str, vendor_owner: str, agent_label: str | None = None, only_if_absent: bool = True) -> bool:
    """
    Persiste la etiqueta del vendedor en el documento de conversación.
    - Guarda en el nivel raíz: vendor_owner, agent_label, vendor_set_at (datetime)
    - Si only_if_absent=True, no sobreescribe si ya existe.
    """
    if db is None:
        logger.error("Firestore no disponible. No se puede guardar vendor_owner.")
        return False
    try:
        doc_id = sanitize_and_recover_doc_id(phone_number)
        if not doc_id:
            logger.error("No se pudo guardar vendor_owner: phone_number inválido.")
            return False
        doc_ref = db.collection(FIRESTORE_COLLECTION_NAME).document(doc_id)
        snapshot = doc_ref.get()
        existing = snapshot.to_dict() if snapshot.exists else {}
        if only_if_absent and existing and existing.get('vendor_owner'):
            # Ya existe; no sobreescribir
            return False
        vendor_clean = (vendor_owner or '').strip().upper()
        if not vendor_clean:
            return False
        label = agent_label or f"AGENTE: {vendor_clean}"
        data_to_set = {
            'vendor_owner': vendor_clean,
            'agent_label': label,
            'vendor_set_at': datetime.now(timezone.utc)
        }
        doc_ref.set(data_to_set, merge=True)
        logger.info(f"[VENDOR] Persistido vendor_owner para {phone_number}: {vendor_clean}")
        return True
    except Exception as e:
        logger.error(f"Error guardando vendor_owner para {phone_number}: {e}")
        return False

# =============================================================================
# SISTEMA DE REVIVAL DE CONVERSACIONES
# =============================================================================

def get_conversations_for_revival() -> List[Dict[str, Any]]:
    """
    Obtiene conversaciones candidatas para revival (sin procesar previamente).
    
    Esta función busca conversaciones que:
    - NO tienen revival_status (nunca fueron procesadas por revival)
    - Tienen historial de mensajes
    - No están en estados críticos del sistema
    
    Returns:
        Lista de diccionarios con datos completos de conversaciones elegibles
    """
    try:
        if db is None:
            logger.error("❌ Firestore no disponible para get_conversations_for_revival")
            return []
        
        logger.info("🔍 Buscando conversaciones candidatas para revival...")
        
        # Query: conversaciones sin revival_status
        conversations_ref = db.collection(FIRESTORE_COLLECTION_NAME)
        
        # Filtrar documentos donde revival_status no existe o es null
        query = conversations_ref.where("state_context.revival_status", "==", None)
        
        # Obtener resultados
        docs = query.get()
        
        conversations = []
        processed_count = 0
        
        for doc in docs:
            try:
                doc_data = doc.to_dict()
                if not doc_data:
                    continue
                
                # Agregar phone_number desde doc.id
                phone_number = doc.id
                doc_data['phone_number'] = phone_number
                
                # Validaciones básicas de elegibilidad
                history = doc_data.get('history', [])
                state_context = doc_data.get('state_context', {})
                
                # Debe tener historial
                if not history or len(history) < 1:
                    continue
                
                # No debe estar ya procesado por revival
                if state_context.get('revival_status') is not None:
                    continue
                
                # Verificar que tenga al menos un mensaje del usuario
                has_user_message = any(
                    entry.get('role') == 'user' 
                    for entry in history
                )
                
                if not has_user_message:
                    continue
                
                conversations.append(doc_data)
                processed_count += 1
                
                # Limitar cantidad para evitar sobrecarga
                if processed_count >= 100:  # Máximo 100 conversaciones por ciclo
                    logger.info("📊 Limitando a 100 conversaciones por consulta")
                    break
                    
            except Exception as e:
                logger.error(f"❌ Error procesando documento {doc.id}: {e}")
                continue
        
        logger.info(f"📊 Encontradas {len(conversations)} conversaciones candidatas para revival")
        return conversations
        
    except Exception as e:
        logger.error(f"❌ Error obteniendo conversaciones para revival: {e}")
        return []