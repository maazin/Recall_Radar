"""Track ingestion coverage and preserve structured recall details.

Revision ID: 0002
Revises: 0001
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    for name in ("product_description", "lot_codes", "distribution_pattern", "recall_number"):
        op.add_column("advisories", sa.Column(name, sa.Text(), nullable=True))
    op.create_table(
        "source_health",
        sa.Column("source_key", sa.Text(), primary_key=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("last_record_count", sa.Integer(), nullable=True),
    )


def downgrade():
    op.drop_table("source_health")
    for name in ("recall_number", "distribution_pattern", "lot_codes", "product_description"):
        op.drop_column("advisories", name)
