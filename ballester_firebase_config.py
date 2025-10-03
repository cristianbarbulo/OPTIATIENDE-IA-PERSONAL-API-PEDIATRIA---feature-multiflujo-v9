"""
ballester_firebase_config.py - Configuración Firebase Centro Pediátrico Ballester
Sistema V11 - Configuración Completa de Base de Datos Médica

Este archivo configura toda la estructura de Firebase específica para Ballester:
- Colecciones de datos médicos
- Reglas de cobertura por obra social
- Precios y aranceles
- Configuración de especialistas
- Datos de preparaciones para estudios

CRÍTICO: Esta configuración debe ejecutarse UNA VEZ para inicializar
la base de datos con todos los datos específicos de Ballester.

Autor: Sistema OPTIATIENDE-IA V11
Cliente: Centro Pediátrico Ballester
Fecha: Enero 2025
"""

import logging
from datetime import datetime
from typing import Dict, Any
import json

import firebase_admin
from firebase_admin import firestore

logger = logging.getLogger(__name__)

class BallesterFirebaseConfig:
    """
    Configurador de Firebase específico para Centro Pediátrico Ballester.
    
    Inicializa todas las colecciones y datos necesarios para el funcionamiento
    del sistema médico V11.
    """
    
    def __init__(self):
        """Inicializa el configurador de Firebase"""
        self.db = firestore.client()
        logger.info("[FIREBASE_CONFIG] Configurador de Ballester inicializado")
    
    def initialize_ballester_database(self) -> bool:
        """
        Inicializa completamente la base de datos de Ballester.
        
        ADVERTENCIA: Esta función debe ejecutarse UNA SOLA VEZ para configurar
        la base de datos inicial. Ejecutar múltiples veces puede sobrescribir datos.
        
        Returns:
            True si se configuró exitosamente
        """
        logger.info("[FIREBASE_CONFIG] Inicializando base de datos Ballester")
        
        try:
            # Configurar cada colección
            self._setup_obras_sociales_collection()
            self._setup_servicios_medicos_collection()
            self._setup_precios_particulares_collection()
            self._setup_preparaciones_estudios_collection()
            self._setup_especialistas_collection()
            self._setup_reglas_especiales_collection()
            self._setup_configuracion_ballester()
            
            logger.info("[FIREBASE_CONFIG] ✅ Base de datos Ballester configurada exitosamente")
            return True
            
        except Exception as e:
            logger.error(f"[FIREBASE_CONFIG] ❌ Error configurando base de datos: {e}", exc_info=True)
            return False
    
    def _setup_obras_sociales_collection(self):
        """Configura la colección de obras sociales y coberturas"""
        
        logger.info("[FIREBASE_CONFIG] Configurando colección obras_sociales_ballester")
        
        # Datos basados en las imágenes de las tablas proporcionadas
        obras_sociales_data = {
            'IOMA': {
                'nombre_completo': 'Instituto de Obra Médico Asistencial',
                'requiere_bono_atencion': False,
                'servicios_cubiertos': {
                    'consultas_pediatricas': {
                        'cobertura': 'COVERED',
                        'copago': 4000,
                        'requiere_autorizacion': False
                    },
                    'neurologia_infantil': {
                        'cobertura': 'WAITLIST', 
                        'copago': 4000,
                        'requiere_autorizacion': False,
                        'max_slots_dia': 5,
                        'bono_contribucion': 2500
                    },
                    'neumonologia_infantil': {
                        'cobertura': 'COVERED',
                        'copago': 4000,
                        'requiere_autorizacion': False,
                        'max_slots_dia': 5
                    },
                    'ecografias': {
                        'cobertura': 'COVERED',
                        'copago': 4000,
                        'requiere_autorizacion': True
                    },
                    'electroencefalograma': {
                        'cobertura': 'NOT_COVERED'
                    }
                }
            },
            'MEDICARDIO': {
                'nombre_completo': 'Medicardio',
                'requiere_bono_atencion': False,
                'servicios_cubiertos': {
                    'consultas_pediatricas': {
                        'cobertura': 'COVERED',
                        'copago': 4000,
                        'requiere_autorizacion': False
                    },
                    'neurologia_infantil': {
                        'cobertura': 'COVERED',
                        'copago': 4000,
                        'requiere_autorizacion': False
                    },
                    'electroencefalograma': {
                        'cobertura': 'COVERED',
                        'copago': 4000,
                        'requiere_autorizacion': False
                    },
                    'ecografias': {
                        'cobertura': 'COVERED',
                        'copago': 4000,
                        'requiere_autorizacion': True
                    }
                }
            },
            'OSDE': {
                'nombre_completo': 'OSDE',
                'requiere_bono_atencion': False,
                'servicios_cubiertos': {
                    'consultas_pediatricas': {
                        'cobertura': 'COVERED',
                        'copago': 4000,
                        'requiere_autorizacion': False
                    },
                    'neurologia_infantil': {
                        'cobertura': 'WAITLIST',
                        'copago': 4000,
                        'requiere_autorizacion': False,
                        'bono_contribucion': 2500
                    },
                    'dr_malacchia_lunes': {
                        'cobertura': 'COVERED',
                        'copago': 0
                    }
                }
            },
            'PASTELEROS': {
                'nombre_completo': 'Obra Social de Pasteleros',
                'requiere_bono_atencion': True,
                'servicios_cubiertos': {
                    'consultas_pediatricas': {
                        'cobertura': 'COVERED',
                        'copago': 4000,
                        'requiere_autorizacion': False,
                        'requiere_bono_atencion': True
                    },
                    'ecografias': {
                        'cobertura': 'COVERED',
                        'copago': 4000,
                        'requiere_autorizacion': True,
                        'requiere_bono_consulta': True  # Específico para ecografías con Dra. Ametller
                    }
                }
            },
            'TELEVISION': {
                'nombre_completo': 'Obra Social de Televisión',
                'requiere_bono_atencion': True,
                'servicios_cubiertos': {
                    'consultas_pediatricas': {
                        'cobertura': 'COVERED',
                        'copago': 0,
                        'requiere_autorizacion': False,
                        'requiere_bono_atencion': True
                    },
                    'ecografias': {
                        'cobertura': 'COVERED',
                        'copago': 0,
                        'requiere_autorizacion': False,
                        'requiere_bono_consulta': True  # Específico para ecografías
                    }
                }
            }
        }
        
        # Guardar en Firebase
        for obra_social, datos in obras_sociales_data.items():
            doc_ref = self.db.collection('ballester_obras_sociales').document(obra_social)
            doc_ref.set(datos)
            logger.info(f"[FIREBASE_CONFIG] Obra social configurada: {obra_social}")
    
    def _setup_servicios_medicos_collection(self):
        """Configura la colección de servicios médicos"""
        
        logger.info("[FIREBASE_CONFIG] Configurando colección servicios_medicos_ballester")
        
        servicios_medicos = {
            'Consulta_Pediatrica': {
                'nombre_display': 'Consulta Pediátrica',
                'categoria': 'consultas',
                'duracion_minutos': 30,
                'requiere_orden_medica': False,
                'edad_minima': 0,
                'edad_maxima': 18,
                'descripcion': 'Consulta pediátrica general'
            },
            'Neurologia_Infantil': {
                'nombre_display': 'Neurología Infantil',
                'categoria': 'subespecialidades',
                'duracion_minutos': 45,
                'requiere_orden_medica': True,
                'edad_minima': 0,
                'edad_maxima': 18,
                'descripcion': 'Consulta con neurólogo infantil',
                'reglas_especiales': {
                    'acceso_directo': ['MEPLIFE', 'OSSEG', 'PARTICULAR'],
                    'lista_espera': ['IOMA', 'OSDE', 'OMINT', 'PASTELEROS', 'TELEVISION'],
                    'max_slots_obra_social_dia': 5
                }
            },
            'Neumonologia_Infantil': {
                'nombre_display': 'Neumonología Infantil', 
                'categoria': 'subespecialidades',
                'duracion_minutos': 30,
                'requiere_orden_medica': True,
                'edad_minima': 0,
                'edad_maxima': 18,
                'descripcion': 'Consulta con neumonólogo infantil',
                'reglas_especiales': {
                    'ioma_max_slots_dia': 5
                }
            },
            'Electroencefalograma_EEG': {
                'nombre_display': 'Electroencefalograma (EEG)',
                'categoria': 'estudios_neurologicos',
                'duracion_minutos': 60,
                'requiere_orden_medica': True,
                'edad_minima': 0,
                'edad_maxima': 18,
                'descripcion': 'Estudio de ondas cerebrales',
                'cobertura_limitada': ['MEDICARDIO', 'PARTICULAR'],
                'preparacion_especial': True
            },
            'Ecografia_Abdominal': {
                'nombre_display': 'Ecografía Abdominal',
                'categoria': 'ecografias',
                'duracion_minutos': 30,
                'requiere_orden_medica': True,
                'edad_minima': 0,
                'edad_maxima': 18,
                'descripcion': 'Ecografía del abdomen',
                'preparacion_especial': True,
                'preparacion_por_edad': True
            },
            'PRUNAPE': {
                'nombre_display': 'PRUNAPE - Prueba Nacional de Pesquisa',
                'categoria': 'evaluaciones',
                'duracion_minutos': 45,
                'requiere_orden_medica': True,
                'edad_minima': 0,
                'edad_maxima': 5,
                'edad_maxima_meses': 11,
                'edad_maxima_dias': 29,
                'descripcion': 'Evaluación del desarrollo infantil',
                'preparacion_especial': True
            },
            'Psicologia': {
                'nombre_display': 'Psicología',
                'categoria': 'salud_mental',
                'duracion_minutos': 50,
                'requiere_orden_medica': False,
                'edad_minima': 0,
                'edad_maxima': None,  # Atiende también adultos
                'descripcion': 'Consulta psicológica',
                'solo_particular': True
            },
            'Neuropsicologia': {
                'nombre_display': 'Neuropsicología',
                'categoria': 'salud_mental',
                'duracion_minutos': 60,
                'requiere_orden_medica': False,
                'edad_minima': 0,
                'edad_maxima': None,
                'descripcion': 'Evaluación neuropsicológica',
                'solo_particular': True,
                'modalidades': {
                    'evaluacion_general': {'sesiones': 1, 'precio_por_sesion': 20000},
                    'test_ados': {'sesiones': 4, 'precio_total': 80000},
                    'test_adir': {'sesiones': 3, 'precio_total': 60000}
                }
            }
        }
        
        # Guardar en Firebase
        for servicio_key, datos in servicios_medicos.items():
            doc_ref = self.db.collection('ballester_servicios_medicos').document(servicio_key)
            doc_ref.set(datos)
            logger.info(f"[FIREBASE_CONFIG] Servicio médico configurado: {servicio_key}")
    
    def _setup_precios_particulares_collection(self):
        """Configura la colección de precios particulares"""
        
        logger.info("[FIREBASE_CONFIG] Configurando colección precios_particulares_ballester")
        
        # Precios basados en la tabla proporcionada (actualizada a enero 2025)
        precios_data = {
            'fecha_actualizacion': datetime.now().isoformat(),
            'version': '2025-01',
            'precios': {
                'consultas': {
                    'Consulta_Pediatrica': 28000,
                    'Cardiologia_Infantil': 28000,
                    'Dermatologia_Infantil': 28000,
                    'Endocrinologia_Infantil': 27000,
                    'Gastroenterologia_Infantil': 28000,
                    'Infectologia_Infantil': 28000,
                    'Neumonologia_Infantil': 28000,
                    'Neurologia_Infantil': 66000,
                    'Nutricion_Infantil': 28000,
                    'Nutricionista_Infantil': 20000,
                    'Oftalmologia_Infantil': 28000,
                    'Otorrinolaringologia_Infantil': 28000,
                    'Traumatologia_Infantil': 28000,
                    'Foniatria': 19000
                },
                'salud_mental': {
                    'Psicopedagogia': 20000,
                    'Psicologia': 32000,
                    'Neuropsicologia_sesion': 20000,
                    'Test_Ados_completo': 80000,
                    'Test_Adir_completo': 60000
                },
                'estudios_cardiologicos': {
                    'Electrocardiograma': 12000,
                    'Ecocardiograma_Doppler_Color': 58000
                },
                'estudios_dermatologicos': {
                    'Curetaje_hasta_2_lesiones': 28000
                },
                'ecografias': {
                    'Ecografia_Abdominal': 45000,
                    'Ecografia_Hepatobiliar': 45000,
                    'Ecografia_Esplenica': 45000,
                    'Ecografia_Suprarrenal': 45000,
                    'Ecografia_Pancreatica': 45000,
                    'Ecografia_Ginecologica': 45000,
                    'Ecografia_Renal': 45000,
                    'Ecografia_Vias_Urinarias': 45000
                },
                'estudios_neurologicos': {
                    'Electroencefalograma_EEG': 50000,
                    'Potencial_Evocado_Auditivo_PEAT': 55000,
                    'Polisomnografia_Diurna': 60000
                },
                'otros_estudios': {
                    'Audiometria': 25000,
                    'PRUNAPE': 30000
                }
            }
        }
        
        # Guardar en Firebase
        doc_ref = self.db.collection('ballester_configuracion').document('precios_particulares')
        doc_ref.set(precios_data)
        
        logger.info("[FIREBASE_CONFIG] Precios particulares configurados")
    
    def _setup_preparaciones_estudios_collection(self):
        """Configura las preparaciones específicas para cada estudio"""
        
        logger.info("[FIREBASE_CONFIG] Configurando preparaciones de estudios")
        
        preparaciones_data = {
            'estudios_neurologicos': {
                'preparacion_comun': [
                    "El niño debe concurrir con mucho sueño, ya que el estudio se realiza mientras duerme",
                    "Recomendamos despertarlo muy temprano ese día para facilitar que se duerma durante el procedimiento",
                    "Si tiene algún objeto de apego como un muñeco o mantita que lo ayude a dormirse puede traerlo",
                    "Que concurra con hambre, de manera de alimentarlo unos minutos antes del procedimiento así se duerme",
                    "Debe tener la cabeza lavada con shampoo neutro, y no usar crema de enjuague",
                    "Traer una toalla personal para higienizar al niño"
                ],
                'estudios_aplicables': [
                    'Electroencefalograma (EEG)',
                    'Potencial Evocado Auditivo (PEAT)',
                    'Polisomnografía Diurna'
                ]
            },
            'ecografias_abdominales': {
                'tipo': 'por_edad',
                'estudios_aplicables': [
                    'Ecografía Abdominal',
                    'Ecografía Hepatobiliar', 
                    'Ecografía Esplénica',
                    'Ecografía Suprarrenal',
                    'Ecografía Pancreática'
                ],
                'preparacion_por_edad': {
                    'bebes_hasta_3_meses': {
                        'instrucciones': ["AYUNO MÍNIMO DE 3 HORAS"],
                        'edad_limite_meses': 3
                    },
                    'ninos_3_meses_a_2_anos': {
                        'instrucciones': ["AYUNO MÍNIMO DE 4 HORAS"],
                        'edad_limite_meses': 24
                    },
                    'ninos_2_anos_a_10_anos': {
                        'instrucciones': ["AYUNO MÍNIMO DE 6 HORAS"],
                        'edad_limite_anos': 10
                    },
                    'ninos_mayor_10_anos': {
                        'instrucciones': ["AYUNO MÍNIMO DE 8 HORAS"],
                        'edad_limite_anos': None
                    }
                }
            },
            'ecografia_ginecologica': {
                'tipo': 'por_edad',
                'preparacion_por_edad': {
                    'bebes': {
                        'instrucciones': ["PECHO O MAMADERA MEDIA HORA ANTES DEL ESTUDIO"],
                        'edad_limite_meses': 12
                    },
                    'ninas_hasta_3_anos': {
                        'instrucciones': [
                            "BEBER 500 ML DE LÍQUIDO SIN GAS (una botellita) 1½ HS PREVIAS AL ESTUDIO Y RETENER SI CONTROLA ESFÍNTERES",
                            "LA NIÑA DEBE ESTAR CON MUCHAS GANAS DE ORINAR"
                        ],
                        'edad_limite_anos': 3
                    },
                    'ninas_3_a_10_anos': {
                        'instrucciones': [
                            "BEBER ¾ LITRO DE LIQUIDO SIN GAS 1½ HS PREVIA AL ESTUDIO Y RETENER",
                            "LA NIÑA DEBE ESTAR CON MUCHAS GANAS DE ORINAR, CASO CONTRARIO DEBERÁ SER RECITADA OTRO DÍA"
                        ],
                        'edad_limite_anos': 10
                    },
                    'ninas_mayor_10_anos': {
                        'instrucciones': [
                            "BEBER 1 LITRO DE LIQUIDO SIN GAS 2 HS PREVIAS AL ESTUDIO Y RETENER",
                            "LA NIÑA DEBE ESTAR CON MUCHAS GANAS DE ORINAR, CASO CONTRARIO DEBERÁ SER RECITADA OTRO DÍA"
                        ],
                        'edad_limite_anos': None
                    }
                }
            },
            'ecografia_renal': {
                'tipo': 'por_edad',
                'preparacion_por_edad': {
                    'bebes': {
                        'instrucciones': ["PECHO O MAMADERA MEDIA HORA ANTES DEL ESTUDIO"],
                        'edad_limite_meses': 12
                    },
                    'ninas_hasta_3_anos': {
                        'instrucciones': [
                            "BEBER 500 ML DE LÍQUIDO SIN GAS (una botellita) 2 HS PREVIAS AL ESTUDIO Y RETENER SI CONTROLA ESFÍNTERES",
                            "LA NIÑA DEBE ESTAR CON MUCHAS GANAS DE ORINAR"
                        ],
                        'edad_limite_anos': 3
                    },
                    'ninas_3_a_10_anos': {
                        'instrucciones': [
                            "BEBER ½ LITRO DE LIQUIDO SIN GAS 1 HS PREVIA AL ESTUDIO Y RETENER",
                            "LA NIÑA DEBE ESTAR CON MUCHAS GANAS DE ORINAR, CASO CONTRARIO DEBERÁ SER RECITADA OTRO DÍA"
                        ],
                        'edad_limite_anos': 10
                    },
                    'ninas_mayor_10_anos': {
                        'instrucciones': [
                            "BEBER ¾ LITRO DE LIQUIDO SIN GAS 2 HS PREVIAS AL ESTUDIO Y RETENER",
                            "LA NIÑA DEBE ESTAR CON MUCHAS GANAS DE ORINAR, CASO CONTRARIO DEBERÁ SER RECITADA OTRO DÍA"
                        ],
                        'edad_limite_anos': None
                    }
                }
            },
            'prunape': {
                'tipo': 'especial',
                'instrucciones': [
                    "Concurrir SIN JUGUETES",
                    "SIN HAMBRE", 
                    "SIN SUEÑO",
                    "SIN HERMANITOS"
                ],
                'restriccion_edad': {
                    'minima': {'anos': 0, 'meses': 0, 'dias': 0},
                    'maxima': {'anos': 5, 'meses': 11, 'dias': 29}
                }
            }
        }
        
        # Guardar en Firebase
        doc_ref = self.db.collection('ballester_configuracion').document('preparaciones_estudios')
        doc_ref.set(preparaciones_data)
        
        logger.info("[FIREBASE_CONFIG] Preparaciones de estudios configuradas")
    
    def _setup_especialistas_collection(self):
        """Configura la colección de especialistas y horarios especiales"""
        
        logger.info("[FIREBASE_CONFIG] Configurando especialistas y reglas especiales")
        
        especialistas_data = {
            'Dr_Malacchia': {
                'nombre_completo': 'Dr. Malacchia',
                'especialidad': 'Pediatría General',
                'dias_atencion': ['lunes'],
                'reglas_especiales': {
                    'obras_sociales_sin_costo': ['PARTICULAR', 'OMINT', 'OSDE', 'PODER_JUDICIAL', 'W.HOPE'],
                    'arancel_especial_otras_obras': 22500,
                    'sistema_bloqueo': {
                        'paciente_ficticio': 'Malacchia, Carlitos',
                        'descripcion': 'Sistema para reservar horarios y evitar toma online no autorizada'
                    }
                },
                'mensaje_arancel_especial': 'Para atenderse con el Dr. Malacchia los lunes, su obra social requiere un arancel preferencial de $22.500. ¿Acepta continuar con este costo?'
            },
            'Dra_Ametller': {
                'nombre_completo': 'Dra. Ametller',
                'especialidad': 'Ecografías',
                'estudios_realizados': [
                    'Ecografía Abdominal',
                    'Ecografía Hepatobiliar',
                    'Ecografía Renal',
                    'Ecografía Ginecológica',
                    'Ecografía de Vías Urinarias'
                ],
                'reglas_especiales': {
                    'obras_requieren_bono_consulta': ['PASTELEROS', 'TELEVISION']
                }
            },
            'Dr_Travaglia': {
                'nombre_completo': 'Dr. Travaglia',
                'especialidad': 'Cardiología Infantil',
                'estudios_realizados': ['Ecocardiograma Doppler Color'],
                'reglas_especiales': {
                    'autorizacion_debe_contener': ['ecocardio', 'doppler'],
                    'nombre_correcto_autorizacion': 'Ecocardiograma doppler color'
                }
            }
        }
        
        # Guardar en Firebase
        doc_ref = self.db.collection('ballester_configuracion').document('especialistas')
        doc_ref.set(especialistas_data)
        
        logger.info("[FIREBASE_CONFIG] Especialistas configurados")
    
    def _setup_reglas_especiales_collection(self):
        """Configura reglas especiales y excepciones"""
        
        logger.info("[FIREBASE_CONFIG] Configurando reglas especiales")
        
        reglas_especiales = {
            'horarios_atencion': {
                'lunes_a_viernes': {
                    'horario_manana': {'inicio': '09:00', 'fin': '13:00'},
                    'horario_tarde': {'inicio': '14:00', 'fin': '20:00'}
                },
                'sabados_domingos': 'cerrado',
                'feriados': 'cerrado'
            },
            'telefonos_urgencia': ['4616-6870', '11-5697-5007'],
            'direccion': {
                'calle': 'Alvear 2307',
                'esquina': 'República',
                'localidad': 'Villa Ballester',
                'referencia': 'A 6 cuadras de la estación de tren de Villa Ballester',
                'codigo_postal': '1653'
            },
            'politicas_especiales': {
                'ausentismo': {
                    'limite_faltas': 2,
                    'periodo_meses': 3,
                    'mensaje_advertencia': 'Detectamos que faltaste a más de 2 turnos en los últimos 3 meses sin cancelar. Por favor, asegúrate de poder asistir a este nuevo turno.'
                },
                'autorizaciones': {
                    'texto_requerido': 'CENTRO PEDIATRICO BALLESTER',
                    'mensaje_verificacion': 'IMPORTANTE: La autorización debe estar emitida específicamente para el CENTRO PEDIATRICO BALLESTER',
                    'no_dar_turnos_sin_autorizacion': ['estudios'],
                    'excepciones_sin_autorizacion': ['consultas', 'electrocardiograma']
                }
            },
            'listas_espera': {
                'neurologia_infantil': {
                    'motivo': 'Neurólogo atiende solo 5 pacientes de obra social por día',
                    'obras_sociales': ['IOMA', 'OSDE', 'OMINT', 'PASTELEROS', 'TELEVISION'],
                    'bono_contribucion': 2500
                },
                'psicopedagogia': {
                    'motivo': 'Alta demanda del servicio',
                    'todas_obras_sociales': True
                }
            },
            'derivacion_humano': {
                'horario_derivacion': 'Lunes a viernes de 9 a 19hs',
                'mensaje_fuera_horario': 'En este momento, nuestros operadores no están disponibles. Por favor, déjenos su consulta detallada y la responderemos mañana ó el lunes a partir de las 9 hs.',
                'criterios_derivacion': [
                    'Obra social no reconocida',
                    'Plan no encontrado en OMNIA',
                    'Solicitud de recetas',
                    'Consultas complejas',
                    'Escalación por frustración'
                ]
            }
        }
        
        # Guardar en Firebase
        doc_ref = self.db.collection('ballester_configuracion').document('reglas_especiales')
        doc_ref.set(reglas_especiales)
        
        logger.info("[FIREBASE_CONFIG] Reglas especiales configuradas")
    
    def _setup_configuracion_ballester(self):
        """Configura parámetros generales del sistema Ballester"""
        
        logger.info("[FIREBASE_CONFIG] Configurando parámetros generales Ballester")
        
        config_general = {
            'sistema': {
                'nombre': 'Centro Pediátrico Ballester',
                'version_bot': 'OptiAtiende-IA V11',
                'fecha_configuracion': datetime.now().isoformat(),
                'configurado_por': 'Sistema Automático V11'
            },
            'parametros_funcionamiento': {
                'edad_maxima_pediatria': 18,
                'duracion_turno_default_minutos': 30,
                'anticipacion_minima_turnos_horas': 24,
                'buffer_mensajes_segundos': 4,
                'timeout_escalacion_minutos': 15
            },
            'integraciones': {
                'sistema_interno': 'OMNIA',
                'whatsapp_api': '360dialog',
                'ai_provider': 'OpenAI GPT-5',
                'storage': 'Firebase Firestore'
            },
            'contactos': {
                'staff_principal': 'Por configurar',
                'emergencias': ['4616-6870', '11-5697-5007'],
                'escalacion_bot': 'Por configurar'
            }
        }
        
        # Guardar en Firebase
        doc_ref = self.db.collection('ballester_configuracion').document('general')
        doc_ref.set(config_general)
        
        logger.info("[FIREBASE_CONFIG] Configuración general guardada")


# =================== FUNCIÓN PRINCIPAL DE CONFIGURACIÓN ===================

def setup_ballester_database() -> bool:
    """
    Función principal para configurar toda la base de datos de Ballester.
    
    ADVERTENCIA: Ejecutar UNA SOLA VEZ para configuración inicial.
    
    Returns:
        True si se configuró exitosamente
    """
    logger.info("[FIREBASE_CONFIG] Iniciando configuración completa de Ballester")
    
    try:
        configurator = BallesterFirebaseConfig()
        return configurator.initialize_ballester_database()
        
    except Exception as e:
        logger.error(f"[FIREBASE_CONFIG] ❌ Error en configuración completa: {e}", exc_info=True)
        return False

def verify_ballester_database() -> Dict[str, bool]:
    """
    Verifica que todas las colecciones de Ballester estén correctamente configuradas.
    
    Returns:
        Dict con estado de cada colección
    """
    logger.info("[FIREBASE_CONFIG] Verificando configuración de base de datos")
    
    db = firestore.client()
    verification_results = {}
    
    # Lista de colecciones que deben existir
    required_collections = [
        'ballester_obras_sociales',
        'ballester_servicios_medicos', 
        'ballester_configuracion'
    ]
    
    required_docs = [
        ('ballester_configuracion', 'precios_particulares'),
        ('ballester_configuracion', 'preparaciones_estudios'),
        ('ballester_configuracion', 'especialistas'),
        ('ballester_configuracion', 'reglas_especiales'),
        ('ballester_configuracion', 'general')
    ]
    
    try:
        # Verificar colecciones
        for collection in required_collections:
            try:
                docs = list(db.collection(collection).limit(1).stream())
                verification_results[f'collection_{collection}'] = len(docs) > 0
            except Exception as e:
                logger.error(f"[FIREBASE_CONFIG] Error verificando colección {collection}: {e}")
                verification_results[f'collection_{collection}'] = False
        
        # Verificar documentos específicos
        for collection, document in required_docs:
            try:
                doc = db.collection(collection).document(document).get()
                verification_results[f'doc_{collection}_{document}'] = doc.exists
            except Exception as e:
                logger.error(f"[FIREBASE_CONFIG] Error verificando documento {collection}/{document}: {e}")
                verification_results[f'doc_{collection}_{document}'] = False
        
        # Resultado general
        all_verified = all(verification_results.values())
        verification_results['all_configured'] = all_verified
        
        logger.info(f"[FIREBASE_CONFIG] Verificación completada: {all_verified}")
        return verification_results
        
    except Exception as e:
        logger.error(f"[FIREBASE_CONFIG] ❌ Error en verificación: {e}", exc_info=True)
        return {'error': True, 'message': str(e)}


# =================== UTILIDADES PARA MAIN.PY ===================

def get_ballester_config_value(config_path: str) -> Any:
    """
    Obtiene un valor de configuración específico de Ballester desde Firebase.
    
    Args:
        config_path: Ruta del config (ej: 'reglas_especiales.telefonos_urgencia')
        
    Returns:
        Valor de configuración o None si no existe
    """
    try:
        db = firestore.client()
        
        # Parsear ruta de configuración
        path_parts = config_path.split('.')
        if len(path_parts) < 2:
            return None
        
        doc_name = path_parts[0]
        field_path = '.'.join(path_parts[1:])
        
        # Consultar Firebase
        doc = db.collection('ballester_configuracion').document(doc_name).get()
        
        if doc.exists:
            data = doc.to_dict()
            
            # Navegar por el path de campos anidados
            current = data
            for field in path_parts[1:]:
                if isinstance(current, dict) and field in current:
                    current = current[field]
                else:
                    return None
            
            return current
        
        return None
        
    except Exception as e:
        logger.error(f"[FIREBASE_CONFIG] Error obteniendo configuración {config_path}: {e}")
        return None
