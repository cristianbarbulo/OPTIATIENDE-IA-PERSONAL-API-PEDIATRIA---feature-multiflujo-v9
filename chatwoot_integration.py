import requests
import json
import os
import logging
from datetime import datetime
import time

logger = logging.getLogger(__name__)

# ==== Formateo visual para destacar mensajes del bot en Chatwoot ====
# Chatwoot no interpreta Markdown en el listado de conversaciones.
# Para resaltar los mensajes del bot, convertimos el texto a "negrita"
# usando caracteres Unicode (Mathematical Bold) y agregamos un icono.

# Valores fijos (no configurables por variables de entorno)
BOT_ICON = '🤖'
BOT_LABEL = 'AGENTE OPTICONNECTA'
BOT_BOLD_ENABLED = True

def _to_unicode_bold(text: str) -> str:
    """Convierte letras y dígitos a su versión Mathematical Bold (Unicode).
    Seguro para texto plano; deja signos, espacios y emojis intactos.
    """
    if not BOT_BOLD_ENABLED or not isinstance(text, str) or not text:
        return text

    result_chars = []
    for ch in text:
        if 'A' <= ch <= 'Z':
            # Uppercase A-Z → U+1D400..U+1D419
            result_chars.append(chr(0x1D400 + (ord(ch) - ord('A'))))
        elif 'a' <= ch <= 'z':
            # Lowercase a-z → U+1D41A..U+1D433
            result_chars.append(chr(0x1D41A + (ord(ch) - ord('a'))))
        elif '0' <= ch <= '9':
            # Digits 0-9 → U+1D7CE..U+1D7D7
            result_chars.append(chr(0x1D7CE + (ord(ch) - ord('0'))))
        else:
            result_chars.append(ch)
    return ''.join(result_chars)

def _format_bot_message_for_chatwoot(original: str) -> str:
    """Aplica prefijo con icono y negrita Unicode al contenido del bot.
    Evita duplicar prefijos si ya existían.
    """
    if not isinstance(original, str):
        return original

    content = original.strip()

    # Limpiar posibles prefijos previos para no duplicar
    if content.startswith('🤖 Bot:'):
        content = content.split(':', 1)[1].strip()
    if content.startswith(BOT_ICON):
        content = content[len(BOT_ICON):].strip(" :")

    bold_label = _to_unicode_bold(BOT_LABEL)
    bold_text = _to_unicode_bold(content)

    return f"{BOT_ICON} {bold_label}: {bold_text}"

class ChatwootIntegration:
    def __init__(self):
        self.enabled = os.getenv('CHATWOOT_ENABLED', 'false').lower() == 'true'
        self.base_url = os.getenv('CHATWOOT_URL', 'https://cliente.optinexia.com')
        self.api_token = os.getenv('CHATWOOT_API_TOKEN', '')
        self.account_id = os.getenv('CHATWOOT_ACCOUNT_ID', '1')
        self.inbox_id = os.getenv('CHATWOOT_INBOX_ID', '2')
        
        # Cache para conversations
        self.conversation_cache = {}
        self.contact_cache = {}
        
        if self.enabled:
            logger.info(f"✅ Chatwoot integración activa")
            logger.info(f"   URL: {self.base_url}")
            logger.info(f"   Account ID: {self.account_id}")
            logger.info(f"   Inbox ID: {self.inbox_id}")
            logger.info(f"   Token presente: {'Sí' if self.api_token else 'No'}")

    def _make_request(self, method, endpoint, data=None, params=None):
        """Hacer peticiones a la API de Chatwoot"""
        endpoint = endpoint.lstrip('/')
        url = f"{self.base_url}/api/v1/accounts/{self.account_id}/{endpoint}"
        headers = {
            'Content-Type': 'application/json',
            'api_access_token': self.api_token
        }
        
        logger.debug(f"🔍 [CHATWOOT] {method} {url}")
        if data:
            logger.debug(f"🔍 [CHATWOOT] Data: {json.dumps(data, indent=2)}")

        try:
            response = requests.request(
                method, url, 
                headers=headers, 
                json=data, 
                params=params, 
                timeout=10
            )
            
            # Solo logear respuestas problemáticas o en modo debug
            if response.status_code >= 400:
                logger.warning(f"⚠️ [CHATWOOT] Response Status: {response.status_code}")
                logger.warning(f"⚠️ [CHATWOOT] Response Body: {response.text}")
            else:
                logger.debug(f"[CHATWOOT] Response Status: {response.status_code}")
            
            if response.status_code >= 400:
                logger.error(f"❌ [CHATWOOT] Error: {response.text}")
                return None
                
            return response.json() if response.text else {}
            
        except Exception as e:
            logger.error(f"❌ [CHATWOOT] Error en petición: {e}")
            return None

    def log_message_to_chatwoot(self, phone, message_content, message_type, sender_name="Usuario"):
        """Registrar mensaje en Chatwoot siguiendo EXACTAMENTE los 3 pasos"""
        if not self.enabled:
            return False

        try:
            phone_clean = phone.replace('+', '').replace(' ', '').replace('-', '')
            phone_e164 = f"+{phone_clean}" if not phone_clean.startswith('+') else phone_clean
            
            logger.debug(f"📱 Procesando mensaje para: {phone_e164}")
            
            # PASO 1: OBTENER O CREAR CONTACTO Y OBTENER SOURCE_ID
            contact_id, source_id = self._get_or_create_contact_with_source_id(phone_clean, phone_e164, sender_name)
            if not contact_id or not source_id:
                logger.error(f"❌ PASO 1 FALLÓ: No se pudo obtener contact_id o source_id para {phone}")
                return False
            
            logger.debug(f"✅ PASO 1 COMPLETO: Contact ID: {contact_id}, Source ID: {source_id}")
            
            # PASO 2: OBTENER O CREAR CONVERSACIÓN
            conversation_id = self._get_or_create_conversation_with_source_id(contact_id, source_id)
            if not conversation_id:
                logger.error(f"❌ PASO 2 FALLÓ: No se pudo crear conversación para {phone}")
                return False
            
            logger.debug(f"✅ PASO 2 COMPLETO: Conversation ID: {conversation_id}")
            
            # PASO 3: ENVIAR MENSAJE
            # IMPORTANTE: Todos los mensajes van como "incoming"
            if message_type == 'outgoing':
                # Formatear SIEMPRE los mensajes del bot para destacarlos en la UI
                message_content = _format_bot_message_for_chatwoot(message_content)
            
            message_data = {
                'content': message_content,
                'message_type': 'incoming',  # SIEMPRE incoming según la documentación
                'private': False
            }
            
            message_response = self._make_request(
                'POST', 
                f'conversations/{conversation_id}/messages', 
                message_data
            )
            
            if message_response:
                # Solo logear el resultado final exitoso como un único mensaje INFO
                logger.info(f"✅ [CHATWOOT] Mensaje {'del bot' if message_type == 'outgoing' else 'del usuario'} registrado exitosamente")
                return True
            else:
                logger.error(f"❌ PASO 3 FALLÓ: Error enviando mensaje a Chatwoot")
                return False

        except Exception as e:
            logger.error(f"❌ Error en log_message_to_chatwoot: {e}", exc_info=True)
            return False

    def _get_or_create_contact_with_source_id(self, phone_clean, phone_e164, sender_name):
        """PASO 1: Obtener o crear contacto con inbox_id y obtener source_id"""
        # Verificar cache primero
        if phone_clean in self.contact_cache:
            cached = self.contact_cache[phone_clean]
            logger.debug(f"📋 Usando contacto desde cache: ID {cached['contact_id']}")
            return cached['contact_id'], cached['source_id']
        
        # PRIMERO: Buscar si el contacto ya existe
        logger.debug(f"🔍 PASO 1A: Buscando contacto existente para {phone_clean}")
        search_response = self._make_request('GET', 'contacts/search', params={'q': phone_clean})
        
        contact_id = None
        source_id = None
        
        if search_response and search_response.get('payload'):
            for contact in search_response['payload']:
                # Verificar si el número coincide
                contact_phone = contact.get('phone_number', '').replace('+', '')
                if contact_phone == phone_clean:
                    contact_id = contact['id']
                    logger.debug(f"✅ Contacto existente encontrado: ID {contact_id}")
                    
                    # Buscar source_id en contact_inboxes
                    for ci in contact.get('contact_inboxes', []):
                        if str(ci.get('inbox', {}).get('id')) == str(self.inbox_id):
                            source_id = ci.get('source_id')
                            logger.debug(f"✅ Source ID encontrado: {source_id}")
                            break
                    
                    if source_id:
                        # Guardar en cache y retornar
                        self.contact_cache[phone_clean] = {
                            'contact_id': contact_id,
                            'source_id': source_id
                        }
                        return contact_id, source_id
                    else:
                        logger.warning(f"⚠️ Contacto existe pero sin source_id para inbox {self.inbox_id}")
                    break
        
        # SEGUNDO: Si no existe o no tiene source_id, crear contacto nuevo
        logger.debug(f"📝 PASO 1B: Creando nuevo contacto para {phone_e164}")
        
        contact_data = {
            'name': sender_name,
            'phone_number': phone_e164,
            'inbox_id': int(self.inbox_id)  # CRÍTICO: DEBE incluir inbox_id
        }
        
        create_response = self._make_request('POST', 'contacts', contact_data)
        
        if not create_response or not create_response.get('payload'):
            logger.error(f"❌ Error creando contacto: No hay payload en la respuesta")
            return None, None
        
        # EXTRAER contact_id
        contact_id = create_response['payload']['contact']['id']
        
        # EXTRAER source_id - Buscar en múltiples lugares según la documentación
        source_id = None
        
        # Opción 1: contact_inbox directo
        if create_response['payload'].get('contact_inbox'):
            source_id = create_response['payload']['contact_inbox'].get('source_id')
            logger.debug(f"✅ Source ID encontrado en contact_inbox: {source_id}")
        
        # Opción 2: contact_inboxes array
        elif create_response['payload']['contact'].get('contact_inboxes'):
            for inbox in create_response['payload']['contact']['contact_inboxes']:
                if inbox.get('source_id'):
                    source_id = inbox['source_id']
                    logger.debug(f"✅ Source ID encontrado en contact_inboxes: {source_id}")
                    break
        
        if not source_id:
            logger.error(f"❌ No se pudo encontrar source_id en la respuesta")
            logger.error(f"❌ Respuesta completa: {json.dumps(create_response, indent=2)}")
            return None, None
        
        # Guardar en cache
        self.contact_cache[phone_clean] = {
            'contact_id': contact_id,
            'source_id': source_id
        }
        
        logger.debug(f"✅ Contacto creado exitosamente: ID {contact_id}, Source ID: {source_id}")
        return contact_id, source_id

    def _get_or_create_conversation_with_source_id(self, contact_id, source_id):
        """PASO 2: Obtener conversación existente o crear nueva usando source_id"""
        # Verificar cache
        cache_key = f"{contact_id}_{source_id}"
        if cache_key in self.conversation_cache:
            conversation_id = self.conversation_cache[cache_key]
            logger.debug(f"📋 Usando conversación desde cache: ID {conversation_id}")
            return conversation_id
        
        # PRIMERO: Buscar conversación existente ABIERTA para este contacto
        logger.debug(f"🔍 PASO 2A: Buscando conversación existente para Contact ID: {contact_id}")
        
        # Buscar conversaciones del contacto
        search_params = {
            'status': 'open',
            'assignee_type': 'all'
        }
        
        conversations_response = self._make_request('GET', 'conversations', params=search_params)
        
        if conversations_response and conversations_response.get('data', {}).get('payload'):
            for conv in conversations_response['data']['payload']:
                # Verificar si la conversación es del mismo contacto
                conv_meta = conv.get('meta', {})
                conv_sender = conv_meta.get('sender', {})
                
                if conv_sender.get('id') == contact_id:
                    conversation_id = conv['id']
                    logger.debug(f"✅ Conversación existente encontrada: ID {conversation_id}")
                    
                    # Guardar en cache
                    self.conversation_cache[cache_key] = conversation_id
                    return conversation_id
        
        # SEGUNDO: Si no hay conversación abierta, buscar la más reciente cerrada
        logger.debug(f"🔍 PASO 2B: Buscando conversación cerrada reciente...")
        search_params['status'] = 'resolved'
        
        resolved_response = self._make_request('GET', 'conversations', params=search_params)
        
        most_recent_conv_id = None
        most_recent_time = None
        
        if resolved_response and resolved_response.get('data', {}).get('payload'):
            for conv in resolved_response['data']['payload']:
                conv_meta = conv.get('meta', {})
                conv_sender = conv_meta.get('sender', {})
                
                if conv_sender.get('id') == contact_id:
                    # Obtener la más reciente
                    conv_time = conv.get('created_at', 0)
                    if most_recent_time is None or conv_time > most_recent_time:
                        most_recent_time = conv_time
                        most_recent_conv_id = conv['id']
        
        # Si encontramos una conversación cerrada reciente, reabrirla
        if most_recent_conv_id:
            logger.debug(f"📂 Reabriendo conversación cerrada: ID {most_recent_conv_id}")
            
            reopen_data = {'status': 'open'}
            reopen_response = self._make_request(
                'POST', 
                f'conversations/{most_recent_conv_id}/toggle_status', 
                reopen_data
            )
            
            if reopen_response:
                # Guardar en cache
                self.conversation_cache[cache_key] = most_recent_conv_id
                return most_recent_conv_id
        
        # TERCERO: Si no hay ninguna conversación, crear nueva
        logger.debug(f"📝 PASO 2C: Creando nueva conversación para Contact ID: {contact_id}")
        
        conv_data = {
            'source_id': source_id,      # CRÍTICO: Del paso anterior
            'inbox_id': int(self.inbox_id),
            'contact_id': contact_id,    # NOTA: Con guión bajo aquí
            'status': 'open'
        }
        
        conv_response = self._make_request('POST', 'conversations', conv_data)
        
        if not conv_response:
            logger.error(f"❌ Error: No hay respuesta al crear conversación")
            return None
        
        if not conv_response.get('id'):
            logger.error(f"❌ Error: No se encontró ID en la respuesta")
            logger.error(f"❌ Respuesta completa: {json.dumps(conv_response, indent=2)}")
            return None
        
        conversation_id = conv_response['id']
        
        # Guardar en cache
        self.conversation_cache[cache_key] = conversation_id
        
        logger.debug(f"✅ Nueva conversación creada: ID {conversation_id}")
        return conversation_id

# Instancia global
chatwoot = ChatwootIntegration()

def log_to_chatwoot(phone, user_message, bot_response, sender_name="Usuario"):
    """
    Función helper para registrar conversación completa en Chatwoot.
    Sigue EXACTAMENTE los 3 pasos de la documentación.
    """
    if not chatwoot.enabled:
        return False

    success = True

    try:
        # Limpiar cache si crece mucho
        if len(chatwoot.conversation_cache) > 100:
            logger.debug("🧹 Limpiando cache...")
            chatwoot.conversation_cache.clear()
            chatwoot.contact_cache.clear()
        
        # Registrar mensaje del usuario
        if user_message:
            logger.debug(f"📨 Registrando mensaje del usuario: {user_message[:50]}...")
            user_success = chatwoot.log_message_to_chatwoot(
                phone, 
                user_message, 
                'incoming',  # Mensaje del cliente
                sender_name
            )
            success = success and user_success
            
            if not user_success:
                logger.error("❌ Falló el registro del mensaje del usuario")
                return False
            
            # Pequeña pausa entre mensajes para evitar race conditions
            time.sleep(0.5)
            
        # Registrar respuesta del bot
        if bot_response and success:
            logger.debug(f"🤖 Registrando respuesta del bot: {bot_response[:50]}...")
            bot_success = chatwoot.log_message_to_chatwoot(
                phone, 
                bot_response, 
                'outgoing',  # Se convertirá a incoming con prefijo "🤖 Bot:"
                "OPTI BOT"
            )
            success = success and bot_success
            
            if not bot_success:
                logger.error("❌ Falló el registro de la respuesta del bot")
        
        return success
        
    except Exception as e:
        logger.error(f"❌ Error en log_to_chatwoot: {e}", exc_info=True)
        return False

# Función de prueba
def test_chatwoot_connection():
    """Función para probar la conexión con Chatwoot"""
    if not chatwoot.enabled:
        return "❌ Chatwoot no está habilitado"
    
    try:
        # Test 1: Probar conexión básica
        logger.info("🧪 Test 1: Probando conexión...")
        test_result = chatwoot._make_request('GET', 'conversations', params={'per_page': 1})
        if test_result is None:
            return "❌ Error: No se puede conectar con Chatwoot"
        
        # Test 2: Crear un contacto de prueba
        logger.info("🧪 Test 2: Creando contacto de prueba...")
        test_phone = f"+549341316{str(int(time.time()))[-4:]}"  # Número único
        contact_id, source_id = chatwoot._get_or_create_contact_with_source_id(
            test_phone.replace('+', ''), 
            test_phone, 
            "Test Usuario"
        )
        
        if not contact_id or not source_id:
            return "❌ Error: No se pudo crear contacto de prueba"
        
        logger.info(f"✅ Contacto de prueba creado: ID {contact_id}, Source ID {source_id}")
        
        # Test 3: Crear conversación
        logger.info("🧪 Test 3: Creando conversación de prueba...")
        conversation_id = chatwoot._get_or_create_conversation_with_source_id(contact_id, source_id)
        
        if not conversation_id:
            return "❌ Error: No se pudo crear conversación de prueba"
        
        logger.info(f"✅ Conversación de prueba creada: ID {conversation_id}")
        
        return f"✅ Conexión exitosa - Contact: {contact_id}, Conversation: {conversation_id}"
        
    except Exception as e:
        return f"❌ Error en test: {str(e)}"

# Función para debug
def debug_chatwoot_flow(phone_number):
    """Función para debuggear el flujo completo paso a paso"""
    logger.info("🔍 === INICIANDO DEBUG DE FLUJO CHATWOOT ===")
    
    if not chatwoot.enabled:
        logger.error("❌ Chatwoot no está habilitado")
        return
    
    phone_clean = phone_number.replace('+', '').replace(' ', '').replace('-', '')
    phone_e164 = f"+{phone_clean}" if not phone_clean.startswith('+') else phone_clean
    
    logger.info(f"📱 Teléfono limpio: {phone_clean}")
    logger.info(f"📱 Teléfono E.164: {phone_e164}")
    
    # PASO 1
    logger.info("🔵 PASO 1: Creando contacto...")
    contact_id, source_id = chatwoot._get_or_create_contact_with_source_id(
        phone_clean, phone_e164, "Debug Usuario"
    )
    
    if not contact_id or not source_id:
        logger.error("❌ PASO 1 FALLÓ")
        return
    
    logger.info(f"✅ PASO 1 EXITOSO: Contact ID: {contact_id}, Source ID: {source_id}")
    
    # PASO 2
    logger.info("🔵 PASO 2: Creando conversación...")
    conversation_id = chatwoot._get_or_create_conversation_with_source_id(contact_id, source_id)
    
    if not conversation_id:
        logger.error("❌ PASO 2 FALLÓ")
        return
    
    logger.info(f"✅ PASO 2 EXITOSO: Conversation ID: {conversation_id}")
    
    # PASO 3
    logger.info("🔵 PASO 3: Enviando mensaje de prueba...")
    message_data = {
        'content': "🧪 Mensaje de prueba - Debug flow",
        'message_type': 'incoming',
        'private': False
    }
    
    message_response = chatwoot._make_request(
        'POST', 
        f'conversations/{conversation_id}/messages', 
        message_data
    )
    
    if message_response:
        logger.info("✅ PASO 3 EXITOSO: Mensaje enviado")
        logger.info("✨ FLUJO COMPLETO EXITOSO!")
    else:
        logger.error("❌ PASO 3 FALLÓ")