from config import CALENDAR_PROVIDER


def get_calendar_service():
    if CALENDAR_PROVIDER == "GOOGLE":
        from calendar_services.google_calendar_service import GoogleCalendarService
        return GoogleCalendarService()
    elif CALENDAR_PROVIDER == "GOOGLE_APPOINTMENTS":
        # Modo Citas sin fallback. Si falla, debe escalar a humano aguas arriba.
        from calendar_services.google_appointments_service import GoogleAppointmentsService
        return GoogleAppointmentsService()
    elif CALENDAR_PROVIDER == "CALENDLY":
        from calendar_services.calendly_service import CalendlyService
        return CalendlyService()
    raise Exception("Calendario no soportado")


def get_payment_service(provider: str):
    if provider == "MERCADOPAGO":
        from payment_services.mercado_pago_service import MercadoPagoService
        return MercadoPagoService()
    elif provider == "MODO":
        from payment_services.modo_service import ModoService
        return ModoService()
    elif provider == "PAYPAL":
        from payment_services.paypal_service import PayPalService
        return PayPalService()
    else:
        raise ValueError(f"Proveedor de pago no soportado: {provider}")
