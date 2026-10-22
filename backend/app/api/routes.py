from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
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
    SourceHealth,
    Subscription,
)
from app.notify.email import notifications_enabled
from app.schemas import AdvisoryOut, FeedResponse, SubscriptionCreate, SubscriptionOut
from app.sources import SOURCES, STALE_AFTER_HOURS, coverage_status

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
        needle = "%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        filters.append(
            or_(
                Advisory.brand_or_chain.ilike(needle, escape="\\"),
                Advisory.reason.ilike(needle, escape="\\"),
                Advisory.description.ilike(needle, escape="\\"),
                Advisory.product_description.ilike(needle, escape="\\"),
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
    q: str = Query(..., min_length=1, description="Product, brand or hazard"),
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
    """Search product names, firms and hazards using the same feed filters."""
    if not q.strip():
        raise HTTPException(status_code=422, detail="Enter a product, brand or hazard.")
    return list_advisories(
        db=db, category=category, type=type, status=status, q=q, limit=limit, offset=offset
    )


@router.get("/advisories/{advisory_id}", response_model=AdvisoryOut)
def advisory_detail(advisory_id: int, db: Session = Depends(get_db)) -> Advisory:
    advisory = db.get(Advisory, advisory_id)
    if advisory is None:
        raise HTTPException(status_code=404, detail="Advisory not found.")
    return advisory


@router.get("/sources")
def source_coverage(db: Session = Depends(get_db)) -> dict:
    now = datetime.now(UTC)
    health = {row.source_key: row for row in db.scalars(select(SourceHealth))}
    counts = {
        (agency, kind): count for agency, kind, count in db.execute(
            select(Advisory.source_agency, Advisory.type, func.count()).group_by(
                Advisory.source_agency, Advisory.type
            )
        )
    }
    sources = []
    for key, definition in SOURCES.items():
        row = health.get(key)
        success = row.last_success_at if row else None
        sources.append({
            "key": key, **definition,
            "last_attempt_at": row.last_attempt_at if row else None,
            "last_success_at": success,
            "outcome": row.outcome if row else None,
            "status": coverage_status(
                success, row.outcome if row else None, now, row.last_attempt_at if row else None
            ),
            "record_count": counts.get((definition["agency"], definition["type"]), 0),
            "last_fetch_count": row.last_record_count if row else None,
        })
    return {"checked_at": now, "stale_after_hours": STALE_AFTER_HOURS, "sources": sources}


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


@router.get("/config")
def config() -> dict[str, bool]:
    """What this deployment can actually do.

    The frontend reads this to decide whether to offer the subscribe form.
    Without a mail provider configured there is nothing to offer, and asking
    for an address anyway would be collecting personal data under a promise the
    deployment cannot keep.
    """
    return {"notifications_enabled": notifications_enabled()}


@router.post("/subscriptions", response_model=SubscriptionOut, status_code=201)
def create_subscription(
    payload: SubscriptionCreate, db: Session = Depends(get_db)
) -> Subscription:
    """Subscribe an email address to new matching advisories.

    Re-subscribing with the same email and filters returns the existing row
    rather than creating a duplicate, so a double-submitted form does not cause
    duplicate emails.
    """
    # Refuse rather than store an address that will never be written to. The
    # UI hides the form in this state, so reaching here means a direct API call
    # or a stale page.
    if not notifications_enabled():
        raise HTTPException(
            status_code=503,
            detail=(
                "Email notifications are not enabled on this deployment, so "
                "subscriptions are not being accepted. No address was stored."
            ),
        )

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
