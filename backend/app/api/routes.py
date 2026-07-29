from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import (
    CATEGORY_GROCERY,
    CATEGORY_RESTAURANT,
    STATUS_ACTIVE,
    STATUS_RESOLVED,
    TYPE_OUTBREAK,
    TYPE_RECALL,
    Advisory,
    Subscription,
)
from app.schemas import AdvisoryOut, FeedResponse, SubscriptionCreate, SubscriptionOut

router = APIRouter(prefix="/api")


def _ordered(statement):
    """Most recent first. started_at is ISO-8601 text, which sorts correctly."""
    return statement.order_by(Advisory.started_at.desc(), Advisory.id.desc())


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/advisories", response_model=FeedResponse)
def list_advisories(
    db: Session = Depends(get_db),
    category: str | None = Query(
        None,
        description="Filter by category",
        pattern=f"^({CATEGORY_GROCERY}|{CATEGORY_RESTAURANT})$",
    ),
    type: str | None = Query(
        None, description="Filter by advisory type", pattern=f"^({TYPE_RECALL}|{TYPE_OUTBREAK})$"
    ),
    status: str | None = Query(
        None, description="Filter by status", pattern=f"^({STATUS_ACTIVE}|{STATUS_RESOLVED})$"
    ),
    q: str | None = Query(None, description="Free-text match across brand, reason and description"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> FeedResponse:
    """The unified feed: recalls and outbreak investigations together."""
    filters = []
    if category:
        filters.append(Advisory.category == category)
    if type:
        filters.append(Advisory.type == type)
    if status:
        filters.append(Advisory.status == status)
    if q and q.strip():
        needle = f"%{q.strip()}%"
        filters.append(
            or_(
                Advisory.brand_or_chain.ilike(needle),
                Advisory.reason.ilike(needle),
                Advisory.description.ilike(needle),
            )
        )

    total = db.scalar(select(func.count()).select_from(Advisory).where(*filters)) or 0
    rows = db.scalars(
        _ordered(select(Advisory).where(*filters)).limit(limit).offset(offset)
    ).all()

    return FeedResponse(
        total=total,
        limit=limit,
        offset=offset,
        items=[AdvisoryOut.model_validate(r) for r in rows],
    )


@router.get("/advisories/search", response_model=FeedResponse)
def search_advisories(
    q: str = Query(..., min_length=1, description="Brand or chain name"),
    db: Session = Depends(get_db),
    category: str | None = Query(
        None, pattern=f"^({CATEGORY_GROCERY}|{CATEGORY_RESTAURANT})$"
    ),
    type: str | None = Query(None, pattern=f"^({TYPE_RECALL}|{TYPE_OUTBREAK})$"),
    status: str | None = Query(
        None, pattern=f"^({STATUS_ACTIVE}|{STATUS_RESOLVED})$"
    ),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> FeedResponse:
    """Brand/chain lookup against `advisories.brand_or_chain`.

    The category/type/status filters compose with the search so the UI's filter
    controls keep working while a search is active.
    """
    filters = [Advisory.brand_or_chain.ilike(f"%{q.strip()}%")]
    if category:
        filters.append(Advisory.category == category)
    if type:
        filters.append(Advisory.type == type)
    if status:
        filters.append(Advisory.status == status)

    total = db.scalar(select(func.count()).select_from(Advisory).where(*filters)) or 0
    rows = db.scalars(
        _ordered(select(Advisory).where(*filters)).limit(limit).offset(offset)
    ).all()

    return FeedResponse(
        total=total,
        limit=limit,
        offset=offset,
        items=[AdvisoryOut.model_validate(r) for r in rows],
    )


@router.get("/stats")
def stats(db: Session = Depends(get_db)) -> dict[str, int]:
    """Counts used by the feed header."""

    def count(*filters) -> int:
        return db.scalar(select(func.count()).select_from(Advisory).where(*filters)) or 0

    return {
        "total": count(),
        "active": count(Advisory.status == STATUS_ACTIVE),
        "recalls": count(Advisory.type == TYPE_RECALL),
        "outbreaks": count(Advisory.type == TYPE_OUTBREAK),
        "grocery": count(Advisory.category == CATEGORY_GROCERY),
        "restaurant": count(Advisory.category == CATEGORY_RESTAURANT),
    }


@router.post("/subscriptions", response_model=SubscriptionOut, status_code=201)
def create_subscription(
    payload: SubscriptionCreate, db: Session = Depends(get_db)
) -> Subscription:
    """Subscribe an email address to new matching advisories.

    Re-subscribing with the same email and filters returns the existing row
    rather than creating a duplicate, so a double-submitted form does not cause
    duplicate emails.
    """
    existing = db.scalars(
        select(Subscription).where(
            Subscription.email == str(payload.email),
            Subscription.category_filter.is_not_distinct_from(payload.category_filter),
            Subscription.keyword_filter.is_not_distinct_from(payload.keyword_filter),
        )
    ).first()
    if existing:
        return existing

    subscription = Subscription(
        email=str(payload.email),
        category_filter=payload.category_filter,
        keyword_filter=payload.keyword_filter,
        created_at=datetime.now(UTC).date().isoformat(),
    )
    db.add(subscription)
    db.commit()
    db.refresh(subscription)
    return subscription
