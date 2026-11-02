"""Disponibilidad para el mapa sin exponer información de otros compradores."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from nexopass import schema as s
from nexopass.availability import get_event_availability, get_zone_seats
from test_integrity import add, data, db, engine, seed


def publish(connection, data):
    connection.execute(update(s.events).where(s.events.c.id == data["event"]).values(status="published"))


def unit(connection, data, number, enabled=True):
    return add(connection, s.inventory_units, event_id=data["event"], zone_id=data["zone"],
               mode="seated", unit_number=number, row_label="A", seat_label=str(number), enabled=enabled)


def test_mixed_states_and_zone_counts(db, data):
    publish(db, data)
    held = unit(db, data, 2)
    sold = unit(db, data, 3)
    unit(db, data, 4, enabled=False)
    for unit_id, status in ((held, "held"), (sold, "committed")):
        add(db, s.allocations, event_id=data["event"], reservation_id=data["reservation"],
            inventory_unit_id=unit_id, status=status)
    seats = get_zone_seats(db, data["event"], data["zone"])
    assert [seat["status"] for seat in seats] == ["available", "reserved", "sold", "blocked"]
    assert [seat["can_select"] for seat in seats] == [True, False, False, False]
    assert [seat["seat_label"] for seat in seats] == ["1", "2", "3", "4"]
    zone = get_event_availability(db, data["event"])["zones"][0]
    assert [zone[key] for key in ("capacity", "available", "reserved", "sold", "blocked")] == [4, 1, 1, 1, 1]
    assert zone["can_select"]
    for seat in seats:
        assert not ({"buyer_id", "email", "reservation_id", "full_name"} & seat.keys())


def test_released_hold_becomes_available(db, data):
    publish(db, data)
    allocation = add(db, s.allocations, event_id=data["event"], reservation_id=data["reservation"], inventory_unit_id=data["unit"])
    assert get_zone_seats(db, data["event"], data["zone"])[0]["status"] == "reserved"
    db.execute(update(s.allocations).where(s.allocations.c.id == allocation).values(status="released"))
    seat = get_zone_seats(db, data["event"], data["zone"])[0]
    assert seat["status"] == "available" and seat["can_select"]


def test_expired_reservation_not_falsely_available_until_release(db, data):
    add(db, s.allocations, event_id=data["event"], reservation_id=data["reservation"], inventory_unit_id=data["unit"])
    now = datetime.now(timezone.utc)
    db.execute(update(s.reservations).where(s.reservations.c.id == data["reservation"]).values(
        status="expired", created_at=now - timedelta(minutes=20), expires_at=now - timedelta(minutes=10)))
    assert get_zone_seats(db, data["event"], data["zone"])[0]["status"] == "reserved"
    assert get_event_availability(db, data["event"])["zones"][0]["available"] == 0


@pytest.mark.parametrize("status", ["draft", "cancelled", "finished"])
def test_non_sale_event_cannot_select_free_seat(db, data, status):
    db.execute(update(s.events).where(s.events.c.id == data["event"]).values(status=status))
    result = get_event_availability(db, data["event"])
    assert not result["sales_open"] and not result["zones"][0]["can_select"]
    seat = get_zone_seats(db, data["event"], data["zone"])[0]
    assert seat["status"] == "available" and not seat["can_select"]


def test_closed_sale_window_cannot_select(db, data):
    publish(db, data)
    now = datetime.now(timezone.utc)
    db.execute(update(s.events).where(s.events.c.id == data["event"]).values(
        sales_open_at=now - timedelta(days=2), sales_close_at=now - timedelta(days=1)))
    assert not get_zone_seats(db, data["event"], data["zone"])[0]["can_select"]


def test_general_admission_has_capacity_not_fictitious_seats(db):
    data = seed(db, mode="general")
    publish(db, data)
    assert get_zone_seats(db, data["event"], data["zone"]) == []
    zone = get_event_availability(db, data["event"])["zones"][0]
    assert zone["mode"] == "general" and zone["capacity"] == zone["available"] == 1


def test_empty_zone_is_visible_but_not_selectable(db, data):
    publish(db, data)
    zone_id = add(db, s.zones, event_id=data["event"], name="Platinum", mode="general", price=100,
                  currency="HNL", display_order=0)
    db.execute(update(s.zones).where(s.zones.c.id == data["zone"]).values(display_order=1))
    result = get_event_availability(db, data["event"])
    assert result["zones"][0]["id"] == zone_id
    assert result["zones"][0]["capacity"] == 0 and not result["zones"][0]["can_select"]


def test_unknown_and_other_event_zone_are_not_exposed(db, data):
    other = seed(db)
    assert get_event_availability(db, uuid4()) is None
    assert get_zone_seats(db, data["event"], other["zone"]) == []


@pytest.mark.parametrize("table", [s.zones, s.inventory_units])
@pytest.mark.parametrize("x,y", [(Decimal("1.1"), Decimal("0.5")), (None, Decimal("0.5"))])
def test_invalid_map_positions_rejected(db, data, table, x, y):
    entity = data["zone"] if table is s.zones else data["unit"]
    with pytest.raises(IntegrityError), db.begin_nested():
        db.execute(update(table).where(table.c.id == entity).values(map_x=x, map_y=y))


def test_map_coordinates_survive_query(db, data):
    db.execute(update(s.zones).where(s.zones.c.id == data["zone"]).values(map_x=Decimal("0.25"), map_y=Decimal("0.50")))
    db.execute(update(s.inventory_units).where(s.inventory_units.c.id == data["unit"]).values(map_x=Decimal("0.75"), map_y=Decimal("0.10")))
    zone = get_event_availability(db, data["event"])["zones"][0]
    seat = get_zone_seats(db, data["event"], data["zone"])[0]
    assert (zone["map_x"], zone["map_y"]) == (Decimal("0.25"), Decimal("0.50"))
    assert (seat["map_x"], seat["map_y"]) == (Decimal("0.75"), Decimal("0.10"))
