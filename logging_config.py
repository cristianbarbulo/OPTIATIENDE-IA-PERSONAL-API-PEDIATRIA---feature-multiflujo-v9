"""
Configuración de logging para reducir el ruido en los logs.
Creado: Enero 2025

Este archivo permite controlar el nivel de logging de diferentes módulos
para mejorar la legibilidad de los logs en producción.
"""

import logging
import os

def configure_logging():
    """
    Configura los niveles de logging para diferentes módulos.
    
    Por defecto, reduce el ruido de chatwoot_integration a WARNING,
    mostrando solo errores y advertencias importantes.
    """
    
    # Nivel global de logging (desde variable de entorno o INFO por defecto)
    global_level = os.getenv('LOG_LEVEL', 'INFO').upper()
    logging.basicConfig(level=getattr(logging, global_level))
    
    # Configuración específica para módulos ruidosos
    # Solo mostrará WARNING y ERROR de chatwoot_integration
    chatwoot_level = os.getenv('CHATWOOT_LOG_LEVEL', 'WARNING').upper()
    logging.getLogger('chatwoot_integration').setLevel(getattr(logging, chatwoot_level))
    
    # Si necesitas debug temporal de Chatwoot, puedes usar:
    # export CHATWOOT_LOG_LEVEL=DEBUG
    
    # También puedes ajustar otros módulos específicos aquí
    # logging.getLogger('urllib3').setLevel(logging.WARNING)  # Reduce ruido de requests HTTP
    # logging.getLogger('requests').setLevel(logging.WARNING)  # Reduce ruido de requests
    
    # Log la configuración actual
    logger = logging.getLogger(__name__)
    logger.info(f"🔧 Logging configurado - Nivel global: {global_level}")
    logger.info(f"🔧 Chatwoot logging nivel: {chatwoot_level}")

# Configuración de logging para desarrollo vs producción
def get_log_format():
    """
    Retorna el formato de log apropiado según el entorno.
    """
    if os.getenv('ENVIRONMENT', 'production').lower() == 'development':
        # Formato más detallado para desarrollo
        return '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
    else:
        # Formato más limpio para producción
        return '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
