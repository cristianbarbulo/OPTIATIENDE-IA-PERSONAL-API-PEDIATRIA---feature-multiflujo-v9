"""
Sistema de notificaciones WhatsApp para OPTIATIENDE-IA
Envía notificaciones automáticas de pagos y turnos programados
"""

import logging
import config
import msgio_handler
import utils
from datetime import datetime
import requests

logger = logging.getLogger(config.TENANT_NAME)

def _enviar_notificacion_directa(phone_number: str, mensaje: str) -> bool:
    """
    Envía notificación directamente por 360dialog SIN pasar por Chatwoot.
    CRÍTICO: Esta función evita que las notificaciones se registren como conversaciones en CRM.
    """
    try:
        # Usar directamente la API de 360dialog para evitar interceptación de Chatwoot
        headers = {
            'D360-API-Key': config.D360_API_KEY,
            'Content-Type': 'application/json'
        }
        
        # Limpiar número de teléfono
        clean_phone = phone_number.strip()
        if clean_phone.startswith('+'):
            clean_phone = clean_phone[1:]
        if clean_phone.endswith('@c.us'):
            clean_phone = clean_phone.replace('@c.us', '')
        
        payload = {
            "messaging_product": "whatsapp",
            "to": clean_phone,
            "type": "text",
            "text": {
                "body": mensaje
            }
        }
        
        response = requests.post(
            f"{config.D360_BASE_URL}/messages",
            headers=headers,
            json=payload,
            timeout=30
        )
        
        if response.status_code == 200:
            logger.info(f"[NOTIF_DIRECT] ✅ Notificación directa enviada a {phone_number}")
            return True
        else:
            logger.error(f"[NOTIF_DIRECT] ❌ Error {response.status_code}: {response.text}")
            return False
            
    except Exception as e:
        logger.error(f"[NOTIF_DIRECT] ❌ Error enviando notificación directa: {e}")
        return False

def obtener_servicio_desde_contexto(state_context: dict) -> str:
    """
    Extrae el nombre del servicio desde el contexto con máxima robustez.
    Prioridades: servicio_seleccionado_id -> servicio_pagado -> fallback
    """
    try:
        # Prioridad 1: servicio_seleccionado_id (usar catálogo)
        service_id = state_context.get('servicio_seleccionado_id')
        if service_id:
            servicio = utils.get_service_by_id(service_id)
            if servicio:
                return servicio.get('nombre', 'Servicio no especificado')
        
        # Prioridad 2: servicio_pagado (directo)
        servicio_pagado = state_context.get('servicio_pagado')
        if servicio_pagado:
            return servicio_pagado
        
        # Prioridad 3: plan (fallback)
        plan = state_context.get('plan')
        if plan:
            return plan
        
        # Fallback final
        return "Servicio no especificado"
        
    except Exception as e:
        logger.error(f"[NOTIF] Error extrayendo servicio: {e}")
        return "Servicio no especificado"

def obtener_nombre_cliente(state_context: dict, author: str) -> str:
    """
    Extrae el nombre del cliente con máxima robustez.
    Prioridades: senderName -> perfil WhatsApp -> fallback
    """
    try:
        # Prioridad 1: senderName del contexto
        sender_name = state_context.get('senderName')
        if sender_name and sender_name.strip():
            return sender_name.strip()
        
        # Prioridad 2: contact_info si existe
        contact_info = state_context.get('contact_info', {})
        if isinstance(contact_info, dict):
            nombre = contact_info.get('nombre') or contact_info.get('name')
            if nombre and nombre.strip():
                return nombre.strip()
        
        # Fallback: usar el número de teléfono
        if author:
            return f"Cliente {author[-4:]}"  # Últimos 4 dígitos
        
        return "Cliente"
        
    except Exception as e:
        logger.error(f"[NOTIF] Error extrayendo nombre: {e}")
        return "Cliente"

def enviar_notificacion_pago_exitoso(datos_pago: dict) -> bool:
    """
    Envía notificación de pago exitoso al contacto configurado.
    
    Args:
        datos_pago: Dict con servicio, monto, nombre, telefono, fecha_pago
    
    Returns:
        bool: True si se envió correctamente, False en caso contrario
    """
    try:
        # Verificar que esté configurado el contacto de notificaciones
        if not hasattr(config, 'NOTIFICATION_CONTACT') or not config.NOTIFICATION_CONTACT:
            logger.info("[NOTIF] NOTIFICATION_CONTACT no configurado. Notificación de pago no enviada.")
            return False
        
        # Construir mensaje de notificación
        servicio = datos_pago.get('servicio', 'Servicio no especificado')
        monto = datos_pago.get('monto', '0')
        nombre = datos_pago.get('nombre', 'Cliente')
        telefono = datos_pago.get('telefono', 'No especificado')
        fecha_pago = datos_pago.get('fecha_pago', datetime.now().strftime('%d/%m/%Y %H:%M'))
        
        mensaje = f"""🎉 PAGO EXITOSO:

💰 Servicio: {servicio}
💵 Monto: ${monto}
👤 Cliente: {nombre}
📱 Teléfono: {telefono}

⏰ AÚN NO AGENDÓ SU TURNO

Hora: {fecha_pago}"""

        # CORRECCIÓN CRÍTICA: Enviar notificación SIN pasar por Chatwoot
        # Usar función directa que evita registro en CRM
        success = _enviar_notificacion_directa(config.NOTIFICATION_CONTACT, mensaje)
        
        if success:
            logger.info(f"[NOTIF] ✅ Notificación de pago enviada exitosamente para {telefono}")
        else:
            logger.error(f"[NOTIF] ❌ Error enviando notificación de pago para {telefono}")
        
        return success
        
    except Exception as e:
        logger.error(f"[NOTIF] Error crítico enviando notificación de pago: {e}")
        return False

def enviar_notificacion_turno_programado(datos_turno: dict) -> bool:
    """
    Envía notificación de turno programado al contacto configurado.
    
    Args:
        datos_turno: Dict con telefono, nombre, fecha_turno, evento_id
    
    Returns:
        bool: True si se envió correctamente, False en caso contrario
    """
    try:
        # Verificar que esté configurado el contacto de notificaciones
        if not hasattr(config, 'NOTIFICATION_CONTACT') or not config.NOTIFICATION_CONTACT:
            logger.info("[NOTIF] NOTIFICATION_CONTACT no configurado. Notificación de turno no enviada.")
            return False
        
        # Construir mensaje de notificación
        telefono = datos_turno.get('telefono', 'No especificado')
        nombre = datos_turno.get('nombre', 'Cliente')
        fecha_turno = datos_turno.get('fecha_turno', 'No especificada')
        evento_id = datos_turno.get('evento_id', 'N/A')
        fecha_envio = datetime.now().strftime('%d/%m/%Y %H:%M')
        
        mensaje = f"""📅 TURNO PROGRAMADO:

📱 Teléfono: {telefono}
👤 Cliente: {nombre}
🗓️ Fecha y horario: {fecha_turno}

✅ Confirmado en calendario
🆔 ID evento: {evento_id}

Hora: {fecha_envio}"""

        # CORRECCIÓN CRÍTICA: Enviar notificación SIN pasar por Chatwoot
        # Usar función directa que evita registro en CRM
        success = _enviar_notificacion_directa(config.NOTIFICATION_CONTACT, mensaje)
        
        if success:
            logger.info(f"[NOTIF] ✅ Notificación de turno enviada exitosamente para {telefono}")
        else:
            logger.error(f"[NOTIF] ❌ Error enviando notificación de turno para {telefono}")
        
        return success
        
    except Exception as e:
        logger.error(f"[NOTIF] Error crítico enviando notificación de turno: {e}")
        return False
