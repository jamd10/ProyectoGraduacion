"""Modelo relacional PostgreSQL. Los permisos y transiciones requieren servicios.

Las unidades de inventario representan asientos o cupos individuales de una zona.
La unicidad parcial protege la asignación; vencer requiere liberar explícitamente.
"""

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Column, DateTime, ForeignKey,
    ForeignKeyConstraint, Index, Integer, LargeBinary, MetaData, Numeric,
    String, Table, Text, UniqueConstraint, Uuid, false, func, text,
)
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData(naming_convention={
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
})


def pk():
    return Column("id", Uuid, primary_key=True, server_default=text("gen_random_uuid()"))


def created():
    return Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now())


def state_check(values):
    return CheckConstraint("status IN (" + ", ".join(repr(v) for v in values) + ")", name="status")


users = Table(
    "users", metadata, pk(),
    Column("email", String(254), nullable=False),
    Column("full_name", String(200), nullable=False),
    Column("password_hash", Text, nullable=False),
    Column("avatar_url", Text),
    Column("email_verified_at", DateTime(timezone=True)),
    Column("disabled_at", DateTime(timezone=True)), created(),
    CheckConstraint("email = lower(btrim(email)) AND position('@' in email) > 1", name="email_normalized"),
    UniqueConstraint("email"),
)
roles = Table("roles", metadata, Column("code", String(32), primary_key=True))
user_roles = Table(
    "user_roles", metadata,
    Column("user_id", Uuid, ForeignKey("users.id"), primary_key=True),
    Column("role_code", String(32), ForeignKey("roles.code"), primary_key=True),
    Column("granted_by", Uuid, ForeignKey("users.id")), created(),
)
wallets = Table(
    "wallets", metadata, pk(),
    Column("user_id", Uuid, ForeignKey("users.id"), nullable=False, index=True),
    Column("address", String(42), nullable=False, unique=True),
    Column("kind", String(16), nullable=False),
    Column("verified_at", DateTime(timezone=True)),
    Column("revoked_at", DateTime(timezone=True)), created(),
    CheckConstraint("address ~ '^0x[0-9a-f]{40}$'", name="address"),
    CheckConstraint("kind IN ('embedded', 'external')", name="kind"),
)
venues = Table(
    "venues", metadata, pk(), Column("name", String(200), nullable=False),
    Column("city", String(120), nullable=False), Column("address", Text, nullable=False),
    Column("timezone", String(80), nullable=False),
    Column("image_url", Text), Column("seating_map_url", Text), created(),
)
events = Table(
    "events", metadata, pk(),
    Column("venue_id", Uuid, ForeignKey("venues.id"), nullable=False, index=True),
    Column("name", String(200), nullable=False), Column("description", Text, nullable=False),
    Column("poster_url", Text), Column("starts_at", DateTime(timezone=True), nullable=False),
    Column("ends_at", DateTime(timezone=True), nullable=False),
    Column("doors_open_at", DateTime(timezone=True), nullable=False),
    Column("sales_open_at", DateTime(timezone=True), nullable=False),
    Column("sales_close_at", DateTime(timezone=True), nullable=False),
    Column("transfer_deadline", DateTime(timezone=True), nullable=False),
    Column("status", String(16), nullable=False, server_default="draft"), created(),
    state_check(["draft", "published", "cancelled", "finished"]),
    CheckConstraint("ends_at > starts_at AND doors_open_at <= starts_at", name="event_times"),
    CheckConstraint("sales_open_at < sales_close_at AND sales_close_at <= starts_at", name="sale_times"),
    CheckConstraint("transfer_deadline <= starts_at - interval '24 hours'", name="transfer_deadline"),
)
event_staff = Table(
    "event_staff", metadata,
    Column("event_id", Uuid, ForeignKey("events.id"), primary_key=True),
    Column("user_id", Uuid, ForeignKey("users.id"), primary_key=True), created(),
)
zones = Table(
    "zones", metadata, pk(), Column("event_id", Uuid, ForeignKey("events.id"), nullable=False),
    Column("name", String(120), nullable=False), Column("mode", String(16), nullable=False),
    Column("price", Numeric(12, 2), nullable=False), Column("currency", String(3), nullable=False),
    Column("benefits", Text), Column("image_url", Text),
    Column("map_x", Numeric(7, 6)), Column("map_y", Numeric(7, 6)),
    Column("display_order", Integer, nullable=False, server_default="0"), created(),
    CheckConstraint("display_order >= 0", name="display_order"),
    CheckConstraint("(map_x IS NULL AND map_y IS NULL) OR (map_x IS NOT NULL AND map_y IS NOT NULL AND map_x BETWEEN 0 AND 1 AND map_y BETWEEN 0 AND 1)", name="map_position"),
    CheckConstraint("mode IN ('seated', 'general')", name="mode"),
    CheckConstraint("price >= 0", name="price"),
    CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency"),
    UniqueConstraint("event_id", "name"), UniqueConstraint("id", "event_id", "mode"),
)
inventory_units = Table(
    "inventory_units", metadata, pk(), Column("event_id", Uuid, nullable=False),
    Column("zone_id", Uuid, nullable=False), Column("mode", String(16), nullable=False),
    Column("unit_number", Integer, nullable=False), Column("row_label", String(20)),
    Column("seat_label", String(20)), Column("enabled", Boolean, nullable=False, server_default=text("true")),
    Column("map_x", Numeric(7, 6)), Column("map_y", Numeric(7, 6)),
    CheckConstraint("(map_x IS NULL AND map_y IS NULL) OR (map_x IS NOT NULL AND map_y IS NOT NULL AND map_x BETWEEN 0 AND 1 AND map_y BETWEEN 0 AND 1)", name="map_position"),
    ForeignKeyConstraint(["zone_id", "event_id", "mode"], ["zones.id", "zones.event_id", "zones.mode"]),
    UniqueConstraint("zone_id", "unit_number"), UniqueConstraint("zone_id", "row_label", "seat_label"),
    UniqueConstraint("id", "event_id"),
    CheckConstraint("unit_number > 0", name="number"),
    CheckConstraint("(mode = 'seated' AND row_label IS NOT NULL AND seat_label IS NOT NULL) OR "
                    "(mode = 'general' AND row_label IS NULL AND seat_label IS NULL)", name="seat_mode"),
)
reservations = Table(
    "reservations", metadata, pk(),
    Column("buyer_id", Uuid, ForeignKey("users.id"), nullable=False, index=True),
    Column("event_id", Uuid, ForeignKey("events.id"), nullable=False, index=True),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("status", String(16), nullable=False, server_default="active"), created(),
    state_check(["active", "committed", "expired", "cancelled"]),
    CheckConstraint("expires_at > created_at", name="expiry"),
    UniqueConstraint("id", "event_id"), UniqueConstraint("id", "event_id", "buyer_id"),
)
allocations = Table(
    "allocations", metadata, pk(), Column("reservation_id", Uuid, nullable=False),
    Column("event_id", Uuid, nullable=False), Column("inventory_unit_id", Uuid, nullable=False),
    Column("status", String(16), nullable=False, server_default="held"), created(),
    ForeignKeyConstraint(["reservation_id", "event_id"], ["reservations.id", "reservations.event_id"]),
    ForeignKeyConstraint(["inventory_unit_id", "event_id"], ["inventory_units.id", "inventory_units.event_id"]),
    UniqueConstraint("id", "event_id", "reservation_id"),
    state_check(["held", "committed", "released"]),
)
Index("uq_allocations_live_unit", allocations.c.inventory_unit_id, unique=True,
      postgresql_where=text("status IN ('held', 'committed')"))
orders = Table(
    "orders", metadata, pk(), Column("reservation_id", Uuid, nullable=False, unique=True),
    Column("event_id", Uuid, nullable=False), Column("buyer_id", Uuid, nullable=False),
    Column("idempotency_key", Uuid, nullable=False), Column("currency", String(3), nullable=False),
    Column("total", Numeric(12, 2), nullable=False),
    Column("status", String(24), nullable=False, server_default="pending_payment"), created(),
    ForeignKeyConstraint(["reservation_id", "event_id", "buyer_id"],
                         ["reservations.id", "reservations.event_id", "reservations.buyer_id"]),
    UniqueConstraint("buyer_id", "idempotency_key"),
    UniqueConstraint("id", "event_id", "reservation_id", "currency"), UniqueConstraint("id", "currency"),
    CheckConstraint("total >= 0", name="total"),
    CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency"),
    state_check(["pending_payment", "paid", "cancelled", "reversed"]),
)
order_items = Table(
    "order_items", metadata, pk(), Column("order_id", Uuid, nullable=False),
    Column("event_id", Uuid, nullable=False), Column("reservation_id", Uuid, nullable=False),
    Column("allocation_id", Uuid, nullable=False, unique=True),
    Column("currency", String(3), nullable=False), Column("unit_price", Numeric(12, 2), nullable=False),
    Column("fee", Numeric(12, 2), nullable=False, server_default="0"),
    ForeignKeyConstraint(["order_id", "event_id", "reservation_id", "currency"],
                         ["orders.id", "orders.event_id", "orders.reservation_id", "orders.currency"]),
    ForeignKeyConstraint(["allocation_id", "event_id", "reservation_id"],
                         ["allocations.id", "allocations.event_id", "allocations.reservation_id"]),
    UniqueConstraint("id", "event_id"), CheckConstraint("unit_price >= 0 AND fee >= 0", name="amounts"),
)
payments = Table(
    "payments", metadata, pk(), Column("order_id", Uuid, nullable=False),
    Column("currency", String(3), nullable=False), Column("amount", Numeric(12, 2), nullable=False),
    Column("method", String(16), nullable=False), Column("reference", Uuid, nullable=False, unique=True),
    Column("status", String(16), nullable=False, server_default="pending"), created(),
    ForeignKeyConstraint(["order_id", "currency"], ["orders.id", "orders.currency"]),
    CheckConstraint("amount >= 0", name="amount"),
    CheckConstraint("method IN ('card_demo', 'crypto_demo')", name="method"),
    state_check(["pending", "approved", "rejected", "reversed"]),
)
Index("uq_payments_live_order", payments.c.order_id, unique=True,
      postgresql_where=text("status IN ('pending', 'approved')"))
tickets = Table(
    "tickets", metadata, pk(), Column("order_item_id", Uuid, nullable=False, unique=True),
    Column("event_id", Uuid, nullable=False),
    Column("expected_wallet_id", Uuid, ForeignKey("wallets.id"), nullable=False),
    Column("status", String(16), nullable=False, server_default="pending_mint"),
    Column("nomination_version", Integer, nullable=False, server_default="1"),
    Column("transfer_count", Integer, nullable=False, server_default="0"),
    Column("credential_version", Integer, nullable=False, server_default="1"),
    Column("used_at", DateTime(timezone=True)), created(),
    ForeignKeyConstraint(["order_item_id", "event_id"], ["order_items.id", "order_items.event_id"]),
    UniqueConstraint("id", "event_id"),
    state_check(["pending_mint", "active", "used", "cancelled"]),
    CheckConstraint("transfer_count BETWEEN 0 AND 1", name="transfer_limit"),
    CheckConstraint("nomination_version > 0 AND credential_version > 0", name="versions"),
    CheckConstraint("(status = 'used') = (used_at IS NOT NULL)", name="used_time"),
)
nominations = Table(
    "nominations", metadata,
    Column("ticket_id", Uuid, ForeignKey("tickets.id"), primary_key=True),
    Column("version", Integer, primary_key=True),
    Column("user_id", Uuid, ForeignKey("users.id")),
    Column("full_name", String(200), nullable=False), Column("email", String(254), nullable=False),
    Column("document_type", String(24), nullable=False),
    Column("document_ciphertext", LargeBinary, nullable=False),
    Column("document_last_four", String(4), nullable=False),
    Column("encryption_key_version", Integer, nullable=False), created(),
    CheckConstraint("version > 0 AND encryption_key_version > 0", name="versions"),
    CheckConstraint("email = lower(btrim(email)) AND position('@' in email) > 1", name="email_normalized"),
)
# Diferida: permite insertar boleto y nominación en una sola transacción.
tickets.append_constraint(ForeignKeyConstraint(
    ["id", "nomination_version"], ["nominations.ticket_id", "nominations.version"],
    name="fk_tickets_current_nomination", use_alter=True, deferrable=True, initially="DEFERRED",
))
transfers = Table(
    "transfers", metadata, pk(), Column("ticket_id", Uuid, ForeignKey("tickets.id"), nullable=False),
    Column("requested_by", Uuid, ForeignKey("users.id"), nullable=False),
    Column("from_nomination_version", Integer, nullable=False),
    Column("recipient_email", String(254), nullable=False),
    Column("recipient_user_id", Uuid, ForeignKey("users.id")),
    Column("target_wallet_id", Uuid, ForeignKey("wallets.id")),
    Column("holder_authorized_at", DateTime(timezone=True)),
    Column("owner_authorized_at", DateTime(timezone=True)),
    Column("recipient_accepted_at", DateTime(timezone=True)),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("status", String(16), nullable=False, server_default="invited"), created(),
    ForeignKeyConstraint(["ticket_id", "from_nomination_version"], ["nominations.ticket_id", "nominations.version"]),
    state_check(["invited", "accepted", "submitted", "confirmed", "rejected", "expired", "cancelled", "failed"]),
    CheckConstraint("expires_at > created_at", name="expiry"),
    CheckConstraint("recipient_email = lower(btrim(recipient_email)) AND position('@' in recipient_email) > 1", name="email_normalized"),
    CheckConstraint("status NOT IN ('accepted', 'submitted', 'confirmed') OR "
                    "(recipient_user_id IS NOT NULL AND target_wallet_id IS NOT NULL AND "
                    "holder_authorized_at IS NOT NULL AND owner_authorized_at IS NOT NULL AND "
                    "recipient_accepted_at IS NOT NULL)", name="acceptance"),
)
Index("uq_transfers_live_ticket", transfers.c.ticket_id, unique=True,
      postgresql_where=text("status IN ('invited', 'accepted', 'submitted', 'confirmed')"))
chain_operations = Table(
    "chain_operations", metadata, pk(),
    Column("ticket_id", Uuid, ForeignKey("tickets.id"), nullable=False, index=True),
    Column("kind", String(16), nullable=False), Column("idempotency_key", Uuid, nullable=False, unique=True),
    Column("chain_id", BigInteger, nullable=False), Column("contract_address", String(42), nullable=False),
    Column("tx_hash", String(66)), Column("block_number", BigInteger), Column("block_hash", String(66)),
    Column("status", String(16), nullable=False, server_default="queued"),
    Column("failure_code", String(80)), created(),
    CheckConstraint("kind IN ('mint', 'transfer', 'consume', 'cancel', 'recover')", name="kind"),
    CheckConstraint("chain_id > 0", name="chain_id"),
    CheckConstraint("contract_address ~ '^0x[0-9a-f]{40}$'", name="address"),
    CheckConstraint("tx_hash IS NULL OR tx_hash ~ '^0x[0-9a-f]{64}$'", name="tx_hash"),
    CheckConstraint("status NOT IN ('submitted', 'confirmed') OR tx_hash IS NOT NULL", name="submitted_tx"),
    CheckConstraint("status != 'confirmed' OR (block_number IS NOT NULL AND block_hash IS NOT NULL)", name="confirmation"),
    state_check(["queued", "submitted", "confirmed", "failed", "orphaned"]),
    UniqueConstraint("chain_id", "tx_hash"), UniqueConstraint("id", "ticket_id", "kind"),
)
Index("uq_chain_operations_live_ticket", chain_operations.c.ticket_id, unique=True,
      postgresql_where=text("status IN ('queued', 'submitted')"))
Index("uq_chain_operations_confirmed_mint", chain_operations.c.ticket_id, unique=True,
      postgresql_where=text("kind = 'mint' AND status = 'confirmed'"))
nft_bindings = Table(
    "nft_bindings", metadata, Column("ticket_id", Uuid, ForeignKey("tickets.id"), primary_key=True),
    Column("chain_id", BigInteger, nullable=False), Column("contract_address", String(42), nullable=False),
    Column("token_id", Numeric(78, 0), nullable=False),
    CheckConstraint("chain_id > 0", name="chain_id"),
    CheckConstraint("contract_address ~ '^0x[0-9a-f]{40}$'", name="address"),
    CheckConstraint("token_id >= 0 AND token_id < power(2::numeric, 256)", name="token_id"),
    UniqueConstraint("chain_id", "contract_address", "token_id"),
)
credentials = Table(
    "credentials", metadata, pk(), Column("token_hash", LargeBinary, nullable=False, unique=True),
    Column("purpose", String(24), nullable=False),
    Column("user_id", Uuid, ForeignKey("users.id")),
    Column("ticket_id", Uuid, ForeignKey("tickets.id")),
    Column("transfer_id", Uuid, ForeignKey("transfers.id")),
    Column("credential_version", Integer), Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("consumed_at", DateTime(timezone=True)), Column("revoked_at", DateTime(timezone=True)), created(),
    CheckConstraint("octet_length(token_hash) = 32", name="token_hash"),
    CheckConstraint("expires_at > created_at", name="expiry"),
    CheckConstraint("purpose IN ('verify_email', 'reset_password', 'ticket_view', 'entry_qr', 'transfer_authorize')", name="purpose"),
    CheckConstraint("(purpose IN ('verify_email', 'reset_password') AND user_id IS NOT NULL AND ticket_id IS NULL AND transfer_id IS NULL) OR "
                    "(purpose IN ('ticket_view', 'entry_qr') AND ticket_id IS NOT NULL AND transfer_id IS NULL AND credential_version IS NOT NULL AND credential_version > 0) OR "
                    "(purpose = 'transfer_authorize' AND transfer_id IS NOT NULL AND ticket_id IS NOT NULL)", name="scope"),
)
admission_attempts = Table(
    "admission_attempts", metadata, pk(), Column("ticket_id", Uuid, nullable=False),
    Column("event_id", Uuid, nullable=False), Column("staff_id", Uuid, nullable=False),
    Column("credential_version", Integer, nullable=False), Column("nomination_version", Integer, nullable=False),
    Column("identity_matched", Boolean, nullable=False),
    Column("chain_operation_id", Uuid, unique=True), Column("operation_kind", String(16), nullable=False, server_default="consume"),
    Column("status", String(16), nullable=False), Column("reason_code", String(80)), created(),
    ForeignKeyConstraint(["ticket_id", "event_id"], ["tickets.id", "tickets.event_id"]),
    ForeignKeyConstraint(["event_id", "staff_id"], ["event_staff.event_id", "event_staff.user_id"]),
    ForeignKeyConstraint(["ticket_id", "nomination_version"], ["nominations.ticket_id", "nominations.version"]),
    ForeignKeyConstraint(["chain_operation_id", "ticket_id", "operation_kind"], ["chain_operations.id", "chain_operations.ticket_id", "chain_operations.kind"]),
    CheckConstraint("operation_kind = 'consume'", name="operation_kind"),
    state_check(["pending", "confirmed", "denied", "failed"]),
    CheckConstraint("status NOT IN ('pending', 'confirmed') OR "
                    "(identity_matched AND chain_operation_id IS NOT NULL)", name="identity_and_chain"),
)
Index("uq_admission_attempts_live_ticket", admission_attempts.c.ticket_id, unique=True,
      postgresql_where=text("status IN ('pending', 'confirmed')"))
outbox = Table(
    "outbox", metadata, pk(), Column("ticket_id", Uuid, ForeignKey("tickets.id")),
    Column("order_id", Uuid, ForeignKey("orders.id")),
    Column("kind", String(40), nullable=False), Column("deduplication_key", String(160), nullable=False, unique=True),
    Column("status", String(16), nullable=False, server_default="pending"),
    Column("attempts", Integer, nullable=False, server_default="0"),
    Column("available_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("sent_at", DateTime(timezone=True)), created(),
    state_check(["pending", "processing", "sent", "failed"]),
    CheckConstraint("attempts >= 0", name="attempts"),
    CheckConstraint("num_nonnulls(ticket_id, order_id) = 1", name="subject"),
)
audit_entries = Table(
    "audit_entries", metadata, pk(), Column("actor_user_id", Uuid, ForeignKey("users.id")),
    Column("action", String(80), nullable=False), Column("entity_type", String(40), nullable=False),
    Column("entity_id", Uuid, nullable=False), Column("request_id", Uuid, nullable=False),
    Column("details", JSONB, nullable=False, server_default=text("'{}'::jsonb")), created(),
)
Index("ix_audit_entries_entity", audit_entries.c.entity_type, audit_entries.c.entity_id)
