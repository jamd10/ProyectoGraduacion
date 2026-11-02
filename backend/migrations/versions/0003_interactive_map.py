"""Posiciones opcionales para el mapa interactivo de zonas y asientos.

Revision ID: 0003
Revises: 0002
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    for table in ("zones", "inventory_units"):
        op.add_column(table, sa.Column("map_x", sa.Numeric(7, 6), nullable=True))
        op.add_column(table, sa.Column("map_y", sa.Numeric(7, 6), nullable=True))
        op.create_check_constraint(op.f(f"ck_{table}_map_position"), table,
            "(map_x IS NULL AND map_y IS NULL) OR "
            "(map_x IS NOT NULL AND map_y IS NOT NULL AND map_x BETWEEN 0 AND 1 AND map_y BETWEEN 0 AND 1)")
    op.add_column("zones", sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"))
    op.create_check_constraint(op.f("ck_zones_display_order"), "zones", "display_order >= 0")


def downgrade():
    op.drop_constraint(op.f("ck_zones_display_order"), "zones", type_="check")
    op.drop_column("zones", "display_order")
    for table in ("inventory_units", "zones"):
        op.drop_constraint(op.f(f"ck_{table}_map_position"), table, type_="check")
        op.drop_column(table, "map_y")
        op.drop_column(table, "map_x")
