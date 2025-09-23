from interfaces.calendar_interface import CalendarInterface


class CalendlyService(CalendarInterface):
    """Placeholder Calendly service."""

    def get_available_slots(self, date_range: tuple) -> list:
        raise NotImplementedError

    def create_event(self, client_name: str, slot: dict) -> str:
        raise NotImplementedError

    def reschedule_event(self, event_id: str, new_slot: dict) -> bool:
        raise NotImplementedError

    def cancel_event(self, event_id: str) -> bool:
        raise NotImplementedError

    def get_event(self, event_id: str) -> dict | None:
        """Obtiene un evento específico por su ID."""
        raise NotImplementedError
