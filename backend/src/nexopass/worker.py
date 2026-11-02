"""Trabajador recuperable para blockchain, expiración y entrega de correo."""
import asyncio
from datetime import timedelta
from email.message import EmailMessage
import logging
import secrets
import smtplib
from types import SimpleNamespace

from sqlalchemy import select, update, and_, func, text
from web3 import Web3

from nexopass import schema as s
from nexopass.chain import ChainClient, reference, token_number
from nexopass.commerce import expire_reservations
from nexopass.mail import queue_mail
from nexopass.security import cipher, digest, now, audit

logger = logging.getLogger(__name__)


def context(settings):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=settings)))


def deliver_mail(settings, engine):
    if not settings.smtp_host:
        return
    with engine.begin() as connection:
        messages = connection.execute(select(s.email_messages).where(s.email_messages.c.status == "pending", s.email_messages.c.attempts < 5)
            .order_by(s.email_messages.c.created_at).limit(5).with_for_update(skip_locked=True)).mappings().all()
        for row in messages:
            try:
                message = EmailMessage()
                message["From"] = settings.smtp_sender
                message["To"] = row["recipient"]
                message["Subject"] = row["subject"]
                message.set_content(cipher(context(settings)).decrypt(row["encrypted_body"]).decode())
                with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
                    if settings.smtp_starttls:
                        import ssl
                        smtp.starttls(context=ssl.create_default_context())
                    if settings.smtp_user:
                        smtp.login(settings.smtp_user, settings.smtp_password.get_secret_value() if settings.smtp_password else "")
                    smtp.send_message(message)
                connection.execute(update(s.email_messages).where(s.email_messages.c.id == row["id"]).values(status="sent", attempts=row["attempts"]+1))
            except Exception:
                logger.warning("mail_delivery_failed")
                connection.execute(update(s.email_messages).where(s.email_messages.c.id == row["id"]).values(attempts=row["attempts"]+1))


def operation_data(engine, operation):
    with engine.connect() as connection:
        ticket = dict(connection.execute(select(s.tickets).where(s.tickets.c.id == operation["ticket_id"])).mappings().one())
        event = dict(connection.execute(select(s.events).where(s.events.c.id == ticket["event_id"])).mappings().one())
        wallet = dict(connection.execute(select(s.wallets).where(s.wallets.c.id == ticket["expected_wallet_id"])).mappings().one())
        unit = connection.execute(select(s.allocations.c.inventory_unit_id).join(s.order_items, s.order_items.c.allocation_id == s.allocations.c.id)
            .where(s.order_items.c.id == ticket["order_item_id"])).scalar_one()
        transfer = None
        if operation["kind"] == "transfer":
            transfer = connection.execute(select(s.transfers).where(s.transfers.c.ticket_id == ticket["id"],
                s.transfers.c.status.in_(["accepted", "submitted"]))).mappings().one_or_none()
            if transfer:
                transfer = dict(transfer)
                transfer["address"] = connection.execute(select(s.wallets.c.address).where(s.wallets.c.id == transfer["target_wallet_id"])).scalar_one()
        return ticket, event, wallet, unit, transfer


def fail_operation(engine, operation, code):
    with engine.begin() as connection:
        connection.execute(update(s.chain_operations).where(s.chain_operations.c.id == operation["id"]).values(status="failed", failure_code=code))
        if operation["kind"] == "transfer":
            connection.execute(update(s.transfers).where(s.transfers.c.ticket_id == operation["ticket_id"], s.transfers.c.status.in_(["accepted", "submitted"])).values(status="failed"))
        if operation["kind"] == "consume":
            connection.execute(update(s.admission_attempts).where(s.admission_attempts.c.chain_operation_id == operation["id"]).values(status="failed", reason_code=code))


def confirm(settings, engine, chain, operation, receipt):
    ticket_id = operation["ticket_id"]
    chain_ticket = chain.contract.functions.tickets(token_number(ticket_id)).call()
    owner = chain.contract.functions.ownerOf(token_number(ticket_id)).call().lower()
    with engine.begin() as connection:
        ticket = connection.execute(select(s.tickets).where(s.tickets.c.id == ticket_id).with_for_update()).mappings().one()
        wallet = connection.execute(select(s.wallets).where(s.wallets.c.id == ticket["expected_wallet_id"])).mappings().one()
        if operation["kind"] == "mint":
            if owner != wallet["address"] or chain_ticket[0] != reference(ticket["event_id"]):
                raise RuntimeError("Emisión incompatible")
            from sqlalchemy.dialects.postgresql import insert
            connection.execute(insert(s.nft_bindings).values(ticket_id=ticket_id, chain_id=settings.chain_id,
                contract_address=chain.contract.address.lower(), token_id=token_number(ticket_id)).on_conflict_do_nothing())
            connection.execute(update(s.tickets).where(s.tickets.c.id == ticket_id).values(status="active", suspended=False))
            nomination = connection.execute(select(s.nominations).where(s.nominations.c.ticket_id == ticket_id, s.nominations.c.version == ticket["nomination_version"])).mappings().one()
            event = connection.execute(select(s.events).where(s.events.c.id == ticket["event_id"])).mappings().one()
            token = secrets.token_urlsafe(32)
            connection.execute(s.credentials.insert().values(token_hash=digest(token), purpose="ticket_view", ticket_id=ticket_id,
                credential_version=ticket["credential_version"], expires_at=max(event["ends_at"], now()+timedelta(days=1))))
            queue_mail(connection, context(settings), nomination["email"], "Tu boleto NexoPass está confirmado",
                "Boleto: " + str(ticket_id) + "\nConcierto: " + event["name"] + "\nAsistente: " + nomination["full_name"] +
                "\nNFT confirmado en la red de pruebas. Presenta tu documento y abre el QR vigente:\n" + settings.public_url + "/guest?token=" + token)
        elif operation["kind"] == "transfer":
            transfer = connection.execute(select(s.transfers).where(s.transfers.c.ticket_id == ticket_id, s.transfers.c.status == "submitted")).mappings().one()
            target = connection.execute(select(s.wallets.c.address).where(s.wallets.c.id == transfer["target_wallet_id"])).scalar_one()
            if owner != target or chain_ticket[2] != transfer["from_nomination_version"]+1 or chain_ticket[3] != 1:
                raise RuntimeError("Transferencia incompatible")
            connection.execute(update(s.tickets).where(s.tickets.c.id == ticket_id).values(expected_wallet_id=transfer["target_wallet_id"],
                nomination_version=chain_ticket[2], transfer_count=1, credential_version=ticket["credential_version"]+1, suspended=False))
            connection.execute(update(s.transfers).where(s.transfers.c.id == transfer["id"]).values(status="confirmed"))
            connection.execute(update(s.credentials).where(s.credentials.c.ticket_id == ticket_id).values(revoked_at=now()))
            queue_mail(connection, context(settings), transfer["recipient_email"], "Transferencia confirmada",
                "Tu boleto ya está en Mis boletos. El QR anterior dejó de ser válido.\n" + settings.public_url + "/tickets")
            old_email = connection.execute(select(s.users.c.email).where(s.users.c.id == transfer["requested_by"])).scalar_one()
            queue_mail(connection, context(settings), old_email, "Boleto transferido", "El boleto " + str(ticket_id) + " cambió de titular. Tu acceso anterior fue invalidado.")
        elif operation["kind"] == "consume":
            if not chain_ticket[4] or owner != wallet["address"] or chain_ticket[2] != ticket["nomination_version"]:
                raise RuntimeError("Consumo incompatible")
            connection.execute(update(s.tickets).where(s.tickets.c.id == ticket_id).values(status="used", used_at=now()))
            connection.execute(update(s.admission_attempts).where(s.admission_attempts.c.chain_operation_id == operation["id"]).values(status="confirmed"))
            connection.execute(update(s.credentials).where(s.credentials.c.ticket_id == ticket_id, s.credentials.c.purpose == "entry_qr").values(consumed_at=now()))
        connection.execute(update(s.chain_operations).where(s.chain_operations.c.id == operation["id"]).values(status="confirmed", failure_code=None,
            block_number=receipt["blockNumber"], block_hash=Web3.to_hex(receipt["blockHash"])))
        audit(connection, None, "blockchain."+operation["kind"]+".confirmed", ticket_id)


def process_operation(settings, engine, chain, operation):
    ticket, event, wallet, unit, transfer = operation_data(engine, operation)
    if event["status"] == "cancelled":
        fail_operation(engine, operation, "event_cancelled")
        return
    if operation["status"] == "queued":
        if operation["kind"] == "mint":
            tx = chain.mint(ticket["id"], event, unit, wallet["address"])
        elif operation["kind"] == "transfer":
            if not transfer or not wallet["encrypted_private_key"]:
                fail_operation(engine, operation, "owner_authorization_missing")
                return
            tx = chain.transfer(ticket, transfer["address"], cipher(context(settings)).decrypt(wallet["encrypted_private_key"]), operation["id"])
        elif operation["kind"] == "consume":
            tx = chain.consume(ticket, wallet["address"], operation["id"])
        else:
            fail_operation(engine, operation, "unsupported_operation")
            return
        if not tx:
            raise RuntimeError("No se obtuvo una transacción")
        with engine.begin() as connection:
            connection.execute(update(s.chain_operations).where(s.chain_operations.c.id == operation["id"]).values(status="submitted", tx_hash=tx,
                contract_address=chain.contract.address.lower(), failure_code=None))
            if transfer:
                connection.execute(update(s.transfers).where(s.transfers.c.id == transfer["id"]).values(status="submitted"))
        operation = {**operation, "status": "submitted", "tx_hash": tx}
    receipt = chain.receipt(operation["tx_hash"])
    if not receipt:
        return
    if receipt["status"] != 1:
        fail_operation(engine, operation, "transaction_reverted")
        return
    confirmations = 1 if settings.chain_id == 31337 else 6
    if chain.web3.eth.block_number - receipt["blockNumber"] + 1 < confirmations:
        return
    if chain.web3.eth.get_block(receipt["blockNumber"])["hash"] != receipt["blockHash"]:
        return
    confirm(settings, engine, chain, operation, receipt)


def tick(settings, engine):
    with engine.connect() as lease:
        locked = lease.execute(text("SELECT pg_try_advisory_lock(168504211)")).scalar_one()
        lease.commit()
        if not locked:
            return
        try:
            with engine.begin() as connection:
                expire_reservations(connection)
                connection.execute(update(s.transfers).where(s.transfers.c.status == "invited", s.transfers.c.expires_at < func.now()).values(status="expired"))
                operations = [dict(row) for row in connection.execute(select(s.chain_operations).where(s.chain_operations.c.status.in_(["queued", "submitted"]))
                    .order_by(s.chain_operations.c.created_at).limit(20)).mappings()]
                cancellations = [dict(row) for row in connection.execute(select(s.events).where(s.events.c.status == "cancelled")).mappings()]
                recent = [dict(row) for row in connection.execute(select(s.chain_operations).where(s.chain_operations.c.status == "confirmed").order_by(s.chain_operations.c.created_at.desc()).limit(50)).mappings()]
            deliver_mail(settings, engine)
            if not operations and not cancellations and not recent:
                return
            try:
                chain = ChainClient(settings)
            except Exception:
                logger.warning("blockchain_temporarily_unavailable")
                return
            for confirmed in recent:
                try:
                    canonical = Web3.to_hex(chain.web3.eth.get_block(confirmed["block_number"])["hash"])
                except Exception:
                    continue
                if canonical != confirmed["block_hash"]:
                    with engine.begin() as connection:
                        connection.execute(update(s.chain_operations).where(s.chain_operations.c.id == confirmed["id"]).values(status="orphaned", failure_code="chain_reorganization"))
                        connection.execute(update(s.tickets).where(s.tickets.c.id == confirmed["ticket_id"]).values(suspended=True))
                        audit(connection, None, "blockchain.reorganization", confirmed["ticket_id"])
            for operation in operations:
                try:
                    process_operation(settings, engine, chain, operation)
                except Exception:
                    logger.warning("blockchain_operation_pending")
                    with engine.begin() as connection:
                        connection.execute(update(s.chain_operations).where(s.chain_operations.c.id == operation["id"]).values(failure_code="awaiting_reconciliation"))
            for event in cancellations:
                try:
                    info = chain.contract.functions.events(reference(event["id"])).call()
                    if info[0] and not info[4]:
                        chain.wait(chain.send(chain.contract.functions.cancelEvent(reference(event["id"]))))
                    with engine.begin() as connection:
                        connection.execute(update(s.tickets).where(s.tickets.c.event_id == event["id"], s.tickets.c.status != "used").values(status="cancelled"))
                        order_ids = select(s.orders.c.id).where(s.orders.c.event_id == event["id"])
                        connection.execute(update(s.payments).where(s.payments.c.order_id.in_(order_ids), s.payments.c.status == "approved").values(status="reversed"))
                        connection.execute(update(s.orders).where(s.orders.c.event_id == event["id"], s.orders.c.status == "paid").values(status="reversed"))
                except Exception:
                    logger.warning("event_cancellation_pending")
        finally:
            lease.execute(text("SELECT pg_advisory_unlock(168504211)"))
            lease.commit()


async def run_worker(settings, engine):
    while True:
        try:
            await asyncio.to_thread(tick, settings, engine)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("worker_cycle_failed")
        await asyncio.sleep(2)
