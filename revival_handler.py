#!/usr/bin/env python3
"""
🔄 REVIVAL HANDLER - Gestión de Revival de Conversaciones
Maneja el proceso de reactivación inteligente de conversaciones inactivas.
100% aislado del flujo principal - solo se activa vía endpoint específico.
"""

import os
import logging
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
from flask import Blueprint, request, jsonify
import traceback

# Imports locales (se importan cuando se necesiten para evitar dependencias circulares)
# from memory import get_conversations_for_revival, update_conversation_state
# from revival_agent import RevivalAgent
# from msgio_handler import send_whatsapp_message
# from memory import _clean_context_for_firestore

# Configuración de logging
logger = logging.getLogger(__name__)

# Blueprint para endpoints de revival
revival_bp = Blueprint('revival', __name__)

class RevivalHandlerError(Exception):
    """Excepción personalizada para errores del revival handler"""
    pass

class RevivalHandler:
    """Handler principal para gestión de revival de conversaciones"""
    
    def __init__(self):
        """Inicializa el handler con configuración desde variables de entorno"""
        self.enabled = os.getenv('REVIVAL_ENABLED', 'false').lower() == 'true'
        self.secret_key = os.getenv('REVIVAL_SECRET_KEY', '')
        self.max_conversations_per_cycle = int(os.getenv('REVIVAL_MAX_PER_CYCLE', '50'))
        self.dry_run = os.getenv('REVIVAL_DRY_RUN', 'false').lower() == 'true'
        
        # Configuración de prompts personalizada por cliente
        self.custom_prompt = os.getenv('REVIVAL_PROMPT', self._get_default_prompt())
        
        logger.info(f"🔄 Revival Handler inicializado - Enabled: {self.enabled}, DryRun: {self.dry_run}")

    def _get_default_prompt(self) -> str:
        """Retorna el prompt por defecto si no se especifica uno personalizado"""
        return """
        Eres un asistente inteligente de reactivación de conversaciones.
        
        Analiza esta conversación inactiva y decide si vale la pena intentar reactivarla.
        
        INSTRUCCIONES:
        1. Si decides ENVIAR mensaje: genera un mensaje personalizado y natural
        2. Si decides NO ENVIAR: etiqueta la razón (ej: DESINTERESADO, ENOJADO, RESUELTO)
        
        Responde SOLO en formato JSON:
        {
            "action": "SEND" | "IGNORE",
            "message": "Tu mensaje personalizado aquí" | null,
            "tag": null | "TU_ETIQUETA_DESCRIPTIVA",
            "confidence": 0.85,
            "reasoning": "Breve explicación de tu decisión"
        }
        """

    def _validate_secret_key(self, provided_key: str) -> bool:
        """Valida que el secret key proporcionado coincida con el configurado"""
        if not self.secret_key:
            logger.error("❌ REVIVAL_SECRET_KEY no configurado")
            return False
        
        return provided_key == self.secret_key

    def _is_conversation_eligible(self, conversation_data: Dict[str, Any]) -> bool:
        """
        Verifica si una conversación es elegible para revival
        
        Args:
            conversation_data: Datos completos de la conversación
            
        Returns:
            True si la conversación puede ser procesada para revival
        """
        state_context = conversation_data.get('state_context', {})
        
        # Ya fue procesada por revival
        if state_context.get('revival_status') is not None:
            return False
        
        # No tiene historial suficiente
        history = conversation_data.get('history', [])
        if len(history) < 1:
            return False
        
        # Verificar que no esté en estados críticos del sistema principal
        current_state = conversation_data.get('conversation_state', 'conversando')
        critical_states = [
            'AGENDA_CONFIRMANDO_TURNO',
            'AGENDA_SOLICITANDO_CANCELACION', 
            'PAGOS_PROCESANDO_PAGO',
            'PAGOS_ESPERANDO_CONFIRMACION'
        ]
        
        if current_state in critical_states:
            logger.info(f"⏸️ Conversación en estado crítico {current_state} - Skip revival")
            return False
        
        return True

    def _get_conversations_for_revival(self) -> List[Dict[str, Any]]:
        """
        Obtiene conversaciones candidatas para revival de forma segura
        
        Returns:
            Lista de conversaciones elegibles para revival
        """
        try:
            # Import aquí para evitar dependencias circulares
            from memory import get_conversations_for_revival
            
            # Obtener conversaciones sin procesar por revival
            raw_conversations = get_conversations_for_revival()
            
            # Filtrar por elegibilidad adicional
            eligible_conversations = []
            for conv_data in raw_conversations:
                if self._is_conversation_eligible(conv_data):
                    eligible_conversations.append(conv_data)
                    
                    # Limitar cantidad por ciclo para evitar sobrecarga
                    if len(eligible_conversations) >= self.max_conversations_per_cycle:
                        logger.info(f"📊 Limitando a {self.max_conversations_per_cycle} conversaciones por ciclo")
                        break
            
            logger.info(f"📊 Conversaciones elegibles para revival: {len(eligible_conversations)}")
            return eligible_conversations
            
        except ImportError as e:
            logger.error(f"❌ Error importando memory.get_conversations_for_revival: {e}")
            return []
        except Exception as e:
            logger.error(f"❌ Error obteniendo conversaciones para revival: {e}")
            return []

    def _process_single_conversation(self, conversation_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Procesa una sola conversación para revival
        
        Args:
            conversation_data: Datos completos de la conversación
            
        Returns:
            Resultado del procesamiento
        """
        phone_number = conversation_data.get('phone_number')
        
        try:
            # Import del agente aquí para evitar dependencias circulares
            from revival_agent import RevivalAgent
            
            # Inicializar agente con prompt personalizado
            agent = RevivalAgent(custom_prompt=self.custom_prompt)
            
            # Analizar conversación
            analysis_result = agent.analyze_conversation(conversation_data)
            
            # Determinar acción basada en análisis
            if analysis_result.get('action') == 'SEND_MESSAGE' and not self.dry_run:
                return self._send_revival_message(
                    conversation_data, 
                    analysis_result.get('message', ''),
                    analysis_result
                )
            else:
                return self._mark_conversation_processed(
                    conversation_data,
                    analysis_result.get('tag', 'ANALYZED_NO_ACTION'),
                    analysis_result
                )
                
        except Exception as e:
            error_msg = f"Error procesando conversación {phone_number}: {str(e)}"
            logger.error(f"❌ {error_msg}")
            return {
                'success': False,
                'phone_number': phone_number,
                'error': error_msg,
                'action': 'ERROR'
            }

    def _send_revival_message(self, conversation_data: Dict[str, Any], message: str, analysis: Dict[str, Any]) -> Dict[str, Any]:
        """
        Envía mensaje de revival y actualiza estado
        
        Args:
            conversation_data: Datos de la conversación
            message: Mensaje a enviar
            analysis: Resultado del análisis del agente
            
        Returns:
            Resultado del envío
        """
        phone_number = conversation_data.get('phone_number')
        
        try:
            if self.dry_run:
                logger.info(f"🧪 DRY_RUN: Simularía envío de mensaje a {phone_number}")
                return {
                    'success': True,
                    'phone_number': phone_number,
                    'action': 'SEND_SIMULATED',
                    'message': message,
                    'dry_run': True
                }
            
            # Import aquí para evitar dependencias circulares
            from msgio_handler import send_whatsapp_message
            
            # Enviar mensaje por WhatsApp
            send_result = send_whatsapp_message(phone_number, message)
            
            # send_whatsapp_message devuelve boolean, no diccionario
            if send_result:
                # Marcar como mensaje enviado
                self._update_conversation_revival_status(
                    phone_number,
                    'ATTEMPTED',
                    {
                        'message_sent': True,
                        'message_content': message,
                        'analysis': analysis,
                        'timestamp': datetime.now(timezone.utc).isoformat()
                    }
                )
                
                # Registrar mensaje en historial para que aparezca en Chatwoot
                from memory import add_to_conversation_history
                add_to_conversation_history(
                    phone_number=phone_number,
                    role='assistant',
                    sender_name='RODI',
                    content=message
                )
                
                # Registrar en Chatwoot usando la función oficial del sistema
                try:
                    # Import de la función oficial que usa el sistema normal
                    from chatwoot_integration import log_to_chatwoot
                    
                    # Limpiar número de teléfono (quitar prefijos)
                    phone_clean = phone_number.replace('+', '').replace(' ', '').replace('-', '')
                    
                    # Usar la función oficial del sistema con formato de revival
                    success = log_to_chatwoot(
                        phone=phone_clean,
                        user_message="",  # No hay mensaje del usuario
                        bot_response=f"[REVIVAL] {message}",  # Mensaje del bot marcado como revival
                        sender_name="Sistema Revival"
                    )
                    
                    if success:
                        logger.info(f"📨 Mensaje de revival registrado en Chatwoot exitosamente")
                    else:
                        logger.warning(f"⚠️ No se pudo registrar mensaje de revival en Chatwoot")
                    
                except Exception as e:
                    logger.warning(f"⚠️ Error registrando en Chatwoot: {e}")
                    # No es crítico si falla, el mensaje ya está en historial
                
                logger.info(f"✅ Mensaje de revival enviado a {phone_number}")
                return {
                    'success': True,
                    'phone_number': phone_number,
                    'action': 'SEND',
                    'message': message,
                    'send_result': send_result
                }
            else:
                raise RevivalHandlerError(f"Error enviando mensaje: {send_result}")
                
        except Exception as e:
            logger.error(f"❌ Error enviando mensaje de revival a {phone_number}: {e}")
            return {
                'success': False,
                'phone_number': phone_number,
                'action': 'SEND_FAILED',
                'error': str(e)
            }

    def _mark_conversation_processed(self, conversation_data: Dict[str, Any], tag: str, analysis: Dict[str, Any]) -> Dict[str, Any]:
        """
        Marca conversación como procesada sin enviar mensaje
        
        Args:
            conversation_data: Datos de la conversación
            tag: Etiqueta de clasificación
            analysis: Resultado del análisis
            
        Returns:
            Resultado del marcado
        """
        phone_number = conversation_data.get('phone_number')
        
        try:
            self._update_conversation_revival_status(
                phone_number,
                tag,
                {
                    'message_sent': False,
                    'analysis': analysis,
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }
            )
            
            logger.info(f"🏷️ Conversación {phone_number} marcada como: {tag}")
            return {
                'success': True,
                'phone_number': phone_number,
                'action': 'TAGGED',
                'tag': tag
            }
            
        except Exception as e:
            logger.error(f"❌ Error marcando conversación {phone_number}: {e}")
            return {
                'success': False,
                'phone_number': phone_number,
                'action': 'TAG_FAILED',
                'error': str(e)
            }

    def _update_conversation_revival_status(self, phone_number: str, status: str, metadata: Dict[str, Any]):
        """
        Actualiza el estado de revival de una conversación en Firestore
        
        Args:
            phone_number: Número de teléfono de la conversación
            status: Nuevo estado de revival
            metadata: Metadatos adicionales
        """
        try:
            # Import aquí para evitar dependencias circulares
            from memory import get_conversation_data, update_conversation_state, _clean_context_for_firestore
            
            # Obtener datos actuales (get_conversation_data devuelve tupla: history, timestamp, state, context)
            history, timestamp, current_state, current_context = get_conversation_data(phone_number)
            current_context = current_context or {}
            
            # Actualizar contexto con datos de revival
            current_context['revival_status'] = status
            current_context['revival_timestamp'] = metadata.get('timestamp')
            current_context['revival_metadata'] = metadata
            
            # Limpiar y actualizar en Firestore
            clean_context = _clean_context_for_firestore(current_context)
            
            update_conversation_state(phone_number, current_state, clean_context)
            
        except Exception as e:
            logger.error(f"❌ Error actualizando estado revival para {phone_number}: {e}")
            raise

    def process_revival_cycle(self) -> Dict[str, Any]:
        """
        Ejecuta un ciclo completo de revival para todas las conversaciones elegibles
        
        Returns:
            Resumen del ciclo ejecutado
        """
        if not self.enabled:
            return {
                'success': False,
                'message': 'Revival no habilitado',
                'enabled': False
            }
        
        cycle_start = datetime.now(timezone.utc)
        logger.info(f"🚀 Iniciando ciclo de revival - {cycle_start.isoformat()}")
        
        try:
            # Obtener conversaciones elegibles
            conversations = self._get_conversations_for_revival()
            
            if not conversations:
                logger.info("📭 No hay conversaciones elegibles para revival")
                return {
                    'success': True,
                    'message': 'No hay conversaciones elegibles',
                    'conversations_processed': 0,
                    'timestamp': cycle_start.isoformat()
                }
            
            # Procesar cada conversación
            results = []
            sent_count = 0
            tagged_count = 0
            error_count = 0
            
            for conversation in conversations:
                result = self._process_single_conversation(conversation)
                results.append(result)
                
                # Contar resultados
                if result.get('success'):
                    action = result.get('action', '')
                    if action in ['SEND', 'SEND_SIMULATED']:
                        sent_count += 1
                    elif action == 'TAGGED':
                        tagged_count += 1
                else:
                    error_count += 1
            
            cycle_end = datetime.now(timezone.utc)
            duration = (cycle_end - cycle_start).total_seconds()
            
            summary = {
                'success': True,
                'cycle_start': cycle_start.isoformat(),
                'cycle_end': cycle_end.isoformat(),
                'duration_seconds': duration,
                'conversations_processed': len(conversations),
                'messages_sent': sent_count,
                'conversations_tagged': tagged_count,
                'errors': error_count,
                'dry_run': self.dry_run,
                'results': results
            }
            
            logger.info(f"📊 Ciclo revival completado: {sent_count} mensajes, {tagged_count} etiquetadas, {error_count} errores en {duration:.2f}s")
            
            return summary
            
        except Exception as e:
            error_msg = f"Error en ciclo de revival: {str(e)}"
            logger.error(f"❌ {error_msg}")
            logger.error(traceback.format_exc())
            
            return {
                'success': False,
                'error': error_msg,
                'timestamp': cycle_start.isoformat()
            }

# =============================================================================
# ENDPOINTS DE REVIVAL
# =============================================================================

@revival_bp.route('/api/revival/process', methods=['POST'])
def process_revival():
    """
    Endpoint principal para procesar revival de conversaciones
    Llamado por el cron service cada 6 horas
    """
    try:
        # Validar secret key
        provided_secret = request.headers.get('X-Revival-Secret', '')
        
        if not provided_secret:
            logger.warning("⚠️ Intento de acceso sin secret key")
            return jsonify({
                'success': False,
                'error': 'Missing X-Revival-Secret header'
            }), 401
        
        handler = RevivalHandler()
        
        if not handler._validate_secret_key(provided_secret):
            logger.warning(f"⚠️ Intento de acceso con secret key inválido")
            return jsonify({
                'success': False,
                'error': 'Invalid secret key'
            }), 403
        
        # Procesar ciclo de revival
        result = handler.process_revival_cycle()
        
        # Determinar código de respuesta HTTP
        status_code = 200 if result.get('success') else 500
        
        return jsonify(result), status_code
        
    except Exception as e:
        error_msg = f"Error crítico en endpoint revival: {str(e)}"
        logger.error(f"💥 {error_msg}")
        logger.error(traceback.format_exc())
        
        return jsonify({
            'success': False,
            'error': error_msg,
            'timestamp': datetime.now(timezone.utc).isoformat()
        }), 500

@revival_bp.route('/api/revival/status', methods=['GET'])
def revival_status():
    """
    Endpoint para verificar estado del sistema de revival
    Útil para monitoreo y debugging
    """
    try:
        handler = RevivalHandler()
        
        # Información básica del sistema
        status_info = {
            'enabled': handler.enabled,
            'dry_run': handler.dry_run,
            'max_per_cycle': handler.max_conversations_per_cycle,
            'has_secret_key': bool(handler.secret_key),
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
        
        # Si está habilitado, obtener estadísticas adicionales
        if handler.enabled:
            try:
                conversations = handler._get_conversations_for_revival()
                status_info['eligible_conversations'] = len(conversations)
            except Exception as e:
                status_info['eligible_conversations'] = f"Error: {str(e)}"
        
        return jsonify({
            'success': True,
            'status': status_info
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'timestamp': datetime.now(timezone.utc).isoformat()
        }), 500

# =============================================================================
# UTILIDADES
# =============================================================================

def register_revival_blueprint(app):
    """
    Registra el blueprint de revival en la aplicación Flask
    
    Args:
        app: Instancia de Flask app
    """
    try:
        app.register_blueprint(revival_bp)
        logger.info("✅ Revival blueprint registrado exitosamente")
    except Exception as e:
        logger.error(f"❌ Error registrando revival blueprint: {e}")
        raise
