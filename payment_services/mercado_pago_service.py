import logging
import uuid
import json
import time
import mercadopago
import config
from interfaces.payment_interface import PaymentInterface


class MercadoPagoService(PaymentInterface):
    """MercadoPago implementation of the PaymentInterface."""

    def __init__(self):
        self.logger = logging.getLogger(config.TENANT_NAME)

    def create_payment_link(self, payment_data: dict) -> tuple[str, dict]:
        self.logger.info(f"FLUJO DE PAGO INICIADO. Detalles: {payment_data}")
        if not config.MERCADOPAGO_TOKEN:
            self.logger.critical("FATAL: MERCADOPAGO_TOKEN no está configurado.")
            return ("Estoy preparando tu link de pago, dame solo un momento por favor.", {"estado_pago": "error", "razon": "token_faltante"})

        # NUEVO: Compatibilidad con el nuevo flujo de pagos
        servicio_seleccionado = payment_data.get("servicio_seleccionado")
        precio = payment_data.get("precio")
        
        # Fallback para compatibilidad con el flujo anterior
        if not servicio_seleccionado:
            plan = payment_data.get("plan")
            if not plan or plan == "servicio mencionado":
                self.logger.error("No se especificó un servicio válido")
                return ("Para generar tu link de pago necesito saber qué servicio deseas abonar. Por favor, indícalo y te lo envío al instante.", {"estado_pago": "faltan_datos", "falta": "servicio"})
            servicio_seleccionado = plan

        # NUEVO: Usar precio directamente si está disponible
        if precio is None:
            try:
                precios = json.loads(config.SERVICE_PRICES_JSON)
                if not precios:
                    self.logger.critical("FATAL: SERVICE_PRICES_JSON está vacío.")
                    return "Estoy teniendo un inconveniente con la lista de precios. Dame un momento mientras lo soluciono.", {}
                
                # Buscar el precio del servicio
                servicio_lower = servicio_seleccionado.lower()
                precio_unitario = None
                
                # Buscar coincidencias exactas primero
                if servicio_lower in precios:
                    precio_unitario = precios[servicio_lower]
                else:
                    # Buscar coincidencias parciales
                    for key, value in precios.items():
                        if servicio_lower in key.lower() or key.lower() in servicio_lower:
                            precio_unitario = value
                            servicio_seleccionado = key  # Usar el nombre correcto del servicio
                            break
                
                if precio_unitario is None:
                    self.logger.error(f"Servicio '{servicio_seleccionado}' no encontrado en SERVICE_PRICES_JSON")
                    return "No pude encontrar ese servicio en mi lista. ¿Podrías verificar el nombre del servicio que quieres abonar?", {}
                
                precio = precio_unitario
                
            except json.JSONDecodeError:
                self.logger.critical("FATAL: SERVICE_PRICES_JSON no es un JSON válido.")
                return "Estoy teniendo un inconveniente con la lista de precios. Dame un momento mientras lo soluciono.", {}

        external_ref = str(uuid.uuid4())
        max_retries = 3
        for attempt in range(max_retries):
            try:
                self.logger.info(f"Intentando generar link de pago (Intento {attempt + 1}/{max_retries})...")
                sdk = mercadopago.SDK(config.MERCADOPAGO_TOKEN)
                payment_data_mp = {
                    "items": [
                        {
                            "title": f"Servicio de {servicio_seleccionado.capitalize()}",
                            "quantity": 1,
                            "unit_price": float(precio),
                            "currency_id": "ARS",
                        }
                    ],
                    "back_urls": {
                        "success": "https://www.tu-sitio.com/pago-exitoso",
                        "failure": "https://www.tu-sitio.com/pago-fallido",
                        "pending": "https://www.tu-sitio.com/pago-pendiente",
                    },
                    "auto_return": "approved",
                    "external_reference": external_ref,
                }
                preference_response = sdk.preference().create(payment_data_mp)
                if preference_response["status"] == 201:
                    pref = preference_response["response"]
                    link = pref["init_point"]
                    self.logger.info(f"Link de pago generado: {link}")
                    mensaje = (
                        f"¡Perfecto! He generado tu link de pago para el servicio de {servicio_seleccionado.capitalize()}.\n"
                        f"Puedes pagar de forma segura aquí: {link}\n\n"
                        f"📸 Una vez que completes el pago, enviá foto del comprobante donde se vea el monto."
                    )
                    contexto = {
                        "external_reference": external_ref,
                        "servicio_seleccionado": servicio_seleccionado,
                        "precio": precio,
                        "proveedor_seleccionado": "MERCADOPAGO",
                        "link_pago": link
                    }
                    return mensaje, contexto
                else:
                    self.logger.warning(f"Intento {attempt + 1} fallido: {preference_response}")
            except Exception as e:
                self.logger.error(f"Intento {attempt + 1} fallido. Error: {e}", exc_info=True)
            if attempt < max_retries - 1:
                time.sleep(2)

        self.logger.critical("Todos los intentos de generar link de pago fallaron.")
        return "Lo siento, estoy teniendo problemas técnicos para generar tu link de pago. Por favor, intenta de nuevo en unos minutos.", {"estado_pago": "error", "razon": "fallo_generacion"}

    def check_payment_status(self, external_reference: str) -> str:
        """Verifica el estado de un pago usando la referencia externa."""
        if not config.MERCADOPAGO_TOKEN:
            return "Error: Token de MercadoPago no configurado"
        
        try:
            sdk = mercadopago.SDK(config.MERCADOPAGO_TOKEN)
            # Buscar pagos por referencia externa
            filters = {
                "external_reference": external_reference
            }
            search_response = sdk.payment().search(filters)
            
            if search_response["status"] == 200:
                results = search_response["response"]["results"]
                if results:
                    payment = results[0]
                    status = payment["status"]
                    if status == "approved":
                        return "approved"
                    elif status == "pending":
                        return "pending"
                    elif status == "rejected":
                        return "rejected"
                    else:
                        return f"unknown_status: {status}"
                else:
                    return "not_found"
            else:
                return f"error_search: {search_response['status']}"
        except Exception as e:
            self.logger.error(f"Error verificando pago: {e}", exc_info=True)
            return f"error: {str(e)}"
