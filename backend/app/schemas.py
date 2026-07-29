from __future__ import annotations

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator

from app.models import (
    CATEGORY_GROCERY,
    CATEGORY_RESTAURANT,
)

VALID_CATEGORIES = {CATEGORY_GROCERY, CATEGORY_RESTAURANT}


class AdvisoryOut(BaseModel):
    """An advisory as returned to the client.

    `source_agency` and `source_url` are non-optional in the response for the
    same reason they are non-null in the table: every card in the UI has to
    attribute its agency and link to the original record.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    type: str
    source_agency: str
    category: str
    brand_or_chain: str
    description: str
    reason: str
    severity: str | None
    states_affected: list[str]
    status: str
    started_at: str
    updated_at: str
    source_url: str


class FeedResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[AdvisoryOut]


class SubscriptionCreate(BaseModel):
    email: EmailStr
    category_filter: str | None = None
    keyword_filter: str | None = None

    @field_validator("category_filter")
    @classmethod
    def _valid_category(cls, value: str | None) -> str | None:
        if value in (None, ""):
            return None
        if value not in VALID_CATEGORIES:
            raise ValueError(
                f"category_filter must be one of {sorted(VALID_CATEGORIES)}"
            )
        return value

    @field_validator("keyword_filter")
    @classmethod
    def _clean_keyword(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class SubscriptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    category_filter: str | None
    keyword_filter: str | None
    created_at: str
