from pydantic import BaseModel, ConfigDict
from app.schemas.product import ProductResponse


class AddToWishlistPayload(BaseModel):
    product_id: str


class WishlistItemResponseSchema(BaseModel):
    id: str
    product: ProductResponse

    model_config = ConfigDict(from_attributes=True)


class WishlistCountResponse(BaseModel):
    count: int


class SyncWishlistPayload(BaseModel):
    product_ids: list[str] = []

