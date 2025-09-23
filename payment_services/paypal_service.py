from interfaces.payment_interface import PaymentInterface


class PayPalService(PaymentInterface):
    """Implementación básica para pagos con PayPal."""

    def create_payment_link(self, payment_data: dict) -> tuple[str, dict]:
        mensaje = (
            "Próximamente podrás abonar con PayPal. Por ahora utiliza MercadoPago."
        )
        return mensaje, {}

    def check_payment_status(self, external_reference: str) -> str:
        return (
            "La confirmación automática de PayPal todavía no está disponible."
        )
