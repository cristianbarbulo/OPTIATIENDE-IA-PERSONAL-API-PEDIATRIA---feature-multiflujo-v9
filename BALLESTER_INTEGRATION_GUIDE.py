"""
BALLESTER_INTEGRATION_GUIDE.py - Guía Completa de Integración Sistema V11
Centro Pediátrico Ballester - Instrucciones Exactas de Implementación

Esta guía contiene las instrucciones EXACTAS para integrar el sistema V11 de Ballester
con el main.py existente SIN SOBREESCRIBIR ningún archivo del sistema actual.

CRÍTICO: Seguir estas instrucciones paso a paso para una integración perfecta.

Autor: Sistema OPTIATIENDE-IA V11
Cliente: Centro Pediátrico Ballester
Fecha: Enero 2025
"""

# =================== IMPORTACIONES A AGREGAR EN MAIN.PY ===================

IMPORT_BALLESTER_CODE = '''
# === IMPORTACIONES ESPECÍFICAS BALLESTER V11 ===
try:
    import verification_handler
    import rules_engine
    import ballester_notifications
    import ballester_agendamiento_adapter
    import ballester_main_extensions
    import ballester_firebase_config
    import clinica_api
    
    # Variable global para indicar que Ballester V11 está habilitado
    BALLESTER_V11_ENABLED = True
    logger.info("[BALLESTER] ✅ Sistema V11 cargado exitosamente")
    
except ImportError as e:
    BALLESTER_V11_ENABLED = False
    logger.warning(f"[BALLESTER] ⚠️ Sistema V11 no disponible: {e}")
    logger.warning("[BALLESTER] Continuando con sistema estándar...")
'''

# =================== MAPA DE ACCIONES A AGREGAR ===================

BALLESTER_ACTION_MAPPINGS = '''
# === ACCIONES ESPECÍFICAS BALLESTER V11 ===
# Agregar estas líneas al MAPA_DE_ACCIONES existente

if BALLESTER_V11_ENABLED:
    MAPA_DE_ACCIONES.update({
        'iniciar_verificacion_medica': ballester_main_extensions.start_ballester_medical_verification,
        'consultar_cobertura': ballester_main_extensions.start_ballester_coverage_check,
        'cancelar_cita_ballester': agendamiento_handler.iniciar_cancelacion_cita,  # Reutilizar función existente
        'reprogramar_cita_ballester': agendamiento_handler.iniciar_reprogramacion_cita,  # Reutilizar función existente
    })
    logger.info("[BALLESTER] Acciones médicas V11 agregadas al mapa")
'''

# =================== MODIFICACIÓN DE PROCESS_MESSAGE_LOGIC ===================

BALLESTER_MESSAGE_LOGIC_ENHANCEMENT = '''
def process_message_logic_enhanced_ballester(messages, author):
    """
    VERSIÓN MEJORADA DE process_message_logic para incluir flujo médico Ballester.
    
    Esta función debe REEMPLAZAR o LLAMARSE ANTES de process_message_logic()
    en main.py para habilitar el flujo médico específico.
    """
    
    # Obtener contexto actual
    conversation_data = memory.get_conversation_data(author)
    history = conversation_data.get('history', [])
    state_context = conversation_data.get('state_context', {})
    
    # Reconstruir mensaje del usuario
    mensaje_completo_usuario = _reconstruir_mensaje_usuario(messages)
    
    # === INTEGRACIÓN BALLESTER V11 ===
    if BALLESTER_V11_ENABLED:
        
        # PASO 1: Verificar si debe usar flujo médico Ballester
        ballester_extensions = ballester_main_extensions.BallesterMainExtensions()
        
        if ballester_extensions.should_use_ballester_flow(mensaje_completo_usuario, state_context):
            logger.info("[BALLESTER] 🏥 Usando flujo médico específico")
            
            try:
                # Procesar con flujo médico de Ballester
                resultado_ballester = ballester_extensions.process_ballester_message(
                    mensaje_completo_usuario, state_context, author, history
                )
                
                if resultado_ballester:
                    mensaje_respuesta, contexto_actualizado, botones = resultado_ballester
                    
                    # Enviar respuesta
                    if botones:
                        msgio_handler.send_interactive_message(author, mensaje_respuesta, botones)
                    else:
                        msgio_handler.send_message(author, mensaje_respuesta)
                    
                    # Actualizar memoria
                    memory.update_conversation_state(author, 
                        contexto_actualizado.get('current_state', 'conversando'), 
                        contexto_actualizado
                    )
                    
                    # Registrar en Chatwoot
                    _registrar_en_chatwoot(author, mensaje_completo_usuario, mensaje_respuesta)
                    
                    return  # Terminar aquí, no continuar con flujo estándar
                
            except Exception as e:
                logger.error(f"[BALLESTER] ❌ Error en flujo médico: {e}")
                # Continuar con flujo estándar en caso de error
        
        # PASO 2: Mejorar Meta-Agente con detección médica
        meta_enhancement = ballester_extensions.enhance_meta_agent_for_ballester(
            mensaje_completo_usuario, state_context, history
        )
        
        if meta_enhancement:
            logger.info(f"[BALLESTER] 🧠 Meta-Agente mejorado: {meta_enhancement.get('decision')}")
            
            # Si se detectó intención médica específica, usar resultado mejorado
            if meta_enhancement.get('ballester_specific'):
                # Procesar con resultado mejorado
                accion_recomendada = meta_enhancement.get('accion_recomendada')
                
                if accion_recomendada in MAPA_DE_ACCIONES:
                    # Ejecutar acción médica específica
                    respuesta, contexto_actualizado = _ejecutar_accion(
                        accion_recomendada, history, 
                        meta_enhancement.get('datos_extraidos', {}),
                        state_context, mensaje_completo_usuario, author
                    )
                    
                    # Enviar y registrar respuesta
                    msgio_handler.send_message(author, respuesta)
                    memory.update_conversation_state(author, 
                        contexto_actualizado.get('current_state', 'conversando'),
                        contexto_actualizado
                    )
                    _registrar_en_chatwoot(author, mensaje_completo_usuario, respuesta)
                    
                    return  # Terminar aquí
    
    # === CONTINUAR CON FLUJO ESTÁNDAR ===
    # Si llegamos aquí, continuar con process_message_logic() original
    return process_message_logic_original(messages, author)
'''

# =================== CONFIGURACIÓN DE VARIABLES DE ENTORNO ===================

BALLESTER_ENV_VARIABLES = '''
# === VARIABLES ESPECÍFICAS BALLESTER V11 ===

# Configuración básica
TENANT_NAME="CENTRO_PEDIATRICO_BALLESTER"
BALLESTER_V11_ENABLED="true"

# API de la clínica
CLINICA_API_BASE="https://api.clinicaballester.com/v1"
CLINICA_API_KEY="[proporcionado_por_la_clinica]"

# Prompt específico Agente Cero Ballester
PROMPT_AGENTE_CERO="[USAR PROMPT_AGENTE_CERO_BALLESTER del archivo ballester_main_extensions.py]"

# Notificaciones específicas
NOTIFICATION_CONTACT="549XXXXXXXXX"  # Teléfono del staff médico
ESCALATION_TIMEOUT="900"  # 15 minutos para escalación

# WhatsApp Business (360dialog) - mantener configuración existente
D360_API_KEY="[existente]"
D360_WHATSAPP_PHONE_ID="[existente]"

# OpenAI GPT-5 - mantener configuración existente  
OPENAI_API_KEY="[existente]"
OPENAI_ORG_ID="[existente]"
OPENAI_MODEL="gpt-5"

# Firebase - mantener configuración existente
GOOGLE_APPLICATION_CREDENTIALS="[existente]"

# Configuración específica médica
REQUIRE_DNI_VALIDATION="true"
REQUIRE_INSURANCE_VERIFICATION="true"
MAX_APPOINTMENT_SEARCH_DAYS="30"
'''

# =================== INSTRUCCIONES DE IMPLEMENTACIÓN PASO A PASO ===================

IMPLEMENTATION_STEPS = '''
📋 **INSTRUCCIONES DE IMPLEMENTACIÓN PASO A PASO**

🔧 **PASO 1: PREPARACIÓN**
1. Hacer backup completo del sistema actual
2. Verificar que todos los archivos V11 estén en el directorio raíz:
   - verification_handler.py
   - rules_engine.py  
   - clinica_api.py
   - ballester_agendamiento_adapter.py
   - ballester_notifications.py
   - ballester_main_extensions.py
   - ballester_firebase_config.py

🔧 **PASO 2: CONFIGURAR VARIABLES DE ENTORNO**
1. Agregar las variables específicas de Ballester al sistema
2. Configurar NOTIFICATION_CONTACT con el teléfono del staff médico
3. Obtener y configurar CLINICA_API_KEY de la clínica
4. Actualizar PROMPT_AGENTE_CERO con el prompt específico de Ballester

🔧 **PASO 3: MODIFICAR MAIN.PY (SIN SOBREESCRIBIR)**
1. Agregar las importaciones de Ballester después de las importaciones existentes
2. Agregar las acciones de Ballester al MAPA_DE_ACCIONES existente
3. Modificar process_message_logic() para incluir verificación de flujo médico
4. Agregar manejo de botones interactivos específicos de Ballester

🔧 **PASO 4: CONFIGURAR FIREBASE**
1. Ejecutar ballester_firebase_config.setup_ballester_database()
2. Verificar configuración con ballester_firebase_config.verify_ballester_database()
3. Revisar que todas las colecciones se crearon correctamente

🔧 **PASO 5: CONFIGURAR API CLÍNICA**
1. Obtener credenciales de API del sistema OMNIA
2. Verificar endpoints disponibles
3. Probar conectividad con clinica_api.BallesterClinicaAPI()

🔧 **PASO 6: TESTING**
1. Probar flujo completo de neurología con IOMA (lista de espera)
2. Probar flujo de ecografía con PASTELEROS (bono consulta)
3. Probar escalación /clientedemorado
4. Verificar notificaciones al staff

🔧 **PASO 7: GO-LIVE**
1. Configurar número de WhatsApp Business específico para Ballester
2. Configurar webhook de 360dialog
3. Activar BALLESTER_V11_ENABLED=true
4. Monitorear primeras conversaciones
'''

# =================== CÓDIGO EXACTO PARA AGREGAR A MAIN.PY ===================

MAIN_PY_ADDITIONS = '''
# ===============================================
# === INTEGRACIONES BALLESTER V11 - INICIO ===
# ===============================================

# AGREGAR DESPUÉS DE LAS IMPORTACIONES EXISTENTES:
try:
    import verification_handler
    import rules_engine 
    import ballester_notifications
    import ballester_agendamiento_adapter
    import ballester_main_extensions
    import clinica_api
    
    BALLESTER_V11_ENABLED = True
    logger.info("[MAIN] ✅ Sistema Ballester V11 cargado")
    
    # Inicializar extensiones de Ballester
    ballester_extensions = ballester_main_extensions.BallesterMainExtensions()
    
except ImportError as e:
    BALLESTER_V11_ENABLED = False
    logger.warning(f"[MAIN] ⚠️ Sistema Ballester V11 no disponible: {e}")

# AGREGAR AL MAPA_DE_ACCIONES EXISTENTE (después de la definición actual):
if BALLESTER_V11_ENABLED:
    MAPA_DE_ACCIONES.update({
        'iniciar_verificacion_medica': ballester_main_extensions.start_ballester_medical_verification,
        'consultar_cobertura_ballester': ballester_main_extensions.start_ballester_coverage_check,
    })

# MODIFICAR LA FUNCIÓN process_message_logic EXISTENTE:
# AGREGAR ESTAS LÍNEAS AL INICIO DE process_message_logic(), ANTES DEL PROCESAMIENTO ACTUAL:

def process_message_logic(messages, author):
    """Función principal de procesamiento con integración Ballester V11"""
    
    # === INTEGRACIÓN BALLESTER V11 - VERIFICACIÓN PREVIA ===
    if BALLESTER_V11_ENABLED:
        try:
            # Reconstruir mensaje del usuario
            mensaje_completo_usuario = _reconstruir_mensaje_usuario(messages)
            
            # Obtener contexto actual
            conversation_data = memory.get_conversation_data(author)
            history = conversation_data.get('history', [])
            state_context = conversation_data.get('state_context', {})
            
            # Verificar si debe usar flujo médico Ballester
            if ballester_extensions.should_use_ballester_flow(mensaje_completo_usuario, state_context):
                logger.info("[MAIN] 🏥 Procesando con flujo médico Ballester")
                
                # Procesar con sistema médico específico
                resultado_ballester = ballester_extensions.process_ballester_message(
                    mensaje_completo_usuario, state_context, author, history
                )
                
                if resultado_ballester:
                    mensaje_respuesta, contexto_actualizado, botones = resultado_ballester
                    
                    # Enviar respuesta
                    if botones:
                        msgio_handler.send_interactive_message(author, mensaje_respuesta, botones)
                    else:
                        msgio_handler.send_message(author, mensaje_respuesta)
                    
                    # Actualizar memoria
                    memory.update_conversation_state(
                        author, 
                        contexto_actualizado.get('current_state', 'conversando'),
                        contexto_actualizado
                    )
                    
                    # Registrar en Chatwoot
                    _registrar_en_chatwoot(author, mensaje_completo_usuario, mensaje_respuesta)
                    
                    return  # TERMINAR AQUÍ - No continuar con flujo estándar
            
        except Exception as e:
            logger.error(f"[MAIN] ❌ Error en flujo Ballester V11: {e}")
            # Continuar con flujo estándar en caso de error
    
    # === CONTINUAR CON LÓGICA ORIGINAL ===
    # [AQUÍ VA TODO EL CÓDIGO ORIGINAL DE process_message_logic()]
    # ... resto del código existente sin modificar ...

# MODIFICAR LA FUNCIÓN _obtener_estrategia EXISTENTE:
# AGREGAR ESTAS LÍNEAS AL INICIO DE _obtener_estrategia():

def _obtener_estrategia(mensaje_completo_usuario, history, current_state=None, state_context=None):
    """Función de estrategia mejorada con integración Ballester V11"""
    
    # === MEJORA BALLESTER V11 DEL META-AGENTE ===
    if BALLESTER_V11_ENABLED:
        try:
            # Mejorar Meta-Agente con detección médica específica
            ballester_enhancement = ballester_extensions.enhance_meta_agent_for_ballester(
                mensaje_completo_usuario, state_context or {}, history
            )
            
            if ballester_enhancement and ballester_enhancement.get('ballester_specific'):
                logger.info(f"[MAIN] 🧠 Meta-Agente mejorado para Ballester: {ballester_enhancement.get('decision')}")
                return ballester_enhancement
                
        except Exception as e:
            logger.error(f"[MAIN] Error en mejora Meta-Agente Ballester: {e}")
    
    # === CONTINUAR CON LÓGICA ORIGINAL ===
    # [AQUÍ VA TODO EL CÓDIGO ORIGINAL DE _obtener_estrategia()]
    # ... resto del código existente sin modificar ...

# AGREGAR FUNCIÓN HELPER PARA MANEJO DE BOTONES BALLESTER:
def _manejar_interactivos_ballester(id_interactivo, state_context, author):
    """Maneja botones interactivos específicos de Ballester"""
    
    if not BALLESTER_V11_ENABLED:
        return None
    
    # Botones de verificación médica
    if any(pattern in id_interactivo for pattern in [
        'paciente_si', 'paciente_no', 'datos_correctos', 'datos_editar',
        'turno_ballester_', 'ver_turnos_ballester', 'confirmar_turno_ballester',
        'agregar_lista_espera_ballester', 'si_contacto_humano_ballester'
    ]):
        try:
            return ballester_extensions.process_ballester_message(
                id_interactivo, state_context, author, []
            )
        except Exception as e:
            logger.error(f"[MAIN] Error manejando botón Ballester {id_interactivo}: {e}")
            return None
    
    return None

# AGREGAR ESTA VERIFICACIÓN EN LA FUNCIÓN DE VALIDACIÓN DE IDs INTERACTIVOS:
# AGREGAR AL INICIO DE _validar_id_interactivo():

def _validar_id_interactivo(id_interactivo, current_state):
    """Función mejorada con soporte para botones Ballester"""
    
    # === VERIFICACIÓN BALLESTER V11 PRIMERO ===
    if BALLESTER_V11_ENABLED and any(pattern in id_interactivo for pattern in [
        'ballester', 'paciente_', 'datos_', 'turno_ballester_', 'lista_espera_ballester'
    ]):
        logger.info(f"[MAIN] 🏥 Botón Ballester detectado: {id_interactivo}")
        
        # Determinar acción específica de Ballester
        if 'turno_ballester_' in id_interactivo:
            return 'confirmar_turno_ballester'
        elif 'agregar_lista_espera_ballester' in id_interactivo:
            return 'agregar_lista_espera'
        elif 'confirmar_turno_ballester' in id_interactivo:
            return 'finalizar_cita_ballester'
        elif any(btn in id_interactivo for btn in ['paciente_si', 'paciente_no']):
            return 'continuar_verificacion_medica'
        elif any(btn in id_interactivo for btn in ['datos_correctos', 'datos_editar']):
            return 'procesar_datos_paciente'
    
    # === CONTINUAR CON LÓGICA ORIGINAL ===
    # [AQUÍ VA TODO EL CÓDIGO ORIGINAL DE _validar_id_interactivo()]
    # ... resto del código existente sin modificar ...
'''

# =================== CONFIGURACIÓN INICIAL DE BASE DE DATOS ===================

FIREBASE_INITIALIZATION_SCRIPT = '''
# SCRIPT DE INICIALIZACIÓN DE BASE DE DATOS BALLESTER
# Ejecutar UNA SOLA VEZ después de deplogar todos los archivos

import ballester_firebase_config

def initialize_ballester_system():
    """
    Función para inicializar completamente el sistema Ballester V11.
    EJECUTAR UNA SOLA VEZ.
    """
    print("🏥 Inicializando Sistema Ballester V11...")
    
    # Paso 1: Configurar base de datos
    print("📊 Configurando base de datos Firebase...")
    success = ballester_firebase_config.setup_ballester_database()
    
    if success:
        print("✅ Base de datos configurada exitosamente")
        
        # Paso 2: Verificar configuración
        print("🔍 Verificando configuración...")
        verification = ballester_firebase_config.verify_ballester_database()
        
        if verification.get('all_configured'):
            print("✅ Verificación exitosa - Sistema listo")
            print("🏥 Centro Pediátrico Ballester V11 configurado completamente")
            return True
        else:
            print("❌ Error en verificación:")
            for key, value in verification.items():
                if not value:
                    print(f"   ❌ {key}: No configurado")
            return False
    else:
        print("❌ Error configurando base de datos")
        return False

# Para ejecutar la inicialización:
if __name__ == "__main__":
    initialize_ballester_system()
'''

# =================== TESTING Y VALIDACIÓN ===================

TESTING_SCENARIOS = '''
🧪 **ESCENARIOS DE TESTING ESPECÍFICOS BALLESTER**

**Test 1: Flujo Neurología con IOMA (Lista de Espera)**
Usuario: "QUIERO AGENDAR neurología"
→ verification_handler identifica: Neurología Infantil
→ Pregunta: "¿Ya eres paciente?"
Usuario: "Sí" 
→ Pide DNI
Usuario: "12345678"
→ clinica_api busca en OMNIA
→ rules_engine determina: WAITLIST (IOMA)
→ Respuesta: Lista de espera + bono contribución $2500
→ ballester_notifications.add_to_waitlist()
✅ **Esperado:** Cliente en lista, staff notificado

**Test 2: Ecografía con PASTELEROS (Bono Requerido)**  
Usuario: "necesito ecografía abdominal"
→ Flujo completo de verificación
→ rules_engine detecta: PASTELEROS + ecografía
→ Respuesta: Autorización + Bono Consulta + preparación específica por edad
✅ **Esperado:** Requisitos claros, instrucciones de preparación

**Test 3: EEG con MEDICARDIO (Cubierto)**
Usuario: "QUIERO AGENDAR electroencefalograma"
→ Verificación completa
→ rules_engine: MEDICARDIO cubre EEG
→ Respuesta: Cubierto + copago $4000 + preparaciones específicas
✅ **Esperado:** Cita disponible, prep instructions

**Test 4: Cliente Frustrado (Escalación)**
Usuario: "no entiendo nada, ayuda"
→ ballester_notifications.detect_client_frustration() detecta frustración
→ Activa trigger_client_delayed_flow()
→ Ofrece escalación con botones
Usuario: "Sí, que me contacten"
→ ballester_notifications.send_escalation_notification()
✅ **Esperado:** Staff notificado con contexto completo

**Test 5: Dr. Malacchia Lunes (Arancel Especial)**
Usuario: "QUIERO AGENDAR Dr Malacchia lunes"
→ rules_engine detecta caso especial
→ Obra social no autorizada → arancel especial $22500
→ Confirmación explícita requerida
✅ **Esperado:** Arancel claro, confirmación explícita

**Test 6: PRUNAPE Fuera de Edad**
Usuario: "QUIERO AGENDAR PRUNAPE"
→ Recopila datos paciente
→ Edad: 7 años
→ rules_engine valida edad → Fuera de rango
→ Respuesta: No elegible + derivación a humano
✅ **Esperado:** Validación de edad, derivación apropiada
'''

print(f"""
🏥 **GUÍA DE INTEGRACIÓN BALLESTER V11 COMPLETA**

✅ **ARCHIVOS CREADOS:**
- verification_handler.py (Orquestador médico)
- rules_engine.py (Motor de reglas determinista)
- clinica_api.py (Wrapper API OMNIA)
- ballester_agendamiento_adapter.py (Adaptador agendamiento)
- ballester_notifications.py (Sistema notificaciones)
- ballester_main_extensions.py (Extensiones main.py)
- ballester_firebase_config.py (Configuración base de datos)

📋 **PRÓXIMOS PASOS:**
1. Configurar variables de entorno específicas
2. Integrar código con main.py existente
3. Inicializar base de datos Firebase
4. Configurar API clínica OMNIA
5. Testing completo de flujos médicos
6. Go-live con Centro Pediátrico Ballester

🎯 **RESULTADO FINAL:**
Sistema OptiAtiende-IA V11 especializado para Centro Pediátrico Ballester
con flujo médico completo, verificación de obras sociales, motor de reglas
determinista, y escalación inteligente.

🏆 **ESTADO:** Implementación completa lista para integración

¿Procedemos con la integración al main.py?
""")
