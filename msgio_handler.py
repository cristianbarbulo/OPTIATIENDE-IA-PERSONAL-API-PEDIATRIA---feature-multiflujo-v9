# msgio_handler.py (Adaptado para 360dialog)

import requests
import logging
import json
from config import D360_API_KEY, D360_WHATSAPP_PHONE_ID, D360_BASE_URL

# Configuración del logger
logger = logging.getLogger(__name__)

def get_360dialog_api_url():
    """
    Obtiene la URL correcta para enviar mensajes a través de 360dialog.
    CORRECCIÓN: Para 360dialog, la URL debe ser /messages directamente.
    """
    return f"{D360_BASE_URL}/messages"

def send_whatsapp_message(phone_number: str, message: str = None, interactive_payload: dict = None, buttons: list = None, list_title: str = None, options: list = None, section_title: str = "Opciones") -> bool:
    """
    FUNCIÓN UNIFICADA: Envía mensajes de texto, botones o listas usando la API de 360dialog.
    ADAPTADO: Usa el formato de payload estándar de Meta/WhatsApp Business API.
    
    Args:
        phone_number: Número de teléfono del destinatario
        message: Mensaje principal (para texto o interactivos)
        interactive_payload: Payload interactivo completo (para re-envío)
        buttons: Lista de botones [{"id": "btn_id", "title": "Texto del botón"}] (máximo 3)
        list_title: Título de la lista (máximo 24 caracteres)
        options: Lista de opciones [{"id": "opt_id", "title": "Texto", "description": "Descripción"}]
        section_title: Título de la sección de la lista (máximo 24 caracteres)
    
    Returns:
        bool: True si se envió correctamente, False en caso contrario
    """
    logger.info(f"[D360] === INICIO send_whatsapp_message UNIFICADA ===")
    logger.info(f"[D360] 📱 Número de teléfono: {phone_number}")
    logger.info(f"[D360] 📝 Mensaje: {message[:100] if message else 'None'}...")
    logger.info(f"[D360] 🔘 Botones: {buttons}")
    logger.info(f"[D360] 📋 Lista: {list_title} - {len(options) if options else 0} opciones")
    logger.info(f"[D360] 🔄 Interactive payload: {'SÍ' if interactive_payload else 'NO'}")

    # Validación de parámetros
    if not phone_number:
        logger.error(f"[D360] ❌ ERROR: Número de teléfono vacío")
        return False
    
    if not D360_API_KEY:
        logger.error(f"[D360] ❌ ERROR: D360_API_KEY no configurado")
        return False
    
    if not D360_WHATSAPP_PHONE_ID:
        logger.error(f"[D360] ❌ ERROR: D360_WHATSAPP_PHONE_ID no configurado")
        return False

    # Limpiar y formatear número de teléfono
    clean_phone = phone_number.strip()
    if clean_phone.startswith('+'):
        clean_phone = clean_phone[1:]  # Remover el + si existe
    if clean_phone.endswith('@c.us'):
        clean_phone = clean_phone.replace('@c.us', '')  # Remover sufijo de WhatsApp
    
    logger.info(f"[D360] 📱 Número limpio: {clean_phone}")

    # Headers para autenticación con 360dialog (SOLO D360-API-Key)
    headers = {
        'D360-API-Key': D360_API_KEY,
        'Content-Type': 'application/json'
    }
    
    # Log adicional para depuración del header
    logger.info(f"[D360] 🔑 API Key (primeros 10 chars): {D360_API_KEY[:10] if D360_API_KEY else 'VACÍA'}...")
    # logger.info(f"[D360] 🔑 API Key completa: {D360_API_KEY}") # REMOVED FOR SECURITY REASONS IN PRODUCTION

    # Decodificar secuencias visibles si quedaran escapadas desde capas anteriores
    if isinstance(message, str) and message:
        try:
            message = message.replace('\\n', '\n').replace('\\t', '\t')
        except Exception:
            pass

    # DETERMINAR TIPO DE MENSAJE Y CONSTRUIR PAYLOAD
    if interactive_payload:
        # CASO 1: Re-envío de payload interactivo (para "forzar interacción")
        logger.info(f"[D360] 🔄 Re-enviando payload interactivo existente")
        
        # CORRECCIÓN: Si el interactive_payload ya tiene estructura completa, usarlo tal como está
        if 'messaging_product' in interactive_payload:
            payload = interactive_payload.copy()
            payload["to"] = clean_phone  # Asegurar que el destinatario sea correcto
        else:
            # Si solo tiene la parte interactive, construir el payload completo
            payload = {
                "messaging_product": "whatsapp",
                "to": clean_phone,
                "type": "interactive",
                "interactive": interactive_payload
            }
        
    elif buttons:
        # CASO 2: Mensaje con botones
        logger.info(f"[D360] 🔘 Enviando mensaje con botones")
        
        # Validar límites de caracteres
        if message and len(message) > 1024:
            logger.error(f"[D360] ❌ ERROR: Mensaje demasiado largo ({len(message)} > 1024)")
            return False
        
        if len(buttons) > 3:
            logger.error(f"[D360] ❌ ERROR: Demasiados botones ({len(buttons)} > 3)")
            return False
        
        for button in buttons:
            if len(button.get('title', '')) > 20:
                logger.error(f"[D360] ❌ ERROR: Título de botón demasiado largo: {button.get('title', '')}")
                return False
        
        # Estructura JSON correcta para botones
        payload = {
            "messaging_product": "whatsapp",
            "to": clean_phone,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {
                    "text": message or "Selecciona una opción:"
                },
                "action": {
                    "buttons": []
                }
            }
        }
        
        # Agregar botones con la estructura correcta
        for button in buttons:
            payload["interactive"]["action"]["buttons"].append({
                "type": "reply",
                "reply": {
                    "id": button.get('id', ''),
                    "title": button.get('title', '')
                }
            })
            
    elif options and list_title:
        # CASO 3: Mensaje con lista
        logger.info(f"[D360] 📋 Enviando mensaje con lista")
        
        # Validar límites de caracteres
        if message and len(message) > 1024:
            logger.error(f"[D360] ❌ ERROR: Mensaje demasiado largo ({len(message)} > 1024)")
            return False
        
        if len(list_title) > 24:
            logger.error(f"[D360] ❌ ERROR: Título de lista demasiado largo ({len(list_title)} > 24)")
            return False
        if len(section_title) > 24:
            logger.error(f"[D360] ❌ ERROR: Título de sección demasiado largo ({len(section_title)} > 24)")
            return False
        
        for option in options:
            if len(option.get('title', '')) > 24:
                logger.error(f"[D360] ❌ ERROR: Título de opción demasiado largo: {option.get('title', '')}")
                return False
            if 'description' in option and len(option.get('description', '')) > 72:
                logger.error(f"[D360] ❌ ERROR: Descripción de opción demasiado larga: {option.get('description', '')}")
                return False
        
        # Estructura JSON correcta para lista
        payload = {
            "messaging_product": "whatsapp",
            "to": clean_phone,
            "type": "interactive",
            "interactive": {
                "type": "list",
                "header": {
                    "type": "text",
                    "text": "Elige una opción"  # Máximo 60 caracteres
                },
                "body": {
                    "text": message or "Selecciona el servicio que te interesa:"
                },
                "footer": {
                    "text": "Tu Asistente Virtual"  # Texto pequeño al final
                },
                "action": {
                    "button": list_title,  # Máximo 20 caracteres
                    "sections": [
                        {
                            "title": section_title,  # Máximo 24 caracteres
                            "rows": []
                        }
                    ]
                }
            }
        }
        
        # Agregar opciones con la estructura correcta
        for option in options:
            row = {
                "id": option.get('id', ''),
                "title": option.get('title', '')
            }
            if 'description' in option:
                row["description"] = option.get('description', '')
            payload["interactive"]["action"]["sections"][0]["rows"].append(row)
            
    else:
        # CASO 4: Mensaje de texto simple
        logger.info(f"[D360] 📝 Enviando mensaje de texto simple")
        
        if not message:
            logger.error(f"[D360] ❌ ERROR: Mensaje vacío")
            return False
        
        # Payload estándar de WhatsApp Business API para texto
        payload = {
            "messaging_product": "whatsapp",
            "to": clean_phone,
            "type": "text",
            "text": {
                "body": message
            }
        }

    logger.info(f"[D360] 🔗 Payload final: {json.dumps(payload, indent=2)}")

    try:
        # ENVIAR MENSAJE USANDO D360-API-Key (método único y correcto)
        logger.info(f"[D360] 🌐 Enviando petición POST con D360-API-Key a {get_360dialog_api_url()}")
        response = requests.post(
            get_360dialog_api_url(), 
            headers=headers, 
            json=payload, 
            timeout=30
        )
        
        logger.info(f"[D360] 📡 Respuesta del servidor:")
        logger.info(f"[D360]   Status Code: {response.status_code}")
        logger.info(f"[D360]   Content: {response.text}")
        
        # Verificar respuesta
        if response.status_code == 200:
            response_data = response.json()
            if 'messages' in response_data:
                message_id = response_data['messages'][0].get('id', 'N/A')
                logger.info(f"[D360] ✅ Mensaje enviado exitosamente!")
                logger.info(f"[D360] 🆔 Message ID: {message_id}")
                
                # Log específico según el tipo de mensaje
                if buttons:
                    logger.info(f"[D360] ✅ Mensaje con botones enviado con éxito")
                elif options:
                    logger.info(f"[D360] ✅ Mensaje con lista enviado con éxito")
                elif interactive_payload:
                    logger.info(f"[D360] ✅ Payload interactivo re-enviado con éxito")
                else:
                    logger.info(f"[D360] ✅ Mensaje de texto enviado con éxito")
                
                return True
            else:
                logger.error(f"[D360] ❌ ERROR: Respuesta exitosa pero sin 'messages' en el JSON")
                logger.error(f"[D360] 📄 Respuesta completa: {response_data}")
                return False
        else:
            logger.error(f"[D360] ❌ ERROR: Fallo al enviar mensaje")
            logger.error(f"[D360] 📄 Status Code: {response.status_code}")
            logger.error(f"[D360] 📄 Respuesta: {response.text}")
            return False
            
    except requests.exceptions.Timeout:
        logger.error(f"[D360] ❌ ERROR: Timeout al enviar mensaje")
        return False
    except requests.exceptions.RequestException as e:
        logger.error(f"[D360] ❌ ERROR: Error de red al enviar mensaje: {e}")
        return False
    except Exception as e:
        logger.error(f"[D360] ❌ ERROR: Error inesperado al enviar mensaje: {e}")
        return False
