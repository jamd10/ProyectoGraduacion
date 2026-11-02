"""Revocar acceso del personal sin eliminar su historial de validaciones.

Revision ID: 0006
Revises: 0005
"""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("event_staff", sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column("event_staff", "disabled_at")
