"""
ballester_agendamiento_adapter.py - Adaptador de Agendamiento para Centro Pediátrico Ballester
Sistema V11 - Adaptador que conecta el verification_handler con el agendamiento usando API clínica

Este adaptador reemplaza Google Calendar con la API OMNIA de la clínica, manteniendo
toda la lógica de botones interactivos y estados del sistema actual.

CRÍTICO: Este adaptador debe mantener compatibilidad completa con el main.py existente
y toda la lógica de botones/interactivos, solo cambiando el backend de Google Calendar
a la API de la clínica.

Autor: Sistema OPTIATIENDE-IA V11
Cliente: Centro Pediátrico Ballester
Fecha: Enero 2025
"""

import logging
import json
import copy
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple

import config
import memory
import utils
import msgio_handler
from clinica_api import BallesterClinicaAPI
import agendamiento_handler  # Para reutilizar funciones existentes

logger = logging.getLogger(config.TENANT_NAME)

class BallesterAgendamientoAdapter:
    """
    Adaptador que conecta el flujo de verificación médica con el agendamiento
    usando la API OMNIA de la clínica en lugar de Google Calendar.
    """
    
    def __init__(self):
        """Inicializa el adaptador de agendamiento"""
        self.clinica_api = BallesterClinicaAPI()
        logger.info("[BALLESTER_AGENDA] Adaptador de agendamiento inicializado")
    
    def handle_medical_appointment_flow(self, context: Dict, author: str, verdict: Dict) -> Tuple[str, Dict, Optional[List[Dict]]]:
        """
        Maneja el flujo de agendamiento médico después de la verificación exitosa.
        
        Args:
            context: Contexto de la conversación con datos verificados
            author: ID del usuario
            verdict: Veredicto del rules_engine con toda la información
            
        Returns:
            Tuple con (mensaje, contexto_actualizado, botones)
        """
        logger.info("[BALLESTER_AGENDA] Iniciando flujo de agendamiento médico")
        
        next_action = verdict.get('next_action', '')
        coverage_status = verdict.get('coverage_status', '')
        
        # Enriquecer contexto con datos del veredicto
        context['medical_verdict'] = verdict
        context['verification_completed'] = True
        
        # Determinar acción según el veredicto
        if next_action == 'SHOW_APPOINTMENTS':
            return self._show_medical_appointments(context, author)
        elif next_action == 'ADD_TO_WAITLIST':
            return self._handle_waitlist_flow(context, author)
        elif next_action == 'CONFIRM_PRIVATE_PAYMENT':
            return self._handle_private_payment_confirmation(context, author)
        elif next_action == 'CONFIRM_SPECIAL_RATE':
            return self._handle_special_rate_confirmation(context, author)
        elif next_action == 'CONTACT_HUMAN_FOR_APPOINTMENT':
            return self._handle_human_contact(context, author)
        else:
            # Acción por defecto
            return self._show_medical_appointments(context, author)
    
    def _show_medical_appointments(self, context: Dict, author: str) -> Tuple[str, Dict, Optional[List[Dict]]]:
        """Muestra turnos disponibles usando la API de la clínica"""
        
        logger.info("[BALLESTER_AGENDA] Mostrando turnos disponibles con API clínica")
        
        # Extraer datos del contexto
        patient_data = context.get('patient_data', {})
        service_name = context.get('service_name', '')
        medical_verdict = context.get('medical_verdict', {})
        
        # Preparar parámetros para búsqueda
        search_params = {
            'service': service_name,
            'insurance': patient_data.get('obra_social', ''),
            'date_from': self._get_search_date(context)
        }
        
        # Verificar si es un caso especial (Dr. Malacchia)
        if medical_verdict.get('special_scheduling') == 'dr_malacchia_lunes':
            search_params['doctor'] = 'Dr. Malacchia'
            
        # Obtener turnos de la API OMNIA
        available_slots = self.clinica_api.get_available_appointments(**search_params)
        
        if not available_slots:
            return self._handle_no_appointments_available(context, author)
        
        # Filtrar y priorizar turnos según preferencias
        filtered_slots = self._filter_slots_by_preferences(available_slots, context)
        
        if not filtered_slots:
            return self._handle_no_preferred_appointments(context, author, available_slots)
        
        # Tomar solo los primeros 10 turnos para mostrar
        display_slots = filtered_slots[:10]
        
        # Guardar slots en contexto para referencias futuras
        context['available_slots'] = display_slots
        context['all_available_slots'] = available_slots
        context['current_state'] = 'BALLESTER_AGENDA_MOSTRANDO_OPCIONES'
        
        # Construir mensaje
        mensaje = self._build_appointments_message(display_slots, service_name, patient_data)
        
        # Construir botones interactivos
        botones = self._build_appointment_buttons(display_slots)
        
        return mensaje, context, botones
    
    def _build_appointments_message(self, slots: List[Dict], service: str, patient_data: Dict) -> str:
        """Construye el mensaje con los turnos disponibles"""
        
        obra_social = patient_data.get('obra_social', '')
        
        mensaje = f"""📅 **Turnos Disponibles - {service}**

👤 **Paciente:** {patient_data.get('nombre', 'No especificado')}
🏥 **Obra Social:** {obra_social}

**Selecciona el turno que prefieras:**

"""
        
        for i, slot in enumerate(slots, 1):
            # Formatear fecha y hora
            fecha_formateada = self._format_appointment_date(slot.get('date', ''), slot.get('time', ''))
            doctor = slot.get('doctor', 'No especificado')
            
            mensaje += f"**{i}.** {fecha_formateada} - {doctor}\n"
        
        mensaje += f"""\n💡 **Instrucciones:**
• Toca 'Ver Turnos' y selecciona el que prefieras
• Para salir del agendamiento, escribí: **SALIR DE AGENDA**
• Si necesitas otro día específico, escríbelo (ej: "viernes 17")

🏥 **Centro Pediátrico Ballester**
📍 Alvear 2307, Villa Ballester
📞 4616-6870 ó 11-5697-5007"""
        
        return mensaje
    
    def _build_appointment_buttons(self, slots: List[Dict]) -> List[Dict]:
        """Construye botones interactivos para selección de turnos"""
        
        botones = []
        
        # Agregar botón principal para mostrar opciones
        botones.append({
            "id": "ver_turnos_ballester",
            "title": "📅 Ver Turnos"
        })
        
        # Agregar botones de turnos específicos (máximo 8)
        for i, slot in enumerate(slots[:8], 1):
            fecha_corta = self._format_short_date(slot.get('date', ''), slot.get('time', ''))
            botones.append({
                "id": f"turno_ballester_{i}",
                "title": f"{i}. {fecha_corta}"
            })
        
        # Botón para salir
        botones.append({
            "id": "salir_agenda_ballester",
            "title": "❌ Salir"
        })
        
        return botones
    
    def process_appointment_selection(self, interactive_id: str, context: Dict, author: str) -> Tuple[str, Dict, Optional[List[Dict]]]:
        """Procesa la selección de un turno específico"""
        
        logger.info(f"[BALLESTER_AGENDA] Procesando selección: {interactive_id}")
        
        if interactive_id == 'ver_turnos_ballester':
            # Mostrar lista completa con opciones
            return self._show_appointment_list(context, author)
            
        elif interactive_id.startswith('turno_ballester_'):
            # Selección de turno específico
            slot_index = int(interactive_id.split('_')[-1]) - 1
            return self._confirm_appointment_selection(slot_index, context, author)
            
        elif interactive_id == 'salir_agenda_ballester':
            # Salir del flujo de agendamiento
            return self._exit_appointment_flow(context, author)
            
        else:
            # ID no reconocido, mostrar opciones nuevamente
            return self._show_medical_appointments(context, author)
    
    def _confirm_appointment_selection(self, slot_index: int, context: Dict, author: str) -> Tuple[str, Dict, Optional[List[Dict]]]:
        """Confirma la selección de un turno específico"""
        
        available_slots = context.get('available_slots', [])
        
        if slot_index < 0 or slot_index >= len(available_slots):
            logger.error(f"[BALLESTER_AGENDA] Índice de turno inválido: {slot_index}")
            return self._show_medical_appointments(context, author)
        
        selected_slot = available_slots[slot_index]
        patient_data = context.get('patient_data', {})
        service_name = context.get('service_name', '')
        medical_verdict = context.get('medical_verdict', {})
        
        # Guardar selección en contexto
        context['selected_slot'] = selected_slot
        context['current_state'] = 'BALLESTER_AGENDA_CONFIRMAR_TURNO'
        
        # Construir mensaje de confirmación
        fecha_completa = self._format_appointment_date(selected_slot.get('date'), selected_slot.get('time'))
        doctor = selected_slot.get('doctor', 'No especificado')
        
        mensaje = f"""✅ **Confirmar Turno Seleccionado**

👤 **Paciente:** {patient_data.get('nombre')}
🩺 **Servicio:** {service_name}
📅 **Fecha y Hora:** {fecha_completa}
👨‍⚕️ **Profesional:** {doctor}
🏥 **Obra Social:** {patient_data.get('obra_social')}

"""
        
        # Agregar información de pagos si corresponde
        payment_info = medical_verdict.get('payment_info', {})
        if payment_info:
            mensaje += "💰 **Información de Pago:**\n"
            
            if payment_info.get('copago'):
                mensaje += f"• Copago: ${payment_info['copago']}\n"
            if payment_info.get('bono_contribucion'):
                mensaje += f"• Bono Contribución: ${payment_info['bono_contribucion']}\n"
            if payment_info.get('arancel_especial'):
                mensaje += f"• Arancel Especial: ${payment_info['arancel_especial']}\n"
            if payment_info.get('particular_fee'):
                mensaje += f"• Arancel Particular: ${payment_info['particular_fee']}\n"
            
            mensaje += "\n"
        
        # Agregar requisitos si los hay
        requirements = medical_verdict.get('requirements', [])
        if requirements:
            mensaje += "📋 **Requisitos Necesarios:**\n"
            for req in requirements:
                mensaje += f"• {req}\n"
            mensaje += "\n"
        
        # Agregar preparaciones si las hay
        prep_instructions = medical_verdict.get('preparation_instructions', [])
        if prep_instructions:
            mensaje += "📝 **Preparación para el Estudio:**\n"
            for prep in prep_instructions:
                mensaje += f"• {prep}\n"
            mensaje += "\n"
        
        mensaje += "¿Confirmas este turno?"
        
        # Botones de confirmación
        botones = [
            {"id": "confirmar_turno_ballester", "title": "✅ Sí, confirmar"},
            {"id": "cambiar_turno_ballester", "title": "🔄 Elegir otro"},
            {"id": "cancelar_turno_ballester", "title": "❌ Cancelar"}
        ]
        
        return mensaje, context, botones
    
    def finalize_appointment(self, context: Dict, author: str) -> Tuple[str, Dict]:
        """Finaliza y confirma la cita en el sistema OMNIA"""
        
        logger.info("[BALLESTER_AGENDA] Finalizando confirmación de cita")
        
        selected_slot = context.get('selected_slot', {})
        patient_data = context.get('patient_data', {})
        service_name = context.get('service_name', '')
        
        if not selected_slot or not patient_data:
            logger.error("[BALLESTER_AGENDA] Datos incompletos para finalizar cita")
            return "Error: Datos incompletos para confirmar la cita.", context
        
        # Preparar datos para la API OMNIA
        appointment_data = {
            'patient_dni': patient_data.get('dni'),
            'service': service_name,
            'datetime': f"{selected_slot.get('date')}T{selected_slot.get('time')}:00",
            'doctor': selected_slot.get('doctor'),
            'insurance': patient_data.get('obra_social'),
            'contact_phone': patient_data.get('celular'),
            'contact_email': patient_data.get('email'),
            'notes': f"Turno confirmado via WhatsApp Bot V11 - Slot ID: {selected_slot.get('slot_id')}"
        }
        
        # Crear cita en el sistema OMNIA
        appointment_id = self.clinica_api.create_appointment(appointment_data)
        
        if appointment_id:
            # Cita creada exitosamente
            context['appointment_confirmed'] = True
            context['appointment_id'] = appointment_id
            context['current_state'] = 'BALLESTER_CITA_CONFIRMADA'
            
            # Construir mensaje de confirmación
            fecha_completa = self._format_appointment_date(selected_slot.get('date'), selected_slot.get('time'))
            
            mensaje = f"""✅ **¡TURNO CONFIRMADO EXITOSAMENTE!**

📋 **DETALLES DE TU CITA:**
🆔 **ID del Turno:** {appointment_id}
👤 **Paciente:** {patient_data.get('nombre')}
🩺 **Servicio:** {service_name}
📅 **Fecha y Hora:** {fecha_completa}
👨‍⚕️ **Profesional:** {selected_slot.get('doctor', 'No especificado')}
🏥 **Obra Social:** {patient_data.get('obra_social')}

📍 **CENTRO PEDIÁTRICO BALLESTER**
🏠 **Dirección:** Alvear 2307, Villa Ballester
📞 **Teléfonos:** 4616-6870 ó 11-5697-5007

⏰ **Horario de Atención:**
Lunes a Viernes de 9 a 13hs y de 14 a 20hs

💡 **Recomendaciones:**
• Llegar 15 minutos antes de la cita
• Traer DNI y credencial de obra social
• Si necesitas cancelar o reprogramar, contactanos

¡Gracias por elegirnos! 🏥"""
            
            # Enviar notificación al staff médico
            self._send_appointment_notification(appointment_data, appointment_id)
            
            return mensaje, context
            
        else:
            # Error creando cita
            logger.error("[BALLESTER_AGENDA] Error creando cita en sistema OMNIA")
            
            mensaje = """❌ **Error Confirmando Turno**

Se produjo un problema técnico al confirmar tu cita.

**¿Qué puedes hacer?**
• Intentar nuevamente en unos minutos
• Contactar directamente al centro:

📞 **4616-6870** ó **11-5697-5007**
🕐 **Horario:** Lunes a Viernes 9 a 19hs

Disculpa las molestias. ¡Estamos aquí para ayudarte!"""
            
            return mensaje, context
    
    def _handle_waitlist_flow(self, context: Dict, author: str) -> Tuple[str, Dict, Optional[List[Dict]]]:
        """Maneja el flujo de lista de espera"""
        
        logger.info("[BALLESTER_AGENDA] Manejando flujo de lista de espera")
        
        patient_data = context.get('patient_data', {})
        service_name = context.get('service_name', '')
        medical_verdict = context.get('medical_verdict', {})
        
        mensaje = medical_verdict.get('message_to_user', 'Lista de espera disponible.')
        
        # Botones para lista de espera
        botones = [
            {"id": "agregar_lista_espera_ballester", "title": "⏳ Sí, agregar a lista"},
            {"id": "no_lista_espera_ballester", "title": "❌ No, gracias"}
        ]
        
        context['current_state'] = 'BALLESTER_ESPERANDO_CONFIRMACION_LISTA'
        
        return mensaje, context, botones
    
    def add_to_waitlist(self, context: Dict, author: str) -> Tuple[str, Dict]:
        """Agrega paciente a lista de espera"""
        
        logger.info("[BALLESTER_AGENDA] Agregando paciente a lista de espera")
        
        patient_data = context.get('patient_data', {})
        service_name = context.get('service_name', '')
        medical_verdict = context.get('medical_verdict', {})
        
        # Preparar datos para lista de espera
        waitlist_data = {
            'patient_dni': patient_data.get('dni'),
            'patient_name': patient_data.get('nombre'),
            'service': service_name,
            'insurance': patient_data.get('obra_social'),
            'contact_phone': patient_data.get('celular'),
            'contact_email': patient_data.get('email'),
            'priority': 'normal',
            'notes': f'Agregado via WhatsApp Bot V11 - {medical_verdict.get("coverage_status", "")}'
        }
        
        # Agregar a lista de espera en sistema OMNIA
        waitlist_id = self.clinica_api.add_to_waitlist(waitlist_data)
        
        if waitlist_id:
            # Agregado exitosamente
            context['waitlist_confirmed'] = True
            context['waitlist_id'] = waitlist_id
            context['current_state'] = 'BALLESTER_LISTA_ESPERA_CONFIRMADA'
            
            mensaje = f"""✅ **¡AGREGADO A LISTA DE ESPERA!**

📋 **DETALLES:**
🆔 **ID Lista:** {waitlist_id}
👤 **Paciente:** {patient_data.get('nombre')}
🩺 **Servicio:** {service_name}
🏥 **Obra Social:** {patient_data.get('obra_social')}

📞 **¿Cómo continuamos?**
• Te contactaremos cuando haya disponibilidad
• Tiempo estimado: depende de la demanda
• Puedes consultar el estado llamando al centro

📍 **CENTRO PEDIÁTRICO BALLESTER**
📞 **4616-6870** ó **11-5697-5007**

¡Gracias por tu paciencia! 🏥"""
            
            return mensaje, context
            
        else:
            # Error agregando a lista
            mensaje = """❌ **Error en Lista de Espera**

No pudimos agregarte a la lista de espera en este momento.

Por favor, contacta directamente al centro:
📞 **4616-6870** ó **11-5697-5007**"""
            
            return mensaje, context
    
    # =================== MÉTODOS AUXILIARES ===================
    
    def _get_search_date(self, context: Dict) -> str:
        """Obtiene la fecha desde cuándo buscar turnos"""
        
        # Si hay fecha deseada en el contexto, usarla
        fecha_deseada = context.get('fecha_deseada')
        if fecha_deseada:
            return fecha_deseada
        
        # Por defecto, buscar desde mañana
        tomorrow = datetime.now() + timedelta(days=1)
        return tomorrow.strftime('%Y-%m-%d')
    
    def _filter_slots_by_preferences(self, slots: List[Dict], context: Dict) -> List[Dict]:
        """Filtra turnos según preferencias del usuario"""
        
        # Implementar filtros según preferencias horarias, días, etc.
        # Por ahora retorna todos los slots disponibles
        return slots
    
    def _format_appointment_date(self, date: str, time: str) -> str:
        """Formatea fecha y hora para mostrar al usuario"""
        
        try:
            # Parsear fecha
            date_obj = datetime.strptime(date, '%Y-%m-%d')
            
            # Formatear en español
            dias_semana = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
            meses = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
                    'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']
            
            dia_semana = dias_semana[date_obj.weekday()]
            mes = meses[date_obj.month - 1]
            
            return f"{dia_semana} {date_obj.day} de {mes} a las {time}hs"
            
        except:
            return f"{date} {time}"
    
    def _format_short_date(self, date: str, time: str) -> str:
        """Formatea fecha corta para botones"""
        
        try:
            date_obj = datetime.strptime(date, '%Y-%m-%d')
            return f"{date_obj.day}/{date_obj.month} {time}"
        except:
            return f"{date} {time}"
    
    def _handle_no_appointments_available(self, context: Dict, author: str) -> Tuple[str, Dict, Optional[List[Dict]]]:
        """Maneja cuando no hay turnos disponibles"""
        
        service_name = context.get('service_name', '')
        
        mensaje = f"""❌ **No hay turnos disponibles**

No encontramos turnos disponibles para **{service_name}** en los próximos días.

**Opciones disponibles:**
• Lista de espera
• Contactar directamente al centro
• Intentar con fechas más lejanas

📞 **Centro Pediátrico Ballester:**
4616-6870 ó 11-5697-5007

¿Qué prefieres hacer?"""
        
        botones = [
            {"id": "agregar_lista_espera_ballester", "title": "⏳ Lista de espera"},
            {"id": "contactar_centro_ballester", "title": "📞 Contactar centro"},
            {"id": "salir_agenda_ballester", "title": "❌ Salir"}
        ]
        
        return mensaje, context, botones
    
    def _send_appointment_notification(self, appointment_data: Dict, appointment_id: str):
        """Envía notificación al staff médico sobre cita confirmada"""
        
        try:
            # Construir mensaje para staff
            staff_message = f"""🏥 **NUEVO TURNO CONFIRMADO**

🆔 **ID:** {appointment_id}
👤 **Paciente:** {appointment_data.get('patient_dni')} 
📧 **Contacto:** {appointment_data.get('contact_phone')}
🏥 **Obra Social:** {appointment_data.get('insurance')}
🩺 **Servicio:** {appointment_data.get('service')}
📅 **Fecha/Hora:** {appointment_data.get('datetime')}
👨‍⚕️ **Doctor:** {appointment_data.get('doctor')}

⏰ **Confirmado:** {datetime.now().strftime('%d/%m/%Y %H:%M')}
🤖 **Vía:** OptiAtiende-IA Bot V11"""
            
            # Enviar notificación (si está configurado)
            notification_contact = getattr(config, 'NOTIFICATION_CONTACT', None)
            if notification_contact:
                msgio_handler.send_message(notification_contact, staff_message)
                logger.info(f"[BALLESTER_AGENDA] Notificación enviada al staff: {appointment_id}")
            
        except Exception as e:
            logger.error(f"[BALLESTER_AGENDA] Error enviando notificación al staff: {e}")
    
    def _exit_appointment_flow(self, context: Dict, author: str) -> Tuple[str, Dict, Optional[List[Dict]]]:
        """Sale del flujo de agendamiento"""
        
        # Limpiar contexto médico pero preservar datos básicos
        clean_context = {
            'author': context.get('author'),
            'senderName': context.get('senderName'),
            'current_state': 'conversando'
        }
        
        mensaje = """✅ **Has salido del agendamiento**

¿En qué más puedo ayudarte?

Puedes escribir:
• "QUIERO AGENDAR" para volver al agendamiento
• "QUIERO CONSULTAR COBERTURA" para verificar coberturas
• O cualquier consulta que tengas

¡Estamos aquí para ayudarte! 🏥"""
        
        return mensaje, clean_context, None


# =================== FUNCIONES HELPER PARA MAIN.PY ===================

def handle_ballester_appointment_flow(context: Dict, author: str, verdict: Dict) -> Tuple[str, Dict, Optional[List[Dict]]]:
    """Función helper para usar desde main.py"""
    adapter = BallesterAgendamientoAdapter()
    return adapter.handle_medical_appointment_flow(context, author, verdict)

def process_ballester_appointment_selection(interactive_id: str, context: Dict, author: str) -> Tuple[str, Dict, Optional[List[Dict]]]:
    """Función helper para procesar selecciones interactivas"""
    adapter = BallesterAgendamientoAdapter()
    return adapter.process_appointment_selection(interactive_id, context, author)

def finalize_ballester_appointment(context: Dict, author: str) -> Tuple[str, Dict]:
    """Función helper para finalizar citas"""
    adapter = BallesterAgendamientoAdapter()
    return adapter.finalize_appointment(context, author)
