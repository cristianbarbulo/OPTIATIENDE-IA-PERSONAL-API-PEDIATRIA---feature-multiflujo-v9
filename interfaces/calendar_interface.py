class CalendarInterface:
    """Interface for calendar service implementations."""

    def get_available_slots(self, date_range: tuple, time_preference: str | None = None) -> list:
        """Return available slots within the given range.

        Args:
            date_range: Tuple of start and end datetimes.
            time_preference: Optional part of the day (e.g. "manana", "tarde").
        """
        raise NotImplementedError

    def create_event(self, client_name: str, slot: dict) -> str:
        """Create an event for the given client and slot.

        Returns the created event ID.
        """
        raise NotImplementedError

    def reschedule_event(self, event_id: str, new_slot: dict) -> bool:
        """Reschedule an existing event. Returns True on success."""
        raise NotImplementedError

    def cancel_event(self, event_id: str) -> bool:
        """Cancel an existing event. Returns True on success."""
        raise NotImplementedError

    def get_event(self, event_id: str) -> dict | None:
        """Get an existing event by its ID. Returns the event dict or None if not found."""
        raise NotImplementedError
