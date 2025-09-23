class PaymentInterface:
    """Interface for payment service implementations."""

    def create_payment_link(self, payment_data: dict) -> tuple[str, dict]:
        """Create a payment link.

        Returns a tuple with a user-facing message and a context dictionary.
        """
        raise NotImplementedError

    def check_payment_status(self, external_reference: str) -> str:
        """Check the payment status for the given reference."""
        raise NotImplementedError
