"""
ballester_main_extensions.py - Extensiones Main.py para Centro Pediátrico Ballester  
Sistema V11 - Integraciones Específicas sin Modificar el Main.py Existente

Este archivo contiene todas las extensiones necesarias para integrar el sistema V11
de Ballester con el main.py existente, sin sobreescribir ni modificar el archivo principal.

CRÍTICO: Estas funciones deben ser llamadas desde main.py para habilitar
las funcionalidades específicas de Ballester manteniendo compatibilidad total.

Autor: Sistema OPTIATIENDE-IA V11
Cliente: Centro Pediátrico Ballester
Fecha: Enero 2025
"""

import logging
import json
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

import config
import memory
import utils
import llm_handler
import verification_handler
import ballester_notifications
import ballester_agendamiento_adapter

logger = logging.getLogger(config.TENANT_NAME)

class BallesterMainExtensions:
    """
    Extensiones específicas para integrar Ballester V11 con el sistema principal.
    
    Esta clase contiene todas las funciones necesarias para manejar el flujo médico
    específico de Ballester sin modificar la lógica existente del main.py.
    """
    
    def __init__(self):
        """Inicializa las extensiones de Ballester"""
        self.verification_orchestrator = verification_handler.MedicalVerificationOrchestrator()
        self.notification_system = ballester_notifications.BallesterNotificationSystem()
        self.agendamiento_adapter = ballester_agendamiento_adapter.BallesterAgendamientoAdapter()
        
        logger.info("[BALLESTER_MAIN] Extensiones de Ballester inicializadas")
    
    def should_use_ballester_flow(self, mensaje_usuario: str, context: Dict) -> bool:
        """
        Determina si debe usar el flujo médico de Ballester en lugar del flujo estándar.
        
        Esta función analiza el contexto y determina si la conversación debe usar
        el flujo de verificación médica específico de Ballester.
        
        Args:
            mensaje_usuario: Mensaje del usuario
            context: Contexto actual de la conversación
            
        Returns:
            True si debe usar flujo Ballester, False para flujo estándar
        """
        
        # Si ya está en flujo de verificación médica
        if context.get('verification_state'):
            return True
        
        # Si está en estados específicos de Ballester
        current_state = context.get('current_state', '')
        if current_state.startswith('BALLESTER_'):
            return True
        
        # Si el Meta-Agente detectó intención médica específica
        if context.get('medical_intent_detected'):
            return True
        
        # Detección de palabras clave médicas específicas de Ballester
        medical_keywords = [
            'turno', 'cita', 'consulta', 'agendar', 
            'neurologia', 'ecografia', 'eeg', 'cardiologia',
            'obra social', 'cobertura', 'autorizacion',
            'pediatria', 'ballester'
        ]
        
        mensaje_lower = mensaje_usuario.lower()
        for keyword in medical_keywords:
            if keyword in mensaje_lower:
                return True
        
        return False
    
    def process_ballester_message(self, mensaje_usuario: str, context: Dict, author: str, history: List[Dict]) -> Tuple[str, Dict, Optional[List[Dict]]]:
        """
        Procesa mensaje usando el flujo médico específico de Ballester.
        
        Esta función es el punto de entrada principal para el flujo V11 de Ballester.
        Maneja la detección de frustración, verificación médica, y escalación.
        
        Args:
            mensaje_usuario: Mensaje del usuario
            context: Contexto actual
            author: ID del usuario
            history: Historial de la conversación
            
        Returns:
            Tuple con (mensaje_respuesta, contexto_actualizado, botones_opcionales)
        """
        logger.info(f"[BALLESTER_MAIN] Procesando mensaje médico para {author}")
        
        try:
            # ========== PASO 1: DETECCIÓN DE FRUSTRACIÓN ==========
            frustration_analysis = self.notification_system.detect_client_frustration(
                mensaje_usuario, context, history
            )
            
            # Si se detecta frustración crítica, activar escalación
            if frustration_analysis.get('frustration_detected') and self._should_escalate(context, frustration_analysis):
                return self.notification_system.trigger_client_delayed_flow(
                    context, author, frustration_analysis
                )
            
            # ========== PASO 2: MANEJO DE ESCALACIÓN EN CURSO ==========
            if context.get('current_state') == 'BALLESTER_CLIENT_ESCALATION':
                return self._handle_escalation_in_progress(mensaje_usuario, context, author, history)
            
            # ========== PASO 3: MANEJO DE BOTONES INTERACTIVOS ESPECÍFICOS ==========
            interactive_result = self._handle_ballester_interactives(mensaje_usuario, context, author)
            if interactive_result:
                return interactive_result
            
            # ========== PASO 4: FLUJO DE VERIFICACIÓN MÉDICA ==========
            if self._is_in_medical_verification(context):
                return self.verification_orchestrator.process_medical_flow(
                    mensaje_usuario, context, author
                )
            
            # ========== PASO 5: INICIAR NUEVO FLUJO MÉDICO ==========
            if self._should_start_medical_flow(mensaje_usuario, context):
                return self._start_ballester_medical_flow(mensaje_usuario, context, author)
            
            # ========== PASO 6: CONTINUAR CON FLUJO ESTÁNDAR ==========
            # Si llegamos aquí, usar el flujo estándar del sistema
            return None  # Indica que debe continuar con el flujo normal
            
        except Exception as e:
            logger.error(f"[BALLESTER_MAIN] Error procesando mensaje médico: {e}", exc_info=True)
            
            mensaje_error = """⚠️ **Error Técnico Temporal**

Se produjo un problema técnico. Por favor:

• Intenta nuevamente en unos minutos
• O contacta directamente:

📞 **4616-6870** ó **11-5697-5007**
🕐 Lunes a Viernes de 9 a 19hs

¡Disculpa las molestias!"""
            
            return mensaje_error, context, None
    
    def enhance_meta_agent_for_ballester(self, mensaje_usuario: str, context: Dict, history: List[Dict]) -> Dict[str, Any]:
        """
        Mejora el Meta-Agente con detección específica para Ballester.
        
        Esta función debe ser llamada ANTES del Meta-Agente estándar para agregar
        detección de intenciones médicas específicas y frustración.
        
        Args:
            mensaje_usuario: Mensaje del usuario
            context: Contexto actual
            history: Historial de la conversación
            
        Returns:
            Dict con análisis mejorado o None si debe continuar con flujo estándar
        """
        logger.info("[BALLESTER_MAIN] Mejorando Meta-Agente para contexto médico")
        
        # Detectar comandos específicos de Ballester
        ballester_commands = self._detect_ballester_commands(mensaje_usuario)
        
        if ballester_commands:
            # Marcar que se detectó intención médica
            context['medical_intent_detected'] = True
            
            # Agregar datos específicos de Ballester
            enhanced_result = ballester_commands.copy()
            enhanced_result['ballester_specific'] = True
            enhanced_result['requires_medical_verification'] = True
            
            return enhanced_result
        
        # Detectar frustración para posible escalación
        frustration_analysis = self.notification_system.detect_client_frustration(
            mensaje_usuario, context, history
        )
        
        if frustration_analysis.get('frustration_detected'):
            logger.warning(f"[BALLESTER_MAIN] Frustración detectada: {frustration_analysis.get('reason')}")
            
            # Marcar para posible escalación en próximo mensaje
            context['frustration_detected'] = True
            context['frustration_analysis'] = frustration_analysis
        
        return None  # Continuar con flujo estándar
    
    # =================== MÉTODOS AUXILIARES ===================
    
    def _detect_ballester_commands(self, mensaje: str) -> Optional[Dict]:
        """Detecta comandos específicos del Centro Pediátrico Ballester"""
        
        mensaje_lower = mensaje.lower().strip()
        
        # Comandos específicos de Ballester
        if any(cmd in mensaje_lower for cmd in ["quiero agendar", "necesito turno", "pedir cita"]):
            return {
                "decision": "BALLESTER_MEDICAL_VERIFICATION",
                "dominio": "BALLESTER_MEDICAL",
                "accion_recomendada": "iniciar_verificacion_medica",
                "datos_extraidos": self._extract_medical_data(mensaje)
            }
        
        if any(cmd in mensaje_lower for cmd in ["consultar cobertura", "que cubre mi obra social", "cuanto cuesta"]):
            return {
                "decision": "BALLESTER_COVERAGE_CHECK",
                "dominio": "BALLESTER_MEDICAL",
                "accion_recomendada": "consultar_cobertura",
                "datos_extraidos": self._extract_medical_data(mensaje)
            }
        
        if any(cmd in mensaje_lower for cmd in ["cancelar turno", "cancelar cita"]):
            return {
                "decision": "BALLESTER_CANCEL_APPOINTMENT",
                "dominio": "BALLESTER_MEDICAL",
                "accion_recomendada": "cancelar_cita",
                "datos_extraidos": {}
            }
        
        if any(cmd in mensaje_lower for cmd in ["reprogramar turno", "cambiar turno"]):
            return {
                "decision": "BALLESTER_RESCHEDULE_APPOINTMENT",
                "dominio": "BALLESTER_MEDICAL", 
                "accion_recomendada": "reprogramar_cita",
                "datos_extraidos": {}
            }
        
        return None
    
    def _extract_medical_data(self, mensaje: str) -> Dict:
        """Extrae datos médicos específicos del mensaje"""
        
        datos = {}
        mensaje_lower = mensaje.lower()
        
        # Detectar estudios específicos
        medical_terms = {
            'neurologia': 'Neurología Infantil',
            'neurologo': 'Neurología Infantil',
            'convulsiones': 'Neurología Infantil',
            'ecografia': 'Ecografía',
            'eco': 'Ecografía',
            'eeg': 'Electroencefalograma (EEG)',
            'electroencefalograma': 'Electroencefalograma (EEG)',
            'peat': 'Potencial Evocado Auditivo (PEAT)',
            'cardiologia': 'Cardiología Infantil',
            'corazon': 'Cardiología Infantil'
        }
        
        for term, service in medical_terms.items():
            if term in mensaje_lower:
                datos['servicio_detectado'] = service
                break
        
        # Detectar obra social mencionada
        if 'ioma' in mensaje_lower:
            datos['obra_social_mencionada'] = 'IOMA'
        elif 'osde' in mensaje_lower:
            datos['obra_social_mencionada'] = 'OSDE'
        elif 'medicardio' in mensaje_lower:
            datos['obra_social_mencionada'] = 'MEDICARDIO'
        # Agregar más según sea necesario
        
        return datos
    
    def _should_escalate(self, context: Dict, frustration_analysis: Dict) -> bool:
        """Determina si debe escalar basado en contexto y análisis"""
        
        # No escalar si ya se escaló recientemente
        if context.get('escalation_triggered'):
            escalation_time = context.get('escalation_timestamp')
            if escalation_time:
                try:
                    escalation_dt = datetime.fromisoformat(escalation_time)
                    time_since_escalation = (datetime.now() - escalation_dt).total_seconds() / 60
                    
                    # No escalar si fue hace menos de 30 minutos
                    if time_since_escalation < 30:
                        return False
                except:
                    pass
        
        # Escalar solo si está en proceso de verificación médica
        if context.get('verification_state') and context.get('service_name'):
            return True
        
        # Escalar si la frustración es muy alta
        if frustration_analysis.get('frustration_score', 0) >= 8:
            return True
        
        return False
    
    def _handle_escalation_in_progress(self, mensaje: str, context: Dict, author: str, history: List[Dict]) -> Tuple[str, Dict, Optional[List[Dict]]]:
        """Maneja escalación en curso"""
        
        if "si_contacto_humano_ballester" in mensaje.lower():
            # Cliente acepta escalación
            return ballester_notifications.handle_ballester_escalation_choice(
                'si_contacto_humano_ballester', context, author, history
            )
        
        elif "no_continuar_bot_ballester" in mensaje.lower():
            # Cliente prefiere continuar con bot
            return ballester_notifications.handle_ballester_escalation_choice(
                'no_continuar_bot_ballester', context, author, history
            )
        
        else:
            # Mensaje no reconocido en escalación, mantener opciones
            return ballester_notifications.trigger_ballester_escalation(
                context, author, context.get('frustration_analysis', {})
            )
    
    def _handle_ballester_interactives(self, mensaje: str, context: Dict, author: str) -> Optional[Tuple[str, Dict, Optional[List[Dict]]]]:
        """Maneja botones interactivos específicos de Ballester"""
        
        mensaje_lower = mensaje.lower().strip()
        
        # Botones de verificación médica
        if any(btn in mensaje_lower for btn in ["paciente_si", "paciente_no", "datos_correctos", "datos_editar"]):
            return self.verification_orchestrator.process_medical_flow(mensaje, context, author)
        
        # Botones de agendamiento médico  
        elif any(btn in mensaje_lower for btn in ["turno_ballester_", "ver_turnos_ballester", "confirmar_turno_ballester"]):
            return ballester_agendamiento_adapter.process_ballester_appointment_selection(
                mensaje, context, author
            )
        
        # Botones de lista de espera
        elif any(btn in mensaje_lower for btn in ["agregar_lista_espera_ballester", "no_lista_espera_ballester"]):
            if "agregar_lista_espera_ballester" in mensaje_lower:
                return self.agendamiento_adapter.add_to_waitlist(context, author)
            else:
                # No quiere lista de espera, ofrecer alternativas
                mensaje = """❌ **Lista de Espera Declinada**

Entiendo que no quieres ingresar a la lista de espera.

**Otras opciones:**
• Contactar directamente: 📞 4616-6870 ó 11-5697-5007
• Intentar como paciente particular
• Consultar otro servicio

¿Cómo prefieres continuar?"""
                
                return mensaje, context, None
        
        # Botones de escalación
        elif any(btn in mensaje_lower for btn in ["si_contacto_humano_ballester", "no_continuar_bot_ballester"]):
            return self._handle_escalation_in_progress(mensaje, context, author, [])
        
        return None  # No es un botón de Ballester
    
    def _is_in_medical_verification(self, context: Dict) -> bool:
        """Verifica si está en proceso de verificación médica"""
        return bool(context.get('verification_state'))
    
    def _should_start_medical_flow(self, mensaje: str, context: Dict) -> bool:
        """Determina si debe iniciar flujo médico nuevo"""
        
        # Ya está en flujo médico
        if context.get('verification_state'):
            return False
        
        # Detectar intención médica en el mensaje
        medical_intents = [
            'quiero agendar',
            'necesito turno',
            'consultar cobertura',
            'pedir cita',
            'que cubre',
            'cuanto cuesta'
        ]
        
        mensaje_lower = mensaje.lower()
        return any(intent in mensaje_lower for intent in medical_intents)
    
    def _start_ballester_medical_flow(self, mensaje: str, context: Dict, author: str) -> Tuple[str, Dict, Optional[List[Dict]]]:
        """Inicia el flujo de verificación médica de Ballester"""
        
        logger.info(f"[BALLESTER_MAIN] Iniciando flujo médico para {author}")
        
        # Marcar inicio del flujo médico
        context['verification_state'] = 'IDENTIFICAR_PRACTICA'
        context['medical_intent_detected'] = True
        context['flow_start_time'] = datetime.now().isoformat()
        
        # Extraer datos iniciales del mensaje
        extracted_data = self._extract_medical_data(mensaje)
        if extracted_data:
            context.update(extracted_data)
        
        # Procesar con el orquestador de verificación
        return self.verification_orchestrator.process_medical_flow(mensaje, context, author)


# =================== CONFIGURACIÓN ESPECÍFICA BALLESTER ===================

# Prompt específico del Agente Cero para Ballester
PROMPT_AGENTE_CERO_BALLESTER = """Eres el asistente virtual del Centro Pediátrico Ballester, especializado en atención pediátrica y manejo de obras sociales.

🏥 **TU IDENTIDAD:**
- Asistente virtual del Centro Pediátrico Ballester
- Especialista en pediatría y obras sociales
- Conocimiento completo sobre servicios médicos pediátricos

🎯 **TU MISIÓN:**
1. **Conversación médica empática:** Responder consultas sobre servicios pediátricos
2. **Educación de comandos:** Enseñar navegación específica médica
3. **Detección de urgencias:** Identificar consultas urgentes
4. **Recomendación de acciones:** Sugerir flujos médicos apropiados

✅ **COMANDOS DISPONIBLES:**
- **"QUIERO AGENDAR"** - Para solicitar turnos médicos
- **"QUIERO CONSULTAR COBERTURA"** - Para verificar obras sociales
- **"QUIERO CANCELAR"** - Para cancelar turnos existentes
- **"SALIR DE AGENDA"** - Para salir del agendamiento

🏥 **INFORMACIÓN CLAVE BALLESTER:**
- Atendemos bebés, niños y adolescentes hasta 18 años
- Múltiples especialidades: Neurología, Neumonología, Cardiología, etc.
- Convenios con obras sociales principales
- Estudios especializados: EEG, Ecografías, PEAT, etc.
- Horario: Lunes a Viernes 9-13hs y 14-20hs
- Dirección: Alvear 2307, Villa Ballester
- Teléfonos urgencia: 4616-6870 ó 11-5697-5007

🚨 **DETECTAR URGENCIAS:**
Si el paciente menciona "urgencia", "urgente", "dolor", "fiebre alta", o solicita ser visto "hoy" o "lo antes posible", inmediatamente recomendar llamar a los teléfonos de urgencia.

💡 **RESPUESTA DUAL:**
- **Texto conversacional** para consultas generales y educación
- **JSON con acción** para intenciones médicas específicas

**Ejemplo de recomendación de acción:**
```json
{
  "accion_recomendada": "iniciar_verificacion_medica",
  "detalles": {"servicio_detectado": "Neurología Infantil"}
}
```

🤝 **TONO:** Profesional, empático, tranquilizador. Recuerda que tratas con padres preocupados por la salud de sus hijos."""

# Configuración del Meta-Agente mejorado para Ballester
BALLESTER_META_AGENT_CONFIG = {
    'medical_keywords': [
        'turno', 'cita', 'consulta', 'pediatria', 'medico', 'doctor',
        'neurologia', 'cardiologia', 'ecografia', 'eeg', 'peat',
        'obra social', 'cobertura', 'cuanto cuesta', 'autorizacion'
    ],
    'urgency_keywords': [
        'urgencia', 'urgente', 'dolor', 'fiebre', 'hoy', 'lo antes posible',
        'emergencia', 'mal', 'grave', 'rapido'
    ],
    'escalation_keywords': [
        'no entiendo', 'ayuda', 'persona', 'humano', 'operador',
        'telefono', 'complicado', 'dificil'
    ]
}

# Mapeo de acciones específicas de Ballester para el MAPA_DE_ACCIONES de main.py
BALLESTER_ACTION_MAP = {
    'iniciar_verificacion_medica': 'start_ballester_medical_verification',
    'consultar_cobertura': 'start_ballester_coverage_check',
    'cancelar_cita': 'start_ballester_cancel_appointment',
    'reprogramar_cita': 'start_ballester_reschedule_appointment'
}


# =================== FUNCIONES HELPER PARA MAIN.PY ===================

def check_use_ballester_flow(mensaje_usuario: str, context: Dict) -> bool:
    """Función helper para main.py - determina si usar flujo Ballester"""
    extensions = BallesterMainExtensions()
    return extensions.should_use_ballester_flow(mensaje_usuario, context)

def process_ballester_medical_message(mensaje_usuario: str, context: Dict, author: str, history: List[Dict]) -> Optional[Tuple[str, Dict, Optional[List[Dict]]]]:
    """Función helper para main.py - procesa mensaje médico"""
    extensions = BallesterMainExtensions()
    return extensions.process_ballester_message(mensaje_usuario, context, author, history)

def enhance_meta_agent_ballester(mensaje_usuario: str, context: Dict, history: List[Dict]) -> Optional[Dict[str, Any]]:
    """Función helper para main.py - mejora Meta-Agente"""
    extensions = BallesterMainExtensions()
    return extensions.enhance_meta_agent_for_ballester(mensaje_usuario, context, history)

def get_ballester_agent_zero_prompt() -> str:
    """Función helper para obtener prompt específico de Ballester"""
    return PROMPT_AGENTE_CERO_BALLESTER

def get_ballester_action_mappings() -> Dict[str, str]:
    """Función helper para obtener mapeo de acciones de Ballester"""
    return BALLESTER_ACTION_MAP


# =================== FUNCIONES DE INTEGRACIÓN CON MAIN.PY ===================

def start_ballester_medical_verification(history: List[Dict], detalles: Dict, state_context: Dict, mensaje: str, author: str) -> Tuple[str, Dict]:
    """
    Función de integración para iniciar verificación médica desde MAPA_DE_ACCIONES.
    Esta función debe ser agregada al MAPA_DE_ACCIONES de main.py.
    """
    logger.info("[BALLESTER_MAIN] Iniciando verificación médica desde MAPA_DE_ACCIONES")
    
    try:
        orchestrator = verification_handler.MedicalVerificationOrchestrator()
        
        # Preparar contexto inicial
        context = state_context.copy() if state_context else {}
        context['verification_state'] = 'IDENTIFICAR_PRACTICA'
        context['flow_start_time'] = datetime.now().isoformat()
        
        # Si hay servicio detectado en detalles, agregarlo al contexto
        if detalles and detalles.get('servicio_detectado'):
            context['service_name'] = detalles['servicio_detectado']
            context['verification_state'] = 'IDENTIFICAR_PACIENTE'
        
        # Procesar con verificación médica
        mensaje_respuesta, contexto_actualizado, botones = orchestrator.process_medical_flow(
            mensaje, context, author
        )
        
        return mensaje_respuesta, contexto_actualizado
        
    except Exception as e:
        logger.error(f"[BALLESTER_MAIN] Error en verificación médica: {e}", exc_info=True)
        
        mensaje_error = """⚠️ **Error Técnico**

Se produjo un problema técnico. Por favor:

📞 **Contacta directamente:**
4616-6870 ó 11-5697-5007
🕐 Lunes a Viernes de 9 a 19hs"""
        
        return mensaje_error, state_context

def start_ballester_coverage_check(history: List[Dict], detalles: Dict, state_context: Dict, mensaje: str, author: str) -> Tuple[str, Dict]:
    """
    Función de integración para consultar cobertura desde MAPA_DE_ACCIONES.
    """
    logger.info("[BALLESTER_MAIN] Iniciando consulta de cobertura")
    
    mensaje_respuesta = """🏥 **Consulta de Cobertura - Centro Pediátrico Ballester**

Para consultar la cobertura de tu obra social necesito algunos datos:

**¿Cuál es tu obra social o prepago?**

Ejemplos: IOMA, OSDE, MEDICARDIO, OMINT, PARTICULAR, etc."""
    
    # Marcar estado para consulta de cobertura
    context = state_context.copy() if state_context else {}
    context['verification_state'] = 'IDENTIFICAR_PACIENTE'
    context['coverage_check_mode'] = True
    
    return mensaje_respuesta, context
