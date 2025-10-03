"""
BALLESTER_OPTIMIZED_CONFIG.py - Configuración Optimizada Sistema Único
Centro Pediátrico Ballester - Optimizaciones Específicas para Cliente Único

Como este sistema será ÚNICAMENTE para Centro Pediátrico Ballester,
podemos hacer optimizaciones específicas sin preocuparnos por multi-cliente.

ESTRATEGIA: Adaptaciones quirúrgicas específicas manteniendo estabilidad del core.

Autor: Sistema OPTIATIENDE-IA V11 Optimizado
Cliente: Centro Pediátrico Ballester (ÚNICO)
Fecha: Enero 2025
"""

# =================== OPTIMIZACIÓN 1: MAPA DE ACCIONES MÉDICO ESPECÍFICO ===================

# Reemplazar completamente el MAPA_DE_ACCIONES genérico con uno médico específico
BALLESTER_OPTIMIZED_ACTION_MAP = {
    # === ACCIONES MÉDICAS PRINCIPALES ===
    'iniciar_verificacion_medica': 'verification_handler.start_medical_verification',
    'continuar_verificacion_medica': 'verification_handler.continue_medical_flow',
    'obtener_veredicto_medico': 'rules_engine.get_verification_verdict',
    
    # === AGENDAMIENTO MÉDICO ESPECÍFICO ===
    'mostrar_turnos_ballester': 'ballester_agendamiento_adapter.show_medical_appointments',
    'confirmar_turno_ballester': 'ballester_agendamiento_adapter.finalize_appointment',
    'agregar_lista_espera': 'ballester_agendamiento_adapter.add_to_waitlist',
    
    # === ESCALACIÓN Y NOTIFICACIONES ===
    'escalar_a_humano_ballester': 'ballester_notifications.trigger_escalation',
    'confirmar_escalacion': 'ballester_notifications.handle_escalation_confirmation',
    
    # === FUNCIONES PRESERVADAS DEL SISTEMA BASE ===
    'preguntar': 'wrapper_preguntar',  # Mantener función clave
    'escalar_a_humano': 'notifications_handler.escalar_a_humano',  # Fallback
    
    # === ELIMINADAS: Acciones genéricas que no se usan en contexto médico ===
    # 'iniciar_triage_pagos': NO SE USA EN BALLESTER
    # 'iniciar_triage_agendamiento': REEMPLAZADO por iniciar_verificacion_medica
    # 'confirmar_servicio_pago': NO SE USA EN BALLESTER
    # 'generar_link_pago': NO SE USA EN BALLESTER
}

# =================== OPTIMIZACIÓN 2: PROMPTS HARDCODEADOS BALLESTER ===================

# En lugar de usar variables de Render, hardcodear prompts específicos
BALLESTER_PROMPTS = {
    'AGENTE_CERO': """Eres el asistente virtual del Centro Pediátrico Ballester.

🏥 **TU IDENTIDAD:**
- Centro Pediátrico Ballester, Villa Ballester
- Especialista en pediatría (0-18 años)
- Conocimiento completo de obras sociales
- Acceso a sistema OMNIA para turnos

🎯 **COMANDOS MÉDICOS:**
• **"QUIERO AGENDAR"** → Solicitar turnos médicos
• **"QUIERO CONSULTAR COBERTURA"** → Verificar obra social  
• **"QUIERO CANCELAR"** → Cancelar turnos
• **"SALIR DE AGENDA"** → Salir del agendamiento

🚨 **URGENCIAS (Deriva INMEDIATAMENTE):**
Si mencionan: "urgencia", "urgente", "dolor", "fiebre", "hoy", "lo antes posible"
→ Deriva a: 📞 4616-6870 ó 11-5697-5007

🏥 **INFO BÁSICA BALLESTER:**
- Horario: Lunes a Viernes 9-13hs y 14-20hs
- Dirección: Alvear 2307, Villa Ballester
- Especialidades: Neurología, Neumonología, Cardiología, Ecografías, etc.
- Sistema: Convenios múltiples obras sociales

Responde médicamente o recomienda acción en JSON.""",

    'META_AGENTE': """Eres el router médico del Centro Pediátrico Ballester.

ÚNICA MISIÓN: Detectar comandos médicos explícitos y extraer datos.

COMANDOS VÁLIDOS:
- "QUIERO AGENDAR" → iniciar_verificacion_medica
- "QUIERO CONSULTAR COBERTURA" → consultar_cobertura_ballester
- "QUIERO CANCELAR" → cancelar_cita_ballester
- "SALIR DE AGENDA" → salir_flujo

EXTRACCIÓN MÉDICA:
- Especialidades: neurología, cardiología, ecografía, etc.
- Obras sociales: IOMA, OSDE, MEDICARDIO, etc.
- Urgencias: urgente, dolor, fiebre, hoy

RESPUESTA: JSON con decision + datos_extraidos + accion_recomendada""",

    'LECTOR': """Analiza documentos médicos del Centro Pediátrico Ballester.

BUSCAR EN IMÁGENES:
- DNI de pacientes (no padres)
- Credenciales de obra social
- Autorizaciones médicas (verificar "CENTRO PEDIATRICO BALLESTER")
- Órdenes médicas
- Comprobantes de pago/bonos

EXTRAER:
- Nombres y DNI exactos
- Obra social y plan
- Números de afiliado
- Fechas de autorizaciones
- Montos de copagos

CRÍTICO: Verificar que autorizaciones sean para "CENTRO PEDIATRICO BALLESTER"""
}

# =================== OPTIMIZACIÓN 3: CONFIGURACIÓN ESPECÍFICA ===================

BALLESTER_SPECIFIC_CONFIG = {
    # Sistema único - no multi-cliente
    'MULTI_CLIENT_MODE': False,
    'SINGLE_CLIENT_NAME': 'Centro Pediátrico Ballester',
    
    # Agentes habilitados - solo médicos
    'ENABLED_AGENTS': ['BALLESTER_MEDICAL'],  # Eliminar 'payment', 'scheduling' genéricos
    
    # Timeouts específicos para contexto médico
    'MEDICAL_VERIFICATION_TIMEOUT': 1800,  # 30 minutos para completar verificación
    'ESCALATION_TIMEOUT': 900,  # 15 minutos antes de escalar por tiempo
    
    # Configuración específica de buffer para consultas médicas
    'BUFFER_WAIT_TIME': 6.0,  # Más tiempo para padres que escriben información médica
    
    # Límites específicos médicos
    'MAX_APPOINTMENT_SEARCH_DAYS': 30,
    'MAX_WAITLIST_ENTRIES_PER_SERVICE': 100,
    
    # Configuración de logging médico
    'LOG_PATIENT_DATA': True,  # Para auditoría médica
    'LOG_MEDICAL_DECISIONS': True,  # Para revisar decisiones del bot
    
    # Integración única con sistema OMNIA
    'USE_GOOGLE_CALENDAR': False,  # Eliminar Google Calendar
    'USE_CLINIC_API': True,  # Solo API clínica
    'USE_MERCADOPAGO': False,  # Eliminar pagos genéricos
}

# =================== OPTIMIZACIÓN 4: FUNCIONES ESPECÍFICAS REEMPLAZOS ===================

# Reemplazos quirúrgicos de funciones genéricas por médicas específicas
BALLESTER_FUNCTION_REPLACEMENTS = {
    # Reemplazar agendamiento genérico
    'agendamiento_handler.iniciar_triage_agendamiento': 'verification_handler.start_medical_verification',
    'agendamiento_handler.mostrar_opciones_turnos': 'ballester_agendamiento_adapter.show_medical_appointments',
    'agendamiento_handler.finalizar_cita_automatico': 'ballester_agendamiento_adapter.finalize_appointment',
    
    # Reemplazar notificaciones genéricas  
    'notifications_handler.escalar_a_humano': 'ballester_notifications.trigger_escalation',
    
    # Mantener funciones core que funcionan
    'memory.get_conversation_data': 'memory.get_conversation_data',  # Mantener
    'msgio_handler.send_message': 'msgio_handler.send_message',  # Mantener
    'llm_handler.llamar_meta_agente': 'llm_handler.llamar_meta_agente'  # Mantener pero mejorar
}

# =================== OPTIMIZACIÓN 5: CONFIGURACIÓN CONFIG.PY SIMPLIFICADA ===================

BALLESTER_CONFIG_OPTIMIZATIONS = """
# AGREGAR A config.py - Configuración hardcodeada específica Ballester

# === BALLESTER ESPECÍFICO - HARDCODEADO ===
BALLESTER_MODE = True
CLIENT_NAME = "Centro Pediátrico Ballester"

# Prompts hardcodeados (no variables de Render)
PROMPT_AGENTE_CERO = '''[PROMPT COMPLETO HARDCODEADO AQUÍ]'''

PROMPT_META_AGENTE = '''[META AGENTE MÉDICO HARDCODEADO]'''

PROMPT_LECTOR = '''[LECTOR MÉDICO HARDCODEADO]'''

# Configuración médica específica (hardcodeada)
MEDICAL_CONFIG = {
    'edad_maxima_pediatria': 18,
    'duracion_turno_default': 30,
    'anticipacion_minima_horas': 24,
    'max_slots_neurologia_obra_social': 5,
    'max_slots_neumonologia_ioma': 5,
    'arancel_especial_dr_malacchia': 22500
}

# API clínica (reemplaza Google Calendar)
CLINICA_API_BASE = "https://api.clinicaballester.com/v1"
USE_CLINIC_API_ONLY = True

# Contactos específicos Ballester
BALLESTER_CONTACTS = {
    'staff_principal': '549XXXXXXXXX',
    'emergencias': ['4616-6870', '11-5697-5007'],
    'administracion': '549XXXXXXXXX'
}

# Obras sociales específicas (hardcodeadas)
BALLESTER_OBRAS_SOCIALES = [
    'IOMA', 'OSDE', 'MEDICARDIO', 'OMINT', 'PASTELEROS', 
    'TELEVISION', 'OSDOP', 'MEPLIFE', 'OSSEG', 'PARTICULAR'
]

# === ELIMINAR CONFIGURACIONES GENÉRICAS NO USADAS ===
# PAYMENT_PROVIDERS = []  # No se usa en Ballester
# CALENDAR_PROVIDER = "CLINIC_API"  # Solo API clínica
# SERVICE_PRICES_JSON = "{}"  # No se usa en Ballester
"""

# =================== OPTIMIZACIÓN 6: LIMPIEZA DE IMPORTS ===================

OPTIMIZED_IMPORTS_SUGGESTION = """
# Optimizar imports en main.py para Ballester únicamente:

# === IMPORTS MÉDICOS ESPECÍFICOS ===
import verification_handler
import rules_engine  
import ballester_notifications
import ballester_agendamiento_adapter
import clinica_api

# === IMPORTS CORE MANTENIDOS ===
import config
import memory
import llm_handler
import msgio_handler  
import audio_handler
import utils

# === ELIMINABLES PARA BALLESTER ÚNICO ===
# import pago_handler  # No se usan pagos genéricos en Ballester
# import hubspot_handler  # No se usa HubSpot en contexto médico
# import lead_generator  # No se generan leads en contexto médico
# import chatwoot_integration  # Opcional - solo si lo usa Ballester
# import service_factory  # No se necesita factory para un solo cliente
"""
```

---

## 🏥 **PROPUESTA OPTIMIZADA: ADAPTACIÓN QUIRÚRGICA**

### **ENFOQUE RECOMENDADO: "CIRUGÍA ESPECÍFICA"**

#### ✅ **CAMBIOS MÍNIMOS DE ALTO IMPACTO**

1. **Reemplazar `agendamiento_handler.py` completamente** con versión médica específica
2. **Simplificar `config.py`** con valores hardcodeados Ballester  
3. **Optimizar MAPA_DE_ACCIONES** solo con acciones médicas
4. **Hardcodear prompts** específicos (no variables Render)
5. **Eliminar imports** no usados para mejor performance

#### ❌ **NO CAMBIAR (MANTENER ESTABILIDAD)**

1. **main.py structure** - Solo agregar imports y 2-3 líneas
2. **process_message_logic** - Mantener lógica principal  
3. **Buffer system** - Funciona perfecto para consultas médicas
4. **Meta-Agente core** - Solo mejorar, no reescribir
5. **Memory system** - Solo agregar funciones médicas

---

## 🎯 **IMPLEMENTACIÓN OPTIMIZADA ESPECÍFICA**

<function_calls>
<invoke name="search_replace">
<parameter name="file_path">agendamiento_handler.py
