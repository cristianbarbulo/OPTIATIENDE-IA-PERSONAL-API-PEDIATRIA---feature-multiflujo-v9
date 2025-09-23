"""Delegates payment actions to the configured payment service."""
import logging
import config
from service_factory import get_payment_service
import utils
import llm_handler
import memory
import copy
import json
from datetime import datetime
import re
import agendamiento_handler
import msgio_handler
from utils import limpiar_contexto_pagos_unificado


def detectar_proveedor_pago(mensaje_usuario: str) -> str:
    mensaje = mensaje_usuario.lower()
    if "modo" in mensaje and "MODO" in config.PAYMENT_PROVIDERS:
        return "MODO"
    elif "paypal" in mensaje and "PAYPAL" in config.PAYMENT_PROVIDERS:
        return "PAYPAL"
    elif "mercado" in mensaje and "MERCADOPAGO" in config.PAYMENT_PROVIDERS:
        return "MERCADOPAGO"
    else:
        return config.PAYMENT_PROVIDERS[0] if config.PAYMENT_PROVIDERS else "MERCADOPAGO"

logger = logging.getLogger(config.TENANT_NAME)


def asegurar_author(context, detalles, history=None):
    from pago_handler import is_valid_doc_id  # Importación segura para evitar ciclos
    logger = logging.getLogger(config.TENANT_NAME)
    detalles = copy.deepcopy(detalles) if detalles else {}
    context = copy.deepcopy(context) if context else {}
    author = None
    if 'author' in detalles and is_valid_doc_id(detalles['author']):
        author = detalles['author']
        context['author'] = author
    elif context and 'author' in context and is_valid_doc_id(context['author']):
        author = context['author']
        detalles['author'] = author
    elif history and isinstance(history, list):
        for msg in reversed(history):
            if isinstance(msg, dict) and 'author' in msg and is_valid_doc_id(msg['author']):
                author = msg['author']
                detalles['author'] = author
                context['author'] = author
                break
    if not author:
        detalles['author'] = ''
        context['author'] = ''
        logger.critical(f"[AUTHOR] No se pudo encontrar un author válido en asegurar_author. detalles={detalles}, context={context}, history={history}")
    return context, detalles


def iniciar_pago_simplificado(history, detalles, state_context=None, mensaje_completo_usuario=None):
    """
    SIMPLIFICADO: Flujo de pagos simplificado usando el nuevo flujo unificado.
    NUEVA IMPLEMENTACIÓN: Usa el flujo unificado en lugar del flujo anterior.
    """
    logger.info(f"[PAGO_SIMPLIFICADO] Iniciando pago con Plan de Flujo Unificado")
    
    # Redirigir al nuevo flujo unificado
    return iniciar_triage_pagos(history, detalles, state_context, mensaje_completo_usuario)


# ELIMINADAS: Funciones viejas que ya no se usan en el flujo unificado
# _mostrar_opciones_servicio, _procesar_seleccion_servicio, _mostrar_proveedores_pago,
# _procesar_seleccion_proveedor, _preguntar_verificar_pago, _mostrar_opciones_pago,
# _reanudar_flujo_pago, _manejar_interrupcion_pago, _detectar_pregunta_en_flujo_pago,
# _procesar_confirmacion_pago, _contiene_imagen, iniciar_pago, registrar_link_pago_enviado,
# verificar_pago_registrado, informar_servicio, reanudar_flujo_anterior


def _reanudar_flujo_pago(history, detalles, state_context, mensaje_usuario):
    """
    Reanuda el flujo de pago después de que el cliente hizo una pregunta
    """
    author = detalles.get('author', '')
    plan = state_context.get('plan', '')
    estado_anterior = state_context.get('estado_anterior', 'seleccionando_proveedor_pago')
    
    # MEJORA CRÍTICA: Cargar servicios_disponibles desde config si no están en state_context
    servicios_disponibles = state_context.get('servicios_disponibles', {})
    if not servicios_disponibles:
        try:
            precios = json.loads(config.SERVICE_PRICES_JSON)
            servicios_disponibles = precios
            logger.info(f"Servicios cargados desde SERVICE_PRICES_JSON en reanudación: {list(servicios_disponibles.keys())}")
        except Exception as e:
            logger.error(f"Error al cargar servicios en reanudación: {e}")
            servicios_disponibles = {}
    
    # Determinar desde dónde reanudar
    if estado_anterior == 'seleccionando_servicio':
        # Reanudar mostrando las opciones de servicios
        return mostrar_servicios_pago(history, detalles, state_context)
    elif estado_anterior == 'seleccionando_proveedor_pago':
        # Reanudar mostrando opciones (flujo simplificado: volvemos a listar servicios)
        return mostrar_servicios_pago(history, detalles, state_context)
    elif estado_anterior == 'esperando_confirmacion':
        # Reanudar esperando confirmación
        return _procesar_confirmacion_pago(history, detalles, state_context, mensaje_usuario)
    else:
        # Fallback: mostrar opciones de pago
        return mostrar_servicios_pago(history, detalles, state_context)


def _manejar_interrupcion_pago(history, detalles, state_context, mensaje_usuario):
    """
    Maneja cuando el cliente hace una pregunta durante el flujo de pago
    Guarda el estado actual para poder reanudar después
    """
    author = detalles.get('author', '')
    estado_actual = state_context.get('estado_pago', '')
    
    # Guardar estado para reanudación
    contexto_guardar = detalles.copy()
    contexto_guardar.update({
        'estado_pago': 'reanudando_pago',
        'estado_anterior': estado_actual,
        'plan': state_context.get('plan', ''),
        'proveedor_seleccionado': state_context.get('proveedor_seleccionado', ''),
        'link_pago': state_context.get('link_pago', ''),
        'opciones_disponibles': state_context.get('opciones_disponibles', [])
    })
    
    if is_valid_doc_id(author):
        memory.update_conversation_state(author, 'preguntando', contexto_guardar)
    
    # Mensaje para el cliente
    mensaje = "**Perfecto, te ayudo con tu pregunta.**\n\n"
    mensaje += "Una vez que resolvamos tu consulta, podremos continuar con el proceso de pago desde donde lo dejamos.\n\n"
    mensaje += "¿En qué puedo ayudarte?"
    
    return mensaje, contexto_guardar


def _detectar_pregunta_en_flujo_pago(mensaje_usuario, state_context):
    """
    Detecta si el mensaje del usuario es una pregunta durante el flujo de pago
    """
    if not state_context or not state_context.get('estado_pago'):
        return False
    
    # Si estamos en un estado de pago activo
    estado_pago = state_context.get('estado_pago')
    if estado_pago in ['seleccionando_servicio', 'seleccionando_proveedor_pago', 'esperando_confirmacion']:
        mensaje_lower = mensaje_usuario.lower()
        
        # Palabras clave que indican una pregunta
        palabras_pregunta = [
            'qué', 'cómo', 'cuándo', 'dónde', 'por qué', 'cuál', 'quién',
            'pregunta', 'duda', 'ayuda', 'información', 'explicar', 'entender',
            'significa', 'funciona', 'cuesta', 'precio', 'tiempo', 'duración',
            'seguro', 'confiable', 'garantía', 'devolución', 'cancelar'
        ]
        
        # Verificar si contiene palabras de pregunta
        if any(palabra in mensaje_lower for palabra in palabras_pregunta):
            return True
        
        # Verificar si termina con signo de interrogación
        if '?' in mensaje_usuario:
            return True
        
        # Verificar si no es un número (cuando estamos esperando selección)
        if estado_pago in ['seleccionando_servicio', 'seleccionando_proveedor_pago']:
            try:
                int(mensaje_usuario.strip())
                return False  # Es un número, no una pregunta
            except ValueError:
                return True  # No es un número, probablemente es una pregunta
    
    return False


def _procesar_confirmacion_pago(history, detalles, state_context, mensaje_usuario):
    """SIMPLIFICADO: Procesa la confirmación de pago mediante imagen del comprobante"""
    
    # SIMPLIFICADO: Usar la función confirmar_pago simplificada
    return confirmar_pago(history, detalles, state_context, mensaje_usuario)


def _contiene_imagen(mensaje_usuario, history):
    """
    Verifica si el mensaje contiene una imagen con comprobante de pago.
    MEJORADA: Detección más robusta de comprobantes de pago.
    """
    # Buscar en el mensaje actual y en el historial reciente
    mensajes_a_revisar = [mensaje_usuario] + [msg.get('content', '') for msg in history[-3:] if isinstance(msg, dict)]
    
    for mensaje in mensajes_a_revisar:
        if isinstance(mensaje, str):
            mensaje_lower = mensaje.lower()
            
            # Indicadores directos de imagen
            if any(indicator in mensaje_lower for indicator in ['imagen', 'foto', 'captura', 'comprobante', 'recibo', 'factura', 'ticket']):
                return True
            
            # URLs de imagen
            if any(ext in mensaje_lower for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']):
                return True
            
            # Descripción de imagen con comprobante de pago
            if '[descripción de imagen]' in mensaje_lower or '[imagen_analizada]' in mensaje_lower:
                # Buscar palabras clave específicas de comprobante de pago
                palabras_clave_pago = [
                    'comprobante', 'pago', 'total', 'transacción', 'mercadopago', 'recibo', 'factura',
                    'ticket', 'transferencia', 'depósito', 'abono', 'monto', 'importe', 'precio',
                    'payment', 'receipt', 'transaction', 'amount', 'total', 'paid'
                ]
                if any(palabra in mensaje_lower for palabra in palabras_clave_pago):
                    logger.info(f"[CONTENER_IMAGEN] Comprobante de pago detectado en descripción de imagen")
                    return True
            
            # Verificar si hay información de pago en el mensaje
            if any(palabra in mensaje_lower for palabra in ['$', 'pesos', 'dólares', 'total', 'monto', 'precio']):
                # Si hay información de monto, es probable que sea un comprobante
                if any(palabra in mensaje_lower for palabra in ['comprobante', 'pago', 'recibo', 'factura']):
                    logger.info(f"[CONTENER_IMAGEN] Comprobante de pago detectado con información de monto")
                    return True
    
    return False


def iniciar_pago(history, detalles, state_context=None, mensaje_completo_usuario=None):
    """Inicia el proceso de pago, validando datos y generando el link o pidiendo lo que falta."""
    if detalles is None:
        detalles = {}
    context, detalles = asegurar_author(detalles.copy() if detalles else {}, detalles, history)
    provider = detalles.get('proveedor') or detalles.get('proveedor_pago') or ''
    plan = detalles.get('plan', '')
    monto = detalles.get('monto', '')
    mensaje_usuario = detalles.get('mensaje_usuario', '') or mensaje_completo_usuario or ''
    author = detalles.get('author', '')
    
    # MEJORA: Detectar si el usuario está pidiendo el link sin especificar plan
    mensaje_lower = mensaje_usuario.lower()
    if any(palabra in mensaje_lower for palabra in ["link", "pago", "pagar", "abonar"]) and not plan:
        # El usuario está pidiendo el link pero no especificó el plan
        instruccion = (
            "Entiendo que quieres el link de pago. Para generarlo necesito saber qué servicio o plan deseas abonar. "
            "¿Podrías indicarme cuál de estos servicios te interesa?\n\n"
            "• Consultita\n"
            "• Asesoramiento Individual\n"
            "• Plan Básico\n"
            "• Plan Premium\n\n"
            "O si tienes otro servicio en mente, dímelo y te genero el link correspondiente."
        )
        # CORRECCIÓN CRÍTICA: Usar función helper para context_info completo
        import main
        context_info_base = {
            "intencion": "pagar",
            "estado_pago": "faltan_datos",
            "plan": "",
            "monto": "",
            "proveedor": provider or "MERCADOPAGO"
        }
        user_message = {"role": "user", "content": mensaje_usuario}
        history_with_current = history + [user_message]
        context_info = main._construir_context_info_completo(context_info_base, state_context, mensaje_usuario, "pagar", author)
        mensaje = main._llamar_agente_cero_directo(history_with_current, context_info)
        contexto_guardar = detalles.copy()
        contexto_guardar.update({
            'plan': '',
            'monto': '',
            'proveedor': provider or 'MERCADOPAGO'
        })
        if is_valid_doc_id(author):
            memory.update_conversation_state(author, 'esperando_confirmacion_pago', contexto_guardar)
        else:
            logger.critical(f"[MEMORY] No se puede actualizar estado: author/doc_id inválido para {author} en iniciar_pago. Contexto: {contexto_guardar}")
        return mensaje, contexto_guardar
    
    # --- Fallback: intentar extraer fecha/hora si el usuario la menciona y no está en detalles ---
    if not detalles.get('fecha_deseada') or not detalles.get('hora_especifica'):
        if mensaje_usuario:
            from utils import parsear_fecha_hora_natural
            dt = parsear_fecha_hora_natural(mensaje_usuario)
            if dt:
                if not detalles.get('fecha_deseada'):
                    detalles['fecha_deseada'] = dt.date().isoformat()
                if not detalles.get('hora_especifica'):
                    detalles['hora_especifica'] = dt.strftime('%H:%M')
    
    # Validación de datos requeridos
    datos_faltantes = []
    if not plan:
        datos_faltantes.append('servicio o plan a abonar')
    if not provider:
        datos_faltantes.append('proveedor de pago (ej: MercadoPago, MODO, PayPal)')
    
    # Si falta algún dato, pedirlo explícitamente
    if datos_faltantes:
        instruccion = (
            f"Para generar tu link de pago necesito: {', '.join(datos_faltantes)}. "
            "Por favor, indícame esa información y te lo envío al instante."
        )
        # CORRECCIÓN CRÍTICA: Usar función helper para context_info completo
        import main
        context_info_base = {
            "intencion": detalles.get("intencion", "pago"),
            "estado_pago": "faltan_datos",
            "plan": plan,
            "monto": monto,
            "proveedor": provider
        }
        user_message = {"role": "user", "content": mensaje_usuario}
        history_with_current = history + [user_message]
        context_info = main._construir_context_info_completo(context_info_base, state_context, mensaje_usuario, "pagar", author)
        mensaje = main._llamar_agente_cero_directo(history_with_current, context_info)
        contexto_guardar = detalles.copy()
        contexto_guardar.update({
            'plan': plan,
            'monto': monto,
            'proveedor': provider
        })
        if is_valid_doc_id(author):
            memory.update_conversation_state(author, 'esperando_confirmacion_pago', contexto_guardar)
        else:
            logger.critical(f"[MEMORY] No se puede actualizar estado: author/doc_id inválido para {author} en iniciar_pago. Contexto: {contexto_guardar}")
        return mensaje, contexto_guardar
    
    # PLAN DE REFACTORIZACIÓN v3: Generar link con retry y exponential backoff
    provider = provider.upper() if provider else 'MERCADOPAGO'
    payment_service = get_payment_service(provider)
    
    try:
        import utils
        mensaje, contexto = utils.retry_with_exponential_backoff(
            payment_service.create_payment_link,
            detalles
        )
    except Exception as e:
        logger.error(f"[PAGO] Error después de reintentos generando link de pago: {e}")
        mensaje, contexto = None, {}
    historial_resumido = '\n'.join([str(m) for m in history[-3:]])
    
    if not mensaje:
        instruccion = (
            "No se pudo generar el link de pago por un inconveniente interno. "
            f"Mensaje del usuario: {mensaje_usuario}\n"
            f"Historial reciente: {historial_resumido}\n"
            f"Plan: {plan}\n"
            f"Monto: {monto}\n"
            "Indica al usuario que intente nuevamente más tarde o que un asistente humano lo contactará si es necesario, sin dar detalles técnicos."
        )
        # CORRECCIÓN CRÍTICA: Usar función helper para context_info completo
        import main
        context_info_base = {
            "intencion": detalles.get("intencion", "pago"),
            "estado_pago": "error",
            "plan": plan,
            "monto": monto,
            "proveedor": provider,
            "link_pago": None
        }
        user_message = {"role": "user", "content": mensaje_usuario}
        history_with_current = history + [user_message]
        context_info = main._construir_context_info_completo(context_info_base, state_context, mensaje_usuario, "pagar", author)
        mensaje = main._llamar_agente_cero_directo(history_with_current, context_info)
        contexto_guardar = detalles.copy()
        contexto_guardar.update({
            'plan': plan,
            'monto': monto,
            'proveedor': provider,
            'link_pago': None
        })
        if is_valid_doc_id(author):
            memory.update_conversation_state(author, 'esperando_confirmacion_pago', contexto_guardar)
        else:
            logger.critical(f"[MEMORY] No se puede actualizar estado: author/doc_id inválido para {author} en iniciar_pago. Contexto: {contexto_guardar}")
        return mensaje, contexto_guardar
    
    # Si el link de pago fue generado correctamente, pásalo en el context_info
    # CORRECCIÓN CRÍTICA: Usar función helper para context_info completo
    import main
    context_info_base = {
        "intencion": detalles.get("intencion", "pago"),
        "estado_pago": "link_generado",
        "plan": plan,
        "monto": monto,
        "proveedor": provider,
        "link_pago": mensaje
    }
    user_message = {"role": "user", "content": mensaje_usuario}
    history_with_current = history + [user_message]
    context_info = main._construir_context_info_completo(context_info_base, state_context, mensaje_usuario, "pagar", author)
    mensaje = main._llamar_agente_cero_directo(history_with_current, context_info)
    contexto_guardar = detalles.copy()
    contexto_guardar.update({
        'plan': plan,
        'monto': monto,
        'proveedor': provider,
        'link_pago': mensaje
    })
    if is_valid_doc_id(author):
        memory.update_conversation_state(author, 'esperando_confirmacion_pago', contexto_guardar)
    else:
        logger.critical(f"[MEMORY] No se puede actualizar estado: author/doc_id inválido para {author} en iniciar_pago. Contexto: {contexto_guardar}")
    return mensaje, contexto_guardar


def registrar_link_pago_enviado(context):
    """
    Registra que se envió un link de pago al usuario.
    Función de compatibilidad mantenida para logging.
    """
    try:
        author = context.get('author')
        link_pago = context.get('link_pago')
        servicio = context.get('servicio_pagado', 'Servicio')
        
        if author and link_pago:
            logger.info(f"[REGISTRAR_LINK] Link enviado para {author}: {servicio} - {link_pago}")
            
            # Guardar en memoria para tracking
            if is_valid_doc_id(author):
                memory.add_to_conversation_history(
                    author, "assistant", "RODI", 
                    f"Link de pago enviado: {servicio}", 
                    name="RODI", context=context
                )
                
        return True
    except Exception as e:
        logger.error(f"[REGISTRAR_LINK] Error registrando link: {e}")
        return False


def verificar_pago_registrado(context):
    """
    Deprecado: ya no se verifican pagos del lado del bot. Se mantiene para compatibilidad.
    """
    try:
        return True if context and context.get('pago_registrado') else False
    except Exception:
        return False


def confirmar_pago(history, context, state_context, mensaje_completo_usuario, author=None):
    """
    Política requerida: no verificar ni pedir validaciones; registrar y agradecer.
    - Si llega un comprobante (o el usuario indica que pagó), agradecer y marcar contexto.
    - No enviar mensajes de error al cliente; ante error, escalar a humano silenciosamente.
    """
    try:
        ctx = state_context or {}
        author_final = (ctx.get('author') or (author if isinstance(author, str) else '') or '').strip()
        if not author_final:
            logger.error(f"[CONFIRMAR_PAGO] Author inválido: {author_final}")
            # No devolver error al cliente; responder neutro y cortar
            return "Perfecto, registramos tu comprobante. ¡Muchas gracias!", ctx

        # Intentar extraer monto desde mensaje de lector si vino en el buffer
        monto_detectado = None
        try:
            if isinstance(mensaje_completo_usuario, str) and 'COMPROBANTE DE PAGO:' in mensaje_completo_usuario.upper():
                # Extraer después de la primera ocurrencia
                import re
                match = re.search(r"COMPROBANTE DE PAGO:\s*(.+)$", mensaje_completo_usuario, re.IGNORECASE)
                if match:
                    monto_detectado = match.group(1).strip()
        except Exception:
            pass

        # Marcar pago registrado sin validaciones
        ctx['pago_registrado'] = True
        ctx['comprobante_enviado'] = True
        ctx['current_state'] = 'conversando'
        
        # NUEVO: Marcar verificación de pago si se detectó monto
        if monto_detectado:
            try:
                # Extraer monto numérico del texto
                import re
                patron_monto = r'\$?\s*(\d+(?:\.\d{1,2})?)'
                match = re.search(patron_monto, monto_detectado)
                if match:
                    monto_numerico = float(match.group(1))
                    ctx['payment_verified'] = True
                    ctx['payment_amount'] = monto_numerico
                    ctx['payment_date'] = datetime.now().strftime('%Y-%m-%d')
                    
                    # NUEVO: Limpiar restricciones y actualizar estado cuando se verifica pago
                    ctx['payment_restriction_active'] = False
                    ctx['requires_payment_first'] = False
                    ctx['blocked_action'] = None
                    
                    # Actualizar estado para salir del flujo de pagos
                    current_state = ctx.get('current_state', '')
                    if current_state.startswith('PAGOS_'):
                        ctx['current_state'] = 'conversando'
                        logger.info(f"[CONFIRMAR_PAGO] 🔄 Estado actualizado de '{current_state}' a 'conversando'")
                    
                    logger.info(f"[CONFIRMAR_PAGO] ✅ Pago verificado automáticamente por ${monto_numerico}")
                    
                    # NOTIFICACIÓN AUTOMÁTICA DE PAGO EXITOSO
                    try:
                        import notification_manager
                        datos_notificacion_pago = {
                            'servicio': notification_manager.obtener_servicio_desde_contexto(ctx),
                            'monto': monto_numerico,
                            'nombre': notification_manager.obtener_nombre_cliente(ctx, author_final),
                            'telefono': author_final,
                            'fecha_pago': datetime.now().strftime('%d/%m/%Y %H:%M')
                        }
                        notification_manager.enviar_notificacion_pago_exitoso(datos_notificacion_pago)
                    except Exception as notif_error:
                        logger.error(f"[CONFIRMAR_PAGO] Error enviando notificación (no afecta flujo principal): {notif_error}")
                    
            except Exception as e:
                logger.error(f"[CONFIRMAR_PAGO] Error extrayendo monto numérico: {e}")
        
        logger.info(f"[CONFIRMAR_PAGO] Comprobante registrado sin validaciones para {author_final}")

        # Mensaje corto; si hay monto, incluirlo con formato del lector
        if monto_detectado:
            mensaje = f"✅ COMPROBANTE DE PAGO: {monto_detectado}\n\nPerfecto, tu pago ha sido verificado. Ya puedes continuar con el agendamiento cuando lo desees."
        else:
            mensaje = "✅ ¡Muchas gracias! Registramos tu comprobante y ya lo informamos al equipo.\n\nAhora puedes continuar con el agendamiento cuando lo desees."
        return mensaje, ctx

    except Exception as e:
        logger.error(f"[CONFIRMAR_PAGO] Error procesando comprobante: {e}", exc_info=True)
        # Escalar a humano silenciosamente, sin mensaje de error al cliente
        try:
            detalles = {"motivo": "error_confirmar_pago", "mensaje_usuario": mensaje_completo_usuario}
            _ = agendamiento_handler.wrapper_escalar_a_humano(history, detalles, state_context or {}, mensaje_completo_usuario)
        except Exception:
            pass
        # Mensaje neutro (sin revelar error)
        return "¡Muchas gracias! Registramos tu comprobante y ya lo informamos al equipo.", (state_context or {})


def informar_servicio(history, detalles, state_context=None, mensaje_completo_usuario=None):
    """
    Informa sobre los servicios disponibles cuando el usuario pregunta.
    Función de compatibilidad mantenida.
    """
    if detalles is None:
        detalles = {}
    
    context, detalles = asegurar_author(detalles.copy() if detalles else {}, detalles, history)
    author = detalles.get('author', '')
    servicio_consultado = detalles.get('servicio_consultado', '').lower()
    mensaje_usuario = detalles.get('mensaje_usuario', '') or mensaje_completo_usuario or ''
    
    # Información sobre servicios disponibles
    servicios_info = {
        'coaching': {
            'descripcion': 'Coaching personalizado para desarrollo profesional y personal',
            'duracion': '60 minutos',
            'precio': '$200',
            'modalidad': 'Online o presencial'
        },
        'consultita': {
            'descripcion': 'Consulta rápida para resolver dudas específicas',
            'duracion': '30 minutos', 
            'precio': '$100',
            'modalidad': 'Online'
        },
        'mentoria': {
            'descripcion': 'Programa de mentoría intensivo con seguimiento',
            'duracion': '90 minutos',
            'precio': '$300',
            'modalidad': 'Online o presencial'
        }
    }
    
    if servicio_consultado in servicios_info:
        servicio = servicios_info[servicio_consultado]
        mensaje = (
            f"**{servicio_consultado.title()}**\n\n"
            f"**Descripción:** {servicio['descripcion']}\n"
            f"**Duración:** {servicio['duracion']}\n"
            f"**Precio:** {servicio['precio']}\n"
            f"**Modalidad:** {servicio['modalidad']}\n\n"
            f"¿Te gustaría agendar una sesión o consultar más detalles?"
        )
    else:
        mensaje = (
            "Tenemos varios servicios disponibles:\n\n"
            "**Coaching:** Desarrollo profesional y personal (60 min - $200)\n"
            "**Consultita:** Consulta rápida (30 min - $100)\n"
            "**Mentoría:** Programa intensivo (90 min - $300)\n\n"
            "¿Cuál te interesa más?"
        )
    
    return mensaje, context


# (Eliminar la función handle_payment_message y cualquier lógica de detección de intención propia)


def reanudar_flujo_anterior(history, detalles, state_context, mensaje_completo_usuario=None):
    """
    Reanuda el flujo anterior después de una pregunta.
    Función de compatibilidad mantenida.
    """
    logger.info(f"[REANUDAR_FLUJO] Reanudando flujo anterior")
    
    # Determinar qué flujo reanudar basado en el contexto
    if state_context and state_context.get('current_state'):
        current_state = state_context['current_state']
        
        if 'PAGOS' in current_state:
            return mostrar_servicios_pago(history, detalles, state_context, mensaje_completo_usuario)
        elif 'AGENDA' in current_state:
            try:
                return agendamiento_handler.mostrar_opciones_turnos(history, detalles, state_context, mensaje_completo_usuario)
            except Exception:
                # Importar perezoso para evitar ciclos y llamar al triage de agendamiento
                try:
                    from agendamiento_handler import iniciar_triage_agendamiento as _iniciar_triage_ag
                    return _iniciar_triage_ag(history, detalles, state_context, mensaje_completo_usuario)
                except Exception:
                    return "¿En qué puedo ayudarte?", state_context or {}
    
    # Fallback: volver a preguntar
    return "¿En qué puedo ayudarte?", state_context or {}


def is_valid_doc_id(doc_id):
    return bool(doc_id and isinstance(doc_id, str) and doc_id.strip() and not doc_id.strip().endswith('/'))


def iniciar_agendamiento_unificado(history, detalles, state_context=None, mensaje_completo_usuario=None, author=None):
    """
    Función de compatibilidad que redirige al nuevo flujo unificado.
    """
    logger.info(f"[AGENDAMIENTO] Redirigiendo al Plan de Flujo Unificado")
    try:
        from agendamiento_handler import iniciar_triage_agendamiento as _iniciar_triage_ag
        return _iniciar_triage_ag(history, detalles, state_context, mensaje_completo_usuario)
    except Exception:
        return "¿En qué puedo ayudarte?", state_context or {}


def limpiar_contexto_pagos_unificado(context):
    """
    Limpia agresivamente el contexto de variables relacionadas con pagos.
    NUEVA FUNCIÓN: Implementa limpieza agresiva para evitar conflictos en el flujo unificado.
    """
    if not context:
        return context
    
    # Lista completa de campos a limpiar
    campos_a_limpiar = [
        'servicio_seleccionado', 'precio', 'opciones_servicios', 'fecha_deseada', 
        'hora_especifica', 'available_slots', 'proveedor_seleccionado', 'link_pago',
        'external_reference', 'estado_pago', 'comprobante_enviado', 'pago_verificado',
        'opciones_proveedores', 'proveedores_disponibles', 'current_state',
        'plan', 'monto', 'proveedor', 'payment_data', 'preference_id'
    ]
    
    # Crear una copia del contexto para no modificar el original
    context_limpio = context.copy()
    
    # Eliminar campos de pagos
    for campo in campos_a_limpiar:
        if campo in context_limpio:
            del context_limpio[campo]
            logger.info(f"[LIMPIEZA_PAGOS] Campo eliminado: {campo}")
    
    # Mantener solo campos esenciales
    campos_esenciales = ['author']
    context_final = {}
    for campo in campos_esenciales:
        if campo in context_limpio:
            context_final[campo] = context_limpio[campo]
    
    logger.info(f"[LIMPIEZA_PAGOS] Contexto limpiado agresivamente. Campos mantenidos: {list(context_final.keys())}")
    return context_final


def iniciar_triage_pagos(history, detalles, state_context=None, mensaje_completo_usuario=None, author=None):
    """
    NUEVO: Función para iniciar el flujo de pagos con triage inteligente.
    CORRECCIÓN CRÍTICA: Preservar información extraída por la IA sin limpiarla.
    MEJORA CRÍTICA: Siempre mostrar lista de servicios directamente.
    """
    logger.info(f"[TRIAGE_PAGOS] Iniciando triage de pagos para usuario")
    
    # Asegurar que tenemos el contexto necesario
    if not state_context:
        state_context = {}
    
    # Usar el parámetro author explícito si está disponible
    if not author:
        author = state_context.get('author') or detalles.get('author')
    
    if not author:
        return "Error interno. No se pudo identificar al usuario.", state_context
    
    # CORRECCIÓN CRÍTICA: Extraer y preservar información de la IA ANTES de cualquier limpieza
    servicio_deseado = None
    proveedor_preferido = None
    
    # Extraer información de los detalles si está disponible
    if isinstance(detalles, dict):
        servicio_deseado = detalles.get('servicio_deseado')
        proveedor_preferido = detalles.get('proveedor_preferido')
        logger.info(f"[TRIAGE_PAGOS] Información extraída de detalles - servicio: {servicio_deseado}, proveedor: {proveedor_preferido}")
    
    # CORRECCIÓN CRÍTICA: NO limpiar el contexto agresivamente, solo preservar información esencial
    # Mantener author y senderName, y agregar información de la IA
    author_guardado = state_context.get('author') or author
    sender_name_guardado = state_context.get('senderName')
    
    # Crear contexto limpio pero preservando información crítica
    state_context = {
        'author': author_guardado,
        'senderName': sender_name_guardado
    }
    
    # CORRECCIÓN CRÍTICA: Agregar información extraída por la IA al contexto
    if servicio_deseado:
        state_context['servicio_deseado'] = servicio_deseado
        logger.info(f"[TRIAGE_PAGOS] Servicio agregado al contexto: {servicio_deseado}")
    if proveedor_preferido:
        state_context['proveedor_preferido'] = proveedor_preferido
        logger.info(f"[TRIAGE_PAGOS] Proveedor agregado al contexto: {proveedor_preferido}")
    
    # MEJORA CRÍTICA: Verificar si se debe forzar la lista
    forzar_lista = detalles.get('forzar_lista', False) if isinstance(detalles, dict) else False
    if forzar_lista:
        logger.info(f"[TRIAGE_PAGOS] Forzando muestra de lista de servicios")
        state_context['forzar_lista_servicios'] = True
    
    # Actualizar estado - SOLO si no hay pago ya verificado
    if not state_context.get('payment_verified', False):
        state_context['current_state'] = 'PAGOS_ESPERANDO_SELECCION_SERVICIO'
    else:
        logger.info(f"[TRIAGE_PAGOS] 🔒 No actualizando estado - pago ya verificado")
    
    logger.info(f"[TRIAGE_PAGOS] Contexto final con información de la IA: {state_context}")
    
    # MEJORA CRÍTICA: Mostrar servicios disponibles directamente
    return mostrar_servicios_pago(history, detalles, state_context, mensaje_completo_usuario, author)



def mostrar_servicios_pago(history, detalles, state_context=None, mensaje_completo_usuario=None, author=None):
    """
    MEJORADO: Muestra servicios disponibles usando catálogo centralizado.
    NUEVA IMPLEMENTACIÓN: Usa el catálogo de servicios centralizado.
    MEJORA CRÍTICA: Siempre mostrar lista directamente sin preguntas.
    """
    logger.info(f"[MOSTRAR_SERVICIOS] Iniciando muestra de servicios disponibles")
    
    # Asegurar que tenemos el contexto necesario
    if not state_context:
        state_context = {}
    
    # Usar el parámetro author explícito si está disponible
    if not author:
        author = state_context.get('author') or detalles.get('author')
    
    if not author:
        return "Error interno. No se pudo identificar al usuario.", state_context
    
    # NUEVO: Obtener servicios desde catálogo centralizado
    import utils
    servicios_disponibles = utils.get_services_catalog()
    
    if not servicios_disponibles:
        logger.error("[MOSTRAR_SERVICIOS] No hay servicios configurados")
        return "Error interno. No hay servicios disponibles.", state_context
    
    # NUEVO: Crear opciones para lista interactiva con IDs temporales
    opciones_lista = []
    from datetime import datetime, timezone
    
    for servicio in servicios_disponibles:
        nombre = servicio.get('nombre', 'Servicio')
        precio = servicio.get('precio', 'Consultar')
        
        # CORRECCIÓN CRÍTICA: Usar función de utilidad para acortar título
        titulo_final = utils.acortar_titulo_servicio(nombre, precio, max_caracteres=24)
        
        # NUEVO: Generar ID temporal único
        timestamp = datetime.now(timezone.utc)
        timestamp_str = timestamp.strftime("%Y%m%d_%H%M%S")
        servicio_id = servicio.get('id', 'servicio_1')
        id_temporal = f"{servicio_id}_{timestamp_str}"
        
        logger.info(f"[MOSTRAR_SERVICIOS] Título generado: '{titulo_final}' ({len(titulo_final)} caracteres), ID temporal: {id_temporal}")
        
        opciones_lista.append({
            "id": id_temporal,
            "title": titulo_final,
            "servicio_original_id": servicio_id  # Guardar ID original para referencia
        })
    
    # MENSAJE EDUCATIVO CON COMANDOS EXPLÍCITOS
    mensaje_principal = (
        "💳 Elegí el servicio y te genero el link de pago.\n"
        "- Tocá 'Elige un Servicio' y seleccioná.\n"
        "- Para salir de pagos, escribí: SALIR DE PAGO\n\n"
        "📸 Una vez que pagues, enviá foto del comprobante donde se vea el monto."
    )
    titulo_lista = "Elige un Servicio"  # 17 caracteres
    titulo_seccion = "Servicios Disponibles"  # 21 caracteres, cumple el límite

    # Obtener el número de teléfono del autor
    author = state_context.get('author', '')
    if not author:
        logger.error(f"[MOSTRAR_SERVICIOS] No hay author válido")
        return "Error interno. Por favor, intenta de nuevo.", state_context

    # NUEVO: Crear payload interactivo para almacenar en state_context
    interactive_payload = {
        "type": "list",
        "header": {
            "type": "text",
            "text": "Elige una opción"
        },
        "body": {
            "text": mensaje_principal
        },
        "action": {
            "button": titulo_lista,
            "sections": [
                {
                    "title": titulo_seccion,
                    "rows": []
                }
            ]
        }
    }
    
    # Agregar opciones al payload
    for option in opciones_lista:
        row = {
            "id": option.get('id', ''),
            "title": option.get('title', '')
        }
        if 'description' in option:
            row["description"] = option.get('description', '')
        interactive_payload["action"]["sections"][0]["rows"].append(row)
    
    # Enviar mensaje interactivo usando función unificada
    success = msgio_handler.send_whatsapp_message(
        phone_number=author,
        message=mensaje_principal,
        list_title=titulo_lista,
        options=opciones_lista,
        section_title=titulo_seccion
    )
    
    if success:
        logger.info(f"[MOSTRAR_SERVICIOS] Mensaje interactivo enviado exitosamente")
        
        # PARA CHATWOOT: Registrar resumen de servicios enviados como botones
        try:
            import chatwoot_integration
            num_servicios = len(opciones_lista)
            resumen_chatwoot = f"Se enviaron {num_servicios} servicios disponibles como botones interactivos"
            chatwoot_integration.log_to_chatwoot(author, "", resumen_chatwoot, "Sistema")
            logger.info(f"[MOSTRAR_SERVICIOS] Resumen registrado en Chatwoot: {resumen_chatwoot}")
        except Exception as e:
            logger.warning(f"[MOSTRAR_SERVICIOS] Error registrando en Chatwoot: {e}")
        
        # NUEVA MEJORA: Solo guardar timestamp para validación de frescura, no el payload completo
        state_context['ultimo_interactive_timestamp'] = datetime.now().isoformat()
        # Actualizar estado - SOLO si no hay pago ya verificado
        if not state_context.get('payment_verified', False):
            state_context['current_state'] = 'PAGOS_ESPERANDO_SELECCION_SERVICIO'
        else:
            logger.info(f"[MOSTRAR_SERVICIOS] 🔒 No actualizando estado - pago ya verificado")
        return None, state_context
    else:
        logger.error(f"[MOSTRAR_SERVICIOS] Error enviando mensaje interactivo, usando fallback")
        # Fallback: mensaje de texto tradicional
        mensaje_servicios = "¡Perfecto! Aquí tenés los servicios disponibles:\n\n"
        for i, servicio in enumerate(servicios_disponibles, 1):
            nombre = servicio.get('nombre', 'Servicio')
            precio = servicio.get('precio', 'Consultar')
            mensaje_servicios += f"{i}. {nombre} - ${precio}\n"
        
        # Mensaje corto y al hueso, sin instrucciones adicionales que confundan
        
        # MEJORA: Solo guardar el estado, no la lista completa - SOLO si no hay pago ya verificado
        if not state_context.get('payment_verified', False):
            state_context['current_state'] = 'PAGOS_ESPERANDO_SELECCION_SERVICIO'
        else:
            logger.info(f"[MOSTRAR_SERVICIOS] 🔒 No actualizando estado (fallback) - pago ya verificado")
        
        logger.info(f"[PAGOS] Mostrando {len(servicios_disponibles)} servicios (sin guardar lista completa)")
        return mensaje_servicios, state_context


def confirmar_servicio_pago(history, detalles, state_context=None, mensaje_completo_usuario=None, author=None):
    """
    MEJORADO: Confirma la selección de servicio usando catálogo centralizado.
    NUEVA MEJORA: Si recibe lenguaje natural, devuelve None para que Meta Agente clasifique.
    """
    logger.info(f"[CONFIRMAR_SERVICIO] Procesando selección de servicio con catálogo centralizado")
    
    # NUEVO: Obtener servicios desde catálogo centralizado
    import utils
    servicios_disponibles = utils.get_services_catalog()
    
    if not servicios_disponibles:
        logger.error("[CONFIRMAR_SERVICIO] No hay servicios disponibles en el catálogo")
        return reiniciar_flujo_pagos(history, detalles, state_context, "Error de catálogo")

    # MEJORADO: Manejar respuestas interactivas con IDs temporales
    if mensaje_completo_usuario and ('servicio_' in mensaje_completo_usuario and '_' in mensaje_completo_usuario):
        try:
            # Extraer ID temporal del servicio (ej: "servicio_3_20241201_143022" -> "servicio_3")
            id_temporal = mensaje_completo_usuario
            partes = id_temporal.split('_')
            if len(partes) >= 2:
                # Extraer el ID original del servicio del ID temporal
                service_id = partes[0] + '_' + partes[1]  # servicio_3
                logger.info(f"[CONFIRMAR_SERVICIO] Respuesta interactiva temporal detectada: {mensaje_completo_usuario} -> {service_id}")
            else:
                logger.error(f"[CONFIRMAR_SERVICIO] Formato de ID temporal inválido: {mensaje_completo_usuario}")
                return reiniciar_flujo_pagos(history, detalles, state_context, "Error de formato")
        except (ValueError, IndexError):
            logger.error(f"[CONFIRMAR_SERVICIO] Error parseando respuesta interactiva temporal: {mensaje_completo_usuario}")
            return reiniciar_flujo_pagos(history, detalles, state_context, "Error de formato")
    elif mensaje_completo_usuario and mensaje_completo_usuario.startswith('servicio_'):
        try:
            # Compatibilidad con IDs sin timestamp (fallback)
            service_id = mensaje_completo_usuario
            logger.info(f"[CONFIRMAR_SERVICIO] Respuesta interactiva legacy detectada: {mensaje_completo_usuario}")
        except (ValueError, IndexError):
            logger.error(f"[CONFIRMAR_SERVICIO] Error parseando respuesta interactiva legacy: {mensaje_completo_usuario}")
            return reiniciar_flujo_pagos(history, detalles, state_context, "Error de formato")
    else:
        # Manejo tradicional de respuestas numéricas
        try:
            numero_seleccionado = int(mensaje_completo_usuario.strip())
            logger.info(f"[CONFIRMAR_SERVICIO] Respuesta numérica detectada: {numero_seleccionado}")
            
            # Convertir número a ID de servicio
            if 1 <= numero_seleccionado <= len(servicios_disponibles):
                service_id = servicios_disponibles[numero_seleccionado - 1].get('id', f'servicio_{numero_seleccionado}')
            else:
                logger.error(f"[CONFIRMAR_SERVICIO] Número fuera de rango: {numero_seleccionado}")
                return reiniciar_flujo_pagos(history, detalles, state_context, "Número inválido")
        except (ValueError, TypeError):
            # NUEVA MEJORA CRÍTICA: Si no es un ID válido, devolver None para que Meta Agente clasifique
            logger.info(f"[CONFIRMAR_SERVICIO] Mensaje no es ID válido, devolviendo None para clasificación: {mensaje_completo_usuario}")
            return None, state_context

    # NUEVO: Obtener servicio por ID desde catálogo
    servicio_seleccionado = utils.get_service_by_id(service_id)
    
    if not servicio_seleccionado:
        logger.error(f"[CONFIRMAR_SERVICIO] Servicio no encontrado: {service_id}")
        return reiniciar_flujo_pagos(history, detalles, state_context, "Servicio no encontrado")
    
    # MEJORA: Guardar solo el ID del servicio, no el objeto completo
    state_context['servicio_seleccionado_id'] = service_id
    state_context['current_state'] = 'PAGOS_ESPERANDO_CONFIRMACION'
    
    nombre = servicio_seleccionado.get('nombre', 'Servicio')
    precio = servicio_seleccionado.get('precio', 'Consultar')
    
    # MENSAJE EDUCATIVO CON COMANDOS EXPLÍCITOS
    mensaje_confirmacion = f"Seleccionaste '{nombre}' por ${precio}. ¿Es correcto?\n\nPara salir de pagos, escribí: SALIR DE PAGO"
    
    # Crear botones de confirmación
    botones_confirmacion = [
        {"id": "confirmar_si", "title": "✅ Sí, es correcto"},
        {"id": "confirmar_no", "title": "❌ No, cambiar"}
    ]
    
    # NUEVO: Crear payload interactivo para almacenar en state_context
    interactive_payload = {
        "type": "button",
        "body": {
            "text": mensaje_confirmacion
        },
        "action": {
            "buttons": []
        }
    }
    
    # Agregar botones al payload
    for button in botones_confirmacion:
        interactive_payload["action"]["buttons"].append({
            "type": "reply",
            "reply": {
                "id": button.get('id', ''),
                "title": button.get('title', '')
            }
        })
    
    # Obtener el número de teléfono del autor
    author = state_context.get('author', '')
    if author:
        success = msgio_handler.send_whatsapp_message(
            phone_number=author,
            message=mensaje_confirmacion,
            buttons=botones_confirmacion
        )
        
        if success:
            logger.info(f"[CONFIRMAR_SERVICIO] Mensaje de confirmación con botones enviado exitosamente")
            # NUEVA MEJORA: Solo guardar timestamp para validación de frescura, no el payload completo
            state_context['ultimo_interactive_timestamp'] = datetime.now().isoformat()
            # CORRECCIÓN CRÍTICA: No retornar texto después de enviar botones interactivos
            # Solo actualizar el estado y retornar None para evitar doble envío
            return None, state_context
    
    # Fallback: mensaje de texto tradicional
    mensaje_confirmacion_fallback = f"Seleccionaste '{nombre}' por ${precio}. ¿Es correcto? Por favor, respondé Sí o No."
    return mensaje_confirmacion_fallback, state_context


def generar_link_pago(history, detalles, state_context=None, mensaje_completo_usuario=None, author=None):
    """
    MEJORADO: Genera el link de pago automáticamente después de confirmación.
    Usa el nuevo sistema con IDs de servicio.
    """
    logger.info(f"[GENERAR_LINK] Generando link de pago automáticamente")
    
    # NUEVO: Obtener servicio por ID desde catálogo
    service_id = state_context.get('servicio_seleccionado_id')
    if not service_id:
        logger.error("[GENERAR_LINK] No hay servicio seleccionado")
        return reiniciar_flujo_pagos(history, detalles, state_context, "Error: No hay servicio seleccionado")
    
    # Obtener servicio desde catálogo centralizado
    import utils
    servicio_seleccionado = utils.get_service_by_id(service_id)
    if not servicio_seleccionado:
        logger.error(f"[GENERAR_LINK] Servicio no encontrado: {service_id}")
        return reiniciar_flujo_pagos(history, detalles, state_context, "Error: Servicio no encontrado")
    
    try:
        # Obtener datos del servicio
        nombre = servicio_seleccionado.get('nombre', 'Servicio')
        precio = servicio_seleccionado.get('precio', 0)
        
        # MEJORADO: Validar que el precio sea válido
        if not precio or precio <= 0:
            logger.error(f"[GENERAR_LINK] Precio inválido para servicio {nombre}: {precio}")
            return "Lo siento, hay un problema con el precio del servicio. Por favor, intenta de nuevo.", state_context
        
        # NUEVA MEJORA: Manejo robusto de errores de API de MercadoPago
        try:
            from service_factory import get_payment_service
            
            payment_service = get_payment_service('MERCADOPAGO')
            if not payment_service:
                logger.error("[GENERAR_LINK] No se pudo obtener el servicio de pago")
                return "Lo siento, hay un problema con el sistema de pagos. Por favor, intenta de nuevo.", state_context
            
            payment_data = {
                "servicio_seleccionado": nombre,  # Pasar el nombre, no el ID
                "precio": precio,
                "proveedor_seleccionado": "MERCADOPAGO"
            }
            
            # PLAN DE REFACTORIZACIÓN v3: Generar link con retry y exponential backoff
            try:
                import utils
                mensaje, contexto_pago = utils.retry_with_exponential_backoff(
                    payment_service.create_payment_link,
                    payment_data
                )
            except Exception as e:
                logger.error(f"[GENERAR_LINK] Error después de reintentos generando link de pago: {e}")
                mensaje, contexto_pago = None, {}
            
            if not mensaje:
                logger.error("[GENERAR_LINK] No se pudo generar el link de pago")
                return "Lo siento, no se pudo generar el link de pago. Por favor, intenta de nuevo.", state_context
                
        except Exception as e:
            logger.error(f"[GENERAR_LINK] Error de API de MercadoPago: {e}")
            # NUEVA MEJORA: Mensaje genérico para el usuario sin exponer errores internos
            return "Lo siento, hay un problema técnico con el sistema de pagos. Por favor, intenta de nuevo en unos minutos.", state_context
        
        # Actualizar contexto
        state_context.update(contexto_pago)
        state_context['servicio_pagado'] = nombre
        state_context['precio_pagado'] = precio
        
        # NUEVA MEJORA: Redirigir a estado de limpieza en lugar de estado final
        state_context_final = limpiar_contexto_pagos_unificado(state_context)
        state_context_final['current_state'] = 'conversando'
        
        logger.info(f"[GENERAR_LINK] Link generado exitosamente para {nombre}")
        return mensaje, state_context_final
        
    except Exception as e:
        logger.error(f"[GENERAR_LINK] Error generando link: {e}")
        return "Lo siento, hubo un error generando tu link de pago. Por favor, intenta de nuevo.", state_context


def reiniciar_flujo_pagos(history, detalles, state_context=None, mensaje_completo_usuario=None, author=None):
    """
    CORREGIDO: Reinicia el flujo de pagos cuando el usuario cambia de opinión.
    """
    logger.info(f"[REINICIAR_PAGOS] Reiniciando flujo de pagos")
    
    # Limpiar contexto agresivamente
    state_context_limpio = limpiar_contexto_pagos_unificado(state_context)
    
    # Reiniciar desde el triage
    return iniciar_triage_pagos(history, detalles, state_context_limpio, mensaje_completo_usuario, author)
