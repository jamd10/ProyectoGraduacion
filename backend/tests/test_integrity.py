"""Integridad real en PostgreSQL migrado, nunca sobre una base de desarrollo.

NEXOPASS_TEST_DATABASE_URL debe apuntar a una base aislada nexopass_test_*.
No sustituye las pruebas futuras de permisos, API ni contrato.
"""
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, insert, select, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from nexopass import schema as s


@pytest.fixture(scope="session")
def engine():
    url = os.environ.get("NEXOPASS_TEST_DATABASE_URL")
    if not url:
        pytest.fail("Falta NEXOPASS_TEST_DATABASE_URL para una base aislada ya migrada.")
    parsed = make_url(url)
    if parsed.get_backend_name() != "postgresql" or not (parsed.database or "").startswith("nexopass_test_"):
        pytest.fail("Las pruebas requieren PostgreSQL y una base nexopass_test_*.")
    engine = create_engine(url, hide_parameters=True)
    yield engine
    engine.dispose()


def add(connection, table, **values):
    return connection.execute(insert(table).values(**values).returning(table.c.id)).scalar_one()


def seed(connection, mode="seated"):
    now = datetime.now(timezone.utc)
    buyer = add(connection, s.users, email=f"{uuid4()}@example.test", full_name="Asistente de prueba", password_hash="test-only")
    wallet = add(connection, s.wallets, user_id=buyer, address="0x" + uuid4().hex + uuid4().hex[:8], kind="embedded")
    venue = add(connection, s.venues, name="Recinto de prueba", city="Ciudad", address="Prueba", timezone="America/Tegucigalpa")
    event = add(connection, s.events, venue_id=venue, name="Evento de prueba", description="Prueba",
                starts_at=now + timedelta(days=10), ends_at=now + timedelta(days=10, hours=4),
                doors_open_at=now + timedelta(days=10, hours=-1), sales_open_at=now,
                sales_close_at=now + timedelta(days=9), transfer_deadline=now + timedelta(days=9))
    zone = add(connection, s.zones, event_id=event, name="VIP", mode=mode, price=Decimal("100.10"), currency="HNL")
    unit = add(connection, s.inventory_units, event_id=event, zone_id=zone, mode=mode, unit_number=1,
               row_label="A" if mode == "seated" else None, seat_label="1" if mode == "seated" else None)
    reservation = add(connection, s.reservations, buyer_id=buyer, event_id=event, expires_at=now + timedelta(minutes=10))
    return dict(buyer=buyer, wallet=wallet, event=event, zone=zone, unit=unit, reservation=reservation)


def order(connection, data):
    allocation = add(connection, s.allocations, reservation_id=data["reservation"], event_id=data["event"], inventory_unit_id=data["unit"])
    order_id = add(connection, s.orders, reservation_id=data["reservation"], event_id=data["event"], buyer_id=data["buyer"],
                   idempotency_key=uuid4(), currency="HNL", total=Decimal("100.10"))
    item = add(connection, s.order_items, order_id=order_id, event_id=data["event"], reservation_id=data["reservation"],
               allocation_id=allocation, currency="HNL", unit_price=Decimal("100.10"))
    return order_id, item


def ticket(connection, data):
    order_id, item = order(connection, data)
    ticket_id = add(connection, s.tickets, order_item_id=item, event_id=data["event"], expected_wallet_id=data["wallet"])
    connection.execute(insert(s.nominations).values(ticket_id=ticket_id, version=1, full_name="Persona de prueba",
        email="person@example.test", document_type="TEST", document_ciphertext=b"test-ciphertext-not-real-data",
        document_last_four="0000", encryption_key_version=1))
    return ticket_id


@pytest.fixture
def db(engine):
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            yield connection
        finally:
            transaction.rollback()


@pytest.fixture
def data(db):
    return seed(db)


def test_no_double_allocation(db, data):
    add(db, s.allocations, reservation_id=data["reservation"], event_id=data["event"], inventory_unit_id=data["unit"])
    with pytest.raises(IntegrityError), db.begin_nested():
        add(db, s.allocations, reservation_id=data["reservation"], event_id=data["event"], inventory_unit_id=data["unit"])


def test_release_allows_new_reservation(db, data):
    allocation = add(db, s.allocations, reservation_id=data["reservation"], event_id=data["event"], inventory_unit_id=data["unit"])
    db.execute(update(s.allocations).where(s.allocations.c.id == allocation).values(status="released"))
    add(db, s.allocations, reservation_id=data["reservation"], event_id=data["event"], inventory_unit_id=data["unit"])


@pytest.mark.parametrize("mode", ["seated", "general"])
def test_parallel_buyers_only_one_allocation(engine, mode):
    # Datos únicos confirmados para que las dos conexiones vean el mismo inventario.
    with engine.begin() as connection:
        data = seed(connection, mode)
        reservation2 = add(connection, s.reservations, buyer_id=data["buyer"], event_id=data["event"],
                           expires_at=datetime.now(timezone.utc) + timedelta(minutes=10))
    barrier = Barrier(2)

    def reserve(reservation_id):
        with engine.connect() as connection:
            with connection.begin():
                connection.exec_driver_sql("SET LOCAL lock_timeout = '5s'")
                barrier.wait(timeout=5)
                try:
                    add(connection, s.allocations, reservation_id=reservation_id, event_id=data["event"], inventory_unit_id=data["unit"])
                    return "won"
                except IntegrityError:
                    return "rejected"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(reserve, [data["reservation"], reservation2]))
    assert sorted(results) == ["rejected", "won"]


def test_cannot_allocate_unit_from_other_event(db, data):
    other = seed(db)
    with pytest.raises(IntegrityError), db.begin_nested():
        add(db, s.allocations, reservation_id=data["reservation"], event_id=data["event"], inventory_unit_id=other["unit"])


def test_seated_unit_requires_row_and_seat(db, data):
    with pytest.raises(IntegrityError), db.begin_nested():
        add(db, s.inventory_units, event_id=data["event"], zone_id=data["zone"], mode="seated", unit_number=2)


def test_order_buyer_must_own_reservation(db, data):
    other = seed(db)
    with pytest.raises(IntegrityError), db.begin_nested():
        add(db, s.orders, reservation_id=data["reservation"], event_id=data["event"], buyer_id=other["buyer"],
            idempotency_key=uuid4(), currency="HNL", total=0)


def test_only_one_active_payment_and_exact_decimal(db, data):
    order_id, _ = order(db, data)
    payment = add(db, s.payments, order_id=order_id, currency="HNL", amount=Decimal("100.10"), method="card_demo", reference=uuid4())
    assert db.execute(select(s.payments.c.amount).where(s.payments.c.id == payment)).scalar_one() == Decimal("100.10")
    with pytest.raises(IntegrityError), db.begin_nested():
        add(db, s.payments, order_id=order_id, currency="HNL", amount=Decimal("100.10"), method="crypto_demo", reference=uuid4())


def test_ticket_requires_current_nomination(db, data):
    _, item = order(db, data)
    with pytest.raises(IntegrityError), db.begin_nested():
        add(db, s.tickets, order_item_id=item, event_id=data["event"], expected_wallet_id=data["wallet"])
        db.exec_driver_sql("SET CONSTRAINTS fk_tickets_current_nomination IMMEDIATE")


def test_nomination_and_ticket_can_be_created_atomically(db, data):
    ticket(db, data)
    db.exec_driver_sql("SET CONSTRAINTS fk_tickets_current_nomination IMMEDIATE")


def test_transfer_count_cannot_exceed_one(db, data):
    ticket_id = ticket(db, data)
    with pytest.raises(IntegrityError), db.begin_nested():
        db.execute(update(s.tickets).where(s.tickets.c.id == ticket_id).values(transfer_count=2))


def test_accepted_transfer_requires_authorizations(db, data):
    ticket_id = ticket(db, data)
    with pytest.raises(IntegrityError), db.begin_nested():
        add(db, s.transfers, ticket_id=ticket_id, requested_by=data["buyer"], from_nomination_version=1,
            recipient_email="recipient@example.test", status="accepted",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1))


def test_only_one_inflight_chain_operation(db, data):
    ticket_id = ticket(db, data)
    values = dict(ticket_id=ticket_id, kind="mint", chain_id=31337, contract_address="0x" + "a" * 40)
    add(db, s.chain_operations, **values, idempotency_key=uuid4())
    with pytest.raises(IntegrityError), db.begin_nested():
        add(db, s.chain_operations, **values, idempotency_key=uuid4())


def test_entry_qr_requires_version(db, data):
    ticket_id = ticket(db, data)
    with pytest.raises(IntegrityError), db.begin_nested():
        add(db, s.credentials, token_hash=bytes(32), purpose="entry_qr", ticket_id=ticket_id,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5))


def test_mismatched_identity_cannot_authorize_entry(db, data):
    ticket_id = ticket(db, data)
    db.execute(insert(s.event_staff).values(event_id=data["event"], user_id=data["buyer"]))
    operation = add(db, s.chain_operations, ticket_id=ticket_id, kind="consume", idempotency_key=uuid4(),
                    chain_id=31337, contract_address="0x" + "a" * 40)
    with pytest.raises(IntegrityError), db.begin_nested():
        add(db, s.admission_attempts, ticket_id=ticket_id, event_id=data["event"], staff_id=data["buyer"],
            credential_version=1, nomination_version=1, identity_matched=False, chain_operation_id=operation, status="confirmed")


def test_mint_cannot_be_used_as_entry_confirmation(db, data):
    ticket_id = ticket(db, data)
    db.execute(insert(s.event_staff).values(event_id=data["event"], user_id=data["buyer"]))
    operation = add(db, s.chain_operations, ticket_id=ticket_id, kind="mint", idempotency_key=uuid4(),
                    chain_id=31337, contract_address="0x" + "a" * 40)
    with pytest.raises(IntegrityError), db.begin_nested():
        add(db, s.admission_attempts, ticket_id=ticket_id, event_id=data["event"], staff_id=data["buyer"],
            credential_version=1, nomination_version=1, identity_matched=True, chain_operation_id=operation, status="confirmed")


def test_confirmed_entry_cannot_be_registered_twice(db, data):
    ticket_id = ticket(db, data)
    db.execute(insert(s.event_staff).values(event_id=data["event"], user_id=data["buyer"]))
    operation = add(db, s.chain_operations, ticket_id=ticket_id, kind="consume", idempotency_key=uuid4(),
                    chain_id=31337, contract_address="0x" + "a" * 40)
    values = dict(ticket_id=ticket_id, event_id=data["event"], staff_id=data["buyer"], credential_version=1,
                  nomination_version=1, identity_matched=True, chain_operation_id=operation, status="pending")
    add(db, s.admission_attempts, **values)
    with pytest.raises(IntegrityError), db.begin_nested():
        add(db, s.admission_attempts, **values)
