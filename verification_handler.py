"""
verification_handler.py - Orquestador Médico Centro Pediátrico Ballester
Sistema V11 - Máquina de Estados Finitos para Verificación Médica

Este módulo gestiona el flujo completo de verificación médica:
Estado 0: Identificar Práctica/Estudio
Estado 1: Identificar Paciente  
Estado 2: Verificar/Editar Datos del Paciente
Estado 3: Obtener Veredicto del Motor de Reglas
Estado 4: Handoff a Agendamiento

Autor: Sistema OPTIATIENDE-IA V11
Cliente: Centro Pediátrico Ballester
Fecha: Enero 2025
"""

import logging
import json
import requests
import copy
from datetime import datetime
from typing import Dict, Any, Tuple, Optional, List

import config
import memory
import rules_engine
import msgio_handler
from clinica_api import BallesterClinicaAPI

logger = logging.getLogger(config.TENANT_NAME)

class MedicalVerificationOrchestrator:
    """
    Orquestador principal para el flujo de verificación médica del Centro Pediátrico Ballester.
    Implementa una máquina de estados finitos con 4 estados principales.
    """
    
    # Estados de la máquina de estados finitos
    STATES = {
        'IDENTIFICAR_PRACTICA': 'identificar_practica',
        'IDENTIFICAR_PACIENTE': 'identificar_paciente',
        'VERIFICAR_DATOS': 'verificar_datos',
        'OBTENER_VEREDICTO': 'obtener_veredicto'
    }
    
    # Categorías de estudios específicas de Ballester
    CATEGORIAS_BALLESTER = [
        {
            'id': 'consultas_pediatricas',
            'titulo': '👶 Consultas Pediátricas',
            'descripcion': 'Consultas generales y urgencias'
        },
        {
            'id': 'subespecialidades',
            'titulo': '🧠 Subespecialidades',
            'descripcion': 'Neurología, Neumonología, Dermatología, etc.'
        },
        {
            'id': 'estudios_neurologicos',
            'titulo': '📊 Estudios Neurológicos',
            'descripcion': 'EEG, PEAT, Polisomnografía'
        },
        {
            'id': 'ecografias',
            'titulo': '🔍 Ecografías',
            'descripcion': 'Abdominal, Renal, Ginecológica'
        },
        {
            'id': 'cardiologia',
            'titulo': '❤️ Cardiología',
            'descripcion': 'Ecocardiograma, Electrocardiograma'
        },
        {
            'id': 'salud_mental',
            'titulo': '🧩 Salud Mental',
            'descripcion': 'Psicología, Psicopedagogía, Neuropsicología'
        },
        {
            'id': 'otros_estudios',
            'titulo': '📋 Otros Estudios',
            'descripcion': 'Audiometría, PRUNAPE, Vacunación'
        }
    ]
    
    # Mapeo de estudios específicos de Ballester (basado en la documentación)
    ESTUDIOS_BALLESTER_MAP = {
        # Consultas
        'consulta pediatrica': 'Consulta Pediátrica',
        'pediatria': 'Consulta Pediátrica',
        'consulta': 'Consulta Pediátrica',
        'urgencia': 'Consulta de Urgencia',
        'urgente': 'Consulta de Urgencia',
        
        # Subespecialidades
        'neurologia infantil': 'Neurología Infantil',
        'neurologo': 'Neurología Infantil',
        'neurologia': 'Neurología Infantil',
        'convulsiones': 'Neurología Infantil',
        'neumonologia': 'Neumonología Infantil',
        'neumologo': 'Neumonología Infantil',
        'asma': 'Neumonología Infantil',
        'dermatologia infantil': 'Dermatología Infantil',
        'dermatologo': 'Dermatología Infantil',
        'piel': 'Dermatología Infantil',
        'oftalmologia infantil': 'Oftalmología Infantil',
        'oftalmologo': 'Oftalmología Infantil',
        'ojos': 'Oftalmología Infantil',
        
        # Estudios Neurológicos
        'electroencefalograma': 'Electroencefalograma (EEG)',
        'eeg': 'Electroencefalograma (EEG)',
        'eeg de sueño': 'Electroencefalograma (EEG)',
        'eeg prolongado': 'Electroencefalograma (EEG)',
        'potencial evocado auditivo': 'Potencial Evocado Auditivo (PEAT)',
        'peat': 'Potencial Evocado Auditivo (PEAT)',
        'bera': 'Potencial Evocado Auditivo (PEAT)',
        'polisomnografia diurna': 'Polisomnografía Diurna',
        'polisomnografia': 'Polisomnografía Diurna',
        'psg': 'Polisomnografía Diurna',
        'polisomnografia de sueño': 'Polisomnografía Diurna',
        
        # Ecografías
        'ecografia abdominal': 'Ecografía Abdominal',
        'eco abdominal': 'Ecografía Abdominal',
        'ecografia hepatobiliar': 'Ecografía Hepatobiliar',
        'ecografia esplenica': 'Ecografía Esplénica',
        'ecografia suprarrenal': 'Ecografía Suprarrenal',
        'ecografia pancreatica': 'Ecografía Pancreática',
        'ecografia ginecologica': 'Ecografía Ginecológica',
        'ecografia renal': 'Ecografía Renal',
        'ecografia uretero vesical': 'Ecografía de Vías Urinarias',
        'ecografia vesical': 'Ecografía de Vías Urinarias',
        'ecografia de vias urinarias': 'Ecografía de Vías Urinarias',
        
        # Cardiología
        'ecocardiograma doppler color': 'Ecocardiograma Doppler Color',
        'ecocardiograma': 'Ecocardiograma Doppler Color',
        'doppler': 'Ecocardiograma Doppler Color',
        'electrocardiograma': 'Electrocardiograma',
        'ecg': 'Electrocardiograma',
        
        # Salud Mental
        'psicologia': 'Psicología',
        'psicologo': 'Psicología',
        'psicopedagogia': 'Psicopedagogía',
        'psicopedagogo': 'Psicopedagogía',
        'neuropsicologia': 'Neuropsicología',
        'psicologia neurocognitiva': 'Neuropsicología',
        'evaluacion neuropsicologica': 'Neuropsicología',
        'evaluacion neurocognitiva': 'Neuropsicología',
        'test de ados': 'Test de Ados (Neuropsicología)',
        'ados': 'Test de Ados (Neuropsicología)',
        'test de adir': 'Test de Adir (Neuropsicología)',
        'adir': 'Test de Adir (Neuropsicología)',
        
        # Otros
        'audiometria': 'Audiometría',
        'prunape': 'PRUNAPE',
        'prueba nacional de pesquisa': 'PRUNAPE',
        'vacunacion': 'Vacunación',
        'vacunas': 'Vacunación'
    }
    
    def __init__(self):
        """Inicializa el orquestador médico"""
        self.rules_engine = rules_engine.BallesterRulesEngine()
        self.clinica_api = BallesterClinicaAPI()
        logger.info("[VERIFICATION_HANDLER] Orquestador médico inicializado")
    
    def process_medical_flow(self, mensaje_usuario: str, context: Dict[str, Any], author: str) -> Tuple[str, Dict[str, Any], Optional[List[Dict]]]:
        """
        Punto de entrada principal para el flujo de verificación médica.
        
        Args:
            mensaje_usuario: Mensaje del usuario
            context: Contexto actual de la conversación
            author: ID del usuario (teléfono)
            
        Returns:
            Tuple con (mensaje_respuesta, contexto_actualizado, botones_opcionales)
        """
        logger.info(f"[VERIFICATION_HANDLER] Procesando flujo médico para {author}")
        logger.info(f"[VERIFICATION_HANDLER] Estado actual: {context.get('verification_state', 'IDENTIFICAR_PRACTICA')}")
        
        # Obtener estado actual de la verificación
        current_state = context.get('verification_state', 'IDENTIFICAR_PRACTICA')
        
        try:
            # Máquina de estados finitos
            if current_state == 'IDENTIFICAR_PRACTICA':
                return self._handle_identificar_practica(mensaje_usuario, context)
            elif current_state == 'IDENTIFICAR_PACIENTE':
                return self._handle_identificar_paciente(mensaje_usuario, context, author)
            elif current_state == 'VERIFICAR_DATOS':
                return self._handle_verificar_datos(mensaje_usuario, context, author)
            elif current_state == 'OBTENER_VEREDICTO':
                return self._handle_obtener_veredicto(context, author)
            else:
                logger.error(f"[VERIFICATION_HANDLER] Estado desconocido: {current_state}")
                return self._reset_to_initial_state(context)
                
        except Exception as e:
            logger.error(f"[VERIFICATION_HANDLER] Error procesando flujo médico: {e}", exc_info=True)
            return self._handle_error(context, str(e))
    
    def _handle_identificar_practica(self, mensaje: str, context: Dict) -> Tuple[str, Dict, Optional[List[Dict]]]:
        """
        Estado 0: Identificar qué práctica/estudio necesita el paciente.
        
        Este es el primer estado donde se determina exactamente qué servicio médico
        está solicitando el paciente.
        """
        logger.info(f"[VERIFICATION_HANDLER] Estado IDENTIFICAR_PRACTICA - Mensaje: '{mensaje[:100]}...'")
        
        # Detectar estudios específicos en el mensaje
        estudios_detectados = self._detectar_estudios_ballester(mensaje)
        logger.info(f"[VERIFICATION_HANDLER] Estudios detectados: {estudios_detectados}")
        
        if len(estudios_detectados) == 1:
            # Un solo estudio detectado claramente
            estudio = estudios_detectados[0]
            context['service_name'] = estudio
            context['verification_state'] = 'IDENTIFICAR_PACIENTE'
            
            # Mensajes específicos según el tipo de consulta
            if estudio == 'Consulta de Urgencia':
                mensaje_respuesta = f"""🚨 **Consulta de Urgencia**

Entiendo que necesitas ser atendido urgentemente.

Para turnos de urgencia, por favor comunicate directamente:
📞 **4616-6870** ó **11-5697-5007**

¿O prefieres agendar un turno de control programado?"""
                
                botones = [
                    {"id": "urgencia_llamar", "title": "🚨 Llamar ahora"},
                    {"id": "turno_control", "title": "📅 Turno programado"}
                ]
                
                return mensaje_respuesta, context, botones
            
            else:
                mensaje_respuesta = f"""✅ **Perfecto, entiendo que necesitas:**
**{estudio}**

Para continuar necesito saber: ¿ya eres paciente del Centro Pediátrico Ballester?"""
                
                botones = [
                    {"id": "paciente_si", "title": "✅ Sí, ya soy paciente"},
                    {"id": "paciente_no", "title": "🆕 No, es la primera vez"}
                ]
                
                return mensaje_respuesta, context, botones
            
        elif len(estudios_detectados) > 1:
            # Múltiples estudios detectados, pedir aclaración
            context['estudios_detectados'] = estudios_detectados
            
            mensaje_respuesta = "Detecté varios estudios posibles. ¿Cuál necesitas específicamente?"
            
            botones = []
            for i, estudio in enumerate(estudios_detectados[:5]):  # Máximo 5 opciones
                botones.append({
                    "id": f"estudio_especifico_{i}",
                    "title": f"🏥 {estudio}"
                })
            
            return mensaje_respuesta, context, botones
            
        else:
            # No se detectó estudio específico, mostrar categorías
            mensaje_respuesta = """🏥 **Centro Pediátrico Ballester**

¿Qué tipo de atención médica necesitas?

Selecciona la categoría que corresponde:"""
            
            botones = []
            for categoria in self.CATEGORIAS_BALLESTER[:6]:  # Máximo 6 categorías por restricción WhatsApp
                botones.append({
                    "id": f"categoria_{categoria['id']}",
                    "title": f"{categoria['titulo']}"
                })
            
            return mensaje_respuesta, context, botones
    
    def _handle_identificar_paciente(self, mensaje: str, context: Dict, author: str) -> Tuple[str, Dict, Optional[List[Dict]]]:
        """
        Estado 1: Identificar si es paciente existente o nuevo.
        
        Este estado determina si el paciente ya está registrado en el sistema OMNIA
        o si es la primera vez que viene.
        """
        logger.info(f"[VERIFICATION_HANDLER] Estado IDENTIFICAR_PACIENTE")
        
        # Procesar respuesta por botón interactivo
        if "paciente_si" in mensaje.lower() or mensaje.lower().strip() in ["sí", "si", "ya soy paciente", "ya soy"]:
            # Es paciente existente, pedir DNI
            context['is_existing_patient'] = True
            context['verification_state'] = 'VERIFICAR_DATOS'
            
            mensaje_respuesta = """✅ **Perfecto, eres paciente del Centro.**

Para buscar tu información necesito el **DNI del paciente** (no de los padres).

Por favor, envíame solo el número de DNI:"""
            
            return mensaje_respuesta, context, None
            
        elif "paciente_no" in mensaje.lower() or mensaje.lower().strip() in ["no", "primera vez", "nuevo", "no soy paciente"]:
            # Paciente nuevo, ir directo a registro
            context['is_existing_patient'] = False
            context['verification_state'] = 'VERIFICAR_DATOS'
            
            mensaje_respuesta = """🆕 **Bienvenido al Centro Pediátrico Ballester**

Como es tu primera vez, necesito registrar algunos datos.

Comencemos con el **DNI del paciente** (no de los padres):"""
            
            return mensaje_respuesta, context, None
            
        elif "turno_control" in mensaje.lower():
            # Usuario prefiere turno programado en lugar de urgencia
            context['service_name'] = 'Consulta Pediátrica'
            
            mensaje_respuesta = """📅 **Turno de Control**

Perfecto, vamos a agendar un turno programado.

¿Ya eres paciente del Centro Pediátrico Ballester?"""
            
            botones = [
                {"id": "paciente_si", "title": "✅ Sí, ya soy paciente"},
                {"id": "paciente_no", "title": "🆕 No, es la primera vez"}
            ]
            
            return mensaje_respuesta, context, botones
        
        else:
            # Respuesta no clara, ofrecer opciones con botones
            mensaje_respuesta = """🤔 Para continuar necesito saber:

¿Ya eres paciente del Centro Pediátrico Ballester?"""
            
            botones = [
                {"id": "paciente_si", "title": "✅ Sí, ya soy paciente"},
                {"id": "paciente_no", "title": "🆕 No, es la primera vez"}
            ]
            
            return mensaje_respuesta, context, botones
    
    def _handle_verificar_datos(self, mensaje: str, context: Dict, author: str) -> Tuple[str, Dict, Optional[List[Dict]]]:
        """
        Estado 2: Verificar y editar datos del paciente.
        
        Este estado maneja la recolección y verificación de datos del paciente,
        ya sea buscándolo en la API OMNIA o registrándolo como nuevo.
        """
        logger.info(f"[VERIFICATION_HANDLER] Estado VERIFICAR_DATOS")
        
        # Si es la primera vez en este estado, pedir datos básicos
        if not context.get('data_collection_started'):
            return self._start_data_collection(mensaje, context, author)
        
        # Si ya estamos en proceso de recolección, continuar
        return self._continue_data_collection(mensaje, context, author)
    
    def _start_data_collection(self, mensaje: str, context: Dict, author: str) -> Tuple[str, Dict, Optional[List[Dict]]]:
        """Inicia la recolección de datos del paciente"""
        
        # Extraer DNI del mensaje
        dni = self._extract_dni(mensaje)
        
        if not dni:
            mensaje_respuesta = """❌ **No pude detectar el DNI**

Por favor, envíame solo el número de DNI del paciente:
**Ejemplo:** 12345678"""
            
            return mensaje_respuesta, context, None
        
        context['patient_dni'] = dni
        context['data_collection_started'] = True
        
        if context.get('is_existing_patient'):
            # Buscar paciente en API OMNIA
            return self._search_existing_patient(dni, context, author)
        else:
            # Paciente nuevo, recopilar datos completos
            return self._collect_new_patient_data(context)
    
    def _search_existing_patient(self, dni: str, context: Dict, author: str) -> Tuple[str, Dict, Optional[List[Dict]]]:
        """Busca paciente existente en API OMNIA"""
        logger.info(f"[VERIFICATION_HANDLER] Buscando paciente con DNI: {dni}")
        
        try:
            # Llamar a API OMNIA para buscar paciente
            patient_data = self.clinica_api.get_patient_by_dni(dni)
            
            if patient_data:
                # Paciente encontrado
                context['patient_data'] = patient_data
                context['data_verified'] = False
                
                # Mostrar datos encontrados para confirmación
                mensaje_respuesta = f"""✅ **Paciente encontrado en nuestro sistema:**

**Datos registrados:**
👤 **Nombre:** {patient_data.get('nombre', 'No disponible')}
🆔 **DNI:** {patient_data.get('dni', 'No disponible')}
📅 **Fecha Nac.:** {patient_data.get('fecha_nacimiento', 'No disponible')}
🏥 **Obra Social:** {patient_data.get('obra_social', 'No disponible')}
📋 **Plan:** {patient_data.get('plan', 'No disponible')}
📱 **Celular:** {patient_data.get('celular', 'No disponible')}
📧 **Email:** {patient_data.get('email', 'No disponible')}

¿Los datos son correctos?"""

                botones = [
                    {"id": "datos_correctos", "title": "✅ Sí, son correctos"},
                    {"id": "datos_editar", "title": "✏️ Quiero editarlos"}
                ]
                
                return mensaje_respuesta, context, botones
            
            else:
                # Paciente no encontrado con ese DNI
                context['is_existing_patient'] = False
                mensaje_respuesta = f"""🔍 **No encontré un paciente con DNI {dni}**

¿Es posible que:
- Sea la primera vez que vienes al Centro?
- El DNI esté mal escrito?

Si es tu primera vez, continuemos con el registro. Si crees que el DNI está mal, envíame el correcto."""
                
                botones = [
                    {"id": "primera_vez_continuar", "title": "🆕 Continuar registro"},
                    {"id": "dni_corregir", "title": "✏️ Corregir DNI"}
                ]
                
                return mensaje_respuesta, context, botones
                
        except Exception as e:
            logger.error(f"[VERIFICATION_HANDLER] Error buscando paciente: {e}")
            mensaje_respuesta = """⚠️ **Problemas técnicos temporales**

No pude acceder al sistema de pacientes en este momento. 

Por favor, intenta nuevamente en unos minutos o comunicate directamente:
📞 **4616-6870** ó **11-5697-5007**"""
            
            return mensaje_respuesta, context, None
    
    def _collect_new_patient_data(self, context: Dict) -> Tuple[str, Dict, Optional[List[Dict]]]:
        """Inicia recolección de datos para paciente nuevo"""
        
        context['collecting_field'] = 'obra_social'  # Primer campo según especificación
        
        mensaje_respuesta = f"""📋 **Registro de Nuevo Paciente**

Perfecto, vamos a registrar tus datos paso a paso.

**PASO 1/7: Obra Social**

¿Cuál es tu obra social o prepago?

**Ejemplos:** IOMA, OSDE, MEDICARDIO, PARTICULAR, etc."""
        
        return mensaje_respuesta, context, None
    
    def _continue_data_collection(self, mensaje: str, context: Dict, author: str) -> Tuple[str, Dict, Optional[List[Dict]]]:
        """Continúa el proceso de recolección de datos"""
        
        # Si el usuario quiere editar datos existentes
        if "datos_editar" in mensaje.lower():
            return self._start_data_editing(context)
        
        # Si confirma que los datos son correctos
        if "datos_correctos" in mensaje.lower():
            context['data_verified'] = True
            context['verification_state'] = 'OBTENER_VEREDICTO'
            return self._handle_obtener_veredicto(context, author)
        
        # Continuar recolección para paciente nuevo
        if context.get('collecting_field'):
            return self._process_field_input(mensaje, context)
        
        # Estado por defecto
        return self._reset_to_initial_state(context)
    
    def _process_field_input(self, mensaje: str, context: Dict) -> Tuple[str, Dict, Optional[List[Dict]]]:
        """Procesa la entrada de un campo específico durante la recolección"""
        
        current_field = context.get('collecting_field')
        
        if not context.get('patient_data'):
            context['patient_data'] = {'dni': context.get('patient_dni')}
        
        if current_field == 'obra_social':
            # Validar obra social contra las disponibles
            obra_social = self._normalize_obra_social(mensaje)
            if obra_social:
                context['patient_data']['obra_social'] = obra_social
                context['collecting_field'] = 'plan'
                
                mensaje_respuesta = f"""✅ **Obra Social:** {obra_social}

**PASO 2/7: Plan**

¿Cuál es tu plan dentro de {obra_social}?

**Ejemplos:** Plan Integral, Plan 450, Plan Único, etc.

Si no sabes el nombre exacto, escribí "no sé" y te ayudo."""
                
                return mensaje_respuesta, context, None
            else:
                # Obra social no reconocida, derivar a humano
                mensaje_respuesta = f"""⚠️ **Obra Social no reconocida: "{mensaje}"**

Esta obra social no está en nuestro sistema de convenios actuales.

Te derivo con nuestro personal para que te ayuden personalmente:
📞 **4616-6870** ó **11-5697-5007**
🕐 **Horario:** Lunes a Viernes 9 a 19hs

¿Querés intentar con otra obra social?"""
                
                botones = [
                    {"id": "otra_obra_social", "title": "🔄 Otra obra social"},
                    {"id": "contactar_humano", "title": "📞 Contactar personal"}
                ]
                
                return mensaje_respuesta, context, botones
        
        elif current_field == 'plan':
            context['patient_data']['plan'] = mensaje.strip()
            context['collecting_field'] = 'nombre'
            
            mensaje_respuesta = f"""✅ **Plan:** {mensaje.strip()}

**PASO 3/7: Nombre Completo**

¿Cuál es el nombre completo del paciente?

**Ejemplo:** Juan Pérez López"""
            
            return mensaje_respuesta, context, None
        
        elif current_field == 'nombre':
            context['patient_data']['nombre'] = mensaje.strip()
            context['collecting_field'] = 'fecha_nacimiento'
            
            mensaje_respuesta = f"""✅ **Nombre:** {mensaje.strip()}

**PASO 4/7: Fecha de Nacimiento**

¿Cuál es la fecha de nacimiento del paciente?

**Formato:** DD/MM/AAAA
**Ejemplo:** 15/03/2010"""
            
            return mensaje_respuesta, context, None
        
        elif current_field == 'fecha_nacimiento':
            fecha = self._parse_fecha(mensaje)
            if fecha:
                context['patient_data']['fecha_nacimiento'] = fecha
                context['collecting_field'] = 'celular'
                
                mensaje_respuesta = f"""✅ **Fecha de Nacimiento:** {fecha}

**PASO 5/7: Celular**

¿Cuál es el número de celular de contacto?

**Ejemplo:** 11-1234-5678"""
                
                return mensaje_respuesta, context, None
            else:
                mensaje_respuesta = f"""❌ **Fecha no válida:** {mensaje}

Por favor, usa el formato DD/MM/AAAA

**Ejemplo:** 15/03/2010"""
                
                return mensaje_respuesta, context, None
        
        elif current_field == 'celular':
            context['patient_data']['celular'] = mensaje.strip()
            context['collecting_field'] = 'email'
            
            mensaje_respuesta = f"""✅ **Celular:** {mensaje.strip()}

**PASO 6/7: Email**

¿Cuál es el email del paciente? (debe ser único por paciente)

**Ejemplo:** juan.perez@gmail.com"""
            
            return mensaje_respuesta, context, None
        
        elif current_field == 'email':
            if self._validate_email(mensaje):
                context['patient_data']['email'] = mensaje.strip().lower()
                context['collecting_field'] = 'numero_afiliado'
                
                mensaje_respuesta = f"""✅ **Email:** {mensaje.strip().lower()}

**PASO 7/7: Número de Afiliado**

¿Cuál es tu número de afiliado de la obra social?

**Ejemplo:** 123456789"""
                
                return mensaje_respuesta, context, None
            else:
                mensaje_respuesta = f"""❌ **Email no válido:** {mensaje}

Por favor, ingresa un email válido:

**Ejemplo:** juan.perez@gmail.com"""
                
                return mensaje_respuesta, context, None
        
        elif current_field == 'numero_afiliado':
            context['patient_data']['numero_afiliado'] = mensaje.strip()
            context['collecting_field'] = None
            context['data_verified'] = True
            context['verification_state'] = 'OBTENER_VEREDICTO'
            
            # Mostrar resumen completo
            patient_data = context['patient_data']
            mensaje_respuesta = f"""✅ **Registro Completo**

**Resumen de los datos ingresados:**
👤 **Nombre:** {patient_data.get('nombre')}
🆔 **DNI:** {patient_data.get('dni')}
📅 **Fecha Nac.:** {patient_data.get('fecha_nacimiento')}
🏥 **Obra Social:** {patient_data.get('obra_social')}
📋 **Plan:** {patient_data.get('plan')}
📱 **Celular:** {patient_data.get('celular')}
📧 **Email:** {patient_data.get('email')}
🔢 **N° Afiliado:** {patient_data.get('numero_afiliado')}

¿Todos los datos son correctos?"""
            
            botones = [
                {"id": "datos_correctos", "title": "✅ Sí, continuar"},
                {"id": "datos_editar", "title": "✏️ Quiero corregir algo"}
            ]
            
            return mensaje_respuesta, context, botones
        
        # Estado por defecto
        return self._reset_to_initial_state(context)
    
    def _handle_obtener_veredicto(self, context: Dict, author: str) -> Tuple[str, Dict, Optional[List[Dict]]]:
        """
        Estado 3: Obtener veredicto del motor de reglas.
        
        Este estado consulta el rules_engine para obtener el veredicto completo
        sobre cobertura, requisitos, precios, etc.
        """
        logger.info(f"[VERIFICATION_HANDLER] Estado OBTENER_VEREDICTO")
        
        patient_data = context.get('patient_data', {})
        service_name = context.get('service_name', '')
        
        if not patient_data or not service_name:
            logger.error("[VERIFICATION_HANDLER] Datos incompletos para obtener veredicto")
            return self._handle_error(context, "Datos incompletos para la verificación")
        
        try:
            # Obtener veredicto del motor de reglas
            verdict = self.rules_engine.get_verification_verdict(
                patient_data=patient_data,
                service_data={'service_name': service_name}
            )
            
            logger.info(f"[VERIFICATION_HANDLER] Veredicto obtenido: {verdict.get('coverage_status')}")
            
            # Guardar veredicto en contexto
            context['medical_verdict'] = verdict
            
            # Formatear mensaje para el usuario
            mensaje_respuesta = self._format_verdict_message(verdict, patient_data, service_name)
            
            # Determinar botones según el veredicto
            botones = self._get_verdict_buttons(verdict)
            
            return mensaje_respuesta, context, botones
            
        except Exception as e:
            logger.error(f"[VERIFICATION_HANDLER] Error obteniendo veredicto: {e}", exc_info=True)
            return self._handle_error(context, f"Error en la verificación médica: {str(e)}")
    
    def _format_verdict_message(self, verdict: Dict, patient_data: Dict, service_name: str) -> str:
        """Formatea el mensaje del veredicto para el usuario"""
        
        obra_social = patient_data.get('obra_social', 'tu obra social')
        coverage_status = verdict.get('coverage_status', 'UNKNOWN')
        
        # Mensaje base
        mensaje = f"""📋 **Verificación Completada**

**Paciente:** {patient_data.get('nombre')}
**Servicio:** {service_name}
**Obra Social:** {obra_social}

"""
        
        # Agregar información según el estado de cobertura
        if coverage_status == 'COVERED':
            mensaje += "✅ **TU OBRA SOCIAL CUBRE ESTE SERVICIO**\n\n"
            
        elif coverage_status == 'WAITLIST':
            mensaje += "⏳ **LISTA DE ESPERA**\n\n"
            mensaje += "Tu obra social cubre el servicio, pero por alta demanda tenemos lista de espera.\n\n"
            
        elif coverage_status == 'PRIVATE_ONLY':
            mensaje += "💰 **ARANCEL PARTICULAR**\n\n"
            mensaje += "Este servicio no está cubierto por tu obra social.\n\n"
            
        elif coverage_status == 'SPECIAL_RATE':
            mensaje += "💳 **ARANCEL ESPECIAL**\n\n"
            
        # Agregar requisitos si los hay
        requirements = verdict.get('requirements', [])
        if requirements:
            mensaje += "📋 **REQUISITOS NECESARIOS:**\n"
            for req in requirements:
                mensaje += f"• {req}\n"
            mensaje += "\n"
        
        # Agregar información de pagos
        payment_info = verdict.get('payment_info', {})
        if payment_info:
            if payment_info.get('copago'):
                mensaje += f"💰 **Copago:** ${payment_info['copago']}\n"
            if payment_info.get('particular_fee'):
                mensaje += f"💰 **Arancel Particular:** ${payment_info['particular_fee']}\n"
            if payment_info.get('bono_contribucion'):
                mensaje += f"💰 **Bono Contribución:** ${payment_info['bono_contribucion']}\n"
            mensaje += "\n"
        
        # Agregar mensaje específico del veredicto
        if verdict.get('message_to_user'):
            mensaje += verdict['message_to_user']
        
        # Agregar instrucciones de preparación si las hay
        prep_instructions = verdict.get('preparation_instructions', [])
        if prep_instructions:
            mensaje += "\n\n📝 **PREPARACIÓN PARA EL ESTUDIO:**\n"
            for instruction in prep_instructions:
                mensaje += f"• {instruction}\n"
        
        # Agregar nota de bono si existe
        if verdict.get('bono_mensaje'):
            mensaje += f"\n💡 **IMPORTANTE:** {verdict['bono_mensaje']}"
        
        return mensaje
    
    def _get_verdict_buttons(self, verdict: Dict) -> Optional[List[Dict]]:
        """Determina qué botones mostrar según el veredicto"""
        
        next_action = verdict.get('next_action', '')
        coverage_status = verdict.get('coverage_status', '')
        
        if next_action == 'SHOW_APPOINTMENTS':
            return [
                {"id": "buscar_turnos", "title": "📅 Buscar Turnos"},
                {"id": "cancelar_proceso", "title": "❌ Cancelar"}
            ]
            
        elif next_action == 'ADD_TO_WAITLIST':
            return [
                {"id": "agregar_lista_espera", "title": "⏳ Ingresar a Lista"},
                {"id": "cancelar_proceso", "title": "❌ No, gracias"}
            ]
            
        elif coverage_status == 'PRIVATE_ONLY':
            return [
                {"id": "aceptar_particular", "title": "💰 Acepto arancel"},
                {"id": "cancelar_proceso", "title": "❌ No, gracias"}
            ]
            
        elif coverage_status == 'SPECIAL_RATE':
            return [
                {"id": "aceptar_arancel_especial", "title": "💳 Acepto arancel"},
                {"id": "cancelar_proceso", "title": "❌ No, gracias"}
            ]
            
        else:
            return [
                {"id": "continuar_proceso", "title": "✅ Continuar"},
                {"id": "cancelar_proceso", "title": "❌ Cancelar"}
            ]
    
    # Métodos auxiliares
    def _detectar_estudios_ballester(self, mensaje: str) -> List[str]:
        """Detecta estudios específicos de Ballester en el mensaje del usuario"""
        mensaje_lower = mensaje.lower().strip()
        estudios_detectados = []
        
        # Buscar coincidencias en el mapa de estudios
        for keyword, estudio in self.ESTUDIOS_BALLESTER_MAP.items():
            if keyword in mensaje_lower:
                if estudio not in estudios_detectados:
                    estudios_detectados.append(estudio)
        
        logger.info(f"[VERIFICATION_HANDLER] Estudios detectados en '{mensaje}': {estudios_detectados}")
        return estudios_detectados
    
    def _extract_dni(self, mensaje: str) -> Optional[str]:
        """Extrae DNI del mensaje del usuario"""
        import re
        
        # Buscar secuencias de 7-8 dígitos
        dni_pattern = r'\b(\d{7,8})\b'
        matches = re.findall(dni_pattern, mensaje)
        
        if matches:
            return matches[0]
        
        return None
    
    def _normalize_obra_social(self, mensaje: str) -> Optional[str]:
        """Normaliza el nombre de la obra social según la base de datos Ballester"""
        
        # Mapa de normalización basado en las imágenes proporcionadas
        obra_social_map = {
            'ioma': 'IOMA',
            'osde': 'OSDE',
            'medicardio': 'MEDICARDIO',
            'omint': 'OMINT',
            'poder judicial': 'PODER JUDICIAL',
            'swiss medical': 'SWISS MEDICAL',
            'pasteleros': 'PASTELEROS',
            'television': 'TELEVISION',
            'osdop': 'OSDOP',
            'particular': 'PARTICULAR',
            'meplife': 'MEPLIFE',
            'osseg': 'OSSEG',
            'activa salud': 'ACTIVA SALUD',
            'alba salud': 'ALBA SALUD',
            'asm': 'ASM',
            'asi': 'ASI',
            'asmepriv': 'ASMEPRIV',
            'assistencial salud': 'ASSISTENCIAL SALUD',
            'avalian': 'AVALIAN',
            'banco provincia': 'BANCO PROVINCIA',
            'bene salud': 'BENE SALUD',
            'bon salud': 'BON SALUD',
            'bristol medicine': 'BRISTOL MEDICINE',
            'casa': 'CASA',
            'caucho': 'CAUCHO',
            'celius': 'CELIUS',
            'cober': 'COBER',
            'comei': 'COMEI',
            'federada salud': 'FEDERADA SALUD',
            'galeno': 'GALENO',
            'jerarquicos salud': 'JERARQUICOS SALUD',
            'luis pasteur': 'LUIS PASTEUR',
            'accord salud': 'ACCORD SALUD',
            'medicus': 'MEDICUS',
            'medife': 'MEDIFE',
            'nobis': 'NOBIS',
            'obsba': 'OBSBA',
            'opdea': 'OPDEA',
            'osecac': 'OSECAC',
            'ospatca': 'OSPATCA',
            'ospia': 'OSPIA',
            'ospecon': 'OSPECON',
            'osprera': 'OSPRERA',
            'pami': 'PAMI',
            'premedic': 'PREMEDIC',
            'redsalud': 'REDSALUD',
            'sancor salud': 'SANCOR SALUD',
            'swiss medical': 'SWISS MEDICAL',
            'union personal': 'UNION PERSONAL',
            'w.hope': 'W.HOPE',
            'whope': 'W.HOPE'
        }
        
        mensaje_lower = mensaje.lower().strip()
        
        # Buscar coincidencia exacta
        if mensaje_lower in obra_social_map:
            return obra_social_map[mensaje_lower]
        
        # Buscar coincidencia parcial
        for key, value in obra_social_map.items():
            if key in mensaje_lower or mensaje_lower in key:
                return value
        
        return None
    
    def _parse_fecha(self, mensaje: str) -> Optional[str]:
        """Parsea fecha en formato DD/MM/AAAA"""
        import re
        
        # Patrón para fecha DD/MM/AAAA
        fecha_pattern = r'(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{4})'
        match = re.search(fecha_pattern, mensaje)
        
        if match:
            day, month, year = match.groups()
            # Validar rangos básicos
            if 1 <= int(day) <= 31 and 1 <= int(month) <= 12 and 1900 <= int(year) <= 2030:
                return f"{day.zfill(2)}/{month.zfill(2)}/{year}"
        
        return None
    
    def _validate_email(self, email: str) -> bool:
        """Valida formato de email"""
        import re
        
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return bool(re.match(email_pattern, email.strip()))
    
    def _handle_error(self, context: Dict, error_msg: str) -> Tuple[str, Dict, Optional[List[Dict]]]:
        """Maneja errores del sistema"""
        logger.error(f"[VERIFICATION_HANDLER] Error manejado: {error_msg}")
        
        mensaje_respuesta = f"""⚠️ **Se produjo un problema técnico**

{error_msg}

Por favor, intenta nuevamente o comunicate directamente:
📞 **4616-6870** ó **11-5697-5007**
🕐 **Horario:** Lunes a Viernes 9 a 19hs"""
        
        return mensaje_respuesta, self._reset_to_initial_state(context), None
    
    def _reset_to_initial_state(self, context: Dict) -> Dict:
        """Resetea el contexto al estado inicial"""
        clean_context = {
            'author': context.get('author'),
            'senderName': context.get('senderName'),
            'verification_state': 'IDENTIFICAR_PRACTICA'
        }
        return clean_context


# Función helper para uso en main.py
def start_medical_verification(mensaje_usuario: str, context: Dict, author: str) -> Tuple[str, Dict, Optional[List[Dict]]]:
    """
    Función helper para iniciar verificación médica desde main.py
    """
    orchestrator = MedicalVerificationOrchestrator()
    return orchestrator.process_medical_flow(mensaje_usuario, context, author)
