from abc import ABC, abstractmethod


class WebhookVerifier(ABC):
    """
    Abstract interface for webhook authenticity and signature verification.
    Separates cryptographic signature checking from domain reconciliation logic.
    """

    @abstractmethod
    def verify_signature(
        self,
        payload_bytes: bytes,
        signature_header: str,
        secret_key: str,
    ) -> bool:
        """
        Verifies that the incoming raw payload was authentically signed by the provider.
        Returns True if valid, False otherwise.
        """
        pass
