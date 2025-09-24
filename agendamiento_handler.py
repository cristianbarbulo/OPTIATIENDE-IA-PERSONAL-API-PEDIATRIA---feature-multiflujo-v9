"""Delegates scheduling actions to the configured calendar service."""
import logging
from datetime import datetime, timedelta
import pytz
import config
from service_factory import get_calendar_service
import llm_handler
# ELIMINADO: from llm_handler import llamar_rodi_generador (ya no se usa)
import utils
from utils import format_fecha_espanol, parsear_fecha_hora_natural, limpiar_contexto_agendamiento_unificado
import memory
import copy
import re
import msgio_handler
import locale

# Configurar logger PRIMERO para evitar NameError
logger = logging.getLogger(config.TENANT_NAME)

# Configurar locale para español (manejo simplificado para entornos como Render)
try:
    locale.setlocale(locale.LC_TIME, 'es_ES.utf8')  # Para Linux/macOS
except locale.Error:
    try:
        locale.setlocale(locale.LC_TIME, 'es_ES')  # Para Windows
    except locale.Error:
        try:
            locale.setlocale(locale.LC_TIME, 'Spanish_Spain.1252')  # Para Windows alternativo
        except locale.Error:
            # NUEVA MEJORA: Manejo silencioso del locale para evitar errores en entornos como Render
            logger.info("Locale español no disponible, usando configuración por defecto del sistema")
            # No intentar configurar locale si no está disponible

TIMEZONE = pytz.timezone('America/Argentina/Buenos_Aires')
APPOINTMENT_DURATION_MINUTES = 60

def iniciar_triage_agendamiento(history, detalles, state_context=None, mensaje_completo_usuario=None, author=None):
    """
    NUEVO: Función para iniciar el flujo de agendamiento con triage inteligente.
    CORRECCIÓN CRÍTICA: Preservar información extraída por la IA sin limpiarla.
    MEJORA CRÍTICA: Siempre mostrar lista de turnos directamente.
    """
    logger.info(f"[TRIAGE_AGENDA] Iniciando triage de agendamiento para usuario")
    
    # Asegurar que tenemos el contexto necesario
    if not state_context:
        state_context = {}
    
    # NUEVO: Marcar información de restricción de pago para el generador
    # NOTA: Verificación de restricciones ahora se maneja centralizadamente en main.py
    
    # Usar el parámetro author explícito si está disponible
    if not author:
        author = state_context.get('author') or detalles.get('author')
    
    if not author:
        return "Error interno. No se pudo identificar al usuario.", state_context
    
    # CORRECCIÓN CRÍTICA: Extraer y preservar información de la IA ANTES de cualquier limpieza
    fecha_deseada = None
    hora_especifica = None
    preferencia_horaria = None
    restricciones_temporales = None
    dia_semana_interes = None
    
    # Extraer información de fecha/hora de los detalles si está disponible
    if isinstance(detalles, dict):
        fecha_deseada = detalles.get('fecha_deseada')
        hora_especifica = detalles.get('hora_especifica')
        preferencia_horaria = detalles.get('preferencia_horaria')
        restricciones_temporales = detalles.get('restricciones_temporales')
        dia_semana_interes = detalles.get('dia_semana')
        
        if isinstance(fecha_deseada, datetime):
            fecha_deseada = fecha_deseada.strftime('%Y-%m-%d')
        if isinstance(hora_especifica, datetime):
            hora_especifica = hora_especifica.strftime('%H:%M')
        logger.info(f"[TRIAGE_AGENDA] Información extraída de detalles - fecha: {fecha_deseada}, hora: {hora_especifica}, preferencia: {preferencia_horaria}")
    
    # CORRECCIÓN CRÍTICA: NO limpiar el contexto agresivamente, solo preservar información esencial
    # Mantener author y senderName, y agregar información de la IA
    author_guardado = state_context.get('author') or author
    sender_name_guardado = state_context.get('senderName')
    
    # Crear contexto limpio pero preservando información crítica
    state_context = {
        'author': author_guardado,
        'senderName': sender_name_guardado
    }
    
    # CORRECCIÓN CRÍTICA: Agregar información extraída por la IA al contexto
    if fecha_deseada:
        state_context['fecha_deseada'] = fecha_deseada
        logger.info(f"[TRIAGE_AGENDA] Fecha agregada al contexto: {fecha_deseada}")
    if hora_especifica:
        state_context['hora_especifica'] = hora_especifica
    if preferencia_horaria:
        state_context['preferencia_horaria'] = preferencia_horaria
        logger.info(f"[TRIAGE_AGENDA] Preferencia horaria agregada al contexto: {preferencia_horaria}")
    if restricciones_temporales:
        state_context['restricciones_temporales'] = restricciones_temporales
        logger.info(f"[TRIAGE_AGENDA] Restricciones temporales agregadas: {restricciones_temporales}")
    if dia_semana_interes and not fecha_deseada:
        state_context['dia_semana_interes'] = dia_semana_interes
        logger.info(f"[TRIAGE_AGENDA] Día de interés agregado al contexto: {dia_semana_interes}")
    
    # MEJORA CRÍTICA: Verificar si se debe forzar la lista
    forzar_lista = detalles.get('forzar_lista', False) if isinstance(detalles, dict) else False
    if forzar_lista:
        logger.info(f"[TRIAGE_AGENDA] Forzando muestra de lista de turnos")
        state_context['forzar_lista_turnos'] = True
    
    # Actualizar estado
    state_context['current_state'] = 'AGENDA_MOSTRANDO_OPCIONES'
    
    logger.info(f"[TRIAGE_AGENDA] Contexto final con información de la IA: {state_context}")
    
    # MEJORA CRÍTICA: Buscar turnos disponibles directamente
    return mostrar_opciones_turnos(history, detalles, state_context, mensaje_completo_usuario, author)

def iniciar_agendamiento_unificado(history, detalles, state_context=None, mensaje_completo_usuario=None, author=None):
    """
    NUEVO: Función unificada para iniciar agendamiento (alias de triage).
    """
    logger.info(f"[AGENDA_UNIFICADA] Iniciando agendamiento unificado")
    return iniciar_triage_agendamiento(history, detalles, state_context, mensaje_completo_usuario, author)

def buscar_y_ofrecer_turnos(history, detalles, state_context=None, mensaje_completo_usuario=None, author=None):
    """
    MEJORADO: Función para buscar y ofrecer turnos disponibles con extracción inteligente de fechas.
    """
    logger.info(f"[BUSCAR_TURNOS] Buscando y ofreciendo turnos")
    
    # Asegurar que tenemos el contexto necesario
    if not state_context:
        state_context = {}
    
    # NOTA: Verificación de restricciones ahora se maneja centralizadamente en main.py
    
    # CORRECCIÓN CRÍTICA: Preservar el author que viene como parámetro, no sobrescribirlo
    if not author:
        author = state_context.get('author') or detalles.get('author')
    
    if not author:
        return "Error interno. No se pudo identificar al usuario.", state_context
    
    # NUEVA MEJORA: Extracción de Fecha/Hora Flexible del mensaje del usuario
    fecha_deseada = None
    hora_especifica = None
    preferencia_horaria = None
    
    # ELIMINADO: Extracción ahora la hace el Meta-Agente directamente
    # Los datos ya vienen extraídos en 'detalles' desde el Meta-Agente amplificado
    
    # Obtener datos extraídos por el Meta-Agente desde 'detalles'
    if isinstance(detalles, dict):
        fecha_deseada = detalles.get('fecha_deseada') or fecha_deseada
        hora_especifica = detalles.get('hora_especifica') or hora_especifica
        preferencia_horaria = detalles.get('preferencia_horaria') or state_context.get('preferencia_horaria')
        if detalles.get('restricciones_temporales'):
            state_context['restricciones_temporales'] = detalles.get('restricciones_temporales')
        if detalles.get('dia_semana'):
            state_context['dia_semana_interes'] = detalles.get('dia_semana')
        logger.info(f"[BUSCAR_TURNOS] Datos del Meta-Agente - fecha: {fecha_deseada}, hora: {hora_especifica}, preferencia: {preferencia_horaria}")
    
    # Si no hay fecha del Meta-Agente, usar la del contexto o fecha actual
    if not fecha_deseada:
        fecha_deseada = state_context.get('fecha_deseada')
        if not fecha_deseada and state_context.get('dia_semana_interes'):
            fecha_deseada = utils.get_next_weekday_date(state_context['dia_semana_interes'])
            logger.info(f"[BUSCAR_TURNOS] Usando próximo {state_context['dia_semana_interes']}: {fecha_deseada}")
        if not fecha_deseada:
            # NUEVA MEJORA: Si no hay contexto de fecha, usar fecha actual
            fecha_deseada = datetime.now(TIMEZONE).strftime('%Y-%m-%d')
            logger.info(f"[BUSCAR_TURNOS] Usando fecha actual: {fecha_deseada}")
    
    # Actualizar contexto con la fecha extraída
    if fecha_deseada:
        state_context['fecha_deseada'] = fecha_deseada
    if hora_especifica:
        state_context['hora_especifica'] = hora_especifica
    if preferencia_horaria:
        state_context['preferencia_horaria'] = preferencia_horaria
    
    # Lógica "Sin Contexto, Da lo Primero Disponible"
    if not fecha_deseada and not hora_especifica:
        logger.info(f"[BUSCAR_TURNOS] Sin contexto específico, buscando primeros turnos disponibles")
        # Buscar desde hoy en adelante
        fecha_deseada = datetime.now(TIMEZONE).strftime('%Y-%m-%d')
        state_context['fecha_deseada'] = fecha_deseada
    
    return mostrar_opciones_turnos(history, detalles, state_context, mensaje_completo_usuario, author)

def _mostrar_error_tecnico_con_botones(author, state_context, tipo_agenda="agendamiento"):
    """
    CORRECCIÓN V10: Mostrar error técnico con botones, nunca texto.
    """
    import msgio_handler
    
    if tipo_agenda == "reprogramación":
        mensaje = "⚠️ **Error técnico en reprogramación**\n\nTengo problemas para obtener los turnos. ¿Qué querés hacer?"
    else:
        mensaje = "⚠️ **Error técnico**\n\nTengo problemas para obtener los turnos disponibles. ¿Qué querés hacer?"
    
    # Crear botones de opciones
    botones = [
        {"id": "reintentar_turnos", "title": "🔄 Intentar de nuevo"},
        {"id": "buscar_otra_fecha", "title": "📅 Buscar otra fecha"},
        {"id": "salir_agenda", "title": "❌ Salir de agenda"}
    ]
    
    success = msgio_handler.send_whatsapp_message(
        phone_number=author,
        message=mensaje,
        buttons=botones
    )
    
    if success:
        return None, state_context
    else:
        logger.error(f"[ERROR_TECNICO] Error enviando botones para {author}")
        state_context['current_state'] = 'AGENDA_MOSTRANDO_OPCIONES'
        return "Para salir del agendamiento, escribí: SALIR DE AGENDA", state_context

def _mostrar_solicitud_identificacion_cita_con_botones(author, state_context):
    """
    CORRECCIÓN V10: Solicitar identificación de cita con botones, nunca texto.
    """
    import msgio_handler
    
    mensaje = "❓ **Para cancelar tu cita necesito identificarla**\n\n¿Qué información podés darme?"
    
    # Crear botones de opciones
    botones = [
        {"id": "fecha_cita", "title": "📅 Decir fecha de la cita"},
        {"id": "buscar_citas", "title": "🔍 Buscar mis citas"},
        {"id": "salir_agenda", "title": "❌ Salir de agenda"}
    ]
    
    success = msgio_handler.send_whatsapp_message(
        phone_number=author,
        message=mensaje,
        buttons=botones
    )
    
    if success:
        return None, state_context
    else:
        logger.error(f"[SOLICITUD_ID_CITA] Error enviando botones para {author}")
        state_context['current_state'] = 'AGENDA_MOSTRANDO_OPCIONES'
        return "Para salir del agendamiento, escribí: SALIR DE AGENDA", state_context

def _mostrar_confirmacion_cancelacion_con_botones(author, state_context):
    """
    CORRECCIÓN V10: Mostrar confirmación de cancelación con botones, nunca texto.
    """
    import msgio_handler
    
    mensaje = "⚠️ **Confirmación de cancelación**\n\n¿Estás seguro de que querés cancelar tu cita?"
    
    # Crear botones de confirmación
    botones = [
        {"id": "cancelar_cita_si", "title": "✅ Sí, cancelar"},
        {"id": "cancelar_cita_no", "title": "❌ No, mantener cita"}
    ]
    
    success = msgio_handler.send_whatsapp_message(
        phone_number=author,
        message=mensaje,
        buttons=botones
    )
    
    if success:
        return None, state_context
    else:
        logger.error(f"[CONFIRMACION_CANCELACION] Error enviando botones para {author}")
        state_context['current_state'] = 'AGENDA_MOSTRANDO_OPCIONES'
        return "Para salir del agendamiento, escribí: SALIR DE AGENDA", state_context

def _mostrar_no_turnos_disponibles_con_botones(author, state_context, tipo_agenda="agendamiento"):
    """
    CORRECCIÓN V10: Mostrar "no hay turnos" con botones, nunca texto.
    """
    import msgio_handler
    
    if tipo_agenda == "reprogramación":
        mensaje = "❌ **No hay turnos disponibles para reprogramación**\n\n¿Qué querés hacer?"
    else:
        mensaje = "❌ **No hay turnos disponibles**\n\nEn los próximos días no encontré turnos libres. ¿Qué querés hacer?"
    
    # Crear botones de opciones
    botones = [
        {"id": "buscar_otra_fecha", "title": "📅 Buscar en otra fecha"},
        {"id": "preferencia_horario", "title": "⏰ Especificar horario"},
        {"id": "salir_agenda", "title": "❌ Salir de agenda"}
    ]
    
    success = msgio_handler.send_whatsapp_message(
        phone_number=author,
        message=mensaje,
        buttons=botones
    )
    
    if success:
        return None, state_context  # No devolver texto adicional
    else:
        # Fallback: mantener en agenda con mensaje educativo
        logger.error(f"[NO_TURNOS] Error enviando botones para {author}")
        state_context['current_state'] = 'AGENDA_MOSTRANDO_OPCIONES'
        return f"{config.COMMAND_TIPS['EXIT_AGENDA']}", state_context

def _mostrar_confirmacion_turno_con_botones(slot_seleccionado, state_context, author):
    """
    CORRECCIÓN V10: Mostrar confirmación de turno con botones, nunca texto.
    """
    import msgio_handler
    
    fecha_formateada = slot_seleccionado.get('fecha_formateada', 'Turno seleccionado')
    
    mensaje = f"✅ **Turno seleccionado:**\n{fecha_formateada}\n\n¿Confirmas este turno?"
    
    # Crear botones de confirmación
    botones = [
        {"id": "confirmar_turno_si", "title": "✅ Sí, confirmar"},
        {"id": "confirmar_turno_no", "title": "❌ No, elegir otro"}
    ]
    
    success = msgio_handler.send_whatsapp_message(
        phone_number=author,
        message=mensaje,
        buttons=botones
    )
    
    if success:
        return None, state_context  # No devolver texto adicional
    else:
        # Fallback: volver a mostrar opciones
        logger.error(f"[CONFIRMACION_TURNO] Error enviando botones para {author}")
        # Importar la función sin referencias circulares
        from agendamiento_handler import mostrar_opciones_turnos
        return mostrar_opciones_turnos([], {}, state_context, "", author)

def confirmar_agendamiento(history, state_context, user_choice):
    """
    NUEVO: Función para confirmar agendamiento (compatibilidad con wrapper).
    NUEVA MEJORA: Si recibe lenguaje natural, devuelve None para que Meta Agente clasifique.
    """
    logger.info(f"[CONFIRMAR_AGENDA] Confirmando agendamiento con choice: {user_choice}")
    
    if not state_context:
        state_context = {}
    
    # Procesar la selección del usuario
    try:
        seleccion = int(user_choice)
        available_slots = state_context.get('available_slots', [])
        
        if 1 <= seleccion <= len(available_slots):
            slot_seleccionado = available_slots[seleccion - 1]
            state_context['slot_seleccionado'] = slot_seleccionado
            state_context['current_state'] = 'AGENDA_CONFIRMANDO_TURNO'
            
            # CORRECCIÓN V10: SIEMPRE BOTONES, NUNCA TEXTO
            # Mostrar confirmación con botones Sí/No
            return _mostrar_confirmacion_turno_con_botones(slot_seleccionado, state_context, author)
        else:
            # CORRECCIÓN V10: SIEMPRE BOTONES, NUNCA TEXTO  
            # Si selección inválida, volver a mostrar turnos con botones
            return mostrar_opciones_turnos(history, detalles, state_context, mensaje_completo_usuario, author)
    except ValueError:
        # NUEVA MEJORA CRÍTICA: Si no es un ID válido, devolver None para que Meta Agente clasifique
        logger.info(f"[CONFIRMAR_AGENDA] Mensaje no es ID válido, devolviendo None para clasificación: {user_choice}")
        return None, state_context

def iniciar_reprogramacion_cita(history, detalles, state_context=None, mensaje_completo_usuario=None, author=None):
    """
    CORRECCIÓN CRÍTICA: Función para iniciar reprogramación de cita - SIMPLE Y DIRECTO.
    Funciona igual que agendamiento pero para reprogramación.
    MEJORA CRÍTICA: Siempre mostrar lista de turnos directamente.
    """
    logger.info(f"[REPROGRAMACION] Iniciando reprogramación de cita - MODO DIRECTO")

    if not state_context:
        state_context = {}

    # CORRECCIÓN CRÍTICA: Preservar el author que viene como parámetro, no sobrescribirlo
    if not author:
        author = state_context.get('author') or detalles.get('author')
    
    if not author:
        return "Error interno. No se pudo identificar al usuario.", state_context

    # PASO 3: Verificación Final del Flujo de Reprogramación
    # Llamar a memory.obtener_ultimo_turno_confirmado al principio
    ultimo_turno = memory.obtener_ultimo_turno_confirmado(author)
    
    if ultimo_turno:
        # Si encuentra un turno, usar esa información para confirmar con el usuario
        fecha_legible = ultimo_turno.get('fecha_completa_legible', 'tu cita confirmada')
        logger.info(f"[REPROGRAMACION] Turno encontrado para reprogramar: {fecha_legible}")
        
        # Guardar información de la cita original
        state_context['cita_original_reprogramar'] = ultimo_turno
        state_context['es_reprogramacion'] = True
        
        # Extraer información de fecha/hora de los detalles si está disponible
        fecha_deseada = None
        hora_especifica = None
        preferencia_horaria = None
        
        if isinstance(detalles, dict):
            fecha_deseada = detalles.get('fecha_deseada')
            hora_especifica = detalles.get('hora_especifica')
            preferencia_horaria = detalles.get('preferencia_horaria')
            logger.info(f"[REPROGRAMACION] Información extraída - fecha: {fecha_deseada}, hora: {hora_especifica}, preferencia: {preferencia_horaria}")
        
        # Agregar información al contexto
        if fecha_deseada:
            state_context['fecha_deseada'] = fecha_deseada
        if hora_especifica:
            state_context['hora_especifica'] = hora_especifica
        if preferencia_horaria:
            state_context['preferencia_horaria'] = preferencia_horaria
        
        # Verificar si se debe forzar la lista
        forzar_lista = detalles.get('forzar_lista', False) if isinstance(detalles, dict) else False
        if forzar_lista:
            logger.info(f"[REPROGRAMACION] Forzando muestra de lista de turnos para reprogramación")
            state_context['forzar_lista_turnos'] = True
        
        # Ejecutar directamente la búsqueda de turnos para reprogramación
        logger.info(f"[REPROGRAMACION] Ejecutando búsqueda directa de turnos para reprogramación")
        return mostrar_opciones_turnos_reprogramacion(history, detalles, state_context, mensaje_completo_usuario)
    
    else:
        # Si no encuentra turno, decir que no encontró pero no hay problema y iniciar el ciclo de agendamiento normal
        logger.info(f"[REPROGRAMACION] No se encontró turno confirmado para {author}. Iniciando ciclo de agendamiento normal.")
        
        mensaje = f"No encontré una cita confirmada para reprogramar, pero no hay problema. Vamos a agendar una nueva cita para ti."
        
        # Limpiar contexto de reprogramación y iniciar agendamiento normal
        if 'cita_original_reprogramar' in state_context:
            del state_context['cita_original_reprogramar']
        if 'es_reprogramacion' in state_context:
            del state_context['es_reprogramacion']
        
        # Iniciar el ciclo de agendamiento normal
        return iniciar_triage_agendamiento(history, detalles, state_context, mensaje_completo_usuario, author)

def confirmar_reprogramacion(history, state_context, user_choice):
    """
    NUEVO: Función para confirmar reprogramación con ejecución directa.
    """
    logger.info(f"[CONFIRMAR_REPROG] Confirmando reprogramación con choice: {user_choice}")
    
    if not state_context:
        state_context = {}
    
    # NUEVA MEJORA: Confirmación directa sin re-confirmación
    if user_choice.lower() in ['si', 'sí', 'yes', 'confirmar', '1']:
        # Ejecutar directamente la reprogramación
        return ejecutar_reprogramacion_cita(history, {}, state_context, user_choice)
    else:
        # CORRECCIÓN V10: NO cambiar estado, mantener flujo de agenda
        # Usuario debe usar "SALIR DE AGENDA" para salir del flujo
        state_context['current_state'] = 'AGENDA_MOSTRANDO_OPCIONES'  
        return "Reprogramación cancelada. Para salir del agendamiento, escribí: SALIR DE AGENDA", state_context

def ejecutar_reprogramacion_cita(history, detalles, state_context=None, mensaje_completo_usuario=None, author=None):
    """
    CORRECCIÓN CRÍTICA: Función para ejecutar la reprogramación de cita - MODO DIRECTO.
    Siempre ejecuta la búsqueda de turnos para reprogramación sin preguntas.
    MEJORA CRÍTICA: Siempre mostrar lista de turnos directamente.
    """
    logger.info(f"[EJECUTAR_REPROG] Ejecutando reprogramación de cita - MODO DIRECTO")
    
    if not state_context:
        state_context = {}
    
    # CORRECCIÓN CRÍTICA: Extraer información de fecha/hora de los detalles si está disponible
    fecha_deseada = None
    hora_especifica = None
    preferencia_horaria = None
    
    if isinstance(detalles, dict):
        fecha_deseada = detalles.get('fecha_deseada')
        hora_especifica = detalles.get('hora_especifica')
        preferencia_horaria = detalles.get('preferencia_horaria')
        logger.info(f"[EJECUTAR_REPROG] Información extraída de detalles - fecha: {fecha_deseada}, hora: {hora_especifica}, preferencia: {preferencia_horaria}")
    
    # CORRECCIÓN CRÍTICA: Agregar información al contexto si no está
    if fecha_deseada and not state_context.get('fecha_deseada'):
        state_context['fecha_deseada'] = fecha_deseada
    if hora_especifica and not state_context.get('hora_especifica'):
        state_context['hora_especifica'] = hora_especifica
    if preferencia_horaria and not state_context.get('preferencia_horaria'):
        state_context['preferencia_horaria'] = preferencia_horaria
    
    # CORRECCIÓN CRÍTICA: Marcar como reprogramación y ejecutar directamente
    state_context['es_reprogramacion'] = True
    
    # MEJORA CRÍTICA: Verificar si se debe forzar la lista
    forzar_lista = detalles.get('forzar_lista', False) if isinstance(detalles, dict) else False
    if forzar_lista:
        logger.info(f"[EJECUTAR_REPROG] Forzando muestra de lista de turnos para reprogramación")
        state_context['forzar_lista_turnos'] = True
    
    # CORRECCIÓN CRÍTICA: Ejecutar directamente la búsqueda de turnos para reprogramación
    logger.info(f"[EJECUTAR_REPROG] Ejecutando búsqueda directa de turnos para reprogramación")
    return mostrar_opciones_turnos_reprogramacion(history, detalles, state_context, mensaje_completo_usuario)

def mostrar_opciones_turnos_reprogramacion(history, detalles, state_context=None, mensaje_completo_usuario=None, author=None):
    """
    CORRECCIÓN CRÍTICA: Función específica para mostrar opciones de turnos en reprogramación.
    Funciona igual que mostrar_opciones_turnos pero mantiene el contexto de reprogramación.
    MEJORA CRÍTICA: Siempre mostrar lista directamente sin preguntas.
    """
    import utils
    
    # Asegurar que tenemos el contexto necesario
    if not state_context:
        state_context = {}
    
    # CORRECCIÓN CRÍTICA: Preservar el author que viene como parámetro, no sobrescribirlo
    if not author:
        author = state_context.get('author') or detalles.get('author')
    
    if not author:
        return "Error interno. No se pudo identificar al usuario.", state_context
    
    fecha_deseada = state_context.get('fecha_deseada')
    preferencia_horaria = state_context.get('preferencia_horaria')
    hora_especifica = state_context.get('hora_especifica')
    
    # NUEVA MEJORA: Logging detallado de la información de fecha para reprogramación
    logger.info(f"[MOSTRAR_TURNOS_REPROG] Información de reprogramación - fecha: {fecha_deseada}, hora: {hora_especifica}, preferencia: {preferencia_horaria}")
    
    # NUEVA MEJORA: Extraer restricciones temporales de los detalles
    restricciones_temporales = []
    if isinstance(detalles, dict):
        restricciones_temporales = detalles.get('restricciones_temporales', [])
        # También extraer de state_context si está disponible
        if state_context.get('restricciones_temporales'):
            restricciones_temporales.extend(state_context.get('restricciones_temporales'))
        if not fecha_deseada and detalles.get('dia_semana'):
            fecha_deseada = utils.get_next_weekday_date(detalles.get('dia_semana'))
            logger.info(f"[MOSTRAR_TURNOS_REPROG] Ajustando fecha por día de semana {detalles.get('dia_semana')}: {fecha_deseada}")
    
    logger.info(f"[MOSTRAR_TURNOS_REPROG] Restricciones temporales detectadas: {restricciones_temporales}")
    
    # NUEVA MEJORA: Manejo robusto de errores de API de Google Calendar
    try:
        logger.info(f"[MOSTRAR_TURNOS_REPROG] Llamando a get_available_slots_catalog_with_cache con fecha: {fecha_deseada}, hora: {hora_especifica}, preferencia: {preferencia_horaria}")
        available_slots = utils.get_available_slots_catalog_with_cache(
            author, fecha_deseada, max_slots=5, preferencia_horaria=preferencia_horaria, hora_especifica=hora_especifica
        )
        
        # NUEVA MEJORA: Filtrar slots según restricciones temporales y preferencia horaria
        if restricciones_temporales or preferencia_horaria:
            available_slots = _filtrar_slots_por_restricciones(available_slots, restricciones_temporales, preferencia_horaria)
            logger.info(f"[MOSTRAR_TURNOS_REPROG] Slots filtrados por restricciones y preferencia horaria: {len(available_slots)} disponibles")
    except Exception as e:
        logger.error(f"[MOSTRAR_TURNOS_REPROG] Error obteniendo turnos con caché: {e}")
        # Fallback a función sin caché
        try:
            available_slots = utils.get_available_slots_catalog(
                author,
                fecha_deseada,
                max_slots=5,
                hora_especifica=hora_especifica,
                preferencia_horaria=preferencia_horaria
            )
        except Exception as e2:
            logger.error(f"[MOSTRAR_TURNOS_REPROG] Error catastrófico obteniendo turnos: {e2}")
            # NUEVA MEJORA: Mensaje genérico para el usuario sin exponer errores internos
            # CORRECCIÓN V10: SIEMPRE BOTONES, NUNCA TEXTO
            return _mostrar_error_tecnico_con_botones(author, state_context, "reprogramación")
    
    if not available_slots:
        # CORRECCIÓN V10: SIEMPRE BOTONES, NUNCA TEXTO
        return _mostrar_no_turnos_disponibles_con_botones(author, state_context, "reprogramación")
    
    # Guardar slots en el contexto para uso posterior
    state_context['available_slots'] = available_slots
    # CORRECCIÓN CRÍTICA: Guardar el estado que el validador SÍ espera para reprogramación
    state_context['current_state'] = 'AGENDA_REPROGRAMACION_ESPERANDO_CONFIRMACION_FINAL'
    # --- !! LA LÍNEA MÁGICA PARA REPROGRAMACIÓN !! ---
    # Guardar la lista de turnos que acabamos de enviar para que finalizar_cita_automatico pueda identificarlos
    state_context['available_slots_sent'] = available_slots
    logger.info(f"[MOSTRAR_TURNOS_REPROG] ✅ Guardado available_slots_sent con {len(available_slots)} turnos")
    logger.info(f"[MOSTRAR_TURNOS_REPROG] ✅ Contexto actualizado: {state_context}")
    # ----------------------------------------------------
    
    # NUEVO: Crear opciones para lista interactiva con IDs temporales
    from main import _generar_id_interactivo_temporal
    
    opciones_lista = []
    for i, slot in enumerate(available_slots, 1):
        # CORRECCIÓN CRÍTICA: Asegurar que slot sea un diccionario con las claves necesarias
        if isinstance(slot, dict):
            # Extraer fecha y hora del slot_iso para generar ID temporal
            try:
                slot_iso = slot.get('slot_iso', '')
                if slot_iso:
                    fecha_hora = datetime.fromisoformat(slot_iso)
                    datos_turno = {
                        'fecha': fecha_hora.strftime('%Y%m%d'),
                        'hora': fecha_hora.strftime('%H%M%S')
                    }
                else:
                    # Fallback si no hay slot_iso
                    datos_turno = {
                        'fecha': '20250101',
                        'hora': '120000'
                    }
            except (ValueError, KeyError) as e:
                logger.warning(f"[MOSTRAR_TURNOS_REPROG] Error parseando slot {i}: {e}, usando datos por defecto")
                datos_turno = {
                    'fecha': '20250101',
                    'hora': '120000'
                }
        else:
            # Si slot no es un diccionario, usar datos por defecto
            logger.warning(f"[MOSTRAR_TURNOS_REPROG] Slot {i} no es un diccionario: {type(slot)}")
            datos_turno = {
                'fecha': '20250101',
                'hora': '120000'
            }
        
        # Generar ID temporal único para cada turno
        turno_id_temporal = _generar_id_interactivo_temporal('turno', datos_turno)
        
        # NUEVA MEJORA: Usar el campo fecha_para_titulo acortado y profesional
        titulo_turno = slot.get('fecha_para_titulo', f'Turno {i}')
        
        opciones_lista.append({
            'id': turno_id_temporal,
            'title': titulo_turno,
            'description': 'Confirmar reprogramación'
        })
    
    # MENSAJE EDUCATIVO PARA REPROGRAMACIÓN CON COMANDOS
    cita_original = state_context.get('cita_original_reprogramar', {})
    fecha_deseada = state_context.get('fecha_deseada')
    hora_especifica = state_context.get('hora_especifica')
    
    if fecha_deseada and hora_especifica:
        mensaje_respuesta = (
            f"🔁 Reprogramación: opciones para {fecha_deseada} a las {hora_especifica}.\n"
            "- Tocá 'Ver Turnos' y elegí.\n"
            "- Para salir del agendamiento, escribí: SALIR DE AGENDA"
        )
    elif fecha_deseada:
        mensaje_respuesta = (
            f"🔁 Reprogramación: opciones para {fecha_deseada}.\n"
            "- Tocá 'Ver Turnos' y elegí.\n"
            "- Para salir del agendamiento, escribí: SALIR DE AGENDA"
        )
    elif hora_especifica:
        mensaje_respuesta = (
            f"🔁 Reprogramación: opciones a las {hora_especifica}.\n"
            "- Tocá 'Ver Turnos' y elegí.\n"
            "- Para salir del agendamiento, escribí: SALIR DE AGENDA"
        )
    elif cita_original and cita_original.get('fecha_completa_legible'):
        mensaje_respuesta = (
            f"🔁 Reprogramación: opciones para la cita del {cita_original['fecha_completa_legible']}.\n"
            "- Tocá 'Ver Turnos' y elegí.\n"
            "- Para salir del agendamiento, escribí: SALIR DE AGENDA"
        )
    else:
        mensaje_respuesta = (
            "🔁 Reprogramación: acá van las nuevas opciones.\n"
            "- Tocá 'Ver Turnos' y elegí.\n"
            "- Para salir del agendamiento, escribí: SALIR DE AGENDA"
        )
    
    # NUEVO: Enviar mensaje con lista interactiva
    mensaje_principal = mensaje_respuesta
    titulo_lista = "Ver Turnos"
    titulo_seccion = "Turnos Disponibles"
    
    success = msgio_handler.send_whatsapp_message(
        phone_number=author,
        message=mensaje_principal,
        list_title=titulo_lista,
        options=opciones_lista,
        section_title=titulo_seccion
    )
    
    if success:
        logger.info(f"[MOSTRAR_TURNOS_REPROG] Mensaje interactivo enviado exitosamente")
        
        # PARA CHATWOOT: Registrar resumen de botones enviados para reprogramación
        try:
            import chatwoot_integration
            num_turnos = len(opciones_lista)
            resumen_chatwoot = f"Se enviaron {num_turnos} turnos disponibles para reprogramación como botones interactivos"
            chatwoot_integration.log_to_chatwoot(author, "", resumen_chatwoot, "Sistema")
            logger.info(f"[MOSTRAR_TURNOS_REPROG] Resumen registrado en Chatwoot: {resumen_chatwoot}")
        except Exception as e:
            logger.warning(f"[MOSTRAR_TURNOS_REPROG] Error registrando en Chatwoot: {e}")
        
        # NUEVA MEJORA: Solo guardar timestamp para validación de frescura, no el payload completo
        state_context['ultimo_interactive_timestamp'] = datetime.now().isoformat()
        # CORRECCIÓN CRÍTICA: No retornar texto después de enviar mensaje interactivo
        # Solo actualizar el estado y retornar None para evitar doble envío
        return None, state_context
    
    # NUEVA MEJORA: Si el mensaje interactivo falla, solo registrar el error y retornar mensaje genérico
    logger.error(f"[MOSTRAR_TURNOS_REPROG] Error enviando mensaje interactivo para {author}")
    return "Lo siento, estoy teniendo problemas para mostrar los turnos de reprogramación. ¿Podrías intentar de nuevo en unos minutos?", state_context

def iniciar_cancelacion_cita(history, detalles, state_context=None, mensaje_completo_usuario=None, author=None):
    """
    MEJORADO: Función para iniciar cancelación de cita con identificación inteligente.
    """
    logger.info(f"[CANCELACION] Iniciando cancelación de cita")
    
    if not state_context:
        state_context = {}
    
    # CORRECCIÓN CRÍTICA: Preservar el author que viene como parámetro, no sobrescribirlo
    if not author:
        author = state_context.get('author') or detalles.get('author')
    
    if not author:
        return "Error interno. No se pudo identificar al usuario.", state_context
    
    # NUEVA MEJORA: Extracción de last_event_id con prioridades
    last_event_id = None
    
    # Prioridad 1: Buscar en state_context (si se guardó el last_event_id de una cita anterior)
    last_event_id = state_context.get('last_event_id')
    if last_event_id:
        logger.info(f"[CANCELACION] last_event_id encontrado en state_context: {last_event_id}")
    
    # ELIMINADO: Extracción ahora la hace el Meta-Agente directamente
    # Los datos ya vienen en 'detalles' si están disponibles
    
    # Fallback: Si no se puede identificar, preguntar al usuario
    if not last_event_id:
        logger.warning(f"[CANCELACION] No se pudo identificar la cita a cancelar")
        state_context['current_state'] = 'AGENDA_CANCELACION_SOLICITANDO_IDENTIFICACION'
        # CORRECCIÓN V10: SIEMPRE BOTONES, NUNCA TEXTO
        return _mostrar_solicitud_identificacion_cita_con_botones(author, state_context)
    
    # Guardar el last_event_id en el contexto
    state_context['last_event_id'] = last_event_id
    state_context['es_cancelacion'] = True
    state_context['current_state'] = 'AGENDA_CANCELACION_CONFIRMANDO'
    
    # CORRECCIÓN V10: SIEMPRE BOTONES, NUNCA TEXTO
    return _mostrar_confirmacion_cancelacion_con_botones(author, state_context)

def confirmar_cancelacion(history, state_context):
    """
    NUEVO: Función para confirmar cancelación.
    """
    logger.info(f"[CONFIRMAR_CANCEL] Confirmando cancelación")
    
    if not state_context:
        state_context = {}
    
    state_context['current_state'] = 'AGENDA_EJECUTANDO_CANCELACION'
    return "Perfecto, voy a ejecutar la cancelación de tu cita.", state_context

def ejecutar_cancelacion_cita(history, detalles, state_context=None, mensaje_completo_usuario=None, author=None):
    """
    NUEVO: Función para ejecutar la cancelación de cita.
    """
    logger.info(f"[EJECUTAR_CANCEL] Ejecutando cancelación de cita")
    
    if not state_context:
        state_context = {}
    
    # Aquí iría la lógica para ejecutar la cancelación
    # Por ahora, simulamos éxito
    state_context['cita_cancelada'] = True
    # CORRECCIÓN V10: NO cambiar estado, mantener flujo de agenda  
    # Usuario debe usar "SALIR DE AGENDA" para salir del flujo
    state_context['current_state'] = 'AGENDA_MOSTRANDO_OPCIONES'
    
    return "Tu cita ha sido cancelada exitosamente. Para salir del agendamiento, escribí: SALIR DE AGENDA", state_context

def reanudar_agendamiento(history, detalles, state_context=None, mensaje_completo_usuario=None, author=None):
    """
    CORRECCIÓN CRÍTICA: Función para reanudar agendamiento desde un estado guardado.
    Ahora maneja tanto agendamiento normal como reprogramación.
    """
    logger.info(f"[REANUDAR_AGENDA] Reanudando agendamiento")
    
    if not state_context:
        state_context = {}
    
    # Verificar si hay contexto guardado
    author = state_context.get('author') or detalles.get('author')
    if author:
        contexto_guardado = memory.obtener_contexto_guardado(author)
        if contexto_guardado:
            state_context.update(contexto_guardado)
            logger.info(f"[REANUDAR_AGENDA] Contexto restaurado: {state_context.get('current_state')}")
    
    # CORRECCIÓN CRÍTICA: Verificar el estado actual para determinar qué hacer
    current_state = state_context.get('current_state', '')
    
    if current_state == 'AGENDA_MOSTRANDO_OPCIONES':
        return mostrar_opciones_turnos(history, detalles, state_context, mensaje_completo_usuario)
    elif current_state == 'AGENDA_ESPERANDO_CONFIRMACION_FINAL':
        return "Por favor, selecciona uno de los turnos disponibles de la lista anterior.", state_context
    elif current_state == 'AGENDA_REPROGRAMACION_ESPERANDO_CONFIRMACION_FINAL':
        return "Por favor, selecciona uno de los turnos disponibles para la reprogramación de la lista anterior.", state_context
    elif current_state == 'AGENDA_REPROGRAMACION_SOLICITANDO_NUEVO_HORARIO':
        # CORRECCIÓN CRÍTICA: Si estamos en reprogramación, ejecutar directamente
        return ejecutar_reprogramacion_cita(history, detalles, state_context, mensaje_completo_usuario)
    elif state_context.get('es_reprogramacion'):
        # CORRECCIÓN CRÍTICA: Si el contexto indica reprogramación, ejecutar directamente
        logger.info(f"[REANUDAR_AGENDA] Detectado contexto de reprogramación, ejecutando directamente")
        return ejecutar_reprogramacion_cita(history, detalles, state_context, mensaje_completo_usuario)
    else:
        # Estado no reconocido, reiniciar agendamiento
        return iniciar_triage_agendamiento(history, detalles, state_context, mensaje_completo_usuario, author)

def mostrar_opciones_turnos(history, detalles, state_context=None, mensaje_completo_usuario=None, author=None):
    """
    NUEVO: Muestra las opciones de turnos disponibles usando el caché optimizado.
    CACHÉ MEJORADO: Usa preferencia_horaria para búsquedas más específicas.
    MEJORA CRÍTICA: Siempre mostrar lista directamente sin preguntas.
    """
    import utils
    import config
    
    # Asegurar que tenemos el contexto necesario
    if not state_context:
        state_context = {}
    
    # NOTA: Verificación de restricciones ahora se maneja centralizadamente en main.py
    
    # Usar el parámetro author explícito si está disponible
    if not author:
        author = state_context.get('author') or detalles.get('author')
    
    if not author:
        return "Error interno. No se pudo identificar al usuario.", state_context
    
    fecha_deseada = state_context.get('fecha_deseada')
    preferencia_horaria = state_context.get('preferencia_horaria')
    restricciones_temporales = state_context.get('restricciones_temporales')
    
    # NUEVA MEJORA: Logging detallado de la información de fecha
    logger.info(f"[MOSTRAR_TURNOS] Información de fecha del contexto - fecha_deseada: {fecha_deseada}, preferencia_horaria: {preferencia_horaria}, restricciones: {restricciones_temporales}")
    
    # NUEVA MEJORA: Extraer restricciones temporales de los detalles
    restricciones_temporales = restricciones_temporales or []
    if isinstance(detalles, dict) and detalles.get('restricciones_temporales'):
        restricciones_temporales.extend(detalles.get('restricciones_temporales', []))
    
    logger.info(f"[MOSTRAR_TURNOS] Restricciones temporales detectadas: {restricciones_temporales}")
    
    # NUEVA MEJORA: Manejo robusto de errores de API de Google Calendar
    try:
        # CORRECCIÓN CRÍTICA: Extraer hora_especifica del contexto
        hora_especifica = state_context.get('hora_especifica')
        logger.info(f"[MOSTRAR_TURNOS] Llamando a get_available_slots_catalog_with_cache con fecha: {fecha_deseada}, hora: {hora_especifica}, preferencia: {preferencia_horaria}")
        available_slots = utils.get_available_slots_catalog_with_cache(
            author, fecha_deseada, max_slots=5, preferencia_horaria=preferencia_horaria, hora_especifica=hora_especifica
        )
        
        # NUEVA MEJORA: Filtrar slots según restricciones temporales y preferencia horaria
        if restricciones_temporales or preferencia_horaria:
            available_slots = _filtrar_slots_por_restricciones(available_slots, restricciones_temporales, preferencia_horaria)
            logger.info(f"[MOSTRAR_TURNOS] Slots filtrados por restricciones y preferencia horaria: {len(available_slots)} disponibles")
    except Exception as e:
        logger.error(f"[MOSTRAR_TURNOS] Error obteniendo turnos con caché: {e}")
        # Fallback a función sin caché
        try:
            available_slots = utils.get_available_slots_catalog(
                author,
                fecha_deseada,
                max_slots=5,
                hora_especifica=hora_especifica,
                preferencia_horaria=preferencia_horaria
            )
        except Exception as e2:
            logger.error(f"[MOSTRAR_TURNOS] Error catastrófico obteniendo turnos: {e2}")
            # NUEVA MEJORA: Mensaje genérico para el usuario sin exponer errores internos
            # CORRECCIÓN V10: SIEMPRE BOTONES, NUNCA TEXTO
            return _mostrar_error_tecnico_con_botones(author, state_context, "agendamiento")
    
    # NUEVO: Fallback automático si hoy no tiene cupos → buscar próximos días
    if not available_slots:
        logger.info("[MOSTRAR_TURNOS] Sin cupos para la fecha dada. Buscando próximos días (fallback)…")
        try:
            # Buscar próximos 7 días priorizando preferencia/horario si existe
            hora_especifica = state_context.get('hora_especifica')
            available_slots = get_available_slots_for_user(author, fecha_deseada=None, max_slots=5, hora_especifica=hora_especifica, preferencia_horaria=preferencia_horaria)
        except Exception as e:
            logger.warning(f"[MOSTRAR_TURNOS] Fallback de rango falló: {e}")
            available_slots = []
    
    if not available_slots:
        # CORRECCIÓN V10: SIEMPRE BOTONES, NUNCA TEXTO
        return _mostrar_no_turnos_disponibles_con_botones(author, state_context, "agendamiento")
    
    # PLAN DE ACCIÓN: Guardar información crítica para el flujo de confirmación
    state_context['available_slots'] = available_slots
    state_context['current_state'] = 'AGENDA_MOSTRANDO_OPCIONES'
    
    # --- !! LÍNEA CRÍTICA DEL PLAN DE ACCIÓN !! ---
    # Guardar la lista EXACTA de turnos que acabamos de enviar para que finalizar_cita_automatico pueda identificarlos
    state_context['available_slots_sent'] = available_slots.copy()  # Copia para evitar referencias
    logger.info(f"[MOSTRAR_TURNOS] ✅ Guardado available_slots_sent con {len(available_slots)} turnos")
    logger.info(f"[MOSTRAR_TURNOS] ✅ Turnos guardados: {[slot.get('fecha_para_titulo', 'N/A') for slot in available_slots]}")
    # ----------------------------------------------------
    
    # NUEVO: Crear opciones para lista interactiva con IDs temporales
    from main import _generar_id_interactivo_temporal
    
    opciones_lista = []
    for i, slot in enumerate(available_slots, 1):
        if isinstance(slot, dict):
            # Extraer fecha y hora del slot_iso para generar ID temporal
            try:
                slot_iso = slot.get('slot_iso', '')
                if slot_iso:
                    fecha_hora = datetime.fromisoformat(slot_iso)
                    datos_turno = {
                        'fecha': fecha_hora.strftime('%Y%m%d'),
                        'hora': fecha_hora.strftime('%H%M%S')
                    }
                else:
                    # Fallback si no hay slot_iso
                    datos_turno = {
                        'fecha': '20250101',
                        'hora': '120000'
                    }
            except (ValueError, KeyError) as e:
                logger.warning(f"[MOSTRAR_TURNOS] Error parseando slot {i}: {e}, usando datos por defecto")
                datos_turno = {
                    'fecha': '20250101',
                    'hora': '120000'
                }
        else:
            # Si slot no es un diccionario, usar datos por defecto
            logger.warning(f"[MOSTRAR_TURNOS] Slot {i} no es un diccionario: {type(slot)}")
            datos_turno = {
                'fecha': '20250101',
                'hora': '120000'
            }
        
        # Generar ID temporal único para cada turno
        turno_id_temporal = _generar_id_interactivo_temporal('turno', datos_turno)
        
        # NUEVA MEJORA: Usar el campo fecha_para_titulo acortado y profesional
        title_display = slot.get('fecha_para_titulo', f'Turno {i}') if isinstance(slot, dict) else f'Turno {i}'
        
        opciones_lista.append({
            "id": turno_id_temporal,
            "title": title_display,
            "description": "Confirmar"
        })
    
    # NUEVO: Crear payload interactivo para almacenar en state_context
    interactive_payload = {
        "type": "list",
        "header": {
            "type": "text",
            "text": "Elige un turno"
        },
        "body": {
            "text": "Aquí tienes los turnos disponibles:"
        },
        "footer": {
            "text": "Tip: podés responder 'DD/MM HH:MM' si querés otro horario"
        },
        "action": {
            "button": "Ver Turnos",
            "sections": [
                {
                    "title": "Turnos Disponibles",
                    "rows": []
                }
            ]
        }
    }
    
    # Agregar opciones al payload
    for option in opciones_lista:
        row = {
            "id": option.get('id', ''),
            "title": option.get('title', '')
        }
        interactive_payload["action"]["sections"][0]["rows"].append(row)
    
    # MENSAJE EDUCATIVO CON COMANDOS EXPLÍCITOS
    mensaje_principal = (
        "📅 Turnos disponibles.\n"
        "- Tocá 'Ver Turnos' y elegí.\n"
        "- Para salir del agendamiento, escribí: SALIR DE AGENDA\n"
        "- Si no te sirven estos turnos, decime el día en número (ej: 06/08) y si tenés preferencia de horario."
    )
    titulo_lista = "Ver Turnos"
    titulo_seccion = "Turnos Disponibles"
    
    success = msgio_handler.send_whatsapp_message(
        phone_number=author,
        message=mensaje_principal,
        list_title=titulo_lista,
        options=opciones_lista,
        section_title=titulo_seccion
    )
    
    if success:
        logger.info(f"[MOSTRAR_TURNOS] Mensaje interactivo enviado exitosamente")
        
        # PARA CHATWOOT: Registrar resumen de botones enviados
        try:
            import chatwoot_integration
            num_turnos = len(opciones_lista)
            resumen_chatwoot = f"Se enviaron {num_turnos} turnos disponibles como botones interactivos"
            chatwoot_integration.log_to_chatwoot(author, "", resumen_chatwoot, "Sistema")
            logger.info(f"[MOSTRAR_TURNOS] Resumen registrado en Chatwoot: {resumen_chatwoot}")
        except Exception as e:
            logger.warning(f"[MOSTRAR_TURNOS] Error registrando en Chatwoot: {e}")
        
        # NUEVA MEJORA: Solo guardar timestamp para validación de frescura, no el payload completo
        state_context['ultimo_interactive_timestamp'] = datetime.now().isoformat()
        # CORRECCIÓN CRÍTICA: No retornar texto después de enviar mensaje interactivo
        # Solo actualizar el estado y retornar None para evitar doble envío
        return None, state_context
    
    # NUEVA MEJORA: Si el mensaje interactivo falla, solo registrar el error y retornar mensaje genérico
    logger.error(f"[MOSTRAR_TURNOS] Error enviando mensaje interactivo para {author}")
    return "Lo siento, estoy teniendo problemas para mostrar los turnos. ¿Podrías intentar de nuevo en unos minutos?", state_context

def reiniciar_busqueda(history, detalles, state_context=None, mensaje_completo_usuario=None, author=None):
    """
    MANEJO DE INTERRUPCIÓN: El usuario no eligió un número. Reinicia el flujo de búsqueda.
    CORRECCIÓN CRÍTICA: Preservar información extraída por la IA al reiniciar.
    """
    logger.info(f"[REINICIO] El usuario proveyó nuevo input: '{mensaje_completo_usuario}'. Reiniciando búsqueda.")
    
    # CORRECCIÓN CRÍTICA: Preservar información de la IA al reiniciar
    # Si detalles contiene información extraída por la IA, pasarla al reinicio
    if isinstance(detalles, dict) and detalles:
        logger.info(f"[REINICIO] Preservando información de la IA: {detalles}")
        return iniciar_triage_agendamiento(history, detalles, state_context, mensaje_completo_usuario)
    else:
        return iniciar_triage_agendamiento(history, {}, state_context, mensaje_completo_usuario)

def confirmar_turno_directo(history, detalles, state_context=None, mensaje_completo_usuario=None, author=None):
    """
    MEJORADO: Confirma la selección de turno usando catálogo centralizado.
    NUEVA MEJORA: Si recibe lenguaje natural, devuelve None para que Meta Agente clasifique.
    """
    logger.info(f"[CONFIRMACIÓN DIRECTA] El usuario seleccionó la opción: {mensaje_completo_usuario}")
    
    # NUEVO: Obtener turnos disponibles desde catálogo centralizado
    # CORRECCIÓN CRÍTICA: Preservar el author que viene como parámetro, no sobrescribirlo
    if not author:
        author = state_context.get('author') or detalles.get('author')
    
    if not author:
        return "Error interno. No se pudo identificar al usuario.", state_context
    
    # Obtener turnos del contexto
    available_slots = state_context.get('available_slots', [])
    if not available_slots:
        return "Error: No hay turnos disponibles en el contexto. Por favor, inicia una nueva búsqueda.", state_context
    
    # MEJORADO: Procesar selección del usuario con IDs temporales
    if mensaje_completo_usuario and ('turno_' in mensaje_completo_usuario and '_' in mensaje_completo_usuario):
        try:
            # CORRECCIÓN CRÍTICA: Usar la misma lógica que finalizar_cita_automatico
            # El ID tiene formato: turno_YYYYMMDD_HHMMSS_timestamp
            partes = mensaje_completo_usuario.split('_')
            if len(partes) >= 3:
                fecha_str_id = partes[1]  # YYYYMMDD
                hora_str_id = partes[2]   # HHMMSS
                
                logger.info(f"[CONFIRMAR_TURNO] ID seleccionado: {mensaje_completo_usuario}")
                logger.info(f"[CONFIRMAR_TURNO] Fecha extraída: {fecha_str_id}, Hora extraída: {hora_str_id}")
                
                # Buscar el slot correspondiente en available_slots
                slot_seleccionado = None
                for slot in available_slots:
                    if isinstance(slot, dict) and 'slot_iso' in slot:
                        try:
                            slot_datetime = datetime.fromisoformat(slot['slot_iso'])
                            fecha_str_turno = slot_datetime.strftime('%Y%m%d')
                            hora_str_turno = slot_datetime.strftime('%H%M%S')
                            
                            logger.info(f"[CONFIRMAR_TURNO] Comparando con turno: fecha={fecha_str_turno}, hora={hora_str_turno}")
                            
                            if fecha_str_id == fecha_str_turno and hora_str_id == hora_str_turno:
                                slot_seleccionado = slot
                                logger.info(f"[CONFIRMAR_TURNO] ¡COINCIDENCIA ENCONTRADA! Turno: {slot.get('fecha_para_titulo', 'N/A')}")
                                break
                        except (ValueError, KeyError) as e:
                            logger.warning(f"[CONFIRMAR_TURNO] Error procesando turno: {e}")
                            continue
                
                if slot_seleccionado:
                    # NUEVA MEJORA: Confirmación directa sin re-confirmación
                    state_context['slot_seleccionado'] = slot_seleccionado
                    # Ejecutar directamente la creación de cita
                    return finalizar_cita_automatico(history, detalles, state_context, mensaje_completo_usuario)
                else:
                    return "Error: No se pudo encontrar el turno seleccionado. Por favor, intenta de nuevo.", state_context
            else:
                return "Error: Formato de ID de turno inválido. Por favor, intenta de nuevo.", state_context
        except (ValueError, IndexError) as e:
            logger.error(f"[CONFIRMAR_TURNO] Error parseando ID temporal de turno: {mensaje_completo_usuario}, error: {e}")
            return "Error: No se pudo procesar la selección. Por favor, intenta de nuevo.", state_context
    
    # Fallback: Procesar selección numérica tradicional
    try:
        # Intentar parsear como número
        seleccion = int(mensaje_completo_usuario)
        if 1 <= seleccion <= len(available_slots):
            slot_seleccionado = available_slots[seleccion - 1]
            # NUEVA MEJORA: Confirmación directa sin re-confirmación
            state_context['slot_seleccionado'] = slot_seleccionado
            # Ejecutar directamente la creación de cita
            return finalizar_cita_automatico(history, detalles, state_context, mensaje_completo_usuario)
        else:
            return f"Por favor, selecciona un número entre 1 y {len(available_slots)}.", state_context
    except ValueError:
        # NUEVA MEJORA CRÍTICA: Si no es un ID válido, devolver None para que Meta Agente clasifique
        logger.info(f"[CONFIRMAR_TURNO] Mensaje no es ID válido, devolviendo None para clasificación: {mensaje_completo_usuario}")
        return None, state_context

def finalizar_cita_automatico(history, detalles, state_context=None, mensaje_completo_usuario=None, author=None):
    """
    NUEVO: Finaliza automáticamente la cita después de la confirmación.
    """
    logger.info(f"[FINALIZAR_CITA] Finalizando cita automáticamente")
    logger.info(f"[FINALIZAR_CITA] Contexto recibido: {state_context}")
    logger.info(f"[FINALIZAR_CITA] Detalles recibidos: {detalles}")
    
    # CORRECCIÓN CRÍTICA: Preservar el author que viene como parámetro, no sobrescribirlo
    if not author:
        author = state_context.get('author') or detalles.get('author')
    
    if not author:
        return "Error interno. No se pudo identificar al usuario.", state_context
    
    # NUEVA MEJORA: Crear evento real en Google Calendar
    slot_seleccionado = state_context.get('slot_seleccionado')
    es_reprogramacion = state_context.get('es_reprogramacion', False)
    
    # --- !! PLAN DE ACCIÓN: IDENTIFICAR TURNO SELECCIONADO !! ---
    if not slot_seleccionado:
        # Buscar el turno seleccionado en los turnos que ofrecimos
        id_turno_seleccionado = (detalles or {}).get('id_interactivo')
        turnos_ofrecidos = state_context.get('available_slots_sent')
        
        logger.info(f"[FINALIZAR_CITA] ID turno seleccionado: {id_turno_seleccionado}")
        logger.info(f"[FINALIZAR_CITA] Turnos ofrecidos disponibles: {bool(turnos_ofrecidos)}")
        logger.info(f"[FINALIZAR_CITA] Cantidad de turnos ofrecidos: {len(turnos_ofrecidos) if turnos_ofrecidos else 0}")
        
        if not id_turno_seleccionado or not turnos_ofrecidos:
            return "Error interno. No se pudo identificar el turno seleccionado.", state_context
        
        # Buscar en los turnos que ofrecimos cuál coincide con el ID que eligió el usuario
        turno_a_agendar = None
        
        # PLAN DE ACCIÓN: Extraer fecha y hora del ID seleccionado para hacer match exacto
        try:
            # El ID tiene formato: turno_YYYYMMDD_HHMMSS_timestamp
            partes_id = id_turno_seleccionado.split('_')
            if len(partes_id) >= 3:
                fecha_str_id = partes_id[1]  # YYYYMMDD
                hora_str_id = partes_id[2]   # HHMMSS
                
                logger.info(f"[FINALIZAR_CITA] ID seleccionado: {id_turno_seleccionado}")
                logger.info(f"[FINALIZAR_CITA] Fecha extraída: {fecha_str_id}, Hora extraída: {hora_str_id}")
                
                # Buscar el turno que coincida con esta fecha y hora
                for i, turno in enumerate(turnos_ofrecidos):
                    if isinstance(turno, dict) and 'slot_iso' in turno:
                        try:
                            slot_datetime = datetime.fromisoformat(turno['slot_iso'])
                            fecha_str_turno = slot_datetime.strftime('%Y%m%d')
                            hora_str_turno = slot_datetime.strftime('%H%M%S')
                            
                            logger.info(f"[FINALIZAR_CITA] Comparando turno {i+1}: fecha={fecha_str_turno}, hora={hora_str_turno}")
                            
                            if fecha_str_id == fecha_str_turno and hora_str_id == hora_str_turno:
                                turno_a_agendar = turno
                                logger.info(f"[FINALIZAR_CITA] ✅ ¡COINCIDENCIA ENCONTRADA! Turno {i+1}: {turno.get('fecha_para_titulo', 'N/A')}")
                                break
                        except (ValueError, KeyError) as e:
                            logger.warning(f"[FINALIZAR_CITA] Error procesando turno {i+1}: {e}")
                            continue
            else:
                logger.error(f"[FINALIZAR_CITA] ❌ ID malformado: {id_turno_seleccionado}")
        except Exception as e:
            logger.error(f"[FINALIZAR_CITA] ❌ Error parseando ID: {e}")
        
        if not turno_a_agendar:
            return "Error. El turno que seleccionaste ya no parece ser válido.", state_context
        
        # Asignar el turno encontrado
        slot_seleccionado = turno_a_agendar
        state_context['slot_seleccionado'] = slot_seleccionado
        logger.info(f"[FINALIZAR_CITA] ✅ Turno identificado correctamente: {slot_seleccionado.get('fecha_para_titulo', 'N/A')}")
    # ----------------------------------------------------
    
    try:
        # Obtener el servicio de calendario
        calendar_service = get_calendar_service()
        
        # Preparar datos del slot para crear evento
        slot_datetime = datetime.fromisoformat(slot_seleccionado['slot_iso'])
        slot_end = slot_datetime + timedelta(minutes=APPOINTMENT_DURATION_MINUTES)
        
        slot_data = {
            'start_time': slot_datetime.isoformat(),
            'end_time': slot_end.isoformat()
        }
        
        # NUEVA MEJORA: Manejar creación vs reprogramación de eventos
        if es_reprogramacion and state_context.get('last_event_id'):
            # REPROGRAMAR evento existente
            last_event_id = state_context['last_event_id']
            logger.info(f"[FINALIZAR_CITA] Reprogramando evento existente: {last_event_id}")
            success = calendar_service.reschedule_event(last_event_id, slot_data)
            if success:
                event_id = last_event_id  # Mantener el mismo ID
                logger.info(f"[FINALIZAR_CITA] Evento reprogramado exitosamente: {event_id}")
            else:
                logger.error(f"[FINALIZAR_CITA] Error al reprogramar evento: {last_event_id}")
                return "Lo siento, hubo un error al reprogramar tu cita. Por favor, intenta de nuevo.", state_context
        else:
            # CREAR nuevo evento
            event_id = calendar_service.create_event(author, slot_data)
            if event_id:
                # GUARDAR EL EVENT_ID PARA FUTURAS REPROGRAMACIONES/CANCELACIONES
                state_context['last_event_id'] = event_id
                logger.info(f"[FINALIZAR_CITA] Evento creado con ID: {event_id}")
            else:
                logger.error("[FINALIZAR_CITA] Error al crear evento en Google Calendar")
                return "Lo siento, hubo un error al crear tu cita. Por favor, intenta de nuevo.", state_context
        
        # PLAN DE ACCIÓN: Guardar turno confirmado en memoria a largo plazo
        try:
            import memory
            datos_turno_persistente = {
                'id_evento': event_id,
                'fecha_para_titulo': slot_seleccionado.get('fecha_para_titulo', ''),
                'fecha_completa_legible': slot_seleccionado.get('fecha_completa_legible', ''),
                'slot_iso': slot_seleccionado.get('slot_iso', ''),
                'es_reprogramacion': es_reprogramacion
            }
            
            # Guardar en memoria a largo plazo
            memory.guardar_ultimo_turno_confirmado(author, datos_turno_persistente)
            logger.info(f"[FINALIZAR_CITA] ✅ Turno guardado en memoria a largo plazo: {datos_turno_persistente.get('fecha_para_titulo', 'N/A')}")
            
            # NOTIFICACIÓN AUTOMÁTICA DE TURNO PROGRAMADO
            try:
                import notification_manager
                sender_name = state_context.get('senderName', 'Cliente')
                datos_notificacion_turno = {
                    'telefono': author,
                    'nombre': notification_manager.obtener_nombre_cliente(state_context, author),
                    'fecha_turno': slot_seleccionado.get('fecha_completa_legible', 'No especificada'),
                    'evento_id': event_id
                }
                notification_manager.enviar_notificacion_turno_programado(datos_notificacion_turno)
            except Exception as notif_error:
                logger.error(f"[FINALIZAR_CITA] Error enviando notificación de turno (no afecta flujo principal): {notif_error}")
            
        except Exception as e:
            logger.error(f"[FINALIZAR_CITA] ❌ Error guardando turno en memoria a largo plazo: {e}")
        
        # Actualizar estado
        state_context['current_state'] = 'evento_creado'
        # Limpieza quirúrgica: no dejar restos de AGENDA una vez confirmada la cita
        for k in ['available_slots', 'available_slots_sent']:
            if k in state_context:
                try:
                    del state_context[k]
                except Exception:
                    pass

        # Construir mensaje de confirmación + (opcional) empuje a pago
        if slot_seleccionado.get('fecha_completa_legible'):
            if es_reprogramacion:
                base_msg = f"¡Perfecto! Tu cita ha sido reprogramada para el {slot_seleccionado['fecha_completa_legible']}."
            else:
                base_msg = f"¡Excelente! Tu cita fue confirmada para el {slot_seleccionado['fecha_completa_legible']}."
        else:
            base_msg = "¡Perfecto! Tu cita fue agendada exitosamente."

        # NUEVO: Con la lógica de "pago primero", no redirigir automáticamente a pagos
        # El usuario ya pagó antes de agendar, o puede pagar cuando quiera
        if config.REQUIRE_PAYMENT_BEFORE_SCHEDULING and state_context.get('payment_verified'):
            # Si ya pagó, confirmar que está todo listo
            mensaje_final = base_msg + " ¡Todo listo! Tu turno está confirmado y el pago fue verificado."
        else:
            # Si no hay restricción de pago o no pagó, mensaje neutro
            mensaje_final = base_msg + " ¡Tu turno está confirmado!"
        
        logger.info("[FINALIZAR_CITA] Turno confirmado. No se redirige automáticamente a pagos con nueva lógica.")
        
    except Exception as e:
        logger.error(f"[FINALIZAR_CITA] Error al finalizar cita: {e}")
        return "Lo siento, hubo un error al crear tu cita. Por favor, intenta de nuevo.", state_context
    
    return mensaje_final, state_context

def _filtrar_slots_por_restricciones(available_slots, restricciones_temporales, preferencia_horaria=None):
    """
    NUEVA FUNCIÓN: Filtra slots según restricciones temporales del usuario.
    CORRECCIÓN CRÍTICA: Agregar soporte para preferencia_horaria.
    
    Args:
        available_slots: Lista de slots disponibles
        restricciones_temporales: Lista de restricciones (ej: ["después_16", "excluir_miércoles"])
        preferencia_horaria: Preferencia horaria del usuario (ej: "tarde", "mañana", "15:00")
    
    Returns:
        Lista de slots filtrados
    """
    if not restricciones_temporales and not preferencia_horaria:
        return available_slots
    
    slots_filtrados = []
    
    for slot in available_slots:
        if not isinstance(slot, dict):
            continue
            
        slot_iso = slot.get('slot_iso', '')
        if not slot_iso:
            continue
            
        try:
            fecha_hora = datetime.fromisoformat(slot_iso)
            hora = fecha_hora.hour
            dia_semana = fecha_hora.weekday()  # 0=Lunes, 6=Domingo
            
            # Mapeo de días de la semana
            dias_semana = {
                0: 'lunes', 1: 'martes', 2: 'miércoles', 3: 'jueves', 
                4: 'viernes', 5: 'sábado', 6: 'domingo'
            }
            dia_nombre = dias_semana[dia_semana]
            
            slot_valido = True
            
            # CORRECCIÓN CRÍTICA: Manejar preferencia horaria
            if preferencia_horaria:
                if preferencia_horaria == "tarde":
                    if hora < 12:  # Solo después del mediodía
                        slot_valido = False
                elif preferencia_horaria == "mañana":
                    if hora >= 12:  # Solo antes del mediodía
                        slot_valido = False
                elif preferencia_horaria == "mañana_temprano":
                    if hora >= 10:  # Solo antes de las 10
                        slot_valido = False
                elif preferencia_horaria == "tarde_tardía":
                    if hora < 16:  # Solo después de las 16
                        slot_valido = False
                elif ":" in preferencia_horaria:  # Hora específica como "15:00"
                    try:
                        hora_preferida = int(preferencia_horaria.split(":")[0])
                        if hora != hora_preferida:
                            slot_valido = False
                    except ValueError:
                        pass  # Si no se puede parsear, ignorar la preferencia
            
            # Si ya no es válido por preferencia horaria, continuar al siguiente slot
            if not slot_valido:
                continue
            
            for restriccion in restricciones_temporales:
                # Restricciones de hora
                if restriccion.startswith('después_'):
                    hora_limite = int(restriccion.split('_')[1])
                    if hora < hora_limite:
                        slot_valido = False
                        break
                        
                elif restriccion.startswith('antes_'):
                    hora_limite = int(restriccion.split('_')[1])
                    if hora >= hora_limite:
                        slot_valido = False
                        break
                        
                # Restricciones de día
                elif restriccion.startswith('excluir_'):
                    dia_excluir = restriccion.split('_')[1]
                    if dia_nombre == dia_excluir:
                        slot_valido = False
                        break
                        
                elif restriccion.startswith('solo_'):
                    dia_permitir = restriccion.split('_')[1]
                    if dia_nombre != dia_permitir:
                        slot_valido = False
                        break
                        
                # Restricciones de horario laboral
                elif restriccion == 'fuera_horario_laboral':
                    if 9 <= hora <= 18:  # Horario laboral típico
                        slot_valido = False
                        break
                        
                elif restriccion == 'solo_tarde':
                    if hora < 12:  # Solo después del mediodía
                        slot_valido = False
                        break
                        
                elif restriccion == 'solo_mañana':
                    if hora >= 12:  # Solo antes del mediodía
                        slot_valido = False
                        break
            
            if slot_valido:
                slots_filtrados.append(slot)
                
        except Exception as e:
            logger.warning(f"[FILTRAR_SLOTS] Error procesando slot: {e}")
            # En caso de error, incluir el slot para no perder opciones
            slots_filtrados.append(slot)
    
    logger.info(f"[FILTRAR_SLOTS] Slots filtrados: {len(slots_filtrados)} de {len(available_slots)}")
    return slots_filtrados

def get_available_slots_for_user(author, fecha_deseada=None, max_slots=5, hora_especifica=None, preferencia_horaria=None):
    """
    NUEVA FUNCIÓN: Obtiene slots disponibles usando el servicio de calendario configurado.
    CORRECCIÓN CRÍTICA: Ahora filtra y prioriza por hora específica y preferencia horaria.
    """
    logger.info(f"[SLOTS_USER] Obteniendo slots para {author}, fecha: {fecha_deseada}, hora: {hora_especifica}, preferencia: {preferencia_horaria}, max: {max_slots}")
    
    try:
        # Obtener el servicio de calendario configurado
        calendar_service = get_calendar_service()
        
        # Calcular rango de fechas
        tz = TIMEZONE
        
        if fecha_deseada:
            # Si hay fecha específica, buscar en esa fecha
            try:
                logger.info(f"[SLOTS_USER] Procesando fecha específica: {fecha_deseada}")
                start_date = datetime.strptime(fecha_deseada, '%Y-%m-%d').replace(tzinfo=tz)
                end_date = start_date + timedelta(days=1)
                logger.info(f"[SLOTS_USER] Rango de búsqueda: {start_date} a {end_date}")
            except ValueError:
                logger.error(f"[SLOTS_USER] Error parseando fecha {fecha_deseada}")
                return []
        else:
            # Si no hay fecha específica, buscar desde hoy
            logger.info(f"[SLOTS_USER] No hay fecha específica, buscando desde hoy")
            start_date = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
            end_date = start_date + timedelta(days=7)  # Buscar en la próxima semana
        
        # Obtener slots disponibles del calendario
        date_range = (start_date, end_date)
        available_slots_iso = calendar_service.get_available_slots(date_range)
        
        if not available_slots_iso:
            logger.warning(f"[SLOTS_USER] No se encontraron slots disponibles para {author}")
            return []
        
        # NUEVA CORRECCIÓN CRÍTICA: Filtrar y priorizar por hora específica
        formatted_slots = []
        slots_exactos = []
        slots_cercanos = []
        slots_otros = []
        
        for slot_iso in available_slots_iso:
            try:
                slot_datetime = datetime.fromisoformat(slot_iso)
                
                # NUEVA MEJORA: Formato corto y profesional para títulos de lista interactiva
                dias_abreviados = {
                    'Mon': 'Lun', 'Tue': 'Mar', 'Wed': 'Mié', 'Thu': 'Jue',
                    'Fri': 'Vie', 'Sat': 'Sáb', 'Sun': 'Dom'
                }
                fecha_ingles = slot_datetime.strftime('%a %d/%m - %H:%M')  # Ej: "Thu 31/07 - 10:00"
                fecha_para_titulo = fecha_ingles
                for dia_eng, dia_esp in dias_abreviados.items():
                    fecha_para_titulo = fecha_para_titulo.replace(dia_eng, dia_esp)  # Ej: "Jue 31/07 - 10:00"
                
                slot_formateado = {
                    'slot_iso': slot_iso,
                    'fecha_formateada': format_fecha_espanol(slot_datetime),  # Mantener formato completo para descripciones
                    'fecha_para_titulo': fecha_para_titulo,  # NUEVO: Título corto para lista interactiva
                    'fecha': slot_datetime.strftime('%Y-%m-%d'),  # Formato YYYY-MM-DD para lógica interna
                    'hora': slot_datetime.strftime('%H:%M'),  # Formato HH:MM para lógica interna
                    'fecha_completa_legible': slot_datetime.strftime('%A %d de %B a las %H:%M hs')  # Para mensajes de confirmación detallados
                }
                
                # CORRECCIÓN CRÍTICA: Clasificar slots según prioridad
                if hora_especifica:
                    hora_slot = slot_datetime.strftime('%H:%M')
                    if hora_slot == hora_especifica:
                        # Turno exacto - máxima prioridad
                        slots_exactos.append(slot_formateado)
                        logger.info(f"[SLOTS_USER] Encontrado turno exacto: {hora_slot}")
                    else:
                        # Calcular proximidad temporal
                        try:
                            hora_solicitada = datetime.strptime(hora_especifica, '%H:%M').time()
                            hora_slot_time = slot_datetime.time()
                            diferencia_minutos = abs((hora_slot_time.hour * 60 + hora_slot_time.minute) - 
                                                   (hora_solicitada.hour * 60 + hora_solicitada.minute))
                            
                            if diferencia_minutos <= 60:  # Dentro de 1 hora
                                slots_cercanos.append((diferencia_minutos, slot_formateado))
                            else:
                                slots_otros.append(slot_formateado)
                        except ValueError:
                            slots_otros.append(slot_formateado)
                else:
                    # Si no hay hora específica, usar preferencia horaria
                    if preferencia_horaria:
                        hora_slot = slot_datetime.hour
                        if preferencia_horaria == 'mañana' and 6 <= hora_slot < 12:
                            slots_cercanos.append((0, slot_formateado))
                        elif preferencia_horaria == 'tarde' and 12 <= hora_slot < 18:
                            slots_cercanos.append((0, slot_formateado))
                        elif preferencia_horaria == 'noche' and (hora_slot >= 18 or hora_slot < 6):
                            slots_cercanos.append((0, slot_formateado))
                        else:
                            slots_otros.append(slot_formateado)
                    else:
                        slots_otros.append(slot_formateado)
                        
            except ValueError as e:
                logger.error(f"[SLOTS_USER] Error parseando slot {slot_iso}: {e}")
                continue
        
        # CORRECCIÓN CRÍTICA: Ordenar y combinar slots según prioridad
        # 1. Turnos exactos primero
        formatted_slots.extend(slots_exactos)
        
        # 2. Turnos cercanos ordenados por proximidad
        slots_cercanos.sort(key=lambda x: x[0])  # Ordenar por diferencia de minutos
        formatted_slots.extend([slot for _, slot in slots_cercanos])
        
        # 3. Otros turnos
        formatted_slots.extend(slots_otros)
        
        # Limitar a max_slots
        formatted_slots = formatted_slots[:max_slots]
        
        logger.info(f"[SLOTS_USER] Retornando {len(formatted_slots)} slots priorizados para {author}")
        if hora_especifica:
            logger.info(f"[SLOTS_USER] Turnos exactos encontrados: {len(slots_exactos)}, cercanos: {len(slots_cercanos)}")
        
        return formatted_slots
        
    except Exception as e:
        logger.error(f"[SLOTS_USER] Error obteniendo slots para {author}: {e}")
        return []
