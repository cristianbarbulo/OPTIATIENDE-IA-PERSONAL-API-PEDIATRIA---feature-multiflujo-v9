# utils.py
import json
import re
import logging
import dateparser
import time
import os
from datetime import datetime, timedelta
from functools import lru_cache
from threading import Lock
import requests
import config

logger = logging.getLogger(config.TENANT_NAME)

def get_media_url(media_id):
    """
    Obtiene la URL temporal de un archivo multimedia desde 360dialog.
    BASADO EN INFORMACIÓN OFICIAL DE 360DIALOG SUPPORT.
    
    Proceso CORRECTO según 360dialog:
    1. Llamar a GET /{media_id} (NO /media/{media_id})
    2. Extraer URL de Facebook del campo "url" en JSON
    3. Reemplazar dominio lookaside.fbsbx.com por waba-v2.360dialog.io
    4. Usar URL modificada con D360-API-KEY para descarga
    """
    if not media_id:
        logger.error("[MEDIA] No se proporcionó media_id")
        return None
    
    try:
        # Configuración de 360dialog
        api_key = os.getenv('D360_API_KEY')
        
        if not api_key:
            logger.error("[MEDIA] D360_API_KEY no configurada")
            return None
        
        # Headers con autenticación según 360dialog
        headers = {
            'D360-API-KEY': api_key
        }
        
        # PASO 1: Obtener metadatos - ENDPOINT CORRECTO según 360dialog
        media_info_url = f"https://waba-v2.360dialog.io/{media_id}"
        
        logger.info(f"[MEDIA] 🔍 Obteniendo metadatos para media ID: {media_id}")
        logger.info(f"[MEDIA] 🌐 URL endpoint: {media_info_url}")
        
        response = requests.get(media_info_url, headers=headers, timeout=10)
        
        logger.info(f"[MEDIA] 📊 Response status: {response.status_code}")
        
        response.raise_for_status()
        
        media_data = response.json()
        logger.info(f"[MEDIA] 📄 Metadatos recibidos: {media_data}")
        
        # PASO 2: Extraer URL de Facebook del campo "url"
        facebook_url = media_data.get('url')
        
        if not facebook_url:
            logger.error(f"[MEDIA] ❌ Campo 'url' no encontrado en metadatos: {media_data}")
            return None
            
        logger.info(f"[MEDIA] 🔗 URL original de Facebook: {facebook_url}")
        
        # PASO 3: Reemplazar dominio según especificación exacta de 360dialog
        modified_url = facebook_url.replace(
            'https://lookaside.fbsbx.com', 
            'https://waba-v2.360dialog.io'
        )
        
        logger.info(f"[MEDIA] ✅ URL modificada para 360dialog: {modified_url}")
        
        # IMPORTANTE: URLs válidas solo por 5 minutos según 360dialog
        logger.warning(f"[MEDIA] ⏰ URL válida por solo 5 minutos para media ID: {media_id}")
        
        return modified_url
            
    except requests.exceptions.HTTPError as e:
        if e.response and e.response.status_code == 404:
            logger.error(f"[MEDIA] ❌ Media ID {media_id} no encontrado (404)")
            logger.error(f"[MEDIA] 🔍 Posibles causas: 1) Media expirado (>5min), 2) Usando Sandbox en lugar de Producción, 3) Rate limit activo")
        else:
            logger.error(f"[MEDIA] ❌ Error HTTP {e.response.status_code if e.response else 'unknown'} para media ID {media_id}")
            logger.error(f"[MEDIA] 📄 Response: {e.response.text if e.response else 'No response'}")
    except requests.exceptions.RequestException as e:
        logger.error(f"[MEDIA] 🌐 Error de red para media ID {media_id}: {e}")
    except KeyError as e:
        logger.error(f"[MEDIA] 🔑 Campo faltante en respuesta JSON: {e}")
    except Exception as e:
        logger.error(f"[MEDIA] 💥 Error inesperado para media ID {media_id}: {e}", exc_info=True)
    
    return None

def get_media_url_alternative(media_id):
    """
    Método alternativo para obtener media URL construyendo directamente la URL con autenticación.
    """
    if not media_id:
        return None
        
    try:
        api_key = os.getenv('D360_API_KEY')
        if not api_key:
            logger.error("[MEDIA] D360_API_KEY no configurada")
            return None
            
        # Construir URL con API key
        media_url = f"https://waba-v2.360dialog.io/media/{media_id}?access_token={api_key}"
        
        # Verificar si la URL es válida
        headers = {'D360-API-KEY': api_key}
        response = requests.head(media_url, headers=headers, timeout=5)
        
        if response.status_code == 200:
            logger.info(f"[MEDIA] URL alternativa válida para {media_id}")
            return media_url
        else:
            logger.warning(f"[MEDIA] URL alternativa no válida: {response.status_code}")
            return None
            
    except Exception as e:
        logger.error(f"[MEDIA] Error en método alternativo: {e}")
        return None


def download_and_store_media(media_id, output_dir="./downloads"):
    """
    Descarga y almacena archivo multimedia usando el script oficial de 360dialog.
    BASADO EN SCRIPT OFICIAL PROPORCIONADO POR 360DIALOG SUPPORT.
    
    Retorna dict con información del archivo descargado.
    """
    if not media_id:
        return {"success": False, "error": "Media ID no proporcionado"}
        
    try:
        api_key = os.getenv('D360_API_KEY')
        if not api_key:
            return {"success": False, "error": "D360_API_KEY no configurada"}
        
        # PASO 1: Obtener metadatos del media (usando endpoint correcto)
        url = f"https://waba-v2.360dialog.io/{media_id}"
        headers = {"D360-API-KEY": api_key}
        
        logger.info(f"[MEDIA DOWNLOAD] 🔍 Obteniendo metadatos para: {media_id}")
        
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        media_data = response.json()
        logger.info(f"[MEDIA DOWNLOAD] 📊 Metadatos: {media_data}")
        
        # PASO 2: Procesar la URL de descarga según 360dialog
        facebook_url = media_data["url"]
        
        # Reemplazar dominio de Facebook por 360dialog
        download_url = facebook_url.replace(
            "https://lookaside.fbsbx.com", 
            "https://waba-v2.360dialog.io"
        )
        
        logger.info(f"[MEDIA DOWNLOAD] 🔗 URL de descarga: {download_url}")
        
        # PASO 3: Descargar el archivo
        download_response = requests.get(download_url, headers=headers, timeout=30)
        download_response.raise_for_status()
        
        # Crear directorio si no existe
        os.makedirs(output_dir, exist_ok=True)
        
        # Generar nombre de archivo usando mime_type
        file_extension = media_data["mime_type"].split("/")[1] if "/" in media_data["mime_type"] else "bin"
        filename = f"{media_id}.{file_extension}"
        filepath = os.path.join(output_dir, filename)
        
        # Guardar archivo
        with open(filepath, "wb") as f:
            f.write(download_response.content)
        
        logger.info(f"[MEDIA DOWNLOAD] ✅ Archivo descargado: {filepath}")
        
        return {
            "success": True,
            "filepath": filepath,
            "mime_type": media_data["mime_type"],
            "file_size": media_data["file_size"],
            "sha256": media_data.get("sha256"),
            "media_id": media_id
        }
        
    except requests.exceptions.HTTPError as e:
        if e.response and e.response.status_code == 404:
            error_msg = f"Media ID {media_id} no encontrado (posible expiración >5min)"
        else:
            error_msg = f"Error HTTP {e.response.status_code if e.response else 'unknown'}: {str(e)}"
        logger.error(f"[MEDIA DOWNLOAD] ❌ {error_msg}")
        return {"success": False, "error": error_msg}
        
    except requests.exceptions.RequestException as e:
        error_msg = f"Error de red: {str(e)}"
        logger.error(f"[MEDIA DOWNLOAD] 🌐 {error_msg}")
        return {"success": False, "error": error_msg}
        
    except KeyError as e:
        error_msg = f"Campo faltante en respuesta: {str(e)}"
        logger.error(f"[MEDIA DOWNLOAD] 🔑 {error_msg}")
        return {"success": False, "error": error_msg}
        
    except Exception as e:
        error_msg = f"Error inesperado: {str(e)}"
        logger.error(f"[MEDIA DOWNLOAD] 💥 {error_msg}", exc_info=True)
        return {"success": False, "error": error_msg}


def cleanup_old_media_files(directory='/tmp/whatsapp_media', max_age_hours=24):
    """
    Limpia archivos multimedia antiguos del directorio temporal
    """
    import time
    from pathlib import Path
    
    try:
        path = Path(directory)
        if not path.exists():
            return
            
        current_time = time.time()
        
        for file_path in path.iterdir():
            if file_path.is_file():
                file_age_hours = (current_time - file_path.stat().st_mtime) / 3600
                
                if file_age_hours > max_age_hours:
                    file_path.unlink()
                    logger.info(f"[MEDIA] Archivo temporal eliminado: {file_path}")
                    
    except Exception as e:
        logger.error(f"[MEDIA] Error limpiando archivos antiguos: {e}")


def get_next_weekday_date(weekday_name: str) -> str:
    """
    Calcula la fecha del próximo día de la semana especificado.
    
    Args:
        weekday_name: Nombre del día de la semana en español (lunes, martes, etc.)
    
    Returns:
        Fecha en formato ISO (YYYY-MM-DD) del próximo día de la semana
    """
    # Mapeo de nombres de días a números (0=Lunes, 6=Domingo)
    weekday_map = {
        'lunes': 0, 'martes': 1, 'miércoles': 2, 'miercoles': 2,
        'jueves': 3, 'viernes': 4, 'sábado': 5, 'sabado': 5,
        'domingo': 6
    }
    
    weekday_lower = weekday_name.lower()
    if weekday_lower not in weekday_map:
        logger.warning(f"Día de la semana no reconocido: {weekday_name}")
        return None
    
    target_weekday = weekday_map[weekday_lower]
    today = datetime.now()
    current_weekday = today.weekday()
    
    # Calcular días hasta el próximo día objetivo
    days_ahead = target_weekday - current_weekday
    if days_ahead <= 0:  # Si ya pasó este día esta semana, ir a la próxima semana
        days_ahead += 7
    
    next_date = today + timedelta(days=days_ahead)
    return next_date.strftime('%Y-%m-%d')

def parse_json_from_llm_robusto(text: str, context: str = "general") -> dict:
    """
    Extrae un objeto JSON de una cadena de texto, incluso si está envuelta
    en un bloque de código Markdown (```json ... ```).
    
    Args:
        text: Texto que puede contener JSON envuelto en Markdown
        context: Contexto para logging
    
    Returns:
        dict: Objeto JSON extraído o diccionario de error
    """
    logger.info(f"[UTILS] Parseando JSON robusto para contexto '{context}'. Texto original: {text[:200]}...")
    
    # Patrón para encontrar un bloque JSON dentro de ```json ... ```
    match = re.search(r'```json\s*(\{.*?\})\s*```', text, re.DOTALL)
    
    json_str = ""
    if match:
        # Si encuentra el bloque Markdown, extrae solo el contenido JSON
        json_str = match.group(1).strip()
        logger.info(f"[UTILS] Encontrado bloque Markdown JSON. Contenido extraído: {json_str[:200]}...")
    else:
        # Si no hay bloque Markdown, asume que el texto entero es el JSON
        json_str = text.strip()
        logger.info(f"[UTILS] No se encontró bloque Markdown. Usando texto completo como JSON: {json_str[:200]}...")

    try:
        # LIMPIEZA AGRESIVA INICIAL: Eliminar BOMs, caracteres de control y espacios al inicio
        # Esto resuelve el error "Expecting property name enclosed in double quotes: line 1 column 2 (char 1)"
        json_str_saneado = re.sub(r'^[\ufeff\xef\xbb\xbf\x00-\x1F\x7F-\x9F\s]*', '', json_str)
        
        # Saneado adicional: normalizar saltos de línea (sin escapar dentro del contenido)
        json_str_saneado = json_str_saneado.replace('\r\n', '\n').replace('\r', '\n')
        # Eliminar otros caracteres de control no imprimibles (excepto los ya tratados)
        json_str_saneado = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F]', '', json_str_saneado)
        
        # LIMPIEZA FINAL: Asegurar que el string comience con { y termine con }
        # Esto evita caracteres extra al inicio/final que causen errores de parsing
        if json_str_saneado.startswith('{') and json_str_saneado.endswith('}'):
            # Si ya está bien formateado, usar tal como está
            pass
        else:
            # Buscar el primer { y último } para extraer solo el JSON válido
            start_idx = json_str_saneado.find('{')
            end_idx = json_str_saneado.rfind('}')
            if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                json_str_saneado = json_str_saneado[start_idx:end_idx + 1]
            else:
                # Si no se encuentran llaves, intentar con el string original limpio
                json_str_saneado = re.sub(r'^[\ufeff\xef\xbb\xbf\x00-\x1F\x7F-\x9F\s]*', '', json_str)

        # Intenta cargar la cadena JSON saneada
        result = json.loads(json_str_saneado)
        logger.info(f"[UTILS] JSON parseado exitosamente para contexto '{context}': {result}")
        return result
    except json.JSONDecodeError as e:
        logger.error(f"[UTILS] Error al decodificar JSON después de limpiar para contexto '{context}': {e}")
        logger.error(f"[UTILS] JSON que falló: {json_str}")

        # Fallback adicional: intentar el otro parser con limpieza agresiva
        try:
            alt = parse_json_from_llm(text, context=f"{context}_fallback_alt") or {}
            if isinstance(alt, dict) and (alt.get('decision') or alt.get('response_text')):
                logger.info(f"[UTILS] JSON parseado por fallback alternativo para contexto '{context}'")
                return alt
        except Exception as _e2:
            logger.warning(f"[UTILS] Fallback alternativo también falló: {_e2}")
        
        # Intentar reparar el JSON de forma más agresiva
        try:
            # Intentar extraer solo los campos clave que necesitamos (permite texto multilinea)
            decision_match = re.search(r'["\']?\s*decision\s*["\']?\s*:\s*["\']([^"\']+)["\']', json_str, re.DOTALL)
            response_text_match = re.search(r'["\']?\s*response_text\s*["\']?\s*:\s*["\']([\s\S]*?)["\']', json_str, re.DOTALL)
            
            if decision_match:
                result = {'decision': decision_match.group(1)}
                # Al reparar manualmente, decodificar secuencias comunes (\n, \t) a caracteres reales
                repaired_text = response_text_match.group(1) if response_text_match else ""
                if isinstance(repaired_text, str):
                    repaired_text = repaired_text.replace('\\n', '\n').replace('\\t', '\t')
                result['response_text'] = repaired_text
                logger.info(f"[UTILS] JSON reparado manualmente para contexto '{context}': {result}")
                return result
        except Exception as repair_error:
            logger.error(f"[UTILS] Error al intentar reparar JSON manualmente: {repair_error}")
        
        # Devuelve un diccionario de error para que el flujo principal lo maneje
        return {"error": "JSON malformado", "raw_text": text}

def parse_json_from_llm(raw_output: str, context: str = "general") -> dict:
    """
    Analiza una cadena de texto que se espera que contenga un JSON y lo devuelve como un diccionario.
    Es robusto contra los formatos comunes de salida de los LLM, como los bloques de código Markdown.

    Args:
        raw_output: La cadena de texto en bruto de la salida del LLM.
        context: Una cadena opcional para identificar desde dónde se llama a la función para un mejor logging.

    Returns:
        Un diccionario con los datos parseados, o un diccionario vacío si ocurre un error o no hay nada que parsear.
    """
    try:
        # LIMPIEZA AGRESIVA INICIAL: Eliminar BOMs, caracteres de control y espacios al inicio
        # Esto resuelve el error "Expecting property name enclosed in double quotes: line 1 column 2 (char 1)"
        cleaned_str = re.sub(r'^[\ufeff\xef\xbb\xbf\x00-\x1F\x7F-\x9F\s]*', '', raw_output)
        
        # Limpia los delimitadores de bloque de código JSON (```json ... ```) que los LLMs suelen añadir.
        # Esto hace que el parseo sea mucho más fiable.
        cleaned_str = re.sub(r'```json\s*|\s*```', '', cleaned_str).strip()

        # Si después de limpiar no queda nada, no hay nada que parsear.
        if not cleaned_str:
            logger.warning(f"La cadena de entrada para parsear JSON en el contexto '{context}' está vacía después de la limpieza.")
            return {}

        # CORRECCIÓN CRÍTICA MEJORADA: Limpiar comillas extra que causan errores de sintaxis
        # Patrón para encontrar comillas extra como ' "fecha_deseada"' o '"fecha_deseada" '
        cleaned_str = re.sub(r"' \"([^\"]+)\"", r'"\1"', cleaned_str)  # ' "campo"' -> "campo"
        cleaned_str = re.sub(r'\"([^\"]+)\" ', r'"\1"', cleaned_str)  # "campo" ' -> "campo"
        cleaned_str = re.sub(r"'([^']+)'", r'"\1"', cleaned_str)      # 'campo' -> "campo"
        
        # NUEVA CORRECCIÓN: Limpiar comillas extra al inicio y final de campos
        cleaned_str = re.sub(r'([{,])\s*\'?\s*"([^"]+)"\s*\'?\s*:', r'\1"\2":', cleaned_str)
        cleaned_str = re.sub(r'([{,])\s*"([^"]+)"\s*\'?\s*:', r'\1"\2":', cleaned_str)
        
        # Limpiar espacios extra alrededor de las comillas
        cleaned_str = re.sub(r'\s*"\s*', '"', cleaned_str)
        
        # Corregir comillas mal formadas
        cleaned_str = re.sub(r'([{,])\s*([^"]+):\s*"([^"]*)"', r'\1"\2":"\3"', cleaned_str)
        
        # NUEVA CORRECCIÓN: Limpiar comillas extra específicas del error reportado
        cleaned_str = re.sub(r'([{,])\s*\'?\s*"([^"]+)"\s*\'?\s*:', r'\1"\2":', cleaned_str)
        
        # LIMPIEZA FINAL: Asegurar que el string comience con { y termine con }
        # Esto evita caracteres extra al inicio/final que causen errores de parsing
        if cleaned_str.startswith('{') and cleaned_str.endswith('}'):
            # Si ya está bien formateado, usar tal como está
            pass
        else:
            # Buscar el primer { y último } para extraer solo el JSON válido
            start_idx = cleaned_str.find('{')
            end_idx = cleaned_str.rfind('}')
            if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                cleaned_str = cleaned_str[start_idx:end_idx + 1]
            else:
                # Si no se encuentran llaves, intentar con el string original limpio
                cleaned_str = re.sub(r'^[\ufeff\xef\xbb\xbf\x00-\x1F\x7F-\x9F\s]*', '', raw_output)
        
        # Log para debug
        logger.info(f"[UTILS] JSON limpio para contexto '{context}': {cleaned_str[:200]}...")

        # Intenta decodificar la cadena limpia como JSON.
        return json.loads(cleaned_str)
    except json.JSONDecodeError as e:
        # Si la decodificación falla, loguea el error con el contexto y la salida problemática para facilitar el debug.
        logger.error(f"Error al parsear JSON en el contexto '{context}'. Error: {e}. Salida en bruto: {raw_output}")
        logger.error(f"JSON limpio que falló: {cleaned_str}")
        
        # NUEVA CORRECCIÓN: Intentar reparar el JSON de forma más agresiva
        try:
            # Intentar extraer solo los campos clave que necesitamos
            fecha_match = re.search(r'["\']?\s*fecha_deseada\s*["\']?\s*:\s*["\']([^"\']+)["\']', raw_output)
            hora_match = re.search(r'["\']?\s*hora_especifica\s*["\']?\s*:\s*["\']([^"\']+)["\']', raw_output)
            intencion_match = re.search(r'["\']?\s*intencion\s*["\']?\s*:\s*["\']([^"\']+)["\']', raw_output)
            
            if fecha_match or hora_match or intencion_match:
                result = {}
                if fecha_match:
                    result['fecha_deseada'] = fecha_match.group(1)
                if hora_match:
                    result['hora_especifica'] = hora_match.group(1)
                if intencion_match:
                    result['intencion'] = intencion_match.group(1)
                else:
                    result['intencion'] = 'agendar'
                
                logger.info(f"[UTILS] JSON reparado manualmente para contexto '{context}': {result}")
                return result
        except Exception as repair_error:
            logger.error(f"Error al intentar reparar JSON manualmente: {repair_error}")
        
        return {}

def ensure_plain_text_from_llm(raw_output: str) -> str:
    """
    Asegura texto plano a partir de una salida del LLM que puede venir como JSON.
    - Si detecta JSON (incluyendo bloque ```json), extrae campos típicos de texto.
    - Fallback: limpia fences Markdown y devuelve el string tal cual.
    """
    try:
        if raw_output is None:
            return ""
        raw_str = str(raw_output).strip()
        if not raw_str:
            return ""
        # Intento 1: parseo robusto directo
        data = parse_json_from_llm_robusto(raw_str, context="ensure_plain_text") or {}
        if isinstance(data, dict):
            for key in [
                "respuesta", "response", "response_text", "texto", "message", "content", "output", "text"
            ]:
                val = data.get(key)
                if isinstance(val, str) and val.strip():
                    text = val.strip()
                    # Decodificar secuencias visibles si quedaran escapadas
                    text = text.replace('\\n', '\n').replace('\\t', '\t')
                    return text
        # Intento 2: limpiar fences y reintentar
        import re as _re
        cleaned = _re.sub(r"```[a-zA-Z]*\s*([\s\S]*?)```", r"\1", raw_str).strip()
        data2 = parse_json_from_llm(cleaned, context="ensure_plain_text_fallback") or {}
        if isinstance(data2, dict):
            for key in [
                "respuesta", "response", "response_text", "texto", "message", "content", "output", "text"
            ]:
                val = data2.get(key)
                if isinstance(val, str) and val.strip():
                    text = val.strip()
                    text = text.replace('\\n', '\n').replace('\\t', '\t')
                    return text
        # Fallback final: devolver el texto limpio decodificando secuencias visibles
        return cleaned.replace('\\n', '\n').replace('\\t', '\t')
    except Exception:
        try:
            return str(raw_output).strip()
        except Exception:
            return ""

def format_fecha_espanol(dt):
    dias = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
    meses = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']
    dia = dias[dt.weekday()]
    mes = meses[dt.month - 1]
    return f"{dia} {dt.day} de {mes} a las {dt.strftime('%H:%M')} hs"

def parsear_fecha_hora_natural(texto, preferencia_tz=None, return_details=False):
    """
    Parsea fechas y horas expresadas en lenguaje natural.

    Args:
        texto (str): Texto que contiene la fecha/hora en lenguaje natural.
        preferencia_tz (str, opcional): Zona horaria preferida para dateparser.
        return_details (bool, opcional): Si es True, devuelve un diccionario con metadatos
            enriquecidos; si es False (comportamiento legado), devuelve una tupla
            (fecha_datetime, hora_str) o None.

    Returns:
        dict | tuple | None: Diccionario con metadatos cuando return_details=True.
            Caso contrario, tupla (datetime | None, str | None) o None si no se detecta nada.
    """
    try:
        if not texto or not isinstance(texto, str):
            return {} if return_details else None

        texto_lower = texto.lower()
        hora_str = None
        hora_datetime = None
        fecha_especifica_iso = None
        fecha_datetime = None
        preferencia_detectada = None
        dia_semana_detectado = None
        restricciones = []

        # --- Extracción de hora explícita ---
        patrones_hora = [
            r'a las (\d{1,2})(?::(\d{2}))?\s*(hs?|horas?)?',
            r'(\d{1,2})(?::(\d{2}))?\s*(hs?|horas?)?',
            r'(\d{1,2})\s*(hs?|horas?)\s*de\s*(mañana|tarde|noche)',
            r'(\d{1,2})\s*de\s*(mañana|tarde|noche)',
            r'(\d{1,2})\s*(hs?|horas?)\s*(de\s*la\s*)?(mañana|tarde|noche)',
        ]

        for patron in patrones_hora:
            match = re.search(patron, texto_lower)
            if match:
                hora = int(match.group(1))
                minutos = int(match.group(2)) if match.group(2) else 0

                if 'tarde' in texto_lower and hora < 12:
                    hora += 12
                    preferencia_detectada = preferencia_detectada or 'tarde'
                elif 'noche' in texto_lower and hora < 12:
                    hora += 12
                    preferencia_detectada = preferencia_detectada or 'noche'
                elif 'mañana' in texto_lower and hora >= 12:
                    hora -= 12
                    preferencia_detectada = preferencia_detectada or 'mañana'

                hora = max(0, min(23, hora))
                minutos = max(0, min(59, minutos))
                hora_str = f"{hora:02d}:{minutos:02d}"
                hora_datetime = datetime.now().replace(hour=hora, minute=minutos, second=0, microsecond=0)
                logger.info(f"[UTILS] Hora específica extraída: {hora_str}")
                break

        # --- Preferencias horarias generales ---
        preferencias_horarias = {
            'mediodía': 12,
            'mediodia': 12,
            'tarde': 14,
            'mañana': 9,
            'noche': 20,
            'temprano': 8,
            'última hora': 18,
            'ultima hora': 18,
        }

        for pref, hora_pref in preferencias_horarias.items():
            if pref in texto_lower:
                preferencia_detectada = preferencia_detectada or pref.split()[0]
                if not hora_str:
                    hora_str = f"{hora_pref:02d}:00"
                    hora_datetime = datetime.now().replace(hour=hora_pref, minute=0, second=0, microsecond=0)
                    logger.info(f"[UTILS] Preferencia horaria extraída: {pref} -> {hora_pref}:00")
                break

        # --- Restricciones temporales ---
        if 'después de las' in texto_lower or 'después de la' in texto_lower:
            match = re.search(r'después de (?:las? )?(\d{1,2})', texto_lower)
            if match:
                hora_limite = int(match.group(1))
                restricciones.append(f"después_{hora_limite}")
                logger.info(f"[UTILS] Restricción temporal extraída: después de las {hora_limite}")

        if 'antes de las' in texto_lower or 'antes de la' in texto_lower:
            match = re.search(r'antes de (?:las? )?(\d{1,2})', texto_lower)
            if match:
                hora_limite = int(match.group(1))
                restricciones.append(f"antes_{hora_limite}")
                logger.info(f"[UTILS] Restricción temporal extraída: antes de las {hora_limite}")

        # --- Normalización de formatos explícitos DD/MM ---
        texto_norm = texto_lower.replace('proximo', 'próximo').replace('siguiente', 'próximo')
        m_dm = re.search(r"\b(\d{1,2})[\./\-\s](\d{1,2})(?:[\./\-\s](\d{2,4}))?\b", texto_norm)
        if m_dm:
            dia = int(m_dm.group(1))
            mes = int(m_dm.group(2))
            anio = datetime.now().year
            if m_dm.group(3):
                y = int(m_dm.group(3))
                anio = y if y > 99 else (2000 + y)
            try:
                fecha_candidata = datetime(anio, mes, dia)
                if not m_dm.group(3) and fecha_candidata.date() < datetime.now().date():
                    fecha_candidata = fecha_candidata.replace(year=anio + 1)
                fecha_especifica_iso = fecha_candidata.strftime('%Y-%m-%d')
                logger.info(f"[UTILS] Fecha dd/mm normalizada: {fecha_especifica_iso}")
            except Exception:
                pass

        # --- Días de la semana ---
        dias_semana = {
            'lunes': 0, 'martes': 1, 'miércoles': 2, 'miercoles': 2,
            'jueves': 3, 'viernes': 4, 'sábado': 5, 'sabado': 5, 'domingo': 6
        }

        for dia_nombre in dias_semana.keys():
            if dia_nombre in texto_lower:
                dia_semana_detectado = 'miércoles' if dia_nombre == 'miercoles' else dia_nombre
                fecha_especifica_iso = get_next_weekday_date(dia_semana_detectado)
                logger.info(f"[UTILS] Día de semana extraído: {dia_semana_detectado} -> {fecha_especifica_iso}")
                break

        # --- dateparser: fallback/general ---
        settings = {
            'PREFER_DAY_OF_MONTH': 'first',
            'PREFER_DATES_FROM': 'future',
            'RELATIVE_BASE': datetime.now()
        }
        if preferencia_tz:
            settings['TIMEZONE'] = preferencia_tz

        parsed_date = dateparser.parse(texto, settings=settings)

        if parsed_date and hora_datetime:
            parsed_date = parsed_date.replace(hour=hora_datetime.hour, minute=hora_datetime.minute)
            logger.info(f"[UTILS] Fecha y hora combinadas: {parsed_date}")

        if fecha_especifica_iso and parsed_date:
            try:
                fecha_obj = datetime.strptime(fecha_especifica_iso, '%Y-%m-%d')
                parsed_date = parsed_date.replace(year=fecha_obj.year, month=fecha_obj.month, day=fecha_obj.day)
                logger.info(f"[UTILS] Fecha específica aplicada: {parsed_date}")
            except Exception as e:
                logger.warning(f"[UTILS] Error al aplicar fecha específica: {e}")

        if parsed_date:
            fecha_datetime = parsed_date
            fecha_especifica_iso = fecha_especifica_iso or parsed_date.strftime('%Y-%m-%d')
        elif fecha_especifica_iso:
            try:
                fecha_datetime = datetime.strptime(fecha_especifica_iso, '%Y-%m-%d')
            except Exception:
                fecha_datetime = None

        resultado_detallado = None
        if fecha_datetime or hora_str or restricciones or preferencia_detectada:
            resultado_detallado = {
                'fecha_datetime': fecha_datetime,
                'fecha_iso': fecha_especifica_iso,
                'hora': hora_str,
                'preferencia_horaria': preferencia_detectada,
                'restricciones_temporales': restricciones if restricciones else None,
                'dia_semana': dia_semana_detectado,
                'expresion_original': texto.strip()
            }

        if return_details:
            return resultado_detallado or {}

        if resultado_detallado:
            return (resultado_detallado['fecha_datetime'], resultado_detallado['hora'])

        return None

    except Exception as e:
        logger.error(f"Error al parsear fecha/hora natural: {e}")
        return {} if return_details else None

def get_current_datetime():
    """Retorna la fecha y hora actual en formato ISO"""
    return datetime.now().isoformat()

def reconstruir_mensaje_completo(messages_to_process, author=""):
    """
    Función centralizada para reconstruir mensajes del buffer de manera consistente.
    Usada por todos los handlers para garantizar que los LLMs reciban el contexto completo.
    
    Args:
        messages_to_process: Lista de mensajes del buffer
        author: Identificador del usuario (opcional, para logs)
    
    Returns:
        tuple: (mensaje_completo_usuario, user_message_for_history, image_content_for_lector)
    """
    import logging
    logger = logging.getLogger("MENTEPARATODOS")
    
    ordered_user_content = []
    image_content_for_lector = []
    user_message_for_history = ""
    
    # Contador para identificar múltiples mensajes
    message_count = len(messages_to_process)
    logger.info(f"[UTILS] Reconstruyendo {message_count} mensajes para {author}")
    
    for i, msg in enumerate(messages_to_process):
        message_type = msg.get('type')
        timestamp = msg.get('time', '')
        
        # Agregar separador si hay múltiples mensajes
        if message_count > 1 and i > 0:
            ordered_user_content.append("---")
            user_message_for_history += " | "
        
        if message_type == 'chat' and msg.get('body'):
            text_content = msg['body']
            # Si hay múltiples mensajes, agregar prefijo
            if message_count > 1:
                text_content = f"[Mensaje {i+1}]: {text_content}"
            ordered_user_content.append(text_content)
            user_message_for_history += text_content + " "
            
        elif message_type == 'audio' and msg.get('body'):
            audio_url = msg.get('body')
            logger.info(f"[UTILS] Procesando audio para {author}")
            from audio_handler import transcribe_audio_from_url
            transcribed_text = transcribe_audio_from_url(audio_url)
            if transcribed_text:
                # Si hay múltiples mensajes, agregar prefijo
                if message_count > 1:
                    transcribed_text = f"[Audio {i+1}]: {transcribed_text}"
                else:
                    transcribed_text = f"[AUDIO]: {transcribed_text}"
                ordered_user_content.append(transcribed_text)
                user_message_for_history += f"[AUDIO] {transcribed_text} "
                
        elif message_type == 'image' and msg.get('body'):
            image_url = msg['body']
            caption = msg.get('caption', '')
            
            # Si hay múltiples mensajes, agregar prefijo
            if message_count > 1:
                image_prefix = f"[Imagen {i+1}]"
            else:
                image_prefix = "[IMAGEN]"
            
            if caption:
                caption_with_prefix = f"{image_prefix}: {caption}"
                ordered_user_content.append(caption_with_prefix)
                user_message_for_history += f"{image_prefix} {caption} "
            else:
                user_message_for_history += f"{image_prefix} "
                
            try:
                logger.info(f"[UTILS] Descargando imagen para {author}")
                import requests
                import base64
                response = requests.get(image_url, timeout=45)
                response.raise_for_status()
                if len(response.content) > 5 * 1024 * 1024:
                    logger.warning(f"La imagen de {author} es demasiado grande. Se ignorará.")
                    continue 
                image_base64 = base64.b64encode(response.content).decode('utf-8')
                image_content_for_lector.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}})
                ordered_user_content.append("[[IMAGEN_ANALIZADA]]")
            except Exception as e:
                logger.error(f"Error al descargar imagen para {author}: {e}")
    
    logger.info(f"[UTILS] ordered_user_content: {ordered_user_content}")
    if not ordered_user_content: 
        logger.info(f"[UTILS] No hay contenido de usuario para {author}")
        return "", "", []
        
    # Procesar imágenes si las hay
    image_description = ""
    if image_content_for_lector:
        logger.info(f"[UTILS] Llamando a agente lector para {author}")
        from llm_handler import llamar_agente_lector
        image_description = llamar_agente_lector(image_content_for_lector).strip()
        
    # Reconstrucción inteligente del mensaje final
    final_user_prompt_parts = []
    for item in ordered_user_content:
        if item == "[[IMAGEN_ANALIZADA]]":
            if image_description and "N/A" not in image_description:
                # Si hay múltiples mensajes, agregar prefijo a la descripción de imagen
                if message_count > 1:
                    image_description = f"[Descripción de imagen]: {image_description}"
                final_user_prompt_parts.append(image_description)
        else:
            final_user_prompt_parts.append(item)
    
    # Usar separadores más claros si hay múltiples mensajes
    if message_count > 1:
        mensaje_completo_usuario = "\n".join(final_user_prompt_parts).strip()
        logger.info(f"[UTILS] Mensaje compuesto de {message_count} fragmentos para {author}")
    else:
        mensaje_completo_usuario = " ".join(final_user_prompt_parts).strip()
        
    logger.info(f"[UTILS] mensaje_completo_usuario: {mensaje_completo_usuario}")
    
    return mensaje_completo_usuario, user_message_for_history, image_content_for_lector

def limpiar_contexto_pagos_unificado(context):
    """
    MEJORADO: Limpieza agresiva del contexto para el flujo unificado de pagos.
    Elimina campos de catálogo que ya no se usan.
    """
    if not context:
        return {}
    
    # Campos específicos de pagos que deben ser eliminados
    campos_pago_a_limpiar = [
        'servicio_seleccionado_id', 'precio', 'proveedor_seleccionado', 'external_reference',
        'current_state', 'plan', 'monto', 
        'proveedor', 'payment_data', 'preference_id', 'link_pago', 'servicio_pagado',
        'precio_pagado', 'comprobante_enviado', 'pago_verificado'
        # ELIMINADO: 'servicios_disponibles_para_seleccion' - ya no se guarda en el estado
    ]
    
    # Crear una copia del contexto para no modificar el original
    context_limpio = context.copy()
    
    # Eliminar campos de pagos
    for campo in campos_pago_a_limpiar:
        context_limpio.pop(campo, None)
    
    # Mantener solo información esencial
    context_limpio['current_state'] = 'preguntando'
    
    logger.info(f"[LIMPIEZA_PAGOS] Contexto limpiado agresivamente (sin catálogos)")
    return context_limpio


def limpiar_contexto_agendamiento_unificado(context):
    """
    MEJORADO: Limpieza agresiva del contexto para el flujo unificado de agendamiento.
    Elimina campos de catálogo que ya no se usan.
    CORRECCIÓN CRÍTICA: Preservar información extraída por la IA (fecha_deseada, preferencia_horaria).
    """
    if not context:
        return {}
    
    # Campos específicos de agendamiento que deben ser eliminados
    campos_agendamiento_a_limpiar = [
        'available_slots',
        'slot_seleccionado_para_finalizar',
        'slots_seleccionados', 'evento_confirmado', 'last_event_id', 'turno_confirmado',
        'cita_agendada', 'cita_reprogramada', 'cita_cancelada', 'no_slots_reason',
        'primer_turno_disponible', 'restricciones_temporales', 'servicio',
        'es_reprogramacion', 'current_state'
        # ELIMINADO: 'available_slots_para_seleccion' - ya no se guarda en el estado
        # CORRECCIÓN CRÍTICA: NO eliminar 'fecha_deseada', 'hora_especifica', 'preferencia_horaria'
    ]
    
    # Crear una copia del contexto para no modificar el original
    context_limpio = context.copy()
    
    # Eliminar campos de agendamiento (pero preservar información de la IA)
    for campo in campos_agendamiento_a_limpiar:
        context_limpio.pop(campo, None)
    
    # Mantener solo información esencial
    context_limpio['current_state'] = 'preguntando'
    
    logger.info(f"[LIMPIEZA_AGENDA] Contexto limpiado preservando información de la IA")
    return context_limpio


def validar_estado_activo(estado):
    """
    NUEVO: Valida si un estado es activo en el orquestador rígido.
    """
    import config
    estados_activos = config.ORQUESTADOR_RIGIDO['estados_activos']
    return estado in estados_activos


def detectar_comprobante_pago(mensaje):
    """
    NUEVO: Detecta si el mensaje contiene un comprobante de pago.
    """
    import config
    if '[Descripción de imagen]' not in mensaje:
        return False
    
    palabras_clave = config.ORQUESTADOR_RIGIDO['detector_comprobantes']['palabras_clave']
    mensaje_lower = mensaje.lower()
    
    return any(palabra in mensaje_lower for palabra in palabras_clave)

@lru_cache(maxsize=None)
def get_services_catalog():
    """
    NUEVO: Función centralizada para obtener el catálogo de servicios.
    No guarda el catálogo en el estado, solo lo devuelve cuando se necesita.
    CACHÉ IMPLEMENTADO: Usa @lru_cache para evitar lecturas repetidas del archivo de configuración.
    """
    import config
    import json
    
    try:
        # Intentar cargar desde SERVICE_PRICES_JSON
        if config.SERVICE_PRICES_JSON and config.SERVICE_PRICES_JSON != '{}':
            precios_dict = json.loads(config.SERVICE_PRICES_JSON)
            servicios = [
                {
                    'id': f'servicio_{i}',
                    'nombre': servicio,
                    'precio': precio,
                    'descripcion': f'Servicio de {servicio.lower()}'
                }
                for i, (servicio, precio) in enumerate(precios_dict.items(), 1)
            ]
            logger.info(f"[CATALOGO] Cargados {len(servicios)} servicios desde SERVICE_PRICES_JSON")
            return servicios
        else:
            # Usar configuración por defecto
            servicios = [
                {
                    'id': 'servicio_1',
                    'nombre': 'Coaching Personalizado',
                    'precio': 200,
                    'descripcion': 'Sesión de coaching para desarrollo profesional y personal'
                },
                {
                    'id': 'servicio_2',
                    'nombre': 'Consultita Rápida',
                    'precio': 100,
                    'descripcion': 'Consulta rápida para resolver dudas específicas'
                },
                {
                    'id': 'servicio_3',
                    'nombre': 'Mentoría Intensiva',
                    'precio': 300,
                    'descripcion': 'Programa de mentoría intensivo con seguimiento'
                }
            ]
            logger.info(f"[CATALOGO] Usando configuración por defecto: {len(servicios)} servicios")
            return servicios
    except Exception as e:
        logger.error(f"[CATALOGO] Error cargando servicios: {e}")
        # VALOR SEGURO: Devolver lista vacía en caso de error para evitar que el bot se rompa
        return []


def get_service_by_id(service_id):
    """
    NUEVO: Obtiene un servicio específico por su ID.
    MANEJO ROBUSTO DE ERRORES: Envuelta en try-except con valores seguros.
    """
    try:
        # Validar parámetros de entrada
        if not service_id:
            logger.error("[SERVICIO] Error: service_id es requerido")
            return None
        
        # Obtener catálogo de servicios (usando caché automáticamente)
        servicios = get_services_catalog()
        
        # Validar que servicios sea una lista
        if not isinstance(servicios, list):
            logger.error(f"[SERVICIO] get_services_catalog no devolvió una lista: {type(servicios)}")
            return None
        
        # Buscar el servicio por ID
        for servicio in servicios:
            try:
                if not isinstance(servicio, dict):
                    logger.warning(f"[SERVICIO] Servicio no es un diccionario: {type(servicio)}")
                    continue
                
                servicio_id = servicio.get('id')
                if servicio_id == service_id:
                    logger.info(f"[SERVICIO] Servicio encontrado: {servicio.get('nombre', 'Sin nombre')}")
                    return servicio
            except Exception as e:
                logger.error(f"[SERVICIO] Error procesando servicio: {e}")
                continue
        
        logger.warning(f"[SERVICIO] Servicio con ID '{service_id}' no encontrado")
        return None
        
    except Exception as e:
        logger.error(f"[SERVICIO] Error catastrófico obteniendo servicio '{service_id}': {e}")
        # VALOR SEGURO: Devolver None en caso de error para evitar que el bot se rompa
        return None


def get_available_slots_catalog(author, fecha_deseada=None, max_slots=5, hora_especifica=None, preferencia_horaria=None):
    """
    NUEVO: Función centralizada para obtener turnos disponibles.
    CORRECCIÓN CRÍTICA: Ahora pasa hora_especifica y preferencia_horaria para filtrado inteligente.
    """
    import agendamiento_handler
    
    try:
        # Validar parámetros de entrada
        if not author:
            logger.error("[CATALOGO] Error: author es requerido para obtener turnos")
            return []
        
        if max_slots <= 0:
            logger.warning(f"[CATALOGO] max_slots inválido ({max_slots}), usando valor por defecto (5)")
            max_slots = 5
        
        # PLAN DE REFACTORIZACIÓN v3: Obtener turnos con retry y exponential backoff
        try:
            logger.info(f"[CATALOGO] Llamando a get_available_slots_for_user con fecha: {fecha_deseada}, hora: {hora_especifica}, preferencia: {preferencia_horaria}")
            available_slots = retry_with_exponential_backoff(
                agendamiento_handler.get_available_slots_for_user,
                author, fecha_deseada, max_slots, hora_especifica, preferencia_horaria
            )
        except Exception as e:
            logger.error(f"[CATALOGO] Error después de reintentos llamando a get_available_slots_for_user: {e}")
            return []
        
        if not available_slots:
            logger.warning(f"[CATALOGO] No se encontraron turnos disponibles para {author}")
            return []

        if hora_especifica or preferencia_horaria:
            available_slots = agendamiento_handler._filtrar_slots_por_restricciones(
                available_slots,
                [],
                preferencia_horaria
            )
        
        # Validar que available_slots sea una lista
        if not isinstance(available_slots, list):
            logger.error(f"[CATALOGO] available_slots no es una lista: {type(available_slots)}")
            return []
        
        # Limitar a max_slots
        slots_limitados = available_slots[:max_slots]
        
        # Formatear los slots para mostrar con manejo de errores
        slots_formateados = []
        for i, slot in enumerate(slots_limitados, 1):
            try:
                if not slot:
                    logger.warning(f"[CATALOGO] Slot vacío en posición {i}, saltando")
                    continue
                
                # Validar que el slot tenga la estructura esperada
                if not isinstance(slot, dict):
                    logger.error(f"[CATALOGO] Slot en posición {i} no es un diccionario: {type(slot)}")
                    continue
                
                slot_iso = slot.get('slot_iso')
                if not slot_iso:
                    logger.warning(f"[CATALOGO] Slot en posición {i} no tiene slot_iso")
                    continue
                
                fecha_hora = datetime.fromisoformat(slot_iso)
                fecha_formateada = format_fecha_espanol(fecha_hora)
                
                # NUEVA MEJORA: Preservar todos los campos originales del slot
                # y solo agregar los campos adicionales necesarios
                slot_formateado = {
                    'id': f'turno_{i}',
                    'slot_iso': slot_iso,
                    'fecha_formateada': fecha_formateada
                }
                
                # Preservar campos críticos del slot original
                if 'fecha_para_titulo' in slot:
                    slot_formateado['fecha_para_titulo'] = slot['fecha_para_titulo']
                if 'fecha_completa_legible' in slot:
                    slot_formateado['fecha_completa_legible'] = slot['fecha_completa_legible']
                if 'fecha' in slot:
                    slot_formateado['fecha'] = slot['fecha']
                if 'hora' in slot:
                    slot_formateado['hora'] = slot['hora']
                
                slots_formateados.append(slot_formateado)
            except ValueError as e:
                logger.error(f"[CATALOGO] Error parseando slot {slot}: {e}")
                continue
            except Exception as e:
                logger.error(f"[CATALOGO] Error inesperado procesando slot {slot}: {e}")
                continue
        
        logger.info(f"[CATALOGO] Cargados {len(slots_formateados)} turnos disponibles")
        return slots_formateados
        
    except Exception as e:
        logger.error(f"[CATALOGO] Error catastrófico obteniendo turnos para {author}: {e}")
        # VALOR SEGURO: Devolver lista vacía en caso de error para evitar que el bot se rompa
        return []


def get_slot_by_id(slot_id, available_slots):
    """
    NUEVO: Obtiene un turno específico por su ID de la lista de turnos disponibles.
    """
    for slot in available_slots:
        if slot.get('id') == slot_id:
            return slot
    return None

def get_selected_service_from_context(state_context):
    """
    NUEVO: Obtiene el servicio seleccionado desde el contexto usando el catálogo centralizado.
    MANEJO ROBUSTO DE ERRORES: Envuelta en try-except con valores seguros.
    """
    try:
        # Validar parámetros de entrada
        if not state_context:
            logger.debug("[CONTEXTO] state_context es None o vacío")
            return None
        
        if not isinstance(state_context, dict):
            logger.error(f"[CONTEXTO] state_context no es un diccionario: {type(state_context)}")
            return None
        
        service_id = state_context.get('servicio_seleccionado_id')
        if not service_id:
            logger.debug("[CONTEXTO] No hay servicio_seleccionado_id en el contexto")
            return None
        
        # Obtener servicio usando la función con caché
        servicio = get_service_by_id(service_id)
        if servicio:
            logger.info(f"[CONTEXTO] Servicio obtenido del contexto: {servicio.get('nombre', 'Sin nombre')}")
        else:
            logger.warning(f"[CONTEXTO] No se pudo obtener servicio con ID: {service_id}")
        
        return servicio
        
    except Exception as e:
        logger.error(f"[CONTEXTO] Error catastrófico obteniendo servicio del contexto: {e}")
        # VALOR SEGURO: Devolver None en caso de error para evitar que el bot se rompa
        return None


def get_selected_slot_from_context(state_context):
    """
    NUEVO: Obtiene el turno seleccionado desde el contexto.
    MANEJO ROBUSTO DE ERRORES: Envuelta en try-except con valores seguros.
    """
    try:
        # Validar parámetros de entrada
        if not state_context:
            logger.debug("[CONTEXTO] state_context es None o vacío")
            return None
        
        if not isinstance(state_context, dict):
            logger.error(f"[CONTEXTO] state_context no es un diccionario: {type(state_context)}")
            return None
        
        slot_seleccionado = state_context.get('slot_seleccionado_para_finalizar')
        if not slot_seleccionado:
            logger.debug("[CONTEXTO] No hay slot_seleccionado_para_finalizar en el contexto")
            return None
        
        # Validar que el slot tenga la estructura esperada
        if not isinstance(slot_seleccionado, dict):
            logger.error(f"[CONTEXTO] slot_seleccionado no es un diccionario: {type(slot_seleccionado)}")
            return None
        
        logger.info(f"[CONTEXTO] Slot obtenido del contexto: {slot_seleccionado.get('fecha_formateada', 'Sin fecha')}")
        return slot_seleccionado
        
    except Exception as e:
        logger.error(f"[CONTEXTO] Error catastrófico obteniendo slot del contexto: {e}")
        # VALOR SEGURO: Devolver None en caso de error para evitar que el bot se rompa
        return None
    
# --- SISTEMA DE CACHÉ CON EXPIRACIÓN PARA TURNOS ---
import time
from threading import Lock

# Caché para turnos disponibles con expiración
_slots_cache = {}
_slots_cache_lock = Lock()
_SLOTS_CACHE_TTL = 60  # 60 segundos de tiempo de vida

def _get_cache_key(author, fecha_deseada=None, max_slots=5, preferencia_horaria=None, hora_especifica=None):
    """
    Genera una clave única para el caché de turnos.
    CORRECCIÓN CRÍTICA: Ahora incluye hora_especifica para evitar mezclas de datos.
    """
    # Normalizar parámetros para evitar claves duplicadas por diferencias menores
    fecha_normalizada = fecha_deseada if fecha_deseada else "default"
    preferencia_normalizada = preferencia_horaria if preferencia_horaria else "default"
    hora_normalizada = hora_especifica if hora_especifica else "default"
    
    # Crear clave única que incluya todos los parámetros de búsqueda
    cache_key = f"slots:{author}:{fecha_normalizada}:{preferencia_normalizada}:{hora_normalizada}:{max_slots}"
    
    logger.debug(f"[CACHE] Clave generada: {cache_key}")
    return cache_key

def _is_cache_valid(cache_entry):
    """
    Verifica si una entrada del caché sigue siendo válida.
    """
    if not cache_entry:
        return False
    return time.time() - cache_entry.get('timestamp', 0) < _SLOTS_CACHE_TTL

def get_available_slots_catalog_with_cache(author, fecha_deseada=None, max_slots=5, preferencia_horaria=None, hora_especifica=None):
    """
    NUEVO: Versión con caché de get_available_slots_catalog.
    CORRECCIÓN CRÍTICA: Ahora incluye hora_especifica para filtrado inteligente.
    """
    cache_key = _get_cache_key(author, fecha_deseada, max_slots, preferencia_horaria, hora_especifica)
    
    with _slots_cache_lock:
        # Verificar si hay una entrada válida en caché
        if cache_key in _slots_cache and _is_cache_valid(_slots_cache[cache_key]):
            cached_data = _slots_cache[cache_key]
            logger.info(f"[CACHE] Turnos servidos desde caché para {author} (TTL: {_SLOTS_CACHE_TTL}s)")
            return cached_data['slots']
    
    # Si no hay caché válido, obtener datos frescos
    try:
        logger.info(f"[CACHE] Obteniendo turnos frescos para {author} con fecha: {fecha_deseada}, hora: {hora_especifica}")
        fresh_slots = get_available_slots_catalog(author, fecha_deseada, max_slots, hora_especifica, preferencia_horaria)
        
        # Guardar en caché con timestamp
        with _slots_cache_lock:
            _slots_cache[cache_key] = {
                'slots': fresh_slots,
                'timestamp': time.time()
            }
        
        logger.info(f"[CACHE] Turnos frescos guardados en caché para {author}")
        return fresh_slots
        
    except Exception as e:
        logger.error(f"[CACHE] Error obteniendo turnos frescos para {author}: {e}")
        # Intentar devolver datos del caché aunque estén expirados como fallback
        with _slots_cache_lock:
            if cache_key in _slots_cache:
                expired_data = _slots_cache[cache_key]
                logger.warning(f"[CACHE] Usando datos expirados como fallback para {author}")
                return expired_data['slots']
        
        # Si no hay nada en caché, devolver lista vacía
        return []

def clear_slots_cache():
    """
    NUEVO: Función para limpiar el caché de turnos (útil para testing o mantenimiento).
    """
    with _slots_cache_lock:
        _slots_cache.clear()
        logger.info("[CACHE] Caché de turnos limpiado")

def get_slots_cache_stats():
    """
    NUEVO: Función para obtener estadísticas del caché de turnos.
    """
    with _slots_cache_lock:
        total_entries = len(_slots_cache)
        valid_entries = sum(1 for entry in _slots_cache.values() if _is_cache_valid(entry))
        expired_entries = total_entries - valid_entries
        
        return {
            'total_entries': total_entries,
            'valid_entries': valid_entries,
            'expired_entries': expired_entries,
            'cache_ttl_seconds': _SLOTS_CACHE_TTL
        }

def clear_user_slots_cache(author):
    """
    NUEVO: Limpia todas las entradas de caché para un usuario específico.
    Se llama después de agendar o reprogramar para evitar datos obsoletos.
    """
    if not author:
        logger.warning("[CACHE] No se puede limpiar caché: author es requerido")
        return
    
    with _slots_cache_lock:
        # Crear una lista de claves a borrar para no modificar el dict mientras se itera
        keys_to_delete = [key for key in _slots_cache if key.startswith(f"slots:{author}:")]
        
        if keys_to_delete:
            for key in keys_to_delete:
                del _slots_cache[key]
            logger.info(f"[CACHE] Caché de turnos limpiado para el usuario {author} ({len(keys_to_delete)} entradas eliminadas)")
        else:
            logger.debug(f"[CACHE] No se encontraron entradas de caché para el usuario {author}")

def acortar_titulo_servicio(nombre_servicio, precio, max_caracteres=24):
    """
    NUEVO: Función para acortar títulos de servicios de manera inteligente.
    Cumple con los límites de WhatsApp para opciones de lista (24 caracteres máximo).
    
    Args:
        nombre_servicio: Nombre completo del servicio
        precio: Precio del servicio
        max_caracteres: Límite máximo de caracteres (default 24 para WhatsApp)
    
    Returns:
        str: Título acortado que cumple con el límite de caracteres
    """
    # Mapeo inteligente de nombres largos a cortos
    mapeo_nombres = {
        'Asesoramiento individual (60 min)': 'Asesoramiento (60 min)',
        'Continuum de la Ruptura Familiar (CRFam)': 'Continuum CRFam',
        'Coaching Personalizado': 'Coaching Personal',
        'Consultita Rápida': 'Consulta Rápida',
        'Mentoría Intensiva': 'Mentoría Intensiva',
        'Terapia Individual': 'Terapia Individual',
        'Terapia de Pareja': 'Terapia de Pareja',
        'Terapia Familiar': 'Terapia Familiar',
        'Evaluación Psicológica': 'Evaluación Psicológica',
        'Sesión de Emergencia': 'Sesión Emergencia'
    }
    
    # Aplicar mapeo inteligente si existe
    if nombre_servicio in mapeo_nombres:
        titulo_corto = mapeo_nombres[nombre_servicio]
    else:
        # Acortar genéricamente si no está en el mapeo
        titulo_corto = nombre_servicio[:20] if len(nombre_servicio) > 20 else nombre_servicio
    
    # Crear título final con precio
    titulo_final = f"{titulo_corto} - ${precio}"
    
    # Validar y ajustar si excede el límite
    if len(titulo_final) > max_caracteres:
        # Intentar acortar más el nombre
        espacio_disponible = max_caracteres - len(f" - ${precio}")
        if espacio_disponible > 0:
            titulo_corto = titulo_corto[:espacio_disponible]
            titulo_final = f"{titulo_corto} - ${precio}"
        else:
            # Si no hay espacio suficiente, usar solo el nombre corto
            titulo_final = titulo_corto[:max_caracteres]
    
    # Validación final de seguridad
    if len(titulo_final) > max_caracteres:
        titulo_final = titulo_final[:max_caracteres]
    
    logger.debug(f"[TITULO] '{nombre_servicio}' -> '{titulo_final}' ({len(titulo_final)}/{max_caracteres} chars)")
    
    return titulo_final

def retry_with_exponential_backoff(func, *args, max_retries=3, base_delay=1, **kwargs):
    """
    PLAN DE REFACTORIZACIÓN v3: Función para implementar reintentos con exponential backoff.
    
    Args:
        func: Función a ejecutar
        *args: Argumentos posicionales para la función
        max_retries: Número máximo de reintentos (default: 3)
        base_delay: Delay base en segundos (default: 1)
        **kwargs: Argumentos nombrados para la función
    
    Returns:
        Resultado de la función si es exitosa, None si falla después de todos los reintentos
    
    Raises:
        Exception: La última excepción si todos los reintentos fallan
    """
    last_exception = None
    
    for attempt in range(max_retries + 1):  # +1 para incluir el intento inicial
        try:
            logger.info(f"[RETRY] Intento {attempt + 1}/{max_retries + 1} para función {func.__name__}")
            return func(*args, **kwargs)
        except Exception as e:
            last_exception = e
            logger.warning(f"[RETRY] Intento {attempt + 1} falló para {func.__name__}: {e}")
            
            if attempt < max_retries:
                # Calcular delay exponencial: 1s, 2s, 4s, etc.
                delay = base_delay * (2 ** attempt)
                logger.info(f"[RETRY] Esperando {delay} segundos antes del siguiente intento")
                time.sleep(delay)
            else:
                logger.error(f"[RETRY] Todos los intentos fallaron para {func.__name__}. Último error: {e}")
    
    # Si llegamos aquí, todos los intentos fallaron
    raise last_exception