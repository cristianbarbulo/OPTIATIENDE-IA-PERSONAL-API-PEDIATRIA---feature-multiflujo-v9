#!/usr/bin/env python3
"""
🤖 REVIVAL AGENT - Agente IA para Análisis de Conversaciones
Utiliza GPT-4 para analizar conversaciones inactivas y decidir estrategias de revival.
Sistema económico y preciso para reactivación inteligente.
"""

import os
import json
import logging
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
import traceback

# Import de OpenAI (se debe instalar: pip install openai)
try:
    import openai
except ImportError:
    openai = None
    logging.warning("⚠️ OpenAI no instalado - Revival Agent no funcionará")

# Configuración de logging
logger = logging.getLogger(__name__)

class RevivalAgentError(Exception):
    """Excepción personalizada para errores del Revival Agent"""
    pass

class RevivalAgent:
    """
    Agente IA especializado en análisis de conversaciones para revival
    Utiliza GPT-4 para decisiones inteligentes y contextualmente apropiadas
    """
    
    def __init__(self, custom_prompt: Optional[str] = None):
        """
        Inicializa el Revival Agent con configuración OpenAI
        
        Args:
            custom_prompt: Prompt personalizado por cliente (opcional)
        """
        # Configuración de OpenAI
        self.api_key = os.getenv('OPENAI_API_KEY', '')
        self.organization = os.getenv('OPENAI_ORG_ID', '')
        self.model = os.getenv('REVIVAL_AI_MODEL', 'gpt-5-nano')  # Más económico que gpt-5
        
        # Configuración hardcodeada para eficiencia y economía (según README)
        # No usar max_tokens ni temperature - GPT-5 tiene configuración fija
        
        # Prompt personalizado o por defecto
        self.system_prompt = custom_prompt or self._get_default_system_prompt()
        
        # Validar configuración
        if not openai:
            raise RevivalAgentError("OpenAI no está instalado")
        
        if not self.api_key:
            raise RevivalAgentError("OPENAI_API_KEY no configurado")
        
        # Configurar cliente OpenAI (nueva API v1.0+ con Responses API para GPT-5)
        self.client = openai.OpenAI(
            api_key=self.api_key,
            organization=self.organization
        )
        
        logger.info(f"🤖 Revival Agent inicializado - Modelo: {self.model}")

    def _get_default_system_prompt(self) -> str:
        """Retorna el prompt de sistema por defecto para el agente"""
        return """
        Eres un asistente experto en reactivación de conversaciones de negocio.
        
        Tu trabajo es analizar conversaciones inactivas y decidir la mejor estrategia:
        
        ANALIZA:
        - Contexto de la conversación
        - Último mensaje del cliente
        - Estado emocional aparente
        - Potencial comercial
        - Tiempo de inactividad
        
        DECIDE:
        1. SEND: Si vale la pena reactivar con un mensaje personalizado
        2. IGNORE: Si es mejor no molestar al cliente
        
        REGLAS:
        - Sé empático y natural
        - No seas invasivo con clientes claramente molestos
        - Personaliza mensajes con información específica de su conversación
        - Usa un tono profesional pero cálido
        - Considera el contexto cultural argentino
        
        RESPONDE SIEMPRE EN FORMATO JSON VÁLIDO:
        {
            "action": "SEND" | "IGNORE",
            "message": "Tu mensaje personalizado aquí" | null,
            "tag": null | "ETIQUETA_DESCRIPTIVA",
            "confidence": 0.85,
            "reasoning": "Explicación breve de tu decisión"
        }
        """

    def _prepare_conversation_context(self, conversation_data: Dict[str, Any]) -> str:
        """
        Prepara el contexto de la conversación para el análisis del agente
        
        Args:
            conversation_data: Datos completos de la conversación
            
        Returns:
            String formateado con el contexto para el agente
        """
        try:
            phone_number = conversation_data.get('phone_number', 'Desconocido')
            state_context = conversation_data.get('state_context', {})
            history = conversation_data.get('history', [])
            conversation_state = conversation_data.get('conversation_state', 'conversando')
            
            # Información del cliente
            contact_info = state_context.get('contact_info', {})
            sender_name = contact_info.get('name') or conversation_data.get('senderName', 'Cliente')
            
            # Último mensaje y timestamp
            last_message = ''
            last_timestamp = None
            if history:
                # Buscar último mensaje del usuario (no del asistente)
                for entry in reversed(history):
                    if entry.get('role') == 'user':
                        last_message = entry.get('content', '')
                        last_timestamp = entry.get('timestamp', '')
                        break
            
            # Información de agendamiento si existe
            turno_info = ''
            if state_context.get('turno_confirmado'):
                turno_data = state_context.get('turno_confirmado', {})
                turno_info = f"\n- Turno confirmado: {turno_data.get('fecha_formateada', 'Fecha no disponible')}"
            
            # Información de pagos si existe
            payment_info = ''
            if state_context.get('payment_verified'):
                payment_amount = state_context.get('payment_amount', 'N/A')
                payment_info = f"\n- Pago verificado: ${payment_amount}"
            
            # Construir contexto completo
            context = f"""
INFORMACIÓN DE LA CONVERSACIÓN:
- Teléfono: {phone_number}
- Nombre: {sender_name}
- Estado actual: {conversation_state}
- Último mensaje del cliente: "{last_message}"
- Timestamp último mensaje: {last_timestamp}
{turno_info}
{payment_info}

HISTORIAL RECIENTE (últimos 5 mensajes):
"""
            
            # Agregar últimos mensajes del historial
            recent_history = history[-10:] if len(history) > 10 else history
            for i, entry in enumerate(recent_history, 1):
                role = "Cliente" if entry.get('role') == 'user' else "Asistente"
                content = entry.get('content', '')[:200]  # Limitar largo
                timestamp = entry.get('timestamp', '')
                context += f"{i}. [{role}] {content}\n"
            
            context += f"""
CONTEXTO ADICIONAL:
- Total mensajes en historial: {len(history)}
- Información de contacto completa: {contact_info}
- Estado del contexto: {json.dumps(state_context, indent=2, ensure_ascii=False)}
"""
            
            return context
            
        except Exception as e:
            logger.error(f"❌ Error preparando contexto de conversación: {e}")
            return f"Error preparando contexto: {str(e)}"

    def _call_openai_api(self, conversation_context: str) -> Dict[str, Any]:
        """
        Realiza llamada a la API de OpenAI para análisis de conversación
        
        Args:
            conversation_context: Contexto preparado de la conversación
            
        Returns:
            Respuesta parseada del agente IA
        """
        try:
                        # Construir prompt completo para Responses API
            full_prompt = f"""INSTRUCCIONES DEL SISTEMA:
{self.system_prompt}

CONVERSACIÓN A ANALIZAR:
{conversation_context}

FORMATO DE RESPUESTA REQUERIDO:
Responde ÚNICAMENTE con un objeto JSON válido que contenga:
{{
    "action": "SEND_MESSAGE|TAG_ONLY",
    "message": "mensaje de revival si action=SEND_MESSAGE",
    "tag": "etiqueta descriptiva",
    "confidence": 0.85,
    "reasoning": "explicación breve"
}}"""
            
            logger.info(f"🤖 Enviando análisis a OpenAI - Modelo: {self.model}")
            
            # Usar Responses API para GPT-5-NANO (según README)
            response = self.client.responses.create(
                model=self.model,
                input=[{
                    "type": "message",
                    "role": "user", 
                    "content": full_prompt
                }],
                reasoning={"effort": "low"},  # Economizar en reasoning para costo
                text={"verbosity": "low"}     # Configuración económica y eficiente
            )
            
            # Extraer contenido de la respuesta
            content = response.output_text.strip()
            
            # Parsear JSON
            try:
                result = json.loads(content)
                logger.info(f"✅ Análisis completado - Acción: {result.get('action', 'UNKNOWN')}")
                return result
            except json.JSONDecodeError as e:
                logger.error(f"❌ Error parseando respuesta JSON de OpenAI: {e}")
                logger.error(f"Contenido recibido: {content}")
                
                # Respuesta de fallback
                return {
                    "action": "IGNORE",
                    "message": None,
                    "tag": "JSON_PARSE_ERROR",
                    "confidence": 0.0,
                    "reasoning": f"Error parseando respuesta de IA: {str(e)}"
                }
                
        except Exception as e:
            logger.error(f"❌ Error en llamada a OpenAI API: {e}")
            logger.error(traceback.format_exc())
            
            # Respuesta de fallback en caso de error
            return {
                "action": "IGNORE",
                "message": None,
                "tag": "API_ERROR",
                "confidence": 0.0,
                "reasoning": f"Error técnico en análisis IA: {str(e)}"
            }

    def _validate_ai_response(self, ai_response: Dict[str, Any]) -> Dict[str, Any]:
        """
        Valida y sanitiza la respuesta del agente IA
        
        Args:
            ai_response: Respuesta cruda del agente IA
            
        Returns:
            Respuesta validada y sanitizada
        """
        try:
            # Validar campos requeridos
            action = ai_response.get('action', '').upper()
            if action not in ['SEND_MESSAGE', 'IGNORE', 'TAG_ONLY']:
                logger.warning(f"⚠️ Acción inválida del AI: {action}, forzando IGNORE")
                action = 'IGNORE'
            
            # Validar mensaje si la acción es SEND_MESSAGE
            message = ai_response.get('message', '')
            if action == 'SEND_MESSAGE':
                if not message or len(message.strip()) < 10:
                    logger.warning("⚠️ Mensaje de revival muy corto o vacío, cambiando a IGNORE")
                    action = 'IGNORE'
                    message = None
                elif len(message) > 1000:
                    logger.warning("⚠️ Mensaje de revival muy largo, truncando")
                    message = message[:1000] + "..."
            else:
                message = None
            
            # Validar etiqueta
            tag = ai_response.get('tag', '').upper() if action == 'IGNORE' else None
            if action == 'IGNORE' and not tag:
                tag = 'NO_TAG_PROVIDED'
            
            # Validar confianza
            confidence = float(ai_response.get('confidence', 0.5))
            confidence = max(0.0, min(1.0, confidence))  # Clamp entre 0 y 1
            
            # Sanitizar reasoning
            reasoning = str(ai_response.get('reasoning', 'Sin explicación'))[:500]
            
            validated_response = {
                'action': action,
                'message': message,
                'tag': tag,
                'confidence': confidence,
                'reasoning': reasoning,
                'original_response': ai_response  # Para debugging
            }
            
            return validated_response
            
        except Exception as e:
            logger.error(f"❌ Error validando respuesta de IA: {e}")
            return {
                'action': 'IGNORE',
                'message': None,
                'tag': 'VALIDATION_ERROR',
                'confidence': 0.0,
                'reasoning': f'Error en validación: {str(e)}'
            }

    def analyze_conversation(self, conversation_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analiza una conversación completa y decide estrategia de revival
        
        Args:
            conversation_data: Datos completos de la conversación desde Firestore
            
        Returns:
            Decisión estructurada del agente sobre cómo proceder
        """
        phone_number = conversation_data.get('phone_number', 'Unknown')
        
        try:
            logger.info(f"🔍 Analizando conversación para revival: {phone_number}")
            
            # Preparar contexto para el agente IA
            conversation_context = self._prepare_conversation_context(conversation_data)
            
            # Llamar a OpenAI para análisis
            ai_response = self._call_openai_api(conversation_context)
            
            # Validar y sanitizar respuesta
            validated_response = self._validate_ai_response(ai_response)
            
            # Agregar metadatos de procesamiento
            validated_response.update({
                'processed_at': datetime.now(timezone.utc).isoformat(),
                'phone_number': phone_number,
                'model_used': self.model,
                'agent_version': '1.0'
            })
            
            action = validated_response.get('action')
            confidence = validated_response.get('confidence', 0)
            
            logger.info(f"📊 Análisis completado para {phone_number}: {action} (confianza: {confidence:.2f})")
            
            return validated_response
            
        except Exception as e:
            error_msg = f"Error crítico analizando conversación {phone_number}: {str(e)}"
            logger.error(f"💥 {error_msg}")
            logger.error(traceback.format_exc())
            
            # Respuesta de emergencia
            return {
                'action': 'IGNORE',
                'message': None,
                'tag': 'CRITICAL_ERROR',
                'confidence': 0.0,
                'reasoning': error_msg,
                'error': True,
                'processed_at': datetime.now(timezone.utc).isoformat(),
                'phone_number': phone_number
            }

    def get_agent_stats(self) -> Dict[str, Any]:
        """
        Retorna estadísticas y configuración del agente
        Útil para monitoreo y debugging
        
        Returns:
            Diccionario con información del agente
        """
        return {
            'model': self.model,
            'max_tokens': self.max_tokens,
            'temperature': self.temperature,
            'has_api_key': bool(self.api_key),
            'has_organization': bool(self.organization),
            'system_prompt_length': len(self.system_prompt),
            'agent_version': '1.0',
            'openai_available': openai is not None
        }

# =============================================================================
# UTILIDADES Y FUNCIONES AUXILIARES
# =============================================================================

def test_revival_agent(test_conversation_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Función de testing para validar funcionamiento del Revival Agent
    
    Args:
        test_conversation_data: Datos de conversación de prueba (opcional)
        
    Returns:
        Resultado del test
    """
    try:
        # Crear conversación de prueba si no se proporciona
        if not test_conversation_data:
            test_conversation_data = {
                'phone_number': '1234567890',
                'senderName': 'Cliente Test',
                'conversation_state': 'conversando',
                'state_context': {
                    'contact_info': {'name': 'Juan Pérez'},
                    'last_interaction': datetime.now(timezone.utc).isoformat()
                },
                'history': [
                    {
                        'role': 'user',
                        'content': 'Hola, quería consultar sobre sus servicios',
                        'timestamp': '2024-01-01T10:00:00Z'
                    },
                    {
                        'role': 'assistant', 
                        'content': 'Hola Juan! Te ayudo con gusto. ¿Qué servicio te interesa?',
                        'timestamp': '2024-01-01T10:01:00Z'
                    },
                    {
                        'role': 'user',
                        'content': 'Necesito información sobre precios',
                        'timestamp': '2024-01-01T10:02:00Z'
                    }
                ]
            }
        
        # Inicializar agente
        agent = RevivalAgent()
        
        # Analizar conversación de prueba
        result = agent.analyze_conversation(test_conversation_data)
        
        return {
            'success': True,
            'agent_stats': agent.get_agent_stats(),
            'analysis_result': result,
            'test_conversation': test_conversation_data
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'traceback': traceback.format_exc()
        }

if __name__ == "__main__":
    """Permite ejecutar tests directos del agente"""
    print("🤖 Testing Revival Agent...")
    
    result = test_revival_agent()
    
    if result['success']:
        print("✅ Test exitoso!")
        print(f"Acción recomendada: {result['analysis_result']['action']}")
        print(f"Confianza: {result['analysis_result']['confidence']}")
        print(f"Reasoning: {result['analysis_result']['reasoning']}")
    else:
        print("❌ Test falló!")
        print(f"Error: {result['error']}")
