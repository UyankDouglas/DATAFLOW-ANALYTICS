from typing import Any

from pydantic import BaseModel, ConfigDict


class APIModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Any = None


class ErrorResponse(BaseModel):
    error: ErrorBody
    request_id: str | None = None


class Page[T](BaseModel):
    items: list[T]
    total: int
    page: int
    page_size: int


class Message(BaseModel):
    message: str
