#!/usr/bin/env python3
"""
🔄 CRON REVIVAL SERVICE - Sistema Multi-Cliente
Servicio independiente que dispara revival de conversaciones cada 6 horas.
100% aislado del sistema principal - solo hace HTTP calls.
"""

import os
import json
import requests
import logging
from datetime import datetime
from typing import List, Dict, Any
import time

# Configuración de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - REVIVAL_CRON - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class RevivalCronService:
    def __init__(self):
        """Inicializa el servicio cron con configuración desde variables de entorno"""
        self.active_clients = self._load_active_clients()
        self.secret_key = os.getenv('CRON_SECRET_KEY', 'default_secret_change_me')
        self.request_timeout = int(os.getenv('REQUEST_TIMEOUT', '30'))
        self.dry_run = os.getenv('DRY_RUN', 'false').lower() == 'true'
        
        logger.info(f"🔄 Revival Cron Service iniciado")
        logger.info(f"📊 Clientes activos: {len(self.active_clients)}")
        logger.info(f"🧪 Modo DRY_RUN: {self.dry_run}")

    def _load_active_clients(self) -> List[Dict[str, str]]:
        """Carga la lista de clientes activos desde variable de entorno"""
        try:
            clients_json = os.getenv('ACTIVE_CLIENTS', '[]')
            clients_list = json.loads(clients_json)
            
            # Validar formato
            validated_clients = []
            for client in clients_list:
                if isinstance(client, dict) and 'name' in client and 'url' in client:
                    validated_clients.append({
                        'name': client['name'],
                        'url': client['url'].rstrip('/'),  # Eliminar trailing slash
                        'enabled': client.get('enabled', True)
                    })
                else:
                    logger.warning(f"⚠️ Cliente con formato inválido ignorado: {client}")
            
            return [c for c in validated_clients if c['enabled']]
            
        except json.JSONDecodeError as e:
            logger.error(f"❌ Error parseando ACTIVE_CLIENTS JSON: {e}")
            return []
        except Exception as e:
            logger.error(f"❌ Error cargando clientes activos: {e}")
            return []

    def trigger_client_revival(self, client: Dict[str, str]) -> Dict[str, Any]:
        """
        Dispara el proceso de revival para un cliente específico
        
        Args:
            client: Diccionario con 'name' y 'url' del cliente
            
        Returns:
            Diccionario con resultado del proceso
        """
        url = f"{client['url']}/api/revival/process"
        headers = {
            'Content-Type': 'application/json',
            'X-Revival-Secret': self.secret_key,
            'User-Agent': 'RevivalCron/1.0'
        }
        
        payload = {
            'timestamp': datetime.utcnow().isoformat(),
            'cron_service': 'revival-multi-client',
            'dry_run': self.dry_run
        }
        
        try:
            logger.info(f"🔄 Disparando revival para {client['name']} -> {url}")
            
            if self.dry_run:
                logger.info(f"🧪 DRY_RUN: Simulando llamada a {client['name']}")
                return {
                    'success': True,
                    'client': client['name'],
                    'dry_run': True,
                    'message': 'Simulación exitosa'
                }
            
            response = requests.post(
                url=url,
                json=payload,
                headers=headers,
                timeout=self.request_timeout
            )
            
            response.raise_for_status()
            result = response.json()
            
            logger.info(f"✅ {client['name']}: {result.get('message', 'Procesado exitosamente')}")
            return {
                'success': True,
                'client': client['name'],
                'response': result,
                'status_code': response.status_code
            }
            
        except requests.exceptions.Timeout:
            error_msg = f"⏱️ Timeout en {client['name']} después de {self.request_timeout}s"
            logger.error(error_msg)
            return {'success': False, 'client': client['name'], 'error': 'timeout'}
            
        except requests.exceptions.ConnectionError:
            error_msg = f"🔌 Error de conexión con {client['name']}"
            logger.error(error_msg)
            return {'success': False, 'client': client['name'], 'error': 'connection_error'}
            
        except requests.exceptions.HTTPError as e:
            error_msg = f"🚫 HTTP Error {e.response.status_code} en {client['name']}"
            logger.error(error_msg)
            return {'success': False, 'client': client['name'], 'error': f'http_{e.response.status_code}'}
            
        except Exception as e:
            error_msg = f"❌ Error inesperado con {client['name']}: {str(e)}"
            logger.error(error_msg)
            return {'success': False, 'client': client['name'], 'error': str(e)}

    def run_revival_cycle(self) -> Dict[str, Any]:
        """
        Ejecuta un ciclo completo de revival para todos los clientes activos
        
        Returns:
            Resumen del ciclo ejecutado
        """
        cycle_start = datetime.utcnow()
        logger.info(f"🚀 Iniciando ciclo de revival - {cycle_start.isoformat()}")
        
        if not self.active_clients:
            logger.warning("⚠️ No hay clientes activos configurados")
            return {
                'success': False,
                'message': 'No hay clientes activos',
                'timestamp': cycle_start.isoformat()
            }
        
        results = []
        successful_clients = 0
        failed_clients = 0
        
        for client in self.active_clients:
            result = self.trigger_client_revival(client)
            results.append(result)
            
            if result['success']:
                successful_clients += 1
            else:
                failed_clients += 1
            
            # Pequeña pausa entre clientes para evitar sobrecarga
            time.sleep(1)
        
        cycle_end = datetime.utcnow()
        duration = (cycle_end - cycle_start).total_seconds()
        
        summary = {
            'success': True,
            'cycle_start': cycle_start.isoformat(),
            'cycle_end': cycle_end.isoformat(),
            'duration_seconds': duration,
            'total_clients': len(self.active_clients),
            'successful_clients': successful_clients,
            'failed_clients': failed_clients,
            'results': results
        }
        
        logger.info(f"📊 Ciclo completado: {successful_clients}/{len(self.active_clients)} clientes exitosos en {duration:.2f}s")
        
        return summary

def main():
    """Función principal del cron service"""
    try:
        service = RevivalCronService()
        
        # Validar configuración
        if not service.active_clients:
            logger.error("❌ No se pudo inicializar: sin clientes activos")
            return
        
        if service.secret_key == 'default_secret_change_me':
            logger.warning("⚠️ Usando secret key por defecto - CAMBIAR EN PRODUCCIÓN")
        
        # Ejecutar ciclo de revival
        result = service.run_revival_cycle()
        
        if result['success']:
            logger.info("✅ Ciclo de revival completado exitosamente")
        else:
            logger.error("❌ Ciclo de revival falló")
            
    except Exception as e:
        logger.error(f"💥 Error crítico en main: {str(e)}")
        raise

if __name__ == "__main__":
    main()
