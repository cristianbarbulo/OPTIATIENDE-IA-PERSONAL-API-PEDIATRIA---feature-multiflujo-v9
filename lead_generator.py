# lead_generator.py
# Este script está diseñado para ser ejecutado por un Cron Job en Render.
# Su única misión es analizar las conversaciones recientes, generar datos de lead
# con la IA y actualizar HubSpot.

import logging
from datetime import datetime, timedelta
import json
import re

# --- Importaciones de nuestros módulos ---
# Asegúrate de que estos módulos estén accesibles para este script.
import config
import memory # Usaremos funciones para leer desde Firebase
import llm_handler # Usaremos al nuevo "Agente Analista de Leads"
import hubspot_handler # Usaremos la función para actualizar HubSpot

# --- Configuración del Logger ---
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(f"{config.TENANT_NAME}_LeadGenerator")

# --- Funciones de Soporte ---

def formatear_transcripcion(historial: list) -> str:
    """
    Convierte el historial de conversación de Firebase (una lista de diccionarios)
    en un string de texto plano y legible para la IA.
    """
    transcripcion = ""
    for mensaje in historial:
        rol = "Cliente" if mensaje.get('role') == 'user' else "RODI"
        contenido = mensaje.get('content', '')
        transcripcion += f"{rol}: {contenido}\n"
    return transcripcion.strip()

def parsear_json_del_analista(respuesta_llm: str) -> dict:
    """
    Extrae de forma segura el bloque JSON de la respuesta del Agente Analista.
    """
    # Usamos una expresión regular para encontrar el bloque JSON, incluso si hay texto antes o después.
    match = re.search(r"\[START_JSON\](.*)\[END_JSON\]", respuesta_llm, re.DOTALL)
    
    if not match:
        logger.error(f"El Agente Analista no devolvió un bloque JSON válido. Respuesta: {respuesta_llm}")
        return {}

    json_string = match.group(1).strip()
    
    try:
        datos_lead = json.loads(json_string)
        return datos_lead
    except json.JSONDecodeError:
        logger.error(f"Error al decodificar el JSON del Agente Analista: {json_string}")
        return {}

# --- Función Principal del Proceso ---

def analizar_conversaciones_recientes():
    """
    Función principal que orquesta todo el proceso de análisis y actualización.
    """
    logger.info("--- Iniciando ciclo de análisis de leads ---")

    # 1. Definir el rango de tiempo. Analizaremos las conversaciones actualizadas en la última hora.
    hace_una_hora = datetime.now() - timedelta(hours=1)
    
    # 2. Obtener las conversaciones recientes desde Firebase.
    #    (NOTA: Esto requiere una función en memory.py que pueda filtrar por timestamp)
    conversaciones = memory.get_conversations_updated_since(hace_una_hora)
    
    if not conversaciones:
        logger.info("No se encontraron conversaciones recientes para analizar. Ciclo finalizado.")
        return

    logger.info(f"Se encontraron {len(conversaciones)} conversaciones para analizar.")

    # 3. Procesar cada conversación de forma individual.
    for autor, datos_conv in conversaciones.items():
        logger.info(f"Procesando conversación de: {autor}...")
        
        try:
            historial = datos_conv.get('history', [])
            sender_name = datos_conv.get('senderName', '') # Recuperamos el nombre si existe
            
            if not historial:
                logger.warning(f"La conversación de {autor} no tiene historial. Saltando.")
                continue

            # 4. Formatear el historial en una transcripción de texto.
            transcripcion = formatear_transcripcion(historial)
            
            # 5. Llamar al Agente Analista de Leads.
            respuesta_analista = llm_handler.llamar_analista_leads(transcripcion)
            
            # 6. Parsear la respuesta para obtener el JSON con los datos del lead.
            datos_lead = parsear_json_del_analista(respuesta_analista)
            
            if not datos_lead:
                logger.error(f"No se pudo generar el JSON para {autor}. Se reintentará en el próximo ciclo.")
                continue

            # 7. Actualizar HubSpot con la información obtenida.
            logger.info(f"Actualizando HubSpot para {autor} con los siguientes datos: {datos_lead}")
            clean_phone_number = autor.split('@')[0]
            # Usamos una cadena vacía para `last_message` ya que no es relevante aquí.
            hubspot_handler.update_hubspot_contact(
                phone_number=clean_phone_number,
                name=sender_name,
                last_message="", 
                lead_data=datos_lead
            )
            logger.info(f"Procesamiento para {autor} finalizado con éxito.")

        except Exception as e:
            logger.error(f"Ocurrió un error inesperado al procesar la conversación de {autor}: {e}", exc_info=True)
            # El bucle continúa con la siguiente conversación.

    logger.info("--- Ciclo de análisis de leads finalizado ---")

# --- Bloque de Ejecución ---
if __name__ == '__main__':
    # Esta línea asegura que Firebase y otras configuraciones se inicialicen.
    if memory.db is None:
        logger.critical("FATAL: No se pudo conectar a Firebase. El script no puede continuar.")
    else:
        analizar_conversaciones_recientes()

