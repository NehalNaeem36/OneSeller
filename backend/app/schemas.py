from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


# ---------- public grading API (contract: do not change) ----------
class ChatRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=128)
    thread_id: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=4000)


class TokenUsage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    in_: int = Field(0, alias="in")
    out: int = 0


class ChatResponse(BaseModel):
    reply: str
    tool_calls: list[dict] = []
    tokens: TokenUsage


# ---------- auth ----------
class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=120)
    role: Literal["customer", "seller"]
    store_name: str | None = Field(default=None, max_length=120)

    @field_validator("full_name", "store_name")
    @classmethod
    def strip(cls, v):
        return v.strip() if isinstance(v, str) else v


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: str
    role: str
    full_name: str
    phone: str | None = None
    address: str | None = None
    city: str | None = None
    postal_code: str | None = None


class AuthOut(BaseModel):
    token: str
    user: UserOut
    store_slug: str | None = None


class ProfileIn(BaseModel):
    full_name: str | None = Field(default=None, max_length=120)
    phone: str | None = Field(default=None, max_length=40)
    address: str | None = Field(default=None, max_length=300)
    city: str | None = Field(default=None, max_length=80)
    postal_code: str | None = Field(default=None, max_length=20)


# ---------- catalog ----------
class ProductIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    category: str = Field(min_length=1, max_length=80)
    price: float = Field(gt=0, le=10_000_000)
    stock: int = Field(ge=0, le=1_000_000)
    colors: list[str] = []
    sizes: list[str] = []
    sku: str | None = Field(default=None, max_length=64)
    image_id: int | None = None
    is_active: bool = True


class ProductUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    category: str | None = Field(default=None, min_length=1, max_length=80)
    price: float | None = Field(default=None, gt=0, le=10_000_000)
    stock: int | None = Field(default=None, ge=0, le=1_000_000)
    colors: list[str] | None = None
    sizes: list[str] | None = None
    sku: str | None = Field(default=None, max_length=64)
    image_id: int | None = None
    is_active: bool | None = None


class BulkAction(BaseModel):
    product_ids: list[int] = Field(min_length=1, max_length=500)
    action: Literal["soft_delete", "restore", "set_stock", "adjust_price_percent", "set_category"]
    value: float | str | None = None


class StoreUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    tagline: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=3000)
    brand_color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    logo_image_id: int | None = None


# ---------- cart / checkout ----------
class CartItemIn(BaseModel):
    product_id: int
    quantity: int = Field(default=1, ge=1, le=100)
    color: str | None = Field(default=None, max_length=40)
    size: str | None = Field(default=None, max_length=20)


class CartItemUpdate(BaseModel):
    quantity: int = Field(ge=1, le=100)


class DeliveryIn(BaseModel):
    customer_name: str = Field(min_length=1, max_length=120)
    phone: str = Field(min_length=5, max_length=40)
    address: str = Field(min_length=5, max_length=300)
    city: str = Field(min_length=2, max_length=80)
    postal_code: str | None = Field(default=None, max_length=20)


class CheckoutIn(BaseModel):
    delivery: DeliveryIn
    confirm: bool = False
    save_details: bool = True


class OrderStatusUpdate(BaseModel):
    status: Literal["processing", "shipped", "delivered", "cancelled"]


class PayIn(BaseModel):
    plan: Literal["standard", "premium"]


class AuthChatIn(BaseModel):
    thread_id: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=4000)


class MemoryOut(BaseModel):
    key: str
    value: str
    updated_at: datetime | None = None
