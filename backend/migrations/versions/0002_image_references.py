"""Referencias opcionales a imágenes de perfiles, recintos y zonas.

Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("avatar_url", sa.Text(), nullable=True))
    op.add_column("venues", sa.Column("image_url", sa.Text(), nullable=True))
    op.add_column("venues", sa.Column("seating_map_url", sa.Text(), nullable=True))
    op.add_column("zones", sa.Column("image_url", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("zones", "image_url")
    op.drop_column("venues", "seating_map_url")
    op.drop_column("venues", "image_url")
    op.drop_column("users", "avatar_url")
