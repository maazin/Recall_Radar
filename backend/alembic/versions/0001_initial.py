"""Create advisories and subscriptions tables.

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "advisories",
        sa.Column("id", sa.Integer(), primary_key=True),
        # Dedupe/diff key: "<AGENCY>:<agency record id>".
        sa.Column("source_uid", sa.Text(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("source_agency", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("brand_or_chain", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=True),
        sa.Column(
            "states_affected",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("started_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        # Required: must resolve to the original agency record.
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.UniqueConstraint("source_uid", name="uq_advisories_source_uid"),
    )
    op.create_index("ix_advisories_started_at", "advisories", ["started_at"])
    op.create_index("ix_advisories_category", "advisories", ["category"])
    op.create_index("ix_advisories_type", "advisories", ["type"])
    op.create_index("ix_advisories_status", "advisories", ["status"])

    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("category_filter", sa.Text(), nullable=True),
        sa.Column("keyword_filter", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
    )
    op.create_index("ix_subscriptions_email", "subscriptions", ["email"])


def downgrade() -> None:
    op.drop_index("ix_subscriptions_email", table_name="subscriptions")
    op.drop_table("subscriptions")
    for index in (
        "ix_advisories_status",
        "ix_advisories_type",
        "ix_advisories_category",
        "ix_advisories_started_at",
    ):
        op.drop_index(index, table_name="advisories")
    op.drop_table("advisories")
