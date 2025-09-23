# audio_handler.py
import requests
import time
import logging
import config
import os

# Define la URL base de la API de AssemblyAI para mantener el código limpio.
API_URL = "https://api.assemblyai.com/v2"

# Obtiene el logger con el nombre del inquilino para mantener la consistencia en los logs.
logger = logging.getLogger(config.TENANT_NAME)

# Verificar API Key al cargar el módulo
ASSEMBLYAI_API_KEY = config.ASSEMBLYAI_API_KEY

if ASSEMBLYAI_API_KEY:
    logger.info(f"[AUDIO_HANDLER] ✅ API Key de AssemblyAI cargada (primeros 10 chars): {ASSEMBLYAI_API_KEY[:10]}...")
else:
    logger.error("[AUDIO_HANDLER] ❌ NO SE ENCONTRÓ API KEY DE ASSEMBLYAI")

def transcribe_audio_from_url(audio_url: str) -> str:
    """
    Toma una URL de un archivo de audio, lo envía a AssemblyAI para transcribirlo
    y devuelve el texto resultante.

    Args:
        audio_url: La URL pública del archivo de audio a transcribir.

    Returns:
        El texto transcrito como una cadena de caracteres, o una cadena vacía si ocurre un error.
    """
    try:
        logger.info(f"[AUDIO_HANDLER] 🎯 Iniciando transcripción de URL: {audio_url[:100]}...")
        
        # Verificar que tenemos API key
        if not ASSEMBLYAI_API_KEY:
            logger.error("[AUDIO_HANDLER] ❌ No hay API key de AssemblyAI configurada")
            return None
            
        # Configurar headers
        headers = {
            "authorization": ASSEMBLYAI_API_KEY,
            "content-type": "application/json"
        }
        
        # Crear transcripción
        transcript_request = {
            "audio_url": audio_url,
            "language_code": "es"  # Español
        }
        
        logger.info(f"[AUDIO_HANDLER] 📤 Enviando request a AssemblyAI: {transcript_request}")
        
        response = requests.post(
            f"{API_URL}/transcript",
            json=transcript_request,
            headers=headers,
            timeout=20
        )
        
        logger.info(f"[AUDIO_HANDLER] 📥 Response status: {response.status_code}")
        logger.info(f"[AUDIO_HANDLER] 📥 Response body: {response.text[:500]}")
        
        if response.status_code != 200:
            logger.error(f"[AUDIO_HANDLER] ❌ Error creando transcripción: {response.status_code} - {response.text}")
            return None
            
        transcript_id = response.json()["id"]
        logger.info(f"[AUDIO_HANDLER] ✅ Transcripción creada con ID: {transcript_id}")
        
        # Polling para obtener resultado CON TIMEOUT
        polling_endpoint = f"{API_URL}/transcript/{transcript_id}"
        
        max_attempts = 24  # 24 intentos x 5 segundos = 2 minutos máximo
        attempt = 0
        
        while attempt < max_attempts:
            attempt += 1
            
            try:
                polling_response = requests.get(polling_endpoint, headers=headers, timeout=20)
                polling_data = polling_response.json()
                
                status = polling_data.get('status')
                logger.info(f"[AUDIO_HANDLER] 🔄 Intento {attempt}/{max_attempts} - Status: {status}")
                
                if status == 'completed':
                    text = polling_data.get('text', '')
                    logger.info(f"[AUDIO_HANDLER] ✅ Transcripción completada: '{text[:100]}...'")
                    return text
                    
                elif status == 'error' or status == 'failed':
                    error = polling_data.get('error', 'Error desconocido')
                    logger.error(f"[AUDIO_HANDLER] ❌ Error en AssemblyAI: {error}")
                    logger.error(f"[AUDIO_HANDLER] ❌ Detalles completos: {polling_data}")
                    return f"[Error al transcribir audio: {error}]"
                    
                elif status == 'queued' or status == 'processing':
                    logger.info(f"[AUDIO_HANDLER] ⏳ Audio en cola/procesando... esperando 5 segundos")
                    time.sleep(5)
                else:
                    logger.warning(f"[AUDIO_HANDLER] ⚠️ Estado desconocido: {status}")
                    logger.warning(f"[AUDIO_HANDLER] ⚠️ Response completa: {polling_data}")
                    time.sleep(5)
                    
            except requests.RequestException as e:
                logger.error(f"[AUDIO_HANDLER] ❌ Error en polling intento {attempt}: {e}")
                if attempt >= 3:  # Si fallan 3 intentos de polling, rendirse
                    logger.error(f"[AUDIO_HANDLER] ❌ Máximo de errores de polling alcanzado")
                    return "[Error de red al obtener transcripción]"
                time.sleep(5)
        
        logger.error(f"[AUDIO_HANDLER] ⏰ TIMEOUT después de {max_attempts} intentos (2 minutos)")
        return "[Audio recibido - timeout en transcripción]"
        
    except requests.RequestException as e:
        logger.error(f"[AUDIO_HANDLER] ❌ Error de red al comunicarse con AssemblyAI: {e}")
        return "[Error de red al transcribir audio]"
    except Exception as e:
        logger.error(f"[AUDIO_HANDLER] 💥 Error general en transcripción: {e}", exc_info=True)
        return None

def transcribe_audio_from_url_with_download(audio_url: str) -> str:
    """
    FUNCIÓN ALTERNATIVA: Descarga el audio primero y luego lo sube a AssemblyAI
    Útil cuando las URLs de 360dialog expiran muy rápido (5 minutos)
    """
    try:
        # Descargar audio
        logger.info("[AUDIO_HANDLER] 📥 Descargando audio primero...")
        headers = {}
        if 'waba-v2.360dialog.io' in audio_url:
            headers = {"D360-API-KEY": os.getenv('D360_API_KEY')}
            
        response = requests.get(audio_url, headers=headers, timeout=30)
        if response.status_code != 200:
            logger.error(f"[AUDIO_HANDLER] Error descargando audio: {response.status_code}")
            return None
            
        # Subir a AssemblyAI
        logger.info("[AUDIO_HANDLER] 📤 Subiendo audio a AssemblyAI...")
        upload_response = requests.post(
            f"{API_URL}/upload",
            headers={"authorization": ASSEMBLYAI_API_KEY},
            data=response.content,
            timeout=60
        )
        
        if upload_response.status_code != 200:
            logger.error(f"[AUDIO_HANDLER] Error subiendo: {upload_response.text}")
            return None
            
        upload_url = upload_response.json()["upload_url"]
        logger.info(f"[AUDIO_HANDLER] ✅ Audio subido a: {upload_url}")
        
        # Ahora transcribir con la URL de AssemblyAI
        return transcribe_audio_from_url(upload_url)
        
    except Exception as e:
        logger.error(f"[AUDIO_HANDLER] Error en descarga+upload: {e}", exc_info=True)
        return None
