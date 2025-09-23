from interfaces.payment_interface import PaymentInterface


class ModoService(PaymentInterface):
    """Implementación básica del servicio Modo."""

    def create_payment_link(self, payment_data: dict) -> tuple[str, dict]:
        mensaje = (
            "El proveedor MODO aún no está integrado por completo. "
            "Usa MercadoPago mientras tanto."
        )
        return mensaje, {}

    def check_payment_status(self, external_reference: str) -> str:
        return (
            "La verificación automática para pagos con MODO todavía no está disponible."
        )
