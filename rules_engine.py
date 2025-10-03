"""
rules_engine.py - Motor de Reglas Determinista Centro Pediátrico Ballester
Sistema V11 - Motor 100% Programático para Decisiones Médicas Críticas

Este módulo centraliza TODA la lógica de negocio médica de la clínica:
- Coberturas por obra social y servicio
- Bonos, copagos y aranceles
- Requisitos y autorizaciones
- Reglas especiales por especialista
- Preparaciones para estudios
- Listas de espera y cupos

CRÍTICO: Este módulo es 100% determinista. NO usa IA para decisiones de cobertura,
precios o requisitos. Toda la lógica está hardcodeada según las especificaciones
exactas del Centro Pediátrico Ballester.

Autor: Sistema OPTIATIENDE-IA V11
Cliente: Centro Pediátrico Ballester  
Fecha: Enero 2025
"""

import logging
import json
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple

import config
import memory

logger = logging.getLogger(config.TENANT_NAME)

class BallesterRulesEngine:
    """
    Motor de reglas 100% determinista para el Centro Pediátrico Ballester.
    
    Este motor contiene hardcodeadas todas las reglas específicas de la clínica:
    - Qué obra social cubre qué servicios
    - Bonos y copagos exactos
    - Reglas especiales por especialista
    - Preparaciones específicas por estudio
    - Aranceles particulares
    """
    
    def __init__(self):
        """Inicializa el motor de reglas con todas las configuraciones de Ballester"""
        logger.info("[RULES_ENGINE] Inicializando motor de reglas Ballester")
        
        # Cargar todas las reglas hardcodeadas
        self._load_ballester_rules()
        
    def _load_ballester_rules(self):
        """Carga todas las reglas específicas de Ballester hardcodeadas"""
        
        # =================== COBERTURAS POR OBRA SOCIAL ===================
        # Basado en las imágenes de las tablas proporcionadas
        self.COBERTURAS_BALLESTER = {
            'IOMA': {
                'consultas': {'cobertura': 'COVERED', 'requiere_autorizacion': False, 'copago': 4000},
                'neurologia_infantil': {'cobertura': 'WAITLIST', 'requiere_autorizacion': False, 'max_slots_dia': 5, 'bono_contribucion': 2500},
                'neumonologia_infantil': {'cobertura': 'COVERED', 'requiere_autorizacion': False, 'copago': 4000, 'max_slots_dia': 5},
                'ecografias': {'cobertura': 'COVERED', 'requiere_autorizacion': True, 'copago': 4000},
                'electroencefalograma': {'cobertura': 'NOT_COVERED'},
                'ecocardiograma_doppler': {'cobertura': 'COVERED', 'requiere_autorizacion': True, 'copago': 4000},
                'psicologia': {'cobertura': 'NOT_COVERED'},
                'psicopedagogia': {'cobertura': 'WAITLIST'},
                'neuropsicologia': {'cobertura': 'NOT_COVERED'}
            },
            'MEDICARDIO': {
                'consultas': {'cobertura': 'COVERED', 'requiere_autorizacion': False, 'copago': 4000},
                'neurologia_infantil': {'cobertura': 'COVERED', 'requiere_autorizacion': False, 'copago': 4000},
                'neumonologia_infantil': {'cobertura': 'COVERED', 'requiere_autorizacion': False, 'copago': 4000},
                'ecografias': {'cobertura': 'COVERED', 'requiere_autorizacion': True, 'copago': 4000},
                'electroencefalograma': {'cobertura': 'COVERED', 'requiere_autorizacion': False, 'copago': 4000},
                'ecocardiograma_doppler': {'cobertura': 'COVERED', 'requiere_autorizacion': True, 'copago': 4000},
                'psicologia': {'cobertura': 'NOT_COVERED'},
                'psicopedagogia': {'cobertura': 'WAITLIST'},
                'neuropsicologia': {'cobertura': 'NOT_COVERED'}
            },
            'OSDE': {
                'consultas': {'cobertura': 'COVERED', 'requiere_autorizacion': False, 'copago': 4000},
                'neurologia_infantil': {'cobertura': 'WAITLIST', 'requiere_autorizacion': False, 'bono_contribucion': 2500},
                'neumonologia_infantil': {'cobertura': 'COVERED', 'requiere_autorizacion': False, 'copago': 4000},
                'ecografias': {'cobertura': 'COVERED', 'requiere_autorizacion': True, 'copago': 4000},
                'electroencefalograma': {'cobertura': 'NOT_COVERED'},
                'ecocardiograma_doppler': {'cobertura': 'COVERED', 'requiere_autorizacion': True, 'copago': 4000},
                'psicologia': {'cobertura': 'NOT_COVERED'},
                'psicopedagogia': {'cobertura': 'WAITLIST'},
                'neuropsicologia': {'cobertura': 'NOT_COVERED'},
                'dr_malacchia_lunes': {'cobertura': 'COVERED', 'copago': 0}  # OSDE puede ver al Dr. Malacchia
            },
            'OMINT': {
                'consultas': {'cobertura': 'COVERED', 'requiere_autorizacion': False, 'copago': 4000},
                'neurologia_infantil': {'cobertura': 'WAITLIST', 'requiere_autorizacion': False, 'bono_contribucion': 2500},
                'neumonologia_infantil': {'cobertura': 'COVERED', 'requiere_autorizacion': False, 'copago': 4000},
                'ecografias': {'cobertura': 'COVERED', 'requiere_autorizacion': True, 'copago': 4000},
                'electroencefalograma': {'cobertura': 'NOT_COVERED'},
                'ecocardiograma_doppler': {'cobertura': 'COVERED', 'requiere_autorizacion': True, 'copago': 4000},
                'psicologia': {'cobertura': 'NOT_COVERED'},
                'psicopedagogia': {'cobertura': 'WAITLIST'},
                'neuropsicologia': {'cobertura': 'NOT_COVERED'},
                'dr_malacchia_lunes': {'cobertura': 'COVERED', 'copago': 0}  # OMINT puede ver al Dr. Malacchia
            },
            'PASTELEROS': {
                'consultas': {'cobertura': 'COVERED', 'requiere_autorizacion': False, 'copago': 4000, 'requiere_bono_atencion': True},
                'neurologia_infantil': {'cobertura': 'WAITLIST', 'requiere_autorizacion': False, 'bono_contribucion': 2500},
                'neumonologia_infantil': {'cobertura': 'COVERED', 'requiere_autorizacion': False, 'copago': 4000},
                'ecografias': {'cobertura': 'COVERED', 'requiere_autorizacion': True, 'copago': 4000, 'requiere_bono_consulta': True},
                'electroencefalograma': {'cobertura': 'NOT_COVERED'},
                'ecocardiograma_doppler': {'cobertura': 'COVERED', 'requiere_autorizacion': True, 'copago': 4000},
                'psicologia': {'cobertura': 'NOT_COVERED'},
                'psicopedagogia': {'cobertura': 'WAITLIST'},
                'neuropsicologia': {'cobertura': 'NOT_COVERED'}
            },
            'TELEVISION': {
                'consultas': {'cobertura': 'COVERED', 'requiere_autorizacion': False, 'copago': 0, 'requiere_bono_atencion': True},
                'neurologia_infantil': {'cobertura': 'WAITLIST', 'requiere_autorizacion': False, 'bono_contribucion': 2500},
                'neumonologia_infantil': {'cobertura': 'COVERED', 'requiere_autorizacion': False, 'copago': 0},
                'ecografias': {'cobertura': 'COVERED', 'requiere_autorizacion': False, 'copago': 0, 'requiere_bono_consulta': True},
                'electroencefalograma': {'cobertura': 'COVERED', 'requiere_autorizacion': False, 'copago': 0},
                'ecocardiograma_doppler': {'cobertura': 'COVERED', 'requiere_autorizacion': False, 'copago': 0},
                'psicologia': {'cobertura': 'NOT_COVERED'},
                'psicopedagogia': {'cobertura': 'WAITLIST'},
                'neuropsicologia': {'cobertura': 'NOT_COVERED'}
            },
            'OSDOP': {
                'consultas': {'cobertura': 'COVERED', 'requiere_autorizacion': False, 'copago': 4000, 'requiere_bono_atencion': True},
                'neurologia_infantil': {'cobertura': 'WAITLIST', 'requiere_autorizacion': False, 'bono_contribucion': 2500},
                'neumonologia_infantil': {'cobertura': 'COVERED', 'requiere_autorizacion': False, 'copago': 4000},
                'ecografias': {'cobertura': 'COVERED', 'requiere_autorizacion': True, 'copago': 4000},
                'electroencefalograma': {'cobertura': 'NOT_COVERED'},
                'ecocardiograma_doppler': {'cobertura': 'COVERED', 'requiere_autorizacion': True, 'copago': 4000},
                'psicologia': {'cobertura': 'NOT_COVERED'},
                'psicopedagogia': {'cobertura': 'WAITLIST'},
                'neuropsicologia': {'cobertura': 'NOT_COVERED'}
            },
            'MEPLIFE': {
                'consultas': {'cobertura': 'COVERED', 'requiere_autorizacion': False, 'copago': 0},
                'neurologia_infantil': {'cobertura': 'COVERED', 'requiere_autorizacion': False, 'copago': 0},  # Acceso directo
                'neumonologia_infantil': {'cobertura': 'COVERED', 'requiere_autorizacion': False, 'copago': 0},
                'ecografias': {'cobertura': 'COVERED', 'requiere_autorizacion': True, 'copago': 0},
                'electroencefalograma': {'cobertura': 'NOT_COVERED'},
                'ecocardiograma_doppler': {'cobertura': 'COVERED', 'requiere_autorizacion': True, 'copago': 0},
                'psicologia': {'cobertura': 'NOT_COVERED'},
                'psicopedagogia': {'cobertura': 'WAITLIST'},
                'neuropsicologia': {'cobertura': 'NOT_COVERED'}
            },
            'OSSEG': {
                'consultas': {'cobertura': 'COVERED', 'requiere_autorizacion': False, 'copago': 0},
                'neurologia_infantil': {'cobertura': 'COVERED', 'requiere_autorizacion': False, 'copago': 0},  # Solo plan integral y 450
                'neumonologia_infantil': {'cobertura': 'COVERED', 'requiere_autorizacion': False, 'copago': 0},
                'ecografias': {'cobertura': 'COVERED', 'requiere_autorizacion': True, 'copago': 0},
                'electroencefalograma': {'cobertura': 'NOT_COVERED'},
                'ecocardiograma_doppler': {'cobertura': 'COVERED', 'requiere_autorizacion': True, 'copago': 0},
                'psicologia': {'cobertura': 'NOT_COVERED'},
                'psicopedagogia': {'cobertura': 'WAITLIST'},
                'neuropsicologia': {'cobertura': 'NOT_COVERED'}
            },
            'PODER_JUDICIAL': {
                'consultas': {'cobertura': 'COVERED', 'requiere_autorizacion': False, 'copago': 0},
                'neurologia_infantil': {'cobertura': 'WAITLIST', 'requiere_autorizacion': False, 'bono_contribucion': 2500},
                'neumonologia_infantil': {'cobertura': 'COVERED', 'requiere_autorizacion': False, 'copago': 0},
                'ecografias': {'cobertura': 'COVERED', 'requiere_autorizacion': True, 'copago': 0},
                'electroencefalograma': {'cobertura': 'NOT_COVERED'},
                'ecocardiograma_doppler': {'cobertura': 'COVERED', 'requiere_autorizacion': True, 'copago': 0},
                'psicologia': {'cobertura': 'NOT_COVERED'},
                'psicopedagogia': {'cobertura': 'WAITLIST'},
                'neuropsicologia': {'cobertura': 'NOT_COVERED'},
                'dr_malacchia_lunes': {'cobertura': 'COVERED', 'copago': 0}  # Poder Judicial puede ver al Dr. Malacchia
            },
            'W.HOPE': {
                'consultas': {'cobertura': 'COVERED', 'requiere_autorizacion': False, 'copago': 0},
                'neurologia_infantil': {'cobertura': 'WAITLIST', 'requiere_autorizacion': False, 'bono_contribucion': 2500},
                'neumonologia_infantil': {'cobertura': 'COVERED', 'requiere_autorizacion': False, 'copago': 0},
                'ecografias': {'cobertura': 'COVERED', 'requiere_autorizacion': True, 'copago': 0},
                'electroencefalograma': {'cobertura': 'NOT_COVERED'},
                'ecocardiograma_doppler': {'cobertura': 'COVERED', 'requiere_autorizacion': True, 'copago': 0},
                'psicologia': {'cobertura': 'NOT_COVERED'},
                'psicopedagogia': {'cobertura': 'WAITLIST'},
                'neuropsicologia': {'cobertura': 'NOT_COVERED'},
                'dr_malacchia_lunes': {'cobertura': 'COVERED', 'copago': 0}  # W.HOPE puede ver al Dr. Malacchia
            },
            'PARTICULAR': {
                'consultas': {'cobertura': 'PRIVATE_ONLY'},
                'neurologia_infantil': {'cobertura': 'PRIVATE_ONLY'},
                'neumonologia_infantil': {'cobertura': 'PRIVATE_ONLY'},
                'ecografias': {'cobertura': 'PRIVATE_ONLY'},
                'electroencefalograma': {'cobertura': 'PRIVATE_ONLY'},
                'ecocardiograma_doppler': {'cobertura': 'PRIVATE_ONLY'},
                'psicologia': {'cobertura': 'PRIVATE_ONLY'},
                'psicopedagogia': {'cobertura': 'PRIVATE_ONLY'},
                'neuropsicologia': {'cobertura': 'PRIVATE_ONLY'},
                'dr_malacchia_lunes': {'cobertura': 'PRIVATE_ONLY'}
            }
        }
        
        # =================== PRECIOS PARTICULARES ===================
        # Basado en la tabla de precios particulares proporcionada
        self.PRECIOS_PARTICULARES = {
            'Consulta Pediátrica': 28000,
            'Cardiología Infantil': 28000,
            'Dermatología Infantil': 28000,
            'Endocrinología Infantil': 27000,
            'Gastroenterología Infantil': 28000,
            'Infectología Infantil': 28000,
            'Neumonología Infantil': 28000,
            'Neurología Infantil': 66000,
            'Nutrición Infantil': 28000,
            'Nutricionista Infantil': 20000,
            'Oftalmología Infantil': 28000,
            'Otorrinolaringología Infantil': 28000,
            'Traumatología Infantil': 28000,
            'Foniatría': 19000,
            'Psicopedagogía': 20000,
            'Psicología': 32000,
            'Electrocardiograma': 12000,
            'Ecocardiograma Doppler Color': 58000,
            'Curetaje hasta 2 lesiones': 28000,
            'Ecografía Abdominal': 45000,
            'Ecografía Hepatobiliar': 45000,
            'Ecografía Esplénica': 45000,
            'Ecografía Suprarrenal': 45000,
            'Ecografía Pancreática': 45000,
            'Ecografía Ginecológica': 45000,
            'Ecografía Renal': 45000,
            'Ecografía de Vías Urinarias': 45000,
            'Electroencefalograma (EEG)': 50000,
            'Potencial Evocado Auditivo (PEAT)': 55000,
            'Polisomnografía Diurna': 60000,
            'Audiometría': 25000,
            'PRUNAPE': 30000,
            'Test de Ados (Neuropsicología)': 80000,  # 4 sesiones x 20000
            'Test de Adir (Neuropsicología)': 60000,  # 3 sesiones x 20000
            'Neuropsicología': 20000  # Por sesión
        }
        
        # =================== PREPARACIONES PARA ESTUDIOS ===================
        self.PREPARACIONES_ESTUDIOS = {
            'Electroencefalograma (EEG)': [
                "El niño debe concurrir con mucho sueño, ya que el estudio se realiza mientras duerme",
                "Recomendamos despertarlo muy temprano ese día para facilitar que se duerma durante el procedimiento",
                "Si tiene algún objeto de apego como un muñeco o mantita que lo ayude a dormirse puede traerlo",
                "Que concurra con hambre, de manera de alimentarlo unos minutos antes del procedimiento así se duerme",
                "Debe tener la cabeza lavada con shampoo neutro, y no usar crema de enjuague",
                "Traer una toalla personal para higienizar al niño"
            ],
            'Potencial Evocado Auditivo (PEAT)': [
                "El niño debe concurrir con mucho sueño, ya que el estudio se realiza mientras duerme",
                "Recomendamos despertarlo muy temprano ese día para facilitar que se duerma durante el procedimiento",
                "Si tiene algún objeto de apego como un muñeco o mantita que lo ayude a dormirse puede traerlo",
                "Que concurra con hambre, de manera de alimentarlo unos minutos antes del procedimiento así se duerme",
                "Debe tener la cabeza lavada con shampoo neutro, y no usar crema de enjuague",
                "Traer una toalla personal para higienizar al niño"
            ],
            'Polisomnografía Diurna': [
                "El niño debe concurrir con mucho sueño, ya que el estudio se realiza mientras duerme",
                "Recomendamos despertarlo muy temprano ese día para facilitar que se duerma durante el procedimiento",
                "Si tiene algún objeto de apego como un muñeco o mantita que lo ayude a dormirse puede traerlo",
                "Que concurra con hambre, de manera de alimentarlo unos minutos antes del procedimiento así se duerme",
                "Debe tener la cabeza lavada con shampoo neutro, y no usar crema de enjuague",
                "Traer una toalla personal para higienizar al niño"
            ],
            'Ecografía Abdominal': {
                'bebés_hasta_3_meses': ["AYUNO MÍNIMO DE 3 HORAS"],
                'niños_3_meses_a_2_años': ["AYUNO MÍNIMO DE 4 HORAS"],
                'niños_2_años_a_10_años': ["AYUNO MÍNIMO DE 6 HORAS"],
                'niños_mayor_10_años': ["AYUNO MÍNIMO DE 8 HORAS"]
            },
            'Ecografía Hepatobiliar': {
                'bebés_hasta_3_meses': ["AYUNO MÍNIMO DE 3 HORAS"],
                'niños_3_meses_a_2_años': ["AYUNO MÍNIMO DE 4 HORAS"],
                'niños_2_años_a_10_años': ["AYUNO MÍNIMO DE 6 HORAS"],
                'niños_mayor_10_años': ["AYUNO MÍNIMO DE 8 HORAS"]
            },
            'Ecografía Esplénica': {
                'bebés_hasta_3_meses': ["AYUNO MÍNIMO DE 3 HORAS"],
                'niños_3_meses_a_2_años': ["AYUNO MÍNIMO DE 4 HORAS"],
                'niños_2_años_a_10_años': ["AYUNO MÍNIMO DE 6 HORAS"],
                'niños_mayor_10_años': ["AYUNO MÍNIMO DE 8 HORAS"]
            },
            'Ecografía Suprarrenal': {
                'bebés_hasta_3_meses': ["AYUNO MÍNIMO DE 3 HORAS"],
                'niños_3_meses_a_2_años': ["AYUNO MÍNIMO DE 4 HORAS"],
                'niños_2_años_a_10_años': ["AYUNO MÍNIMO DE 6 HORAS"],
                'niños_mayor_10_años': ["AYUNO MÍNIMO DE 8 HORAS"]
            },
            'Ecografía Pancreática': {
                'bebés_hasta_3_meses': ["AYUNO MÍNIMO DE 3 HORAS"],
                'niños_3_meses_a_2_años': ["AYUNO MÍNIMO DE 4 HORAS"],
                'niños_2_años_a_10_años': ["AYUNO MÍNIMO DE 6 HORAS"],
                'niños_mayor_10_años': ["AYUNO MÍNIMO DE 8 HORAS"]
            },
            'Ecografía Ginecológica': {
                'bebés': ["PECHO O MAMADERA MEDIA HORA ANTES DEL ESTUDIO"],
                'niñas_hasta_3_años': [
                    "BEBER 500 ML DE LÍQUIDO SIN GAS (una botellita) 1½ HS PREVIAS AL ESTUDIO Y RETENER SI CONTROLA ESFÍNTERES",
                    "LA NIÑA DEBE ESTAR CON MUCHAS GANAS DE ORINAR"
                ],
                'niñas_3_a_10_años': [
                    "BEBER ¾ LITRO DE LIQUIDO SIN GAS 1½ HS PREVIA AL ESTUDIO Y RETENER",
                    "LA NIÑA DEBE ESTAR CON MUCHAS GANAS DE ORINAR, CASO CONTRARIO DEBERÁ SER RECITADA OTRO DÍA"
                ],
                'niñas_mayor_10_años': [
                    "BEBER 1 LITRO DE LIQUIDO SIN GAS 2 HS PREVIAS AL ESTUDIO Y RETENER",
                    "LA NIÑA DEBE ESTAR CON MUCHAS GANAS DE ORINAR, CASO CONTRARIO DEBERÁ SER RECITADA OTRO DÍA"
                ]
            },
            'Ecografía Renal': {
                'bebés': ["PECHO O MAMADERA MEDIA HORA ANTES DEL ESTUDIO"],
                'niñas_hasta_3_años': [
                    "BEBER 500 ML DE LÍQUIDO SIN GAS (una botellita) 2 HS PREVIAS AL ESTUDIO Y RETENER SI CONTROLA ESFÍNTERES",
                    "LA NIÑA DEBE ESTAR CON MUCHAS GANAS DE ORINAR"
                ],
                'niñas_3_a_10_años': [
                    "BEBER ½ LITRO DE LIQUIDO SIN GAS 1 HS PREVIA AL ESTUDIO Y RETENER",
                    "LA NIÑA DEBE ESTAR CON MUCHAS GANAS DE ORINAR, CASO CONTRARIO DEBERÁ SER RECITADA OTRO DÍA"
                ],
                'niñas_mayor_10_años': [
                    "BEBER ¾ LITRO DE LIQUIDO SIN GAS 2 HS PREVIAS AL ESTUDIO Y RETENER",
                    "LA NIÑA DEBE ESTAR CON MUCHAS GANAS DE ORINAR, CASO CONTRARIO DEBERÁ SER RECITADA OTRO DÍA"
                ]
            },
            'Ecografía de Vías Urinarias': {
                'bebés': ["PECHO O MAMADERA MEDIA HORA ANTES DEL ESTUDIO"],
                'niñas_hasta_3_años': [
                    "BEBER 500 ML DE LÍQUIDO SIN GAS (una botellita) 2 HS PREVIAS AL ESTUDIO Y RETENER SI CONTROLA ESFÍNTERES",
                    "LA NIÑA DEBE ESTAR CON MUCHAS GANAS DE ORINAR"
                ],
                'niñas_3_a_10_años': [
                    "BEBER ½ LITRO DE LIQUIDO SIN GAS 1 HS PREVIA AL ESTUDIO Y RETENER",
                    "LA NIÑA DEBE ESTAR CON MUCHAS GANAS DE ORINAR, CASO CONTRARIO DEBERÁ SER RECITADA OTRO DÍA"
                ],
                'niñas_mayor_10_años': [
                    "BEBER ¾ LITRO DE LIQUIDO SIN GAS 2 HS PREVIAS AL ESTUDIO Y RETENER",
                    "LA NIÑA DEBE ESTAR CON MUCHAS GANAS DE ORINAR, CASO CONTRARIO DEBERÁ SER RECITADA OTRO DÍA"
                ]
            },
            'PRUNAPE': [
                "El paciente debe tener entre 0 años y 5 años 11 meses 29 días",
                "Concurrir SIN JUGUETES",
                "SIN HAMBRE",
                "SIN SUEÑO",
                "SIN HERMANITOS"
            ]
        }
        
        # =================== REGLAS ESPECIALES ===================
        self.REGLAS_ESPECIALES = {
            'neurologia_infantil_acceso_directo': ['MEPLIFE', 'OSSEG', 'PARTICULAR'],
            'neurologia_infantil_lista_espera': [
                'IOMA', 'OSDE', 'OMINT', 'PASTELEROS', 'TELEVISION', 'OSDOP', 'PODER_JUDICIAL', 'W.HOPE'
            ],
            'dr_malacchia_lunes_permitidas': ['PARTICULAR', 'OMINT', 'OSDE', 'PODER_JUDICIAL', 'W.HOPE'],
            'dr_malacchia_lunes_arancel_especial': 22500,
            'obras_sociales_bono_atencion': ['OSDOP', 'PASTELEROS', 'TELEVISION'],
            'obras_sociales_bono_consulta_ecografias': ['PASTELEROS', 'TELEVISION'],
            'neumonologia_ioma_max_slots': 5,
            'edad_maxima_prunape': {'años': 5, 'meses': 11, 'dias': 29}
        }
        
        # =================== MAPEO DE SERVICIOS ===================
        self.SERVICIO_TO_KEY = {
            'Consulta Pediátrica': 'consultas',
            'Consulta de Urgencia': 'consultas',
            'Neurología Infantil': 'neurologia_infantil',
            'Neumonología Infantil': 'neumonologia_infantil',
            'Dermatología Infantil': 'consultas',  # Se maneja como consulta general
            'Oftalmología Infantil': 'consultas',  # Se maneja como consulta general
            'Cardiología Infantil': 'consultas',  # Se maneja como consulta general
            'Ecografía Abdominal': 'ecografias',
            'Ecografía Hepatobiliar': 'ecografias',
            'Ecografía Esplénica': 'ecografias',
            'Ecografía Suprarrenal': 'ecografias',
            'Ecografía Pancreática': 'ecografias',
            'Ecografía Ginecológica': 'ecografias',
            'Ecografía Renal': 'ecografias',
            'Ecografía de Vías Urinarias': 'ecografias',
            'Electroencefalograma (EEG)': 'electroencefalograma',
            'Potencial Evocado Auditivo (PEAT)': 'ecografias',  # Cobertura similar a ecografías
            'Polisomnografía Diurna': 'ecografias',  # Cobertura similar a ecografías
            'Ecocardiograma Doppler Color': 'ecocardiograma_doppler',
            'Electrocardiograma': 'consultas',  # Se maneja como consulta
            'Psicología': 'psicologia',
            'Psicopedagogía': 'psicopedagogia',
            'Neuropsicología': 'neuropsicologia',
            'Test de Ados (Neuropsicología)': 'neuropsicologia',
            'Test de Adir (Neuropsicología)': 'neuropsicologia',
            'PRUNAPE': 'consultas',  # Se maneja como consulta especial
            'Audiometría': 'consultas',  # Se maneja como consulta
            'Vacunación': 'consultas'  # Se maneja como consulta especial
        }
        
        logger.info("[RULES_ENGINE] Reglas de Ballester cargadas exitosamente")
    
    def get_verification_verdict(self, patient_data: Dict, service_data: Dict) -> Dict[str, Any]:
        """
        FUNCIÓN PRINCIPAL: Obtiene el veredicto completo de verificación médica.
        
        Esta función es el corazón del sistema. Toma los datos del paciente y del servicio,
        y retorna un veredicto completo con toda la información necesaria:
        - Estado de cobertura
        - Requisitos necesarios
        - Información de pagos
        - Restricciones especiales
        - Próxima acción a tomar
        - Mensaje específico para el usuario
        
        Args:
            patient_data: Datos completos del paciente
            service_data: Datos del servicio solicitado
            
        Returns:
            Dict con veredicto completo
        """
        logger.info(f"[RULES_ENGINE] Procesando veredicto para {service_data.get('service_name')} con {patient_data.get('obra_social')}")
        
        obra_social = patient_data.get('obra_social', '').upper()
        plan = patient_data.get('plan', '')
        service_name = service_data.get('service_name', '')
        
        # Validaciones básicas
        if not obra_social or not service_name:
            return self._build_error_verdict("Faltan datos básicos para la verificación")
        
        # Aplicar reglas especiales primero
        special_verdict = self._check_special_rules(patient_data, service_data)
        if special_verdict:
            return special_verdict
        
        # Obtener clave del servicio para búsqueda en reglas
        service_key = self.SERVICIO_TO_KEY.get(service_name, 'consultas')
        
        # Buscar reglas de cobertura
        coverage_rules = self.COBERTURAS_BALLESTER.get(obra_social, {}).get(service_key, {})
        
        if not coverage_rules:
            # Obra social no cubre este servicio
            return self._build_private_verdict(patient_data, service_data)
        
        # Procesar veredicto según el tipo de cobertura
        coverage_status = coverage_rules.get('cobertura', 'NOT_COVERED')
        
        if coverage_status == 'COVERED':
            return self._build_covered_verdict(coverage_rules, patient_data, service_data)
        elif coverage_status == 'WAITLIST':
            return self._build_waitlist_verdict(coverage_rules, patient_data, service_data)
        elif coverage_status == 'PRIVATE_ONLY':
            return self._build_private_verdict(patient_data, service_data)
        elif coverage_status == 'NOT_COVERED':
            return self._build_private_verdict(patient_data, service_data)
        else:
            return self._build_error_verdict(f"Estado de cobertura no reconocido: {coverage_status}")
    
    def _check_special_rules(self, patient_data: Dict, service_data: Dict) -> Optional[Dict]:
        """Verifica reglas especiales que tienen precedencia sobre las reglas normales"""
        
        obra_social = patient_data.get('obra_social', '').upper()
        service_name = service_data.get('service_name', '')
        
        # ============= REGLA ESPECIAL: DR. MALACCHIA LUNES =============
        if self._is_dr_malacchia_monday_request(service_data):
            return self._handle_dr_malacchia_monday(patient_data, service_data)
        
        # ============= REGLA ESPECIAL: NEUROLOGÍA INFANTIL =============
        if service_name == 'Neurología Infantil':
            return self._handle_neurologia_special_rules(patient_data, service_data)
        
        # ============= REGLA ESPECIAL: NEUMONOLOGÍA CON IOMA =============
        if service_name == 'Neumonología Infantil' and obra_social == 'IOMA':
            return self._handle_neumonologia_ioma(patient_data, service_data)
        
        # ============= REGLA ESPECIAL: ELECTROENCEFALOGRAMA =============
        if service_name == 'Electroencefalograma (EEG)':
            return self._handle_eeg_special_rules(patient_data, service_data)
        
        # ============= REGLA ESPECIAL: PSICOLOGÍA =============
        if service_name == 'Psicología':
            return self._handle_psicologia_special_rules(patient_data, service_data)
        
        # ============= REGLA ESPECIAL: NEUROPSICOLOGÍA =============
        if service_name in ['Neuropsicología', 'Test de Ados (Neuropsicología)', 'Test de Adir (Neuropsicología)']:
            return self._handle_neuropsicologia_special_rules(patient_data, service_data)
        
        # ============= REGLA ESPECIAL: PSICOPEDAGOGÍA =============
        if service_name == 'Psicopedagogía':
            return self._handle_psicopedagogia_special_rules(patient_data, service_data)
        
        # ============= REGLA ESPECIAL: PRUNAPE =============
        if service_name == 'PRUNAPE':
            return self._handle_prunape_special_rules(patient_data, service_data)
        
        # ============= REGLA ESPECIAL: VACUNACIÓN =============
        if service_name == 'Vacunación':
            return self._handle_vacunacion_special_rules(patient_data, service_data)
        
        return None  # No hay reglas especiales aplicables
    
    def _handle_neurologia_special_rules(self, patient_data: Dict, service_data: Dict) -> Dict:
        """Maneja las reglas especiales de neurología infantil"""
        
        obra_social = patient_data.get('obra_social', '').upper()
        
        # Acceso directo solo para estas obras sociales
        if obra_social in self.REGLAS_ESPECIALES['neurologia_infantil_acceso_directo']:
            return {
                "coverage_status": "COVERED",
                "requirements": [],
                "payment_info": {"copago": 0 if obra_social in ['MEPLIFE', 'OSSEG'] else 4000},
                "next_action": "SHOW_APPOINTMENTS",
                "message_to_user": f"✅ Tu obra social {obra_social} tiene acceso directo a Neurología Infantil. Procedemos a buscar turnos disponibles.",
                "preparation_instructions": []
            }
        
        # Lista de espera para el resto (excepto PARTICULAR que se maneja aparte)
        elif obra_social in self.REGLAS_ESPECIALES['neurologia_infantil_lista_espera']:
            # Verificar si hay cupo disponible (simulación - en producción consultaría la API)
            daily_slots_used = self._get_daily_neurologia_slots_used()  # Simula consulta a API
            
            return {
                "coverage_status": "WAITLIST",
                "requirements": ["Lista de espera por cupo limitado", "Bono de Contribución requerido"],
                "payment_info": {"bono_contribucion": 2500},
                "next_action": "ADD_TO_WAITLIST",
                "message_to_user": f"""⏳ **Neurología Infantil - Lista de Espera**

Tu obra social {obra_social} cubre Neurología Infantil, pero por la alta demanda tenemos lista de espera.

**¿Cómo funciona?**
• El neurólogo atiende solo 5 pacientes de obra social por día
• Te agregamos a la lista y te contactamos cuando haya disponibilidad
• Se requiere un Bono de Contribución de $2.500

¿Deseas ingresar a la lista de espera?""",
                "bono_mensaje": "Le informamos que su obra social requiere un Bono de Contribución Temporal de $2.500 que lo cobra íntegramente el profesional que lo atenderá ya que la obra social no alcanza a pagarle el mínimo ético. Esto nos ayuda a mantener la calidad y el servicio especializado."
            }
        
        # PARTICULAR
        elif obra_social == 'PARTICULAR':
            precio = self.PRECIOS_PARTICULARES.get('Neurología Infantil', 66000)
            return {
                "coverage_status": "PRIVATE_ONLY",
                "requirements": [],
                "payment_info": {"particular_fee": precio},
                "next_action": "SHOW_APPOINTMENTS",
                "message_to_user": f"Como paciente particular, el arancel para Neurología Infantil es ${precio}. ¿Deseas continuar?",
                "preparation_instructions": []
            }
        
        else:
            # Obra social no reconocida para neurología
            return {
                "coverage_status": "NOT_COVERED",
                "requirements": [],
                "payment_info": {"particular_fee": 66000},
                "next_action": "CONTACT_HUMAN",
                "message_to_user": f"Tu obra social {obra_social} no está en nuestros convenios para Neurología Infantil. Te derivamos al personal para una consulta personalizada.",
                "preparation_instructions": []
            }
    
    def _handle_dr_malacchia_monday(self, patient_data: Dict, service_data: Dict) -> Dict:
        """Maneja las reglas especiales del Dr. Malacchia los lunes"""
        
        obra_social = patient_data.get('obra_social', '').upper()
        
        if obra_social in self.REGLAS_ESPECIALES['dr_malacchia_lunes_permitidas']:
            # Obras sociales que pueden ver al Dr. Malacchia sin costo adicional
            return {
                "coverage_status": "COVERED",
                "requirements": [],
                "payment_info": {"copago": 0},
                "next_action": "SHOW_APPOINTMENTS",
                "message_to_user": f"✅ Tu obra social {obra_social} puede atenderse con el Dr. Malacchia los lunes sin costo adicional.",
                "preparation_instructions": [],
                "special_scheduling": "dr_malacchia_lunes"
            }
        
        elif obra_social == 'PARTICULAR':
            # Particulares pagan arancel normal
            precio = self.PRECIOS_PARTICULARES.get('Consulta Pediátrica', 28000)
            return {
                "coverage_status": "PRIVATE_ONLY",
                "requirements": [],
                "payment_info": {"particular_fee": precio},
                "next_action": "SHOW_APPOINTMENTS",
                "message_to_user": f"Como paciente particular, el arancel con el Dr. Malacchia es ${precio}. ¿Deseas continuar?",
                "preparation_instructions": [],
                "special_scheduling": "dr_malacchia_lunes"
            }
        
        else:
            # Otras obras sociales pagan arancel especial
            arancel_especial = self.REGLAS_ESPECIALES['dr_malacchia_lunes_arancel_especial']
            return {
                "coverage_status": "SPECIAL_RATE",
                "requirements": [f"Arancel especial de ${arancel_especial}"],
                "payment_info": {"arancel_especial": arancel_especial},
                "next_action": "CONFIRM_SPECIAL_RATE",
                "message_to_user": f"""💳 **Consulta con Dr. Malacchia - Lunes**

Tu obra social {obra_social} no tiene convenio directo con el Dr. Malacchia los lunes.

**Opción disponible:**
• Arancel preferencial: ${arancel_especial}
• Atención especializada personalizada
• Turno garantizado

¿Aceptas el arancel especial de ${arancel_especial}?""",
                "preparation_instructions": [],
                "special_scheduling": "dr_malacchia_lunes"
            }
    
    def _handle_eeg_special_rules(self, patient_data: Dict, service_data: Dict) -> Dict:
        """Maneja reglas especiales para Electroencefalograma"""
        
        obra_social = patient_data.get('obra_social', '').upper()
        
        # Solo MEDICARDIO y PARTICULAR cubren EEG
        if obra_social == 'MEDICARDIO':
            return {
                "coverage_status": "COVERED",
                "requirements": ["Orden médica"],
                "payment_info": {"copago": 4000},
                "next_action": "SHOW_APPOINTMENTS",
                "message_to_user": "✅ MEDICARDIO cubre el Electroencefalograma con copago de $4.000.",
                "preparation_instructions": self.PREPARACIONES_ESTUDIOS.get('Electroencefalograma (EEG)', [])
            }
        
        elif obra_social == 'PARTICULAR':
            precio = self.PRECIOS_PARTICULARES.get('Electroencefalograma (EEG)', 50000)
            return {
                "coverage_status": "PRIVATE_ONLY",
                "requirements": ["Orden médica"],
                "payment_info": {"particular_fee": precio},
                "next_action": "SHOW_APPOINTMENTS",
                "message_to_user": f"Como paciente particular, el arancel del EEG es ${precio}. ¿Deseas continuar?",
                "preparation_instructions": self.PREPARACIONES_ESTUDIOS.get('Electroencefalograma (EEG)', [])
            }
        
        else:
            # Otras obras sociales no cubren EEG
            precio = self.PRECIOS_PARTICULARES.get('Electroencefalograma (EEG)', 50000)
            return {
                "coverage_status": "NOT_COVERED",
                "requirements": ["Orden médica", "Pago particular"],
                "payment_info": {"particular_fee": precio},
                "next_action": "CONFIRM_PRIVATE_PAYMENT",
                "message_to_user": f"""❌ **EEG No Cubierto**

Tu obra social {obra_social} no cubre el Electroencefalograma.

**Opción disponible:**
• Arancel particular: ${precio}
• Estudio especializado con preparación específica

¿Deseas continuar como paciente particular?""",
                "preparation_instructions": self.PREPARACIONES_ESTUDIOS.get('Electroencefalograma (EEG)', [])
            }
    
    def _handle_psicologia_special_rules(self, patient_data: Dict, service_data: Dict) -> Dict:
        """Maneja reglas especiales para Psicología (solo particular)"""
        
        precio = self.PRECIOS_PARTICULARES.get('Psicología', 32000)
        
        return {
            "coverage_status": "PRIVATE_ONLY",
            "requirements": [],
            "payment_info": {"particular_fee": precio},
            "next_action": "CONTACT_HUMAN_FOR_APPOINTMENT",
            "message_to_user": f"""🧠 **Psicología - Solo Atención Particular**

Nuestro servicio de Psicología atiende:
• Niños, adolescentes y adultos
• Solo modalidad particular
• Arancel por sesión: ${precio}

Si estás de acuerdo con el valor, te derivo con el personal para coordinar el turno.

¿Deseas continuar?""",
            "preparation_instructions": []
        }
    
    def _handle_neuropsicologia_special_rules(self, patient_data: Dict, service_data: Dict) -> Dict:
        """Maneja reglas especiales para Neuropsicología (solo particular)"""
        
        service_name = service_data.get('service_name', '')
        
        if service_name == 'Test de Ados (Neuropsicología)':
            precio_total = self.PRECIOS_PARTICULARES.get('Test de Ados (Neuropsicología)', 80000)
            sesiones = 4
            precio_sesion = 20000
            
            mensaje = f"""🧩 **Test de Ados - Evaluación Neuropsicológica**

**Detalles del estudio:**
• 4 sesiones de evaluación
• Precio por sesión: ${precio_sesion}
• **Total del estudio: ${precio_total}**
• Solo atención particular"""
            
        elif service_name == 'Test de Adir (Neuropsicología)':
            precio_total = self.PRECIOS_PARTICULARES.get('Test de Adir (Neuropsicología)', 60000)
            sesiones = 3
            precio_sesion = 20000
            
            mensaje = f"""🧩 **Test de Adir - Evaluación Neuropsicológica**

**Detalles del estudio:**
• 3 sesiones de evaluación  
• Precio por sesión: ${precio_sesion}
• **Total del estudio: ${precio_total}**
• Solo atención particular"""
            
        else:  # Neuropsicología general
            precio_sesion = self.PRECIOS_PARTICULARES.get('Neuropsicología', 20000)
            
            mensaje = f"""🧩 **Neuropsicología - Evaluación Neurocognitiva**

**Servicios disponibles:**
• Neuropsicología general
• Psicología neurocognitiva
• Evaluación neuropsicológica
• Evaluación neurocognitiva

**Precio por sesión: ${precio_sesion}**
• Solo atención particular"""
            
            precio_total = precio_sesion
        
        return {
            "coverage_status": "PRIVATE_ONLY",
            "requirements": ["Solo atención particular"],
            "payment_info": {"particular_fee": precio_total, "precio_por_sesion": precio_sesion if 'precio_sesion' in locals() else precio_total},
            "next_action": "CONTACT_HUMAN_FOR_APPOINTMENT",
            "message_to_user": mensaje + "\n\nSi estás de acuerdo, te derivo con el personal para coordinar las sesiones.\n\n¿Deseas continuar?",
            "preparation_instructions": []
        }
    
    def _handle_psicopedagogia_special_rules(self, patient_data: Dict, service_data: Dict) -> Dict:
        """Maneja reglas especiales para Psicopedagogía (lista de espera o particular)"""
        
        obra_social = patient_data.get('obra_social', '').upper()
        precio = self.PRECIOS_PARTICULARES.get('Psicopedagogía', 20000)
        
        if obra_social == 'PARTICULAR':
            return {
                "coverage_status": "PRIVATE_ONLY",
                "requirements": [],
                "payment_info": {"particular_fee": precio},
                "next_action": "ADD_TO_WAITLIST",
                "message_to_user": f"""📚 **Psicopedagogía**

**Como paciente particular:**
• Arancel por sesión: ${precio}
• Te agregamos a la lista de espera
• Te contactamos cuando haya disponibilidad

¿Deseas ingresar a la lista de espera?""",
                "preparation_instructions": []
            }
        
        else:
            return {
                "coverage_status": "WAITLIST",
                "requirements": ["Lista de espera"],
                "payment_info": {},
                "next_action": "ADD_TO_WAITLIST",
                "message_to_user": f"""📚 **Psicopedagogía - Lista de Espera**

Tu obra social {obra_social} está en evaluación para este servicio.

• Te agregamos a la lista de espera
• Te contactamos cuando haya disponibilidad
• Si prefieres atención particular: ${precio} por sesión

¿Cómo prefieres continuar?""",
                "preparation_instructions": []
            }
    
    def _handle_prunape_special_rules(self, patient_data: Dict, service_data: Dict) -> Dict:
        """Maneja reglas especiales para PRUNAPE (edad específica)"""
        
        # Verificar edad (0 a 5 años 11 meses 29 días)
        fecha_nacimiento = patient_data.get('fecha_nacimiento', '')
        
        if not self._validate_prunape_age(fecha_nacimiento):
            return {
                "coverage_status": "NOT_ELIGIBLE",
                "requirements": ["Edad entre 0 y 5 años 11 meses 29 días"],
                "payment_info": {},
                "next_action": "CONTACT_HUMAN",
                "message_to_user": """❌ **PRUNAPE - Fuera de Rango de Edad**

El PRUNAPE (Prueba Nacional de Pesquisa) se realiza exclusivamente para niños entre:
• **0 años a 5 años 11 meses 29 días**

Según los datos proporcionados, el paciente no está en el rango de edad requerido.

Te derivamos al personal para una consulta personalizada.""",
                "preparation_instructions": []
            }
        
        # Paciente en edad correcta
        obra_social = patient_data.get('obra_social', '').upper()
        
        if obra_social == 'PARTICULAR':
            precio = self.PRECIOS_PARTICULARES.get('PRUNAPE', 30000)
            return {
                "coverage_status": "PRIVATE_ONLY",
                "requirements": [],
                "payment_info": {"particular_fee": precio},
                "next_action": "SHOW_APPOINTMENTS",
                "message_to_user": f"✅ PRUNAPE disponible para paciente particular. Arancel: ${precio}",
                "preparation_instructions": self.PREPARACIONES_ESTUDIOS.get('PRUNAPE', [])
            }
        
        else:
            # La mayoría de obras sociales cubren PRUNAPE
            return {
                "coverage_status": "COVERED",
                "requirements": ["Edad verificada", "Orden médica"],
                "payment_info": {"copago": 0},
                "next_action": "SHOW_APPOINTMENTS",
                "message_to_user": f"✅ Tu obra social {obra_social} cubre el PRUNAPE sin costo.",
                "preparation_instructions": self.PREPARACIONES_ESTUDIOS.get('PRUNAPE', [])
            }
    
    def _handle_vacunacion_special_rules(self, patient_data: Dict, service_data: Dict) -> Dict:
        """Maneja reglas especiales para Vacunación"""
        
        obra_social = patient_data.get('obra_social', '').upper()
        
        return {
            "coverage_status": "REQUIRES_VERIFICATION",
            "requirements": ["Verificar convenio de vacunas"],
            "payment_info": {},
            "next_action": "CONTACT_HUMAN_FOR_VERIFICATION",
            "message_to_user": f"""💉 **Vacunación**

Para el servicio de vacunación necesitamos verificar si tu obra social {obra_social} tiene convenio específico de vacunas con nuestro centro.

Te derivo con nuestro personal para que te informen sobre:
• Vacunas cubiertas
• Disponibilidad
• Requisitos específicos

¿Continuamos con la derivación?""",
            "preparation_instructions": []
        }
    
    def _handle_neumonologia_ioma(self, patient_data: Dict, service_data: Dict) -> Dict:
        """Maneja la regla especial de neumonología con IOMA (máximo 5 por día)"""
        
        # Simular verificación de slots usados (en producción consultaría la API)
        slots_used_today = self._get_daily_neumonologia_ioma_slots()
        max_slots = self.REGLAS_ESPECIALES['neumonologia_ioma_max_slots']
        
        if slots_used_today >= max_slots:
            return {
                "coverage_status": "QUOTA_EXCEEDED",
                "requirements": ["Cupo diario completo"],
                "payment_info": {},
                "next_action": "OFFER_ALTERNATIVE_DATE",
                "message_to_user": f"""⚠️ **Neumonología - Cupo IOMA Completo**

Ya se asignaron los {max_slots} turnos diarios disponibles para pacientes IOMA en Neumonología.

**Opciones disponibles:**
• Agendar para otro día
• Lista de espera para cancelaciones

¿Cómo prefieres continuar?""",
                "preparation_instructions": []
            }
        
        else:
            return {
                "coverage_status": "COVERED",
                "requirements": [],
                "payment_info": {"copago": 4000},
                "next_action": "SHOW_APPOINTMENTS",
                "message_to_user": f"✅ IOMA cubre Neumonología con copago de $4.000. Quedan {max_slots - slots_used_today} turnos disponibles hoy.",
                "preparation_instructions": []
            }
    
    def _build_covered_verdict(self, coverage_rules: Dict, patient_data: Dict, service_data: Dict) -> Dict:
        """Construye veredicto para servicios cubiertos"""
        
        obra_social = patient_data.get('obra_social', '')
        service_name = service_data.get('service_name', '')
        
        # Construir lista de requisitos
        requirements = []
        
        if coverage_rules.get('requiere_autorizacion'):
            requirements.append(f"Autorización previa emitida para el CENTRO PEDIATRICO BALLESTER")
        
        if coverage_rules.get('requiere_bono_atencion'):
            requirements.append("Bono de Atención de la obra social")
        
        if coverage_rules.get('requiere_bono_consulta'):
            requirements.append("Bono de Consulta de la obra social")
        
        if service_name in ['Ecografía Abdominal', 'Ecografía Hepatobiliar', 'Ecografía Esplénica', 'Ecografía Suprarrenal', 'Ecografía Pancreática']:
            if obra_social in ['PASTELEROS', 'TELEVISION']:
                requirements.append("Bono de Consulta (adicional para ecografías con Dra. Ametller)")
        
        # Información de pagos
        payment_info = {}
        copago = coverage_rules.get('copago', 0)
        if copago > 0:
            payment_info['copago'] = copago
        
        bono_contribucion = coverage_rules.get('bono_contribucion')
        if bono_contribucion:
            payment_info['bono_contribucion'] = bono_contribucion
        
        # Mensaje para el usuario
        mensaje = f"✅ **{obra_social} cubre {service_name}**"
        if copago > 0:
            mensaje += f" con copago de ${copago}"
        mensaje += "."
        
        if bono_contribucion:
            mensaje += f"\n\n💰 **Bono de Contribución:** ${bono_contribucion}"
        
        # Preparaciones del estudio
        prep_instructions = self._get_study_preparations(service_name, patient_data)
        
        return {
            "coverage_status": "COVERED",
            "requirements": requirements,
            "payment_info": payment_info,
            "next_action": "SHOW_APPOINTMENTS",
            "message_to_user": mensaje,
            "preparation_instructions": prep_instructions,
            "bono_mensaje": "Le informamos que su obra social requiere un Bono de Contribución Temporal que lo cobra íntegramente el profesional que lo atenderá ya que la obra social no alcanza a pagarle el mínimo ético. Esto nos ayuda a mantener la calidad y el servicio especializado." if bono_contribucion else None
        }
    
    def _build_waitlist_verdict(self, coverage_rules: Dict, patient_data: Dict, service_data: Dict) -> Dict:
        """Construye veredicto para servicios en lista de espera"""
        
        obra_social = patient_data.get('obra_social', '')
        service_name = service_data.get('service_name', '')
        
        bono_contribucion = coverage_rules.get('bono_contribucion', 0)
        
        mensaje = f"""⏳ **{service_name} - Lista de Espera**

Tu obra social {obra_social} cubre este servicio, pero por la alta demanda tenemos lista de espera.

**¿Cómo funciona?**
• Te agregamos a nuestra lista de espera
• Te contactamos cuando haya disponibilidad
• Tiempo estimado: depende de la demanda"""
        
        if bono_contribucion:
            mensaje += f"\n• Se requiere Bono de Contribución de ${bono_contribucion}"
        
        mensaje += "\n\n¿Deseas ingresar a la lista de espera?"
        
        return {
            "coverage_status": "WAITLIST",
            "requirements": ["Lista de espera por alta demanda"],
            "payment_info": {"bono_contribucion": bono_contribucion} if bono_contribucion else {},
            "next_action": "ADD_TO_WAITLIST",
            "message_to_user": mensaje,
            "preparation_instructions": self._get_study_preparations(service_name, patient_data),
            "bono_mensaje": "Le informamos que su obra social requiere un Bono de Contribución Temporal que lo cobra íntegramente el profesional que lo atenderá ya que la obra social no alcanza a pagarle el mínimo ético. Esto nos ayuda a mantener la calidad y el servicio especializado." if bono_contribucion else None
        }
    
    def _build_private_verdict(self, patient_data: Dict, service_data: Dict) -> Dict:
        """Construye veredicto para servicios particulares"""
        
        obra_social = patient_data.get('obra_social', '')
        service_name = service_data.get('service_name', '')
        
        precio = self.PRECIOS_PARTICULARES.get(service_name, 0)
        
        if precio == 0:
            # Precio no encontrado
            mensaje = f"""❌ **Servicio No Disponible**

{service_name} no está disponible en este momento o requiere consulta personalizada.

Te derivamos al personal para información detallada."""
            
            return {
                "coverage_status": "NOT_AVAILABLE",
                "requirements": [],
                "payment_info": {},
                "next_action": "CONTACT_HUMAN",
                "message_to_user": mensaje,
                "preparation_instructions": []
            }
        
        mensaje = f"""💰 **{service_name} - Arancel Particular**

Tu obra social {obra_social} no cubre este servicio.

**Opción disponible:**
• Arancel particular: ${precio}
• Atención especializada de calidad

¿Deseas continuar como paciente particular?"""
        
        return {
            "coverage_status": "PRIVATE_ONLY",
            "requirements": ["Pago particular"],
            "payment_info": {"particular_fee": precio},
            "next_action": "CONFIRM_PRIVATE_PAYMENT",
            "message_to_user": mensaje,
            "preparation_instructions": self._get_study_preparations(service_name, patient_data)
        }
    
    def _build_error_verdict(self, error_message: str) -> Dict:
        """Construye veredicto de error"""
        
        return {
            "coverage_status": "ERROR",
            "requirements": [],
            "payment_info": {},
            "next_action": "CONTACT_HUMAN",
            "message_to_user": f"⚠️ Se produjo un problema en la verificación: {error_message}. Te derivamos al personal para asistencia.",
            "preparation_instructions": []
        }
    
    def _get_study_preparations(self, service_name: str, patient_data: Dict) -> List[str]:
        """Obtiene las preparaciones específicas para un estudio según la edad del paciente"""
        
        preparations = self.PREPARACIONES_ESTUDIOS.get(service_name, [])
        
        # Si las preparaciones son específicas por edad (como ecografías)
        if isinstance(preparations, dict):
            edad_grupo = self._determine_age_group(patient_data.get('fecha_nacimiento', ''))
            return preparations.get(edad_grupo, [])
        
        return preparations
    
    def _determine_age_group(self, fecha_nacimiento: str) -> str:
        """Determina el grupo etario para preparaciones específicas"""
        
        if not fecha_nacimiento:
            return 'niños_2_años_a_10_años'  # Grupo por defecto
        
        try:
            from datetime import datetime
            
            # Parsear fecha DD/MM/YYYY
            parts = fecha_nacimiento.split('/')
            if len(parts) != 3:
                return 'niños_2_años_a_10_años'
            
            birth_date = datetime(int(parts[2]), int(parts[1]), int(parts[0]))
            today = datetime.now()
            
            age_months = (today.year - birth_date.year) * 12 + today.month - birth_date.month
            
            if age_months <= 3:
                return 'bebés_hasta_3_meses'
            elif age_months <= 24:
                return 'niños_3_meses_a_2_años'
            elif age_months <= 120:  # 10 años
                return 'niños_2_años_a_10_años'
            else:
                return 'niños_mayor_10_años'
            
        except:
            return 'niños_2_años_a_10_años'  # Grupo por defecto en caso de error
    
    def _validate_prunape_age(self, fecha_nacimiento: str) -> bool:
        """Valida si la edad es válida para PRUNAPE (0 a 5 años 11 meses 29 días)"""
        
        if not fecha_nacimiento:
            return False
        
        try:
            from datetime import datetime
            
            # Parsear fecha DD/MM/YYYY
            parts = fecha_nacimiento.split('/')
            if len(parts) != 3:
                return False
            
            birth_date = datetime(int(parts[2]), int(parts[1]), int(parts[0]))
            today = datetime.now()
            
            # Calcular edad exacta
            age_years = today.year - birth_date.year
            age_months = today.month - birth_date.month
            age_days = today.day - birth_date.day
            
            # Ajustar si los días son negativos
            if age_days < 0:
                age_months -= 1
                
            # Ajustar si los meses son negativos
            if age_months < 0:
                age_years -= 1
                age_months += 12
            
            # Verificar límites: 0 años a 5 años 11 meses 29 días
            if age_years > 5:
                return False
            elif age_years == 5:
                if age_months > 11:
                    return False
                elif age_months == 11 and age_days > 29:
                    return False
            
            return age_years >= 0
            
        except:
            return False
    
    # Métodos auxiliares para simulación (en producción consultarían APIs reales)
    def _get_daily_neurologia_slots_used(self) -> int:
        """Simula consulta de slots de neurología usados hoy"""
        # En producción consultaría la API de la clínica
        return 3  # Simulación
    
    def _get_daily_neumonologia_ioma_slots(self) -> int:
        """Simula consulta de slots de neumonología IOMA usados hoy"""
        # En producción consultaría la API de la clínica
        return 2  # Simulación
    
    def _is_dr_malacchia_monday_request(self, service_data: Dict) -> bool:
        """Detecta si la solicitud es específica para Dr. Malacchia los lunes"""
        # En producción esto vendría en los datos del service o se detectaría por contexto
        return service_data.get('doctor', '').lower() == 'malacchia' or service_data.get('day', '').lower() == 'lunes'


# Función helper para uso en verification_handler.py
def get_ballester_verdict(patient_data: Dict, service_data: Dict) -> Dict[str, Any]:
    """
    Función helper para obtener veredicto desde verification_handler.py
    """
    engine = BallesterRulesEngine()
    return engine.get_verification_verdict(patient_data, service_data)
