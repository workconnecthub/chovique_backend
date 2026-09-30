from abc import abstractmethod
from decimal import Decimal
from typing import Optional, Dict, Any
from app.services.shipping.base import BaseShippingProvider


class CourierProvider(BaseShippingProvider):
    """Abstract base for third-party courier aggregators."""

    @abstractmethod
    def provider_name(self) -> str:
        pass
