"""
ballester_notifications.py - Sistema de Notificaciones Centro Pediátrico Ballester
Sistema V11 - Gestión Completa de Notificaciones y Escalación Médica

Este módulo maneja todas las notificaciones específicas del Centro Pediátrico Ballester:
- Detección de frustración del cliente
- Sistema /clientedemorado con escalación inteligente
- Notificaciones al staff médico sobre turnos confirmados
- Alertas de lista de espera
- Manejo de horarios de atención para derivaciones

CRÍTICO: Este sistema debe ser inteligente para detectar cuándo escalar y cuándo no,
evitando spam al personal médico pero asegurando que ningún paciente quede sin atención.

Autor: Sistema OPTIATIENDE-IA V11
Cliente: Centro Pediátrico Ballester
Fecha: Enero 2025
"""

import logging
import json
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple

import config
import memory
import msgio_handler

logger = logging.getLogger(config.TENANT_NAME)

class BallesterNotificationSystem:
    """
    Sistema de notificaciones específico para Centro Pediátrico Ballester.
    
    Maneja la escalación inteligente, detección de frustración, y notificaciones
    al staff médico con contexto completo.
    """
    
    # Configuración específica de Ballester
    STAFF_CONTACT = "5493413167185"  # Contacto del staff médico (desde config después)
    BUSINESS_HOURS = {
        'start': 9,
        'end': 19,
        'days': ['monday', 'tuesday', 'wednesday', 'thursday', 'friday']
    }
    
    # Patrones de frustración del cliente
    FRUSTRATION_PATTERNS = [
        'no entiendo',
        'no me sirve',
        'esto no funciona',
        'me canse',
        'basta',
        'ya probe',
        'no puedo',
        'dificil',
        'complicado',
        'me perdí',
        'confuso',
        'ayuda',
        'ayudame',
        'no se que hacer',
        'hable con una persona',
        'operador',
        'humano',
        'persona real',
        'telefono',
        'llamar',
        'comunicar'
    ]
    
    # Umbrales para detección de frustración
    FRUSTRATION_THRESHOLDS = {
        'message_count': 8,        # Si envía más de 8 mensajes sin progreso
        'same_message_count': 3,   # Si repite el mismo mensaje 3 veces
        'time_in_flow': 600,      # Si está más de 10 minutos en el mismo flujo
        'pattern_matches': 2       # Si usa 2 o más patrones de frustración
    }
    
    def __init__(self):
        """Inicializa el sistema de notificaciones"""
        
        # Configurar contacto del staff desde configuración
        self.staff_contact = getattr(config, 'NOTIFICATION_CONTACT', self.STAFF_CONTACT)
        logger.info(f"[BALLESTER_NOTIF] Sistema de notificaciones inicializado - Staff: {self.staff_contact}")
    
    def detect_client_frustration(self, mensaje_usuario: str, context: Dict, history: List[Dict]) -> Dict[str, Any]:
        """
        Detecta si el cliente está frustrado y necesita escalación.
        
        Esta función analiza múltiples señales de frustración y determina
        si se debe activar el sistema /clientedemorado.
        
        Args:
            mensaje_usuario: Último mensaje del cliente
            context: Contexto actual de la conversación
            history: Historial completo de la conversación
            
        Returns:
            Dict con análisis de frustración y recomendación de escalación
        """
        logger.info("[BALLESTER_NOTIF] Analizando posible frustración del cliente")
        
        frustration_score = 0
        detected_signals = []
        
        # ========== SEÑAL 1: PATRONES DE FRUSTRACIÓN EN EL MENSAJE ==========
        mensaje_lower = mensaje_usuario.lower().strip()
        pattern_count = 0
        
        for pattern in self.FRUSTRATION_PATTERNS:
            if pattern in mensaje_lower:
                pattern_count += 1
                detected_signals.append(f"Patrón frustrante: '{pattern}'")
        
        if pattern_count >= self.FRUSTRATION_THRESHOLDS['pattern_matches']:
            frustration_score += 3
            detected_signals.append(f"Múltiples patrones de frustración ({pattern_count})")
        
        # ========== SEÑAL 2: REPETICIÓN DEL MISMO MENSAJE ==========
        recent_messages = [msg.get('content', '') for msg in history[-5:] if msg.get('role') == 'user']
        same_message_count = recent_messages.count(mensaje_usuario) if recent_messages else 0
        
        if same_message_count >= self.FRUSTRATION_THRESHOLDS['same_message_count']:
            frustration_score += 2
            detected_signals.append(f"Mensaje repetido {same_message_count} veces")
        
        # ========== SEÑAL 3: DEMASIADOS MENSAJES SIN PROGRESO ==========
        user_messages = [msg for msg in history if msg.get('role') == 'user']
        message_count = len(user_messages)
        
        # Verificar progreso: si está en el mismo estado por mucho tiempo
        current_state = context.get('current_state', '')
        verification_state = context.get('verification_state', '')
        
        if message_count >= self.FRUSTRATION_THRESHOLDS['message_count'] and not context.get('progress_made'):
            frustration_score += 2
            detected_signals.append(f"Muchos mensajes sin progreso ({message_count})")
        
        # ========== SEÑAL 4: TIEMPO EXCESIVO EN EL MISMO FLUJO ==========
        flow_start_time = context.get('flow_start_time')
        if flow_start_time:
            try:
                start_time = datetime.fromisoformat(flow_start_time)
                time_in_flow = (datetime.now() - start_time).total_seconds()
                
                if time_in_flow > self.FRUSTRATION_THRESHOLDS['time_in_flow']:
                    frustration_score += 2
                    detected_signals.append(f"Tiempo excesivo en flujo ({int(time_in_flow/60)} minutos)")
            except:
                pass
        
        # ========== SEÑAL 5: ESTADOS PROBLEMÁTICOS ==========
        if current_state in ['LOCKED', 'ERROR', 'FAILED']:
            frustration_score += 3
            detected_signals.append(f"Estado problemático: {current_state}")
        
        # ========== EVALUACIÓN FINAL ==========
        should_escalate = frustration_score >= 5  # Umbral de escalación
        escalation_urgency = 'high' if frustration_score >= 8 else 'medium'
        
        analysis = {
            'frustration_detected': should_escalate,
            'frustration_score': frustration_score,
            'escalation_urgency': escalation_urgency,
            'detected_signals': detected_signals,
            'recommendation': 'escalate_to_human' if should_escalate else 'continue_bot',
            'reason': f"Score {frustration_score}/10 - {len(detected_signals)} señales detectadas"
        }
        
        logger.info(f"[BALLESTER_NOTIF] Análisis frustración: {analysis}")
        
        return analysis
    
    def trigger_client_delayed_flow(self, context: Dict, author: str, frustration_analysis: Dict) -> Tuple[str, Dict, Optional[List[Dict]]]:
        """
        Activa el flujo /clientedemorado cuando se detecta frustración crítica.
        
        Args:
            context: Contexto actual con todos los datos recopilados
            author: ID del cliente
            frustration_analysis: Análisis de frustración detectada
            
        Returns:
            Tuple con mensaje, contexto actualizado, y botones de escalación
        """
        logger.info("[BALLESTER_NOTIF] Activando flujo /clientedemorado")
        
        # Marcar que se activó el flujo de escalación
        context['escalation_triggered'] = True
        context['escalation_timestamp'] = datetime.now().isoformat()
        context['escalation_reason'] = frustration_analysis.get('reason', 'Frustración detectada')
        context['current_state'] = 'BALLESTER_CLIENT_ESCALATION'
        
        # Mensaje empático y profesional para el cliente
        mensaje_cliente = f"""🏥 **Centro Pediátrico Ballester**

Entiendo que puedes estar teniendo algunas dificultades con nuestro sistema automatizado.

**¿Te gustaría que nuestro equipo médico se comunique contigo directamente?**

Nuestros profesionales pueden ayudarte personalmente con:
• Agendamiento de turnos
• Consultas sobre coberturas
• Información sobre estudios y preparaciones
• Cualquier duda que tengas

📞 **También puedes llamar directamente:**
4616-6870 ó 11-5697-5007
🕐 Lunes a Viernes de 9 a 19hs

¿Cómo prefieres continuar?"""
        
        # Botones de escalación
        botones = [
            {"id": "si_contacto_humano_ballester", "title": "✅ Sí, que me contacten"},
            {"id": "no_continuar_bot_ballester", "title": "🤖 Seguir con el bot"}
        ]
        
        return mensaje_cliente, context, botones
    
    def handle_escalation_confirmation(self, choice: str, context: Dict, author: str, history: List[Dict]) -> Tuple[str, Dict]:
        """
        Maneja la confirmación de escalación del cliente.
        
        Args:
            choice: Elección del cliente (si_contacto o no_continuar)
            context: Contexto con todos los datos recopilados
            author: ID del cliente
            history: Historial completo para enviar al staff
            
        Returns:
            Tuple con mensaje de respuesta y contexto actualizado
        """
        logger.info(f"[BALLESTER_NOTIF] Procesando confirmación de escalación: {choice}")
        
        if choice == 'si_contacto_humano_ballester':
            # Cliente acepta escalación, notificar al staff
            notification_sent = self._send_escalation_notification(context, author, history)
            
            if notification_sent:
                context['escalation_confirmed'] = True
                context['staff_notified'] = True
                context['current_state'] = 'BALLESTER_ESCALATION_COMPLETED'
                
                mensaje = """✅ **¡Listo! Escalación Activada**

He notificado a nuestro equipo médico sobre tu consulta.

**¿Qué sigue?**
• Te contactarán en los próximos **15 minutos**
• Te llamarán al número desde el que escribes
• Si no contestan, volverán a intentar

📞 **Mientras tanto, también puedes llamar:**
**4616-6870** ó **11-5697-5007**
🕐 Lunes a Viernes de 9 a 19hs

📍 **Centro Pediátrico Ballester**
Alvear 2307, Villa Ballester

¡Gracias por elegirnos! 🏥"""
                
            else:
                mensaje = """❌ **Error en la Escalación**

No pude enviar la notificación al equipo en este momento.

Por favor, contacta directamente:
📞 **4616-6870** ó **11-5697-5007**
🕐 Lunes a Viernes de 9 a 19hs

¡Disculpa las molestias!"""
            
            return mensaje, context
            
        elif choice == 'no_continuar_bot_ballester':
            # Cliente prefiere continuar con el bot
            context['escalation_declined'] = True
            context['current_state'] = 'conversando'
            
            mensaje = """🤖 **¡Perfecto! Continuemos**

Entiendo, sigamos juntos. Voy a ayudarte paso a paso.

**Para una experiencia más fluida, puedes usar estos comandos:**
• **"QUIERO AGENDAR"** - Para solicitar turnos
• **"QUIERO CONSULTAR COBERTURA"** - Para verificar tu obra social
• **"QUIERO CANCELAR"** - Para cancelar turnos

¿Qué necesitas hacer hoy? Te guío paso a paso. 😊"""
            
            return mensaje, context
        
        else:
            # Opción no reconocida
            return self.trigger_client_delayed_flow(context, author, {'reason': 'Opción de escalación no reconocida'})
    
    def _send_escalation_notification(self, context: Dict, author: str, history: List[Dict]) -> bool:
        """
        Envía notificación detallada al staff médico sobre escalación de cliente.
        
        Args:
            context: Contexto completo con datos del paciente
            author: ID del cliente (teléfono WhatsApp)
            history: Historial completo de la conversación
            
        Returns:
            True si se envió exitosamente, False si falló
        """
        logger.info(f"[BALLESTER_NOTIF] Enviando notificación de escalación para {author}")
        
        try:
            # Extraer datos del paciente si están disponibles
            patient_data = context.get('patient_data', {})
            service_name = context.get('service_name', 'No especificado')
            verification_state = context.get('verification_state', 'No iniciada')
            escalation_reason = context.get('escalation_reason', 'Cliente solicitó ayuda')
            
            # Construir información del progreso
            progress_info = self._analyze_client_progress(context, history)
            
            # Construir mensaje detallado para el staff
            staff_message = f"""🚨 **ESCALACIÓN REQUERIDA - Cliente con Dificultades**

⏰ **Timestamp:** {datetime.now().strftime('%d/%m/%Y %H:%M')}
📱 **WhatsApp Cliente:** {author}
🤖 **Sistema:** OptiAtiende-IA V11

👤 **INFORMACIÓN DEL PACIENTE:**
• **Nombre:** {patient_data.get('nombre', 'No recopilado')}
• **DNI:** {patient_data.get('dni', 'No recopilado')}
• **Obra Social:** {patient_data.get('obra_social', 'No recopilada')}
• **Plan:** {patient_data.get('plan', 'No recopilado')}
• **Teléfono:** {patient_data.get('celular', author)}
• **Email:** {patient_data.get('email', 'No recopilado')}

🎯 **SERVICIO SOLICITADO:**
• **Especialidad/Estudio:** {service_name}
• **Estado de Verificación:** {verification_state}

📊 **ANÁLISIS DEL PROGRESO:**
• **Progreso completado:** {progress_info['completion_percentage']}%
• **Estado actual:** {context.get('current_state', 'Desconocido')}
• **Tiempo en el sistema:** {progress_info['time_in_system']} minutos
• **Mensajes enviados:** {progress_info['user_message_count']}

⚠️ **RAZÓN DE ESCALACIÓN:**
{escalation_reason}

🗨️ **ÚLTIMOS 3 MENSAJES DEL CLIENTE:**
{self._format_last_messages(history, 3)}

🔄 **PRÓXIMOS PASOS RECOMENDADOS:**
1. Contactar al cliente en los próximos 15 minutos
2. Ayudar a completar el proceso de {service_name}
3. Registrar el turno manualmente si es necesario
4. Reportar cualquier mejora necesaria al sistema

📞 **Acción:** CONTACTAR AL CLIENTE AHORA"""
            
            # Enviar notificación al staff
            if self.staff_contact and self._is_business_hours():
                result = msgio_handler.send_message(self.staff_contact, staff_message)
                
                if result:
                    logger.info(f"[BALLESTER_NOTIF] ✅ Notificación de escalación enviada exitosamente")
                    
                    # Registrar escalación en memoria para auditoría
                    self._log_escalation_to_memory(author, context, escalation_reason)
                    
                    return True
                else:
                    logger.error("[BALLESTER_NOTIF] ❌ Error enviando notificación de escalación")
                    return False
            
            elif not self._is_business_hours():
                # Fuera de horario laboral, programar notificación
                self._schedule_out_of_hours_notification(context, author, staff_message)
                return True
            
            else:
                logger.error("[BALLESTER_NOTIF] Staff contact no configurado")
                return False
                
        except Exception as e:
            logger.error(f"[BALLESTER_NOTIF] ❌ Error enviando notificación de escalación: {e}", exc_info=True)
            return False
    
    def send_appointment_confirmed_notification(self, appointment_data: Dict, patient_data: Dict) -> bool:
        """
        Envía notificación al staff sobre turno confirmado exitosamente.
        
        Args:
            appointment_data: Datos de la cita confirmada
            patient_data: Datos completos del paciente
            
        Returns:
            True si se envió exitosamente
        """
        logger.info("[BALLESTER_NOTIF] Enviando notificación de turno confirmado")
        
        try:
            # Construir mensaje para el staff
            staff_message = f"""🏥 **NUEVO TURNO CONFIRMADO**

⏰ **Confirmado:** {datetime.now().strftime('%d/%m/%Y %H:%M')}
🆔 **ID Turno:** {appointment_data.get('appointment_id', 'No disponible')}

👤 **DATOS DEL PACIENTE:**
• **Nombre:** {patient_data.get('nombre')}
• **DNI:** {patient_data.get('dni')}
• **Fecha Nac.:** {patient_data.get('fecha_nacimiento')}
• **Teléfono:** {patient_data.get('celular')}
• **Email:** {patient_data.get('email')}

🏥 **INFORMACIÓN MÉDICA:**
• **Obra Social:** {patient_data.get('obra_social')}
• **Plan:** {patient_data.get('plan')}
• **N° Afiliado:** {patient_data.get('numero_afiliado')}

🩺 **DETALLES DE LA CITA:**
• **Servicio:** {appointment_data.get('service')}
• **Fecha:** {appointment_data.get('date')}
• **Hora:** {appointment_data.get('time')}
• **Doctor:** {appointment_data.get('doctor')}

💰 **INFORMACIÓN DE PAGO:**
{self._format_payment_info(appointment_data.get('payment_info', {}))}

🤖 **Confirmado vía:** OptiAtiende-IA Bot V11
📱 **WhatsApp:** {appointment_data.get('patient_whatsapp', 'No disponible')}"""
            
            # Enviar notificación
            if self.staff_contact:
                result = msgio_handler.send_message(self.staff_contact, staff_message)
                
                if result:
                    logger.info("[BALLESTER_NOTIF] ✅ Notificación de turno confirmado enviada")
                    return True
                else:
                    logger.error("[BALLESTER_NOTIF] ❌ Error enviando notificación de turno")
                    return False
            else:
                logger.warning("[BALLESTER_NOTIF] Staff contact no configurado para notificaciones")
                return False
                
        except Exception as e:
            logger.error(f"[BALLESTER_NOTIF] ❌ Error enviando notificación de turno: {e}", exc_info=True)
            return False
    
    def send_waitlist_notification(self, waitlist_data: Dict, patient_data: Dict) -> bool:
        """
        Envía notificación al staff sobre paciente agregado a lista de espera.
        
        Args:
            waitlist_data: Datos de la lista de espera
            patient_data: Datos del paciente
            
        Returns:
            True si se envió exitosamente
        """
        logger.info("[BALLESTER_NOTIF] Enviando notificación de lista de espera")
        
        try:
            staff_message = f"""⏳ **NUEVO PACIENTE EN LISTA DE ESPERA**

⏰ **Agregado:** {datetime.now().strftime('%d/%m/%Y %H:%M')}
🆔 **ID Lista:** {waitlist_data.get('waitlist_id', 'No disponible')}

👤 **PACIENTE:**
• **Nombre:** {patient_data.get('nombre')}
• **DNI:** {patient_data.get('dni')}
• **Teléfono:** {patient_data.get('celular')}
• **Obra Social:** {patient_data.get('obra_social')}

🩺 **SERVICIO:** {waitlist_data.get('service')}
📞 **WhatsApp:** {waitlist_data.get('patient_whatsapp')}

🤖 **Agregado vía:** OptiAtiende-IA Bot V11

**Recordatorio:** Contactar cuando haya disponibilidad"""
            
            # Enviar notificación
            if self.staff_contact:
                result = msgio_handler.send_message(self.staff_contact, staff_message)
                
                if result:
                    logger.info("[BALLESTER_NOTIF] ✅ Notificación de lista de espera enviada")
                    return True
                else:
                    logger.error("[BALLESTER_NOTIF] ❌ Error enviando notificación de lista de espera")
                    return False
            else:
                logger.warning("[BALLESTER_NOTIF] Staff contact no configurado")
                return False
                
        except Exception as e:
            logger.error(f"[BALLESTER_NOTIF] ❌ Error enviando notificación de lista de espera: {e}", exc_info=True)
            return False
    
    def get_out_of_hours_message(self) -> str:
        """Retorna mensaje para cuando el sistema está fuera del horario de atención"""
        
        return """🕐 **Fuera del Horario de Atención**

En este momento, nuestro personal no está disponible para derivaciones humanas.

📞 **Horario de Atención:**
**Lunes a Viernes de 9 a 19hs**

🤖 **Opciones disponibles ahora:**
• Continuar con el bot automatizado
• Dejar tu consulta detallada para mañana
• Para urgencias: **4616-6870** ó **11-5697-5007**

Por favor, déjanos tu consulta detallada y te responderemos mañana o el lunes a partir de las 9hs."""
    
    # =================== MÉTODOS AUXILIARES ===================
    
    def _analyze_client_progress(self, context: Dict, history: List[Dict]) -> Dict[str, Any]:
        """Analiza el progreso del cliente en el sistema"""
        
        # Contar mensajes del usuario
        user_messages = [msg for msg in history if msg.get('role') == 'user']
        user_message_count = len(user_messages)
        
        # Calcular tiempo en el sistema
        first_message_time = None
        if history:
            try:
                first_message_time = datetime.fromisoformat(history[0].get('timestamp', ''))
                time_in_system = (datetime.now() - first_message_time).total_seconds() / 60
            except:
                time_in_system = 0
        else:
            time_in_system = 0
        
        # Calcular porcentaje de completitud
        completion_percentage = 0
        
        verification_state = context.get('verification_state', '')
        if verification_state == 'IDENTIFICAR_PRACTICA':
            completion_percentage = 25
        elif verification_state == 'IDENTIFICAR_PACIENTE':
            completion_percentage = 50
        elif verification_state == 'VERIFICAR_DATOS':
            completion_percentage = 75
        elif verification_state == 'OBTENER_VEREDICTO':
            completion_percentage = 90
        elif context.get('verification_completed'):
            completion_percentage = 100
        
        return {
            'user_message_count': user_message_count,
            'time_in_system': round(time_in_system, 1),
            'completion_percentage': completion_percentage,
            'has_patient_data': bool(context.get('patient_data')),
            'has_service_selected': bool(context.get('service_name')),
            'verification_completed': context.get('verification_completed', False)
        }
    
    def _format_last_messages(self, history: List[Dict], count: int = 3) -> str:
        """Formatea los últimos N mensajes para incluir en notificaciones"""
        
        if not history:
            return "Sin historial disponible"
        
        # Obtener últimos mensajes del usuario y del bot
        recent_messages = history[-count*2:]  # Tomar más para asegurar que hay suficientes
        formatted_messages = []
        
        for msg in recent_messages:
            role = msg.get('role', 'unknown')
            content = msg.get('content', '')
            timestamp = msg.get('timestamp', '')
            
            try:
                # Formatear timestamp
                if timestamp:
                    dt = datetime.fromisoformat(timestamp)
                    time_str = dt.strftime('%H:%M')
                else:
                    time_str = 'N/A'
            except:
                time_str = 'N/A'
            
            if role == 'user':
                formatted_messages.append(f"[{time_str}] Cliente: {content}")
            else:
                formatted_messages.append(f"[{time_str}] Bot: {content}")
        
        return '\n'.join(formatted_messages[-count*2:])  # Últimos N intercambios
    
    def _format_payment_info(self, payment_info: Dict) -> str:
        """Formatea información de pagos para notificaciones"""
        
        if not payment_info:
            return "Sin información de pagos"
        
        info_lines = []
        
        if payment_info.get('copago'):
            info_lines.append(f"• Copago: ${payment_info['copago']}")
        
        if payment_info.get('bono_contribucion'):
            info_lines.append(f"• Bono Contribución: ${payment_info['bono_contribucion']}")
        
        if payment_info.get('particular_fee'):
            info_lines.append(f"• Arancel Particular: ${payment_info['particular_fee']}")
        
        if payment_info.get('arancel_especial'):
            info_lines.append(f"• Arancel Especial: ${payment_info['arancel_especial']}")
        
        return '\n'.join(info_lines) if info_lines else "Cobertura total por obra social"
    
    def _is_business_hours(self) -> bool:
        """Verifica si estamos en horario laboral"""
        
        now = datetime.now()
        current_hour = now.hour
        current_day = now.strftime('%A').lower()
        
        # Verificar día de la semana
        if current_day not in self.BUSINESS_HOURS['days']:
            return False
        
        # Verificar hora (9 a 19hs)
        if self.BUSINESS_HOURS['start'] <= current_hour < self.BUSINESS_HOURS['end']:
            return True
        
        return False
    
    def _schedule_out_of_hours_notification(self, context: Dict, author: str, message: str):
        """Programa notificación para el próximo horario laboral"""
        
        logger.info("[BALLESTER_NOTIF] Programando notificación para horario laboral")
        
        # En producción, esto se implementaría con un sistema de colas o scheduler
        # Por ahora, simplemente logueamos la intención
        logger.warning(f"[BALLESTER_NOTIF] Notificación fuera de horario programada para {author}")
        
        # Guardar en memoria para procesamiento posterior
        try:
            out_of_hours_data = {
                'author': author,
                'context': context,
                'message': message,
                'scheduled_for': self._get_next_business_hour(),
                'created_at': datetime.now().isoformat()
            }
            
            # Guardar en Firebase para procesamiento posterior
            memory.save_out_of_hours_notification(author, out_of_hours_data)
            
        except Exception as e:
            logger.error(f"[BALLESTER_NOTIF] Error programando notificación: {e}")
    
    def _get_next_business_hour(self) -> str:
        """Calcula la próxima hora laboral"""
        
        now = datetime.now()
        
        # Si es fin de semana, ir al próximo lunes a las 9
        if now.weekday() >= 5:  # Sábado o domingo
            days_until_monday = 7 - now.weekday()
            next_business_day = now + timedelta(days=days_until_monday)
            next_business_time = next_business_day.replace(hour=9, minute=0, second=0, microsecond=0)
        
        # Si es día laboral pero fuera de horario
        elif now.hour < 9:
            # Mismo día a las 9
            next_business_time = now.replace(hour=9, minute=0, second=0, microsecond=0)
        
        elif now.hour >= 19:
            # Próximo día laboral a las 9
            tomorrow = now + timedelta(days=1)
            if tomorrow.weekday() >= 5:  # Si mañana es fin de semana
                days_until_monday = 7 - tomorrow.weekday()
                next_business_time = tomorrow + timedelta(days=days_until_monday)
                next_business_time = next_business_time.replace(hour=9, minute=0, second=0, microsecond=0)
            else:
                next_business_time = tomorrow.replace(hour=9, minute=0, second=0, microsecond=0)
        
        else:
            # Dentro del horario laboral (esto no debería pasar si se llama correctamente)
            next_business_time = now
        
        return next_business_time.isoformat()
    
    def _log_escalation_to_memory(self, author: str, context: Dict, reason: str):
        """Guarda registro de escalación en memoria para auditoría"""
        
        try:
            escalation_log = {
                'author': author,
                'timestamp': datetime.now().isoformat(),
                'reason': reason,
                'context_snapshot': context.copy(),
                'escalation_type': 'client_frustration',
                'system_version': 'V11'
            }
            
            # Guardar en Firebase
            memory.save_escalation_log(author, escalation_log)
            
            logger.info(f"[BALLESTER_NOTIF] Escalación registrada en memoria para auditoría")
            
        except Exception as e:
            logger.error(f"[BALLESTER_NOTIF] Error guardando escalación en memoria: {e}")


# =================== FUNCIONES HELPER PARA MAIN.PY ===================

def detect_ballester_frustration(mensaje_usuario: str, context: Dict, history: List[Dict]) -> Dict[str, Any]:
    """Función helper para detectar frustración desde main.py o meta-agente"""
    notif_system = BallesterNotificationSystem()
    return notif_system.detect_client_frustration(mensaje_usuario, context, history)

def trigger_ballester_escalation(context: Dict, author: str, frustration_analysis: Dict) -> Tuple[str, Dict, Optional[List[Dict]]]:
    """Función helper para activar escalación desde main.py"""
    notif_system = BallesterNotificationSystem()
    return notif_system.trigger_client_delayed_flow(context, author, frustration_analysis)

def handle_ballester_escalation_choice(choice: str, context: Dict, author: str, history: List[Dict]) -> Tuple[str, Dict]:
    """Función helper para manejar elección de escalación"""
    notif_system = BallesterNotificationSystem()
    return notif_system.handle_escalation_confirmation(choice, context, author, history)

def notify_ballester_appointment_confirmed(appointment_data: Dict, patient_data: Dict) -> bool:
    """Función helper para notificar turno confirmado"""
    notif_system = BallesterNotificationSystem()
    return notif_system.send_appointment_confirmed_notification(appointment_data, patient_data)

def notify_ballester_waitlist_added(waitlist_data: Dict, patient_data: Dict) -> bool:
    """Función helper para notificar agregado a lista de espera"""
    notif_system = BallesterNotificationSystem()
    return notif_system.send_waitlist_notification(waitlist_data, patient_data)

def get_ballester_out_of_hours_message() -> str:
    """Función helper para mensaje fuera de horario"""
    notif_system = BallesterNotificationSystem()
    return notif_system.get_out_of_hours_message()
