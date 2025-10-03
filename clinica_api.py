"""
clinica_api.py - Wrapper para API del Sistema OMNIA - Centro Pediátrico Ballester
Sistema V11 - Comunicación con Sistema Interno de la Clínica

Este módulo maneja toda la comunicación con la API del sistema interno OMNIA:
- Búsqueda de pacientes por DNI
- Consulta de disponibilidad de turnos
- Creación y cancelación de citas
- Gestión de listas de espera
- Consultas de especialistas y horarios

CRÍTICO: Este wrapper debe ser robusto y manejar todos los errores posibles
de la API de la clínica, incluyendo timeouts, errores de red, y respuestas inesperadas.

Autor: Sistema OPTIATIENDE-IA V11
Cliente: Centro Pediátrico Ballester
Fecha: Enero 2025
"""

import logging
import requests
import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import config

logger = logging.getLogger(config.TENANT_NAME)

class BallesterClinicaAPI:
    """
    Wrapper para la API del sistema OMNIA del Centro Pediátrico Ballester.
    
    Este wrapper maneja toda la comunicación con el sistema interno de la clínica,
    incluyendo manejo de errores robusto, reintentos automáticos, y logging detallado.
    """
    
    # Configuración de la API
    BASE_URL = "https://api.clinicaballester.com/v1"
    API_KEY = "ballester_api_key_2025"  # En producción desde variable de entorno
    TIMEOUT = 30  # Timeout en segundos
    MAX_RETRIES = 3
    RETRY_BACKOFF = 2.0
    
    def __init__(self):
        """Inicializa el wrapper de la API con configuración robusta"""
        
        logger.info("[CLINICA_API] Inicializando wrapper API OMNIA Ballester")
        
        # Configurar session con reintentos automáticos
        self.session = requests.Session()
        
        # Estrategia de reintentos
        retry_strategy = Retry(
            total=self.MAX_RETRIES,
            backoff_factor=self.RETRY_BACKOFF,
            status_forcelist=[429, 500, 502, 503, 504],
            method_whitelist=["HEAD", "GET", "OPTIONS", "POST", "PUT"]
        )
        
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        
        # Headers por defecto
        self.headers = {
            'Authorization': f'Bearer {self.API_KEY}',
            'Content-Type': 'application/json',
            'User-Agent': 'OptiAtiende-IA-V11/1.0',
            'X-Client-Source': 'WhatsApp-Bot'
        }
        
        # Verificar conectividad al inicializar
        self._verify_api_connection()
    
    def _verify_api_connection(self) -> bool:
        """Verifica la conectividad con la API de la clínica"""
        
        try:
            logger.info("[CLINICA_API] Verificando conectividad con API OMNIA...")
            
            # Endpoint de health check (simulado)
            response = self.session.get(
                f"{self.BASE_URL}/health",
                headers=self.headers,
                timeout=10
            )
            
            if response.status_code == 200:
                logger.info("[CLINICA_API] ✅ Conectividad con API OMNIA verificada")
                return True
            else:
                logger.warning(f"[CLINICA_API] ⚠️ API OMNIA responde con estado {response.status_code}")
                return False
                
        except requests.RequestException as e:
            logger.warning(f"[CLINICA_API] ⚠️ No se pudo verificar conectividad con API OMNIA: {e}")
            return False
    
    def get_patient_by_dni(self, dni: str) -> Optional[Dict]:
        """
        Busca un paciente por DNI en el sistema OMNIA.
        
        Args:
            dni: DNI del paciente a buscar
            
        Returns:
            Dict con datos del paciente o None si no se encuentra
        """
        logger.info(f"[CLINICA_API] Buscando paciente con DNI: {dni}")
        
        if not dni or not dni.strip():
            logger.error("[CLINICA_API] DNI vacío o inválido")
            return None
        
        try:
            # Llamada a la API OMNIA
            response = self.session.get(
                f"{self.BASE_URL}/patients/by-personal-id",
                params={'dni': dni.strip()},
                headers=self.headers,
                timeout=self.TIMEOUT
            )
            
            logger.info(f"[CLINICA_API] Response status para DNI {dni}: {response.status_code}")
            
            if response.status_code == 200:
                patient_data = response.json()
                logger.info(f"[CLINICA_API] ✅ Paciente encontrado: {patient_data.get('nombre', 'Sin nombre')}")
                
                # Normalizar datos del paciente
                normalized_patient = self._normalize_patient_data(patient_data)
                return normalized_patient
                
            elif response.status_code == 404:
                logger.info(f"[CLINICA_API] Paciente con DNI {dni} no encontrado en OMNIA")
                return None
                
            elif response.status_code == 401:
                logger.error("[CLINICA_API] ❌ Error de autenticación con API OMNIA")
                return None
                
            elif response.status_code == 403:
                logger.error("[CLINICA_API] ❌ Sin permisos para consultar pacientes en OMNIA")
                return None
                
            else:
                logger.error(f"[CLINICA_API] ❌ Error inesperado consultando paciente: {response.status_code} - {response.text}")
                return None
                
        except requests.Timeout:
            logger.error(f"[CLINICA_API] ⏰ Timeout consultando paciente DNI {dni}")
            return None
            
        except requests.ConnectionError:
            logger.error(f"[CLINICA_API] 🔌 Error de conexión consultando paciente DNI {dni}")
            return None
            
        except requests.RequestException as e:
            logger.error(f"[CLINICA_API] ❌ Error de red consultando paciente DNI {dni}: {e}")
            return None
            
        except json.JSONDecodeError:
            logger.error(f"[CLINICA_API] ❌ Respuesta inválida del servidor para DNI {dni}")
            return None
            
        except Exception as e:
            logger.error(f"[CLINICA_API] ❌ Error inesperado consultando paciente DNI {dni}: {e}", exc_info=True)
            return None
    
    def get_available_appointments(self, service: str, date_from: str = None, insurance: str = None, doctor: str = None) -> List[Dict]:
        """
        Obtiene turnos disponibles para un servicio específico.
        
        Args:
            service: Nombre del servicio (ej: "Neurología Infantil")
            date_from: Fecha desde cuándo buscar (YYYY-MM-DD)
            insurance: Obra social del paciente (opcional)
            doctor: Doctor específico (opcional)
            
        Returns:
            Lista de turnos disponibles
        """
        logger.info(f"[CLINICA_API] Buscando turnos para {service} desde {date_from} con seguro {insurance}")
        
        if not service:
            logger.error("[CLINICA_API] Servicio requerido para buscar turnos")
            return []
        
        try:
            # Construir parámetros de consulta
            params = {
                'service': service,
                'limit': 20  # Máximo 20 turnos
            }
            
            if date_from:
                params['date_from'] = date_from
            else:
                # Por defecto, buscar desde mañana
                tomorrow = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
                params['date_from'] = tomorrow
            
            if insurance:
                params['insurance'] = insurance
                
            if doctor:
                params['doctor'] = doctor
            
            # Llamada a la API OMNIA
            response = self.session.get(
                f"{self.BASE_URL}/availabilities",
                params=params,
                headers=self.headers,
                timeout=self.TIMEOUT
            )
            
            logger.info(f"[CLINICA_API] Response status para turnos {service}: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                available_slots = data.get('available_slots', [])
                
                logger.info(f"[CLINICA_API] ✅ {len(available_slots)} turnos disponibles para {service}")
                
                # Normalizar turnos
                normalized_slots = [self._normalize_appointment_slot(slot) for slot in available_slots]
                return normalized_slots
                
            elif response.status_code == 404:
                logger.info(f"[CLINICA_API] No hay turnos disponibles para {service}")
                return []
                
            else:
                logger.error(f"[CLINICA_API] ❌ Error consultando turnos: {response.status_code} - {response.text}")
                return []
                
        except requests.RequestException as e:
            logger.error(f"[CLINICA_API] ❌ Error de red consultando turnos para {service}: {e}")
            return []
            
        except json.JSONDecodeError:
            logger.error(f"[CLINICA_API] ❌ Respuesta inválida consultando turnos para {service}")
            return []
            
        except Exception as e:
            logger.error(f"[CLINICA_API] ❌ Error inesperado consultando turnos para {service}: {e}", exc_info=True)
            return []
    
    def create_appointment(self, appointment_data: Dict) -> Optional[str]:
        """
        Crea una nueva cita en el sistema OMNIA.
        
        Args:
            appointment_data: Datos completos de la cita
            
        Returns:
            ID de la cita creada o None si falla
        """
        logger.info(f"[CLINICA_API] Creando cita para paciente {appointment_data.get('patient_dni')}")
        
        if not self._validate_appointment_data(appointment_data):
            logger.error("[CLINICA_API] Datos de cita inválidos")
            return None
        
        try:
            # Preparar datos para la API
            api_data = {
                'patient_dni': appointment_data.get('patient_dni'),
                'service': appointment_data.get('service'),
                'datetime': appointment_data.get('datetime'),  # ISO format
                'doctor': appointment_data.get('doctor'),
                'insurance': appointment_data.get('insurance'),
                'notes': appointment_data.get('notes', 'Creado via WhatsApp Bot'),
                'source': 'whatsapp_bot_v11',
                'contact_phone': appointment_data.get('contact_phone'),
                'contact_email': appointment_data.get('contact_email')
            }
            
            # Llamada a la API OMNIA
            response = self.session.post(
                f"{self.BASE_URL}/appointments/create",
                json=api_data,
                headers=self.headers,
                timeout=self.TIMEOUT
            )
            
            logger.info(f"[CLINICA_API] Response status crear cita: {response.status_code}")
            
            if response.status_code == 201:
                result = response.json()
                appointment_id = result.get('appointment_id')
                
                logger.info(f"[CLINICA_API] ✅ Cita creada exitosamente: {appointment_id}")
                
                # Log adicional para auditoria
                self._log_appointment_created(appointment_id, appointment_data)
                
                return appointment_id
                
            elif response.status_code == 409:
                logger.warning(f"[CLINICA_API] ⚠️ Conflicto creando cita: turno ya ocupado")
                return None
                
            elif response.status_code == 400:
                logger.error(f"[CLINICA_API] ❌ Datos inválidos para crear cita: {response.text}")
                return None
                
            else:
                logger.error(f"[CLINICA_API] ❌ Error creando cita: {response.status_code} - {response.text}")
                return None
                
        except requests.RequestException as e:
            logger.error(f"[CLINICA_API] ❌ Error de red creando cita: {e}")
            return None
            
        except json.JSONDecodeError:
            logger.error("[CLINICA_API] ❌ Respuesta inválida creando cita")
            return None
            
        except Exception as e:
            logger.error(f"[CLINICA_API] ❌ Error inesperado creando cita: {e}", exc_info=True)
            return None
    
    def cancel_appointment(self, appointment_id: str, reason: str = "Cancelado por paciente") -> bool:
        """
        Cancela una cita existente.
        
        Args:
            appointment_id: ID de la cita a cancelar
            reason: Razón de la cancelación
            
        Returns:
            True si se canceló exitosamente, False si falló
        """
        logger.info(f"[CLINICA_API] Cancelando cita: {appointment_id}")
        
        if not appointment_id:
            logger.error("[CLINICA_API] ID de cita requerido para cancelar")
            return False
        
        try:
            # Datos para cancelación
            cancel_data = {
                'appointment_id': appointment_id,
                'reason': reason,
                'cancelled_by': 'whatsapp_bot_v11',
                'cancelled_at': datetime.now().isoformat()
            }
            
            # Llamada a la API OMNIA
            response = self.session.post(
                f"{self.BASE_URL}/appointments/cancel",
                json=cancel_data,
                headers=self.headers,
                timeout=self.TIMEOUT
            )
            
            logger.info(f"[CLINICA_API] Response status cancelar cita: {response.status_code}")
            
            if response.status_code == 200:
                logger.info(f"[CLINICA_API] ✅ Cita {appointment_id} cancelada exitosamente")
                return True
                
            elif response.status_code == 404:
                logger.warning(f"[CLINICA_API] ⚠️ Cita {appointment_id} no encontrada para cancelar")
                return False
                
            elif response.status_code == 409:
                logger.warning(f"[CLINICA_API] ⚠️ Cita {appointment_id} no se puede cancelar (estado inválido)")
                return False
                
            else:
                logger.error(f"[CLINICA_API] ❌ Error cancelando cita {appointment_id}: {response.status_code} - {response.text}")
                return False
                
        except requests.RequestException as e:
            logger.error(f"[CLINICA_API] ❌ Error de red cancelando cita {appointment_id}: {e}")
            return False
            
        except Exception as e:
            logger.error(f"[CLINICA_API] ❌ Error inesperado cancelando cita {appointment_id}: {e}", exc_info=True)
            return False
    
    def add_to_waitlist(self, waitlist_data: Dict) -> Optional[str]:
        """
        Agrega un paciente a la lista de espera.
        
        Args:
            waitlist_data: Datos del paciente para lista de espera
            
        Returns:
            ID de la entrada en lista de espera o None si falla
        """
        logger.info(f"[CLINICA_API] Agregando a lista de espera: {waitlist_data.get('service')}")
        
        try:
            # Preparar datos para lista de espera
            api_data = {
                'patient_dni': waitlist_data.get('patient_dni'),
                'patient_name': waitlist_data.get('patient_name'),
                'service': waitlist_data.get('service'),
                'insurance': waitlist_data.get('insurance'),
                'contact_phone': waitlist_data.get('contact_phone'),
                'contact_email': waitlist_data.get('contact_email'),
                'priority': waitlist_data.get('priority', 'normal'),
                'notes': waitlist_data.get('notes', ''),
                'source': 'whatsapp_bot_v11',
                'created_at': datetime.now().isoformat()
            }
            
            # Llamada a la API OMNIA
            response = self.session.post(
                f"{self.BASE_URL}/waitlist/add",
                json=api_data,
                headers=self.headers,
                timeout=self.TIMEOUT
            )
            
            logger.info(f"[CLINICA_API] Response status lista espera: {response.status_code}")
            
            if response.status_code == 201:
                result = response.json()
                waitlist_id = result.get('waitlist_id')
                
                logger.info(f"[CLINICA_API] ✅ Agregado a lista de espera: {waitlist_id}")
                return waitlist_id
                
            else:
                logger.error(f"[CLINICA_API] ❌ Error agregando a lista de espera: {response.status_code} - {response.text}")
                return None
                
        except requests.RequestException as e:
            logger.error(f"[CLINICA_API] ❌ Error de red agregando a lista de espera: {e}")
            return None
            
        except Exception as e:
            logger.error(f"[CLINICA_API] ❌ Error inesperado agregando a lista de espera: {e}", exc_info=True)
            return None
    
    def get_doctor_schedule(self, doctor_name: str, date: str = None) -> List[Dict]:
        """
        Obtiene el horario de un doctor específico.
        
        Args:
            doctor_name: Nombre del doctor
            date: Fecha específica (YYYY-MM-DD) o None para la semana actual
            
        Returns:
            Lista de horarios del doctor
        """
        logger.info(f"[CLINICA_API] Consultando horario del Dr. {doctor_name}")
        
        try:
            params = {'doctor': doctor_name}
            if date:
                params['date'] = date
            
            response = self.session.get(
                f"{self.BASE_URL}/doctors/schedule",
                params=params,
                headers=self.headers,
                timeout=self.TIMEOUT
            )
            
            if response.status_code == 200:
                schedule_data = response.json()
                schedule = schedule_data.get('schedule', [])
                
                logger.info(f"[CLINICA_API] ✅ Horario obtenido para Dr. {doctor_name}: {len(schedule)} entradas")
                return schedule
                
            else:
                logger.warning(f"[CLINICA_API] No se pudo obtener horario del Dr. {doctor_name}: {response.status_code}")
                return []
                
        except requests.RequestException as e:
            logger.error(f"[CLINICA_API] ❌ Error consultando horario del Dr. {doctor_name}: {e}")
            return []
        
        except Exception as e:
            logger.error(f"[CLINICA_API] ❌ Error inesperado consultando horario del Dr. {doctor_name}: {e}", exc_info=True)
            return []
    
    # =================== MÉTODOS AUXILIARES ===================
    
    def _normalize_patient_data(self, raw_data: Dict) -> Dict:
        """Normaliza los datos del paciente desde la API OMNIA"""
        
        return {
            'dni': raw_data.get('personal_id', ''),
            'nombre': raw_data.get('full_name', ''),
            'fecha_nacimiento': raw_data.get('birth_date', ''),
            'obra_social': raw_data.get('insurance_name', ''),
            'plan': raw_data.get('insurance_plan', ''),
            'numero_afiliado': raw_data.get('insurance_number', ''),
            'celular': raw_data.get('phone', ''),
            'email': raw_data.get('email', ''),
            'direccion': raw_data.get('address', ''),
            'last_visit': raw_data.get('last_visit_date', ''),
            'patient_id': raw_data.get('id', ''),
            'active': raw_data.get('active', True)
        }
    
    def _normalize_appointment_slot(self, raw_slot: Dict) -> Dict:
        """Normaliza un slot de turno desde la API OMNIA"""
        
        return {
            'slot_id': raw_slot.get('id', ''),
            'datetime': raw_slot.get('datetime', ''),
            'date': raw_slot.get('date', ''),
            'time': raw_slot.get('time', ''),
            'doctor': raw_slot.get('doctor_name', ''),
            'service': raw_slot.get('service_name', ''),
            'duration_minutes': raw_slot.get('duration', 30),
            'available': raw_slot.get('available', True),
            'room': raw_slot.get('room', ''),
            'notes': raw_slot.get('notes', '')
        }
    
    def _validate_appointment_data(self, data: Dict) -> bool:
        """Valida que los datos de la cita estén completos"""
        
        required_fields = ['patient_dni', 'service', 'datetime']
        
        for field in required_fields:
            if not data.get(field):
                logger.error(f"[CLINICA_API] Campo requerido faltante: {field}")
                return False
        
        return True
    
    def _log_appointment_created(self, appointment_id: str, appointment_data: Dict):
        """Log detallado para auditoria de citas creadas"""
        
        logger.info(f"""[CLINICA_API] 📋 CITA CREADA - AUDITORIA:
        ID: {appointment_id}
        Paciente DNI: {appointment_data.get('patient_dni')}
        Servicio: {appointment_data.get('service')}
        Fecha/Hora: {appointment_data.get('datetime')}
        Doctor: {appointment_data.get('doctor', 'No especificado')}
        Obra Social: {appointment_data.get('insurance', 'No especificada')}
        Teléfono: {appointment_data.get('contact_phone', 'No especificado')}
        Fuente: WhatsApp Bot V11
        Timestamp: {datetime.now().isoformat()}""")


# =================== FUNCIONES HELPER PARA OTROS MÓDULOS ===================

def get_ballester_patient(dni: str) -> Optional[Dict]:
    """Función helper para buscar paciente por DNI"""
    api = BallesterClinicaAPI()
    return api.get_patient_by_dni(dni)

def get_ballester_appointments(service: str, date_from: str = None, insurance: str = None) -> List[Dict]:
    """Función helper para obtener turnos disponibles"""
    api = BallesterClinicaAPI()
    return api.get_available_appointments(service, date_from, insurance)

def create_ballester_appointment(appointment_data: Dict) -> Optional[str]:
    """Función helper para crear cita"""
    api = BallesterClinicaAPI()
    return api.create_appointment(appointment_data)

def add_to_ballester_waitlist(waitlist_data: Dict) -> Optional[str]:
    """Función helper para agregar a lista de espera"""
    api = BallesterClinicaAPI()
    return api.add_to_waitlist(waitlist_data)
