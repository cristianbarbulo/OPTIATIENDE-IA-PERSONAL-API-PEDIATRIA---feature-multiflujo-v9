# config.py (Arquitectura V9 - Estricto y Resiliente)
import os
import sys
import json
import logging
from dotenv import load_dotenv

load_dotenv()
# Se configura un logger básico aquí para capturar errores de configuración inicial.
# La configuración completa del logger se hará en main.py, pero esto nos sirve para el arranque.
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# === BALLESTER ESPECÍFICO - SISTEMA ÚNICO ===
# Como este sistema es ÚNICAMENTE para Centro Pediátrico Ballester,
# configuramos directamente sin variables de entorno genéricas
BALLESTER_MODE = True
CLIENT_NAME = "Centro Pediátrico Ballester"

# Agentes específicos Ballester (hardcodeado)
ENABLED_AGENTS = ['BALLESTER_MEDICAL']  # Solo agente médico específico
logger.info(f"Sistema configurado para: {CLIENT_NAME}")

# --- Activadores opcionales ---
# Carga los activadores (triggers) que cambian el estado de la conversación.
# Debe ser una cadena JSON válida.
AGENT_TRIGGERS = []
try:
    triggers_json_string = os.environ.get('AGENT_TRIGGERS', '{}')
    if triggers_json_string and triggers_json_string != '{}':
        AGENT_TRIGGERS = json.loads(triggers_json_string).get('triggers', [])
        logger.info(f"Se cargaron {len(AGENT_TRIGGERS)} activadores de agentes.")
except json.JSONDecodeError:
    logger.error("Error al decodificar AGENT_TRIGGERS. Debe ser un JSON válido. Se continuará sin activadores.")

# --- Validación estricta de configuración ---
# Este bloque intenta cargar todas las variables de entorno necesarias.
# Si una variable crítica falta, el programa fallará inmediatamente al iniciar.
try:
    # Variables críticas existentes (de tu V6.2)
    TENANT_NAME = os.environ['TENANT_NAME']
    OPENAI_API_KEY = os.environ['OPENAI_API_KEY']
    
    # NUEVO: Configuración de modelos GPT-5 y organización
    OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5")
    AGENTE_CERO_MODEL = os.getenv("AGENTE_CERO_MODEL", OPENAI_MODEL)
    GENERATOR_MODEL = os.getenv("GENERADOR_MODEL", OPENAI_MODEL)
    OPENAI_ORG_ID = os.getenv("OPENAI_ORG_ID")  # Obligatorio para GPT-5
    
    # Configuración de parámetros de GPT-5 (pueden personalizarse por variable de entorno)
    # Reasoning effort: "minimal", "low", "medium", "high"
    AGENTE_CERO_REASONING = os.getenv("AGENTE_CERO_REASONING", "low")
    GENERATOR_REASONING = os.getenv("GENERADOR_REASONING", "medium")
    META_AGENTE_REASONING = os.getenv("META_AGENTE_REASONING", "minimal")
    INTENCION_REASONING = os.getenv("INTENCION_REASONING", "low")
    
    # Text verbosity: "low", "medium", "high"
    AGENTE_CERO_VERBOSITY = os.getenv("AGENTE_CERO_VERBOSITY", "medium")
    GENERATOR_VERBOSITY = os.getenv("GENERADOR_VERBOSITY", "high")
    META_AGENTE_VERBOSITY = os.getenv("META_AGENTE_VERBOSITY", "low")
    INTENCION_VERBOSITY = os.getenv("INTENCION_VERBOSITY", "low")
    
    # NUEVO: Configuración del buffer de mensajes (tiempo de espera antes de procesar)
    # Por defecto 4.0 segundos, pero personalizable por cliente
    BUFFER_WAIT_TIME = float(os.getenv("BUFFER_WAIT_TIME", "1.0"))
    if BUFFER_WAIT_TIME < 0.5:
        logger.warning(f"BUFFER_WAIT_TIME muy bajo ({BUFFER_WAIT_TIME}s). Mínimo recomendado: 0.5s")
    elif BUFFER_WAIT_TIME > 10.0:
        logger.warning(f"BUFFER_WAIT_TIME muy alto ({BUFFER_WAIT_TIME}s). Máximo recomendado: 10s")
    
    PROMPT_LECTOR = os.environ['PROMPT_LECTOR']
    # PROMPT_GENERADOR es opcional y SIN valor por defecto.
    # Si no está definido, el sistema no debe invocar al generador.
    PROMPT_GENERADOR = os.environ.get('PROMPT_GENERADOR')
    # ELIMINADO: PROMPT_CORRECTOR (ya no se usa en el sistema)
    # ELIMINADO: PROMPT_META_AGENTE (ahora hardcodeado en llm_handler.py)
    # ELIMINADAS: PROMPT_INTENCION_AGENDAMIENTO y PROMPT_INTENCION_PAGOS (ahora hardcodeadas en llm_handler.py)
    SALUDO_INICIAL = os.environ.get(
        'SALUDO_INICIAL',
        '¡Hola! Soy tu asistente virtual. ¿En qué puedo ayudarte hoy?'
    )
    # PROMPT_ANALISTA_LEADS también es opcional a menos que se active el analizador de leads
    PROMPT_ANALISTA_LEADS = os.environ.get(
        'PROMPT_ANALISTA_LEADS',
        (
            'Eres un analista de leads. Extrae datos básicos (nombre, contacto, interés) de forma '
            'estructurada a partir del historial sin inventar información.'
        )
    )
    
    # === PROMPTS BALLESTER HARDCODEADOS ===
    # Como sistema único, hardcodeamos prompts específicos para mejor performance
    PROMPT_AGENTE_CERO = """Eres el asistente virtual del Centro Pediátrico Ballester.

🏥 **TU IDENTIDAD:**
- Centro Pediátrico Ballester, Villa Ballester  
- Especialista en atención pediátrica (0-18 años)
- Conocimiento completo de obras sociales argentinas
- Acceso directo al sistema OMNIA para turnos

🎯 **COMANDOS MÉDICOS ESPECÍFICOS:**
• **"QUIERO AGENDAR"** → Iniciar solicitud de turnos médicos
• **"QUIERO CONSULTAR COBERTURA"** → Verificar cobertura de obra social
• **"QUIERO CANCELAR"** → Cancelar turnos existentes
• **"SALIR DE AGENDA"** → Salir del flujo de agendamiento

🚨 **DETECCIÓN DE URGENCIAS:**
Si mencionan: "urgencia", "urgente", "dolor", "fiebre alta", "hoy", "lo antes posible"
→ Deriva INMEDIATAMENTE a teléfonos: 📞 4616-6870 ó 11-5697-5007

🏥 **INFORMACIÓN CENTRO BALLESTER:**
- **Horario:** Lunes a Viernes 9-13hs y 14-20hs
- **Dirección:** Alvear 2307, Villa Ballester  
- **Especialidades:** Neurología, Neumonología, Cardiología, Ecografías, EEG, etc.
- **Obras Sociales:** IOMA, OSDE, MEDICARDIO, OMINT, PASTELEROS, y más

🩺 **SERVICIOS PRINCIPALES:**
- Consultas pediátricas generales
- Neurología Infantil (lista de espera algunas obras sociales)
- Estudios neurológicos (EEG, PEAT, Polisomnografía)
- Ecografías con preparación específica por edad
- Cardiología pediátrica
- Salud mental (Psicología, Neuropsicología - particulares)

💡 **RESPUESTA DUAL:**
- **Texto conversacional médico** para consultas e información
- **JSON con acción médica** para intenciones de agendamiento

Ejemplo JSON: {"accion_recomendada": "iniciar_verificacion_medica", "detalles": {"servicio_detectado": "Neurología Infantil"}}

🤝 **TONO:** Profesional médico, empático, tranquilizador. Recuerda que tratas con padres preocupados por la salud de sus hijos."""
    
    # NUEVO: Configuración para 360dialog (reemplaza MSG.IO)
    D360_API_KEY = os.environ['D360_API_KEY']
    D360_WHATSAPP_PHONE_ID = os.environ['D360_WHATSAPP_PHONE_ID']
    
    # VALIDACIÓN CRÍTICA: Verificar que las variables no estén vacías
    if not D360_API_KEY or D360_API_KEY.strip() == '':
        logger.critical("FATAL: D360_API_KEY está vacía o no configurada correctamente.")
        sys.exit(1)
    if not D360_WHATSAPP_PHONE_ID or D360_WHATSAPP_PHONE_ID.strip() == '':
        logger.critical("FATAL: D360_WHATSAPP_PHONE_ID está vacía o no configurada correctamente.")
        sys.exit(1)
    # CORRECCIÓN CRÍTICA: URL correcta para 360dialog
    D360_BASE_URL = os.environ.get('D360_BASE_URL', 'https://waba.360dialog.io/v3')
    D360_WEBHOOK_VERIFY_TOKEN = os.environ.get('D360_WEBHOOK_VERIFY_TOKEN', 'default_verify_token')
    D360_HUMAN_WEBHOOK_VERIFY_TOKEN = os.environ.get('D360_HUMAN_WEBHOOK_VERIFY_TOKEN', 'default_human_verify_token')
    
    # COMENTADO: Variables de MSG.IO (ya no se usan)
    # MSGIO_API_URL = os.environ['MSGIO_API_URL']
    # MSGIO_API_TOKEN = os.environ['MSGIO_API_TOKEN']
    # MSGIO_WEBHOOK_VERIFY_TOKEN = os.environ['MSGIO_WEBHOOK_VERIFY_TOKEN']
    # MSGIO_HUMAN_WEBHOOK_VERIFY_TOKEN = os.environ["MSGIO_HUMAN_WEBHOOK_VERIFY_TOKEN"]
    
    # Integración CRM opcional
    HUBSPOT_API_KEY = os.getenv('HUBSPOT_API_KEY', '')
    if not HUBSPOT_API_KEY:
        logger.info("HUBSPOT_API_KEY no configurada. Integración HubSpot desactivada.")

    # Transcripción de audio OBLIGATORIA: requerida para que el Lector alimente al Agente Cero
    ASSEMBLYAI_API_KEY = os.environ['ASSEMBLYAI_API_KEY']
    SERVICE_PRICES_JSON = os.environ.get('SERVICE_PRICES_JSON', '{}')

    # Proveedores configurables para pagos y calendarios
    PAYMENT_PROVIDERS = [
        p.strip().upper()
        for p in os.environ.get("PAYMENT_PROVIDER", "MERCADOPAGO").split(",")
    ]
    CALENDAR_PROVIDER = os.getenv("CALENDAR_PROVIDER", "GOOGLE").upper()
    # Modo Citas (Google Appointments): requiere definir de dónde leer ventanas y la duración de slot
    GOOGLE_APPOINTMENTS_CALENDAR_ID = os.getenv('GOOGLE_APPOINTMENTS_CALENDAR_ID', '')
    APPOINTMENTS_SLOT_MINUTES = int(os.getenv('APPOINTMENTS_SLOT_MINUTES', '30'))
    
    # Configuración de Google Calendar
    GOOGLE_CALENDAR_ID = os.getenv('GOOGLE_CALENDAR_ID', 'primary')
    GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv('GOOGLE_APPLICATION_CREDENTIALS', 'credenciales-google.json')

    # --- Variables condicionales para la arquitectura multi-flujo ---

    # Si hay cualquier agente habilitado, el prompt de intención es obligatorio.
    # (ELIMINADO: PROMPT_INTENCION ya no es requerido)

    # === CONFIGURACIÓN MÉDICA BALLESTER ===
    # Como sistema único médico, configuramos directamente sin agentes genéricos
    
    # API de la clínica (reemplaza Google Calendar y servicios genéricos)
    CLINICA_API_BASE = os.environ.get('CLINICA_API_BASE', 'https://api.clinicaballester.com/v1')
    CLINICA_API_KEY = os.environ.get('CLINICA_API_KEY', '')
    
    # Configuración médica específica (hardcodeada)
    BALLESTER_MEDICAL_CONFIG = {
        'edad_maxima_pediatria': 18,
        'duracion_turno_default_minutos': 30,
        'anticipacion_minima_turnos_horas': 24,
        'max_slots_neurologia_obra_social_dia': 5,
        'max_slots_neumonologia_ioma_dia': 5,
        'arancel_especial_dr_malacchia': 22500,
        'edad_maxima_prunape_anos': 5,
        'edad_maxima_prunape_meses': 11,
        'edad_maxima_prunape_dias': 29
    }
    
    # Contactos específicos Ballester
    BALLESTER_CONTACTS = {
        'staff_principal': os.environ.get('NOTIFICATION_CONTACT', ''),
        'emergencias': ['4616-6870', '11-5697-5007'],
        'direccion': 'Alvear 2307, Villa Ballester',
        'horario': 'Lunes a Viernes 9-13hs y 14-20hs'
    }
    
    # === ELIMINAMOS CONFIGURACIÓN DE PAGOS GENÉRICOS ===
    # Ballester no usa el sistema de pagos genérico, usa verificación de obra social
    # if 'PAYMENT' in ENABLED_AGENTS:  # COMENTADO - No se usa en Ballester

    # Si el agente de AGENDAMIENTO está habilitado, sus variables son obligatorias.
    # ELIMINADO: PROMPT_AGENDAMIENTO ya no se usa en el sistema

    # Lista opcional de nombres que identifican a los agentes humanos

    HUMAN_AGENT_NAMES = [
        n.strip() for n in os.environ.get('HUMAN_AGENT_NAMES', '').split(',') if n.strip()
    ]

    if HUMAN_AGENT_NAMES:
        logger.info(f"Agentes humanos configurados: {HUMAN_AGENT_NAMES}")
        
    # NUEVO: Validación crítica para el nuevo flujo de pagos
    if 'PAYMENT' in ENABLED_AGENTS:
        # Validar que SERVICE_PRICES_JSON sea un JSON válido
        try:
            if SERVICE_PRICES_JSON and SERVICE_PRICES_JSON != '{}':
                json.loads(SERVICE_PRICES_JSON)
                logger.info("SERVICE_PRICES_JSON validado correctamente")
            else:
                logger.warning("SERVICE_PRICES_JSON está vacío o no configurado")
        except json.JSONDecodeError:
            logger.critical("FATAL: SERVICE_PRICES_JSON no es un JSON válido. El sistema de pagos no funcionará correctamente.")
        
        # Validar que PAYMENT_PROVIDERS no esté vacío
        if not PAYMENT_PROVIDERS:
            logger.critical("FATAL: PAYMENT_PROVIDERS está vacío. El sistema de pagos no funcionará.")
    
    # NUEVO: Configuración de servicios para el flujo unificado de pagos
    SERVICIOS_DISPONIBLES = []
    try:
        if SERVICE_PRICES_JSON and SERVICE_PRICES_JSON != '{}':
            precios_dict = json.loads(SERVICE_PRICES_JSON)
            SERVICIOS_DISPONIBLES = [
                {
                    'nombre': servicio,
                    'precio': precio,
                    'descripcion': f'Servicio de {servicio.lower()}'
                }
                for servicio, precio in precios_dict.items()
            ]
            logger.info(f"Servicios configurados: {len(SERVICIOS_DISPONIBLES)} servicios")
        else:
            # Configuración por defecto si no hay SERVICE_PRICES_JSON
            SERVICIOS_DISPONIBLES = [
                {
                    'nombre': 'Coaching Personalizado',
                    'precio': 200,
                    'descripcion': 'Sesión de coaching para desarrollo profesional y personal'
                },
                {
                    'nombre': 'Consultita Rápida',
                    'precio': 100,
                    'descripcion': 'Consulta rápida para resolver dudas específicas'
                },
                {
                    'nombre': 'Mentoría Intensiva',
                    'precio': 300,
                    'descripcion': 'Programa de mentoría intensivo con seguimiento'
                }
            ]
            logger.info("Usando configuración por defecto de servicios")
    except Exception as e:
        logger.error(f"Error configurando servicios: {e}")
        SERVICIOS_DISPONIBLES = []

    # NUEVO: Configuración del orquestador rígido
    ORQUESTADOR_RIGIDO = {
        'enabled': True,
        'estados_activos': [
            'PAGOS_ESPERANDO_SELECCION_SERVICIO',
            'PAGOS_ESPERANDO_CONFIRMACION',
            'PAGOS_GENERANDO_LINK',
            'AGENDA_MOSTRANDO_OPCIONES',
            'AGENDA_ESPERANDO_CONFIRMACION_FINAL',
            'AGENDA_FINALIZANDO_CITA'
        ],
        'detector_comprobantes': {
            'enabled': True,
            'palabras_clave': ['comprobante', 'pago', 'transferencia', 'mercadopago', 'ticket'],
            'respuesta_automatica': "Perfecto, registramos tu comprobante de pago. Muchas gracias."
        }
    }

    # Mensajes centralizados de comandos (educación y navegación)
    COMMAND_TIPS = {
        'ENTER_AGENDA': os.getenv('CMD_ENTER_AGENDA', 'Para agendar, escribí: QUIERO AGENDAR'),
        'ENTER_PAGO': os.getenv('CMD_ENTER_PAGO', 'Para pagos, escribí: QUIERO PAGAR'),
        'EXIT_AGENDA': os.getenv('CMD_EXIT_AGENDA', 'Para salir del agendamiento, escribí: SALIR DE AGENDA'),
        'EXIT_PAGO': os.getenv('CMD_EXIT_PAGO', 'Para salir de pagos, escribí: SALIR DE PAGO'),
        'GEN_PROBLEMA_PAGO': os.getenv('CMD_PROBLEMA_PAGO', 'Estoy teniendo problemas en el flujo de pagos.'),
        'GEN_PROBLEMA_AGENDA': os.getenv('CMD_PROBLEMA_AGENDA', 'Estoy teniendo problemas en el flujo de agendamiento.'),
        'GEN_INICIO': os.getenv('CMD_GEN_INICIO', '¿En qué puedo ayudarte?')
    }

    # NUEVO: Configuración de zona horaria corregida
    TIMEZONE_CONFIG = {
        'zona_horaria': 'America/Argentina/Buenos_Aires',
        'offset_esperado': '-0300',
        'formato_fecha': '%Y-%m-%d',
        'formato_hora': '%H:%M',
        'horario_laboral': {
            'inicio': 9,
            'fin': 18
        }
    }

    # NUEVO: Configuración para requerir pago antes de agendamiento (opcional)
    # Si está en true, no se permitirá agendar sin verificación de pago
    REQUIRE_PAYMENT_BEFORE_SCHEDULING = os.getenv('REQUIRE_PAYMENT_BEFORE_SCHEDULING', 'false').lower() == 'true'
    if REQUIRE_PAYMENT_BEFORE_SCHEDULING:
        logger.info("✅ Restricción activa: Se requiere verificación de pago antes de agendar")
    else:
        logger.info("ℹ️ Sin restricciones: Flujo normal de agendamiento y pagos")

    # --- Variables opcionales para Chatwoot (centro de gestión) ---
    # Si están configuradas, se habilita integración con Chatwoot
    CHATWOOT_ENABLED = os.getenv('CHATWOOT_ENABLED', 'false').lower() == 'true'
    CHATWOOT_URL = os.getenv('CHATWOOT_URL', '')
    CHATWOOT_ACCOUNT_ID = os.getenv('CHATWOOT_ACCOUNT_ID', '')
    CHATWOOT_INBOX_ID = os.getenv('CHATWOOT_INBOX_ID', '')
    CHATWOOT_API_TOKEN = os.getenv('CHATWOOT_API_TOKEN', '')
    CHATWOOT_CLIENT_NAME = os.getenv('CHATWOOT_CLIENT_NAME', 'CLIENTE')
    CHATWOOT_CLIENT_PHONE = os.getenv('CHATWOOT_CLIENT_PHONE', '')

    # --- Variables para notificaciones WhatsApp ---
    # Contacto que recibirá notificaciones automáticas de pagos y turnos
    NOTIFICATION_CONTACT = os.getenv('NOTIFICATION_CONTACT', '')
    if NOTIFICATION_CONTACT:
        logger.info(f"Sistema de notificaciones configurado para: {NOTIFICATION_CONTACT}")
    else:
        logger.info("Sistema de notificaciones desactivado (NOTIFICATION_CONTACT no configurado)")

except KeyError as e:
    # Si falta alguna variable, se captura el error, se loguea y se detiene el programa.
    logger.critical(f"FATAL: Falta la variable de entorno crítica '{e.args[0]}'. La aplicación no puede iniciar.")
    logger.critical("Por favor, configura esta variable en tu entorno (Render, .env, etc.) y redespliega.")
    sys.exit(1)



