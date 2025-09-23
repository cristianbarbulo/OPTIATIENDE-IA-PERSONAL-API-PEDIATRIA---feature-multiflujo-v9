import logging
import config
import msgio_handler

logger = logging.getLogger("notificaciones")

def notificar_equipo_humano(author, history):
    """Notifica al equipo humano que se ha escalado un caso y registra el historial."""
    # Aquí podrías enviar un email, webhook, mensaje a Slack, etc.
    logger.info(f"[ESCALAMIENTO] Caso escalado a humano para {author}. Historial: {history[-5:]}")
    # Simulación de notificación
    return True

def escalar_a_humano(phone_number, user_message, reason):
    """
    NUEVO: Función para escalar conversaciones a agentes humanos.
    """
    logger.info(f"[ESCALAR_HUMANO] Escalamiento a humano para {phone_number}. Razón: {reason}. Último mensaje: {user_message[:200]}...")

    # Ejemplo de notificación a un canal/grupo de agentes. Adapta esto a tu sistema.
    # Asume que config.HUMAN_AGENT_GROUP_ID existe y es el chat ID del grupo o agente.
    # Y que msgio_handler puede enviar a ese ID.
    try:
        escalation_message = (
            f"🚨 **URGENTE: Conversación escalada a humano**\n\n"
            f"📞 Cliente: {phone_number}\n"
            f"🗣️ Motivo: {reason}\n"
            f"💬 Último mensaje del cliente: '{user_message}'\n\n"
            f"Por favor, revisen el historial de conversación."
        )
        # Aquí puedes usar msgio_handler para enviar al grupo de agentes o a un CRM
        # msgio_handler.send_whatsapp_message(
        #     phone_number=config.HUMAN_AGENT_GROUP_ID, # O algún otro número/ID para el agente
        #     message=escalation_message
        # )
        logger.info(f"[ESCALAR_HUMANO] Notificación de escalamiento enviada para {phone_number}.")
    except Exception as e:
        logger.error(f"[ESCALAR_HUMANO] Fallo al enviar notificación de escalamiento para {phone_number}: {e}") 