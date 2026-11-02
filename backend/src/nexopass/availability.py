"""Consultas para el futuro mapa; no crean reservas ni autorizan compras.

La disponibilidad es una fotografía. La compra revalida inventario con bloqueo.
No se exponen compradores, asistentes, correos ni identificadores de reservas.
"""
from uuid import UUID

from sqlalchemy import and_, case, func, select
from sqlalchemy.engine import Connection

from nexopass.schema import allocations, events, inventory_units, zones


def _availability(event_id: UUID):
    live = allocations.alias("live_allocation")
    status = case(
        (live.c.status == "committed", "sold"),
        (live.c.status == "held", "reserved"),
        (~inventory_units.c.enabled, "blocked"),
        else_="available",
    )
    return select(
        inventory_units.c.id.label("unit_id"), inventory_units.c.zone_id,
        inventory_units.c.unit_number, inventory_units.c.row_label,
        inventory_units.c.seat_label, inventory_units.c.mode,
        inventory_units.c.enabled, inventory_units.c.map_x, inventory_units.c.map_y,
        status.label("status"),
    ).select_from(inventory_units.outerjoin(live, and_(
        live.c.inventory_unit_id == inventory_units.c.id,
        live.c.status.in_(("held", "committed")),
    ))).where(inventory_units.c.event_id == event_id).subquery("availability")


def _sales_open():
    return and_(events.c.status == "published", events.c.sales_open_at <= func.now(),
                events.c.sales_close_at > func.now())


def get_event_availability(connection: Connection, event_id: UUID) -> dict | None:
    """Resumen de todas las zonas, incluidas las vacías o agotadas.

    capacity es inventario configurado, también el bloqueado. available solo
    describe ocupación; can_select exige adicionalmente que la venta esté abierta.
    """
    event = connection.execute(select(
        events.c.id, events.c.name, events.c.status, events.c.poster_url,
        _sales_open().label("sales_open"),
    ).where(events.c.id == event_id)).mappings().one_or_none()
    if event is None:
        return None
    available = _availability(event_id)
    counts = select(
        available.c.zone_id,
        func.count().label("capacity"),
        *[func.count().filter(available.c.status == state).label(state)
          for state in ("available", "reserved", "sold", "blocked")],
    ).group_by(available.c.zone_id).subquery("zone_counts")
    query = select(
        zones.c.id, zones.c.name, zones.c.mode, zones.c.price, zones.c.currency,
        zones.c.benefits, zones.c.image_url, zones.c.map_x, zones.c.map_y, zones.c.display_order,
        *[func.coalesce(counts.c[name], 0).label(name)
          for name in ("capacity", "available", "reserved", "sold", "blocked")],
    ).select_from(zones.outerjoin(counts, zones.c.id == counts.c.zone_id)).where(
        zones.c.event_id == event_id,
    ).order_by(zones.c.display_order, zones.c.name, zones.c.id)
    result = dict(event)
    result["zones"] = []
    for row in connection.execute(query).mappings():
        zone = dict(row)
        zone["can_select"] = bool(event["sales_open"] and zone["available"] > 0)
        result["zones"].append(zone)
    return result


def get_zone_seats(connection: Connection, event_id: UUID, zone_id: UUID) -> list[dict]:
    """Asientos numerados de una zona del evento. General se muestra por cupos.

    Los cupos internos de admisión general nunca se presentan como sillas.
    """
    available = _availability(event_id)
    query = select(
        available.c.unit_id, available.c.zone_id, available.c.unit_number,
        available.c.row_label, available.c.seat_label, available.c.enabled,
        available.c.map_x, available.c.map_y, available.c.status,
        and_(available.c.status == "available", _sales_open()).label("can_select"),
    ).select_from(available.join(zones, available.c.zone_id == zones.c.id).join(
        events, zones.c.event_id == events.c.id,
    )).where(zones.c.id == zone_id, zones.c.event_id == event_id,
             available.c.mode == "seated").order_by(available.c.unit_number)
    return [dict(row) for row in connection.execute(query).mappings()]
