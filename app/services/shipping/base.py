from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Optional, Dict, Any


class BaseShippingProvider(ABC):

    @abstractmethod
    async def check_serviceability(
        self,
        origin_pincode: str,
        destination_pincode: str,
        **kwargs,
    ) -> Dict[str, Any]:
        """Check if destination pincode is serviceable."""
        pass

    @abstractmethod
    async def calculate_rate(
        self,
        origin_pincode: str,
        destination_pincode: str,
        subtotal: Decimal,
        **kwargs,
    ) -> Decimal:
        """Calculate the shipping fee."""
        pass
