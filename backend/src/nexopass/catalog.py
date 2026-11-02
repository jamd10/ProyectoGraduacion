from datetime import datetime
from decimal import Decimal
from uuid import UUID
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from pydantic import BaseModel, Field, AwareDatetime, model_validator, EmailStr
from sqlalchemy import select, update, delete, func, and_, exists

from nexopass import schema as s
from nexopass.inputs import InputModel
from nexopass.security import db, current_user, admin_user, roles_for, audit, now
from nexopass.availability import get_event_availability, get_zone_seats

router = APIRouter(prefix="/api/v1", tags=["Events"])


class VenueInput(InputModel):
    name: str = Field(min_length=2, max_length=200)
    city: str = Field(min_length=2, max_length=120)
    address: str = Field(min_length=2, max_length=1000)
    timezone: str = "America/Tegucigalpa"


class EventInput(InputModel):
    venue_id: UUID
    name: str = Field(min_length=2, max_length=200)
    description: str = Field(min_length=5, max_length=10000)
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    doors_open_at: AwareDatetime
    sales_open_at: AwareDatetime
    sales_close_at: AwareDatetime
    transfer_deadline: AwareDatetime
    status: Literal["draft", "published"] = "draft"

    @model_validator(mode="after")
    def dates(self):
        from datetime import timedelta
        if not (self.ends_at > self.starts_at >= self.doors_open_at and
                self.sales_open_at < self.sales_close_at <= self.starts_at and
                self.transfer_deadline <= self.starts_at - timedelta(hours=24)):
            raise ValueError("Revisa los horarios de venta, ingreso y transferencia")
        return self


class ZoneInput(InputModel):
    name: str = Field(min_length=2, max_length=120)
    mode: Literal["seated", "general"]
    price: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    currency: str = Field(default="HNL", pattern="^[A-Z]{3}$")
    capacity: int = Field(ge=1, le=3000)
    seats_per_row: int = Field(default=10, ge=1, le=100)
    benefits: str = Field(default="", max_length=2000)
    display_order: int = Field(default=0, ge=0)


class BlockInput(InputModel):
    enabled: bool


class PositionInput(InputModel):
    x: Decimal = Field(ge=0, le=1, decimal_places=6)
    y: Decimal = Field(ge=0, le=1, decimal_places=6)


class StaffInput(InputModel):
    email: EmailStr


def require_event(connection, event_id):
    row = connection.execute(select(s.events).where(s.events.c.id == event_id)).mappings().one_or_none()
    if not row:
        raise HTTPException(404, "Concierto no encontrado")
    return row


@router.get("/events")
def events(search: str = "", city: str = "", connection=Depends(db)):
    query = select(s.events, s.venues.c.name.label("venue_name"), s.venues.c.city).join(s.venues).where(
        s.events.c.status == "published", s.events.c.ends_at > func.now())
    if search:
        query = query.where(s.events.c.name.ilike("%" + search[:100] + "%"))
    if city:
        query = query.where(s.venues.c.city.ilike("%" + city[:100] + "%"))
    return list(connection.execute(query.order_by(s.events.c.starts_at).limit(100)).mappings())


@router.get("/events/{event_id}")
def event(event_id: UUID, connection=Depends(db)):
    row = require_event(connection, event_id)
    if row["status"] != "published":
        raise HTTPException(404, "Concierto no disponible")
    result = dict(row)
    result["venue"] = dict(connection.execute(select(s.venues).where(s.venues.c.id == row["venue_id"])).mappings().one())
    result["availability"] = get_event_availability(connection, event_id)
    return result


@router.get("/events/{event_id}/zones/{zone_id}/seats")
def seats(event_id: UUID, zone_id: UUID, connection=Depends(db)):
    if require_event(connection, event_id)["status"] != "published":
        raise HTTPException(404, "Concierto no disponible")
    return get_zone_seats(connection, event_id, zone_id)


@router.get("/admin/venues")
def admin_venues(user=Depends(admin_user), connection=Depends(db)):
    return list(connection.execute(select(s.venues).order_by(s.venues.c.name)).mappings())


@router.post("/admin/venues", status_code=201)
def create_venue(body: VenueInput, user=Depends(admin_user), connection=Depends(db)):
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    try:
        ZoneInfo(body.timezone)
    except ZoneInfoNotFoundError:
        raise HTTPException(422, "Zona horaria inválida")
    return dict(connection.execute(s.venues.insert().values(**body.model_dump()).returning(s.venues)).mappings().one())


@router.delete("/admin/venues/{venue_id}")
def delete_venue(venue_id: UUID, user=Depends(admin_user), connection=Depends(db)):
    if connection.execute(select(s.events.c.id).where(s.events.c.venue_id == venue_id).limit(1)).first():
        raise HTTPException(409, "El recinto tiene conciertos asociados")
    if not connection.execute(delete(s.venues).where(s.venues.c.id == venue_id)).rowcount:
        raise HTTPException(404, "Recinto no encontrado")
    return {"message": "Recinto eliminado"}


@router.get("/admin/events")
def admin_events(user=Depends(admin_user), connection=Depends(db)):
    return list(connection.execute(select(s.events).order_by(s.events.c.starts_at.desc())).mappings())


@router.post("/admin/events", status_code=201)
def create_event(body: EventInput, user=Depends(admin_user), connection=Depends(db)):
    result = connection.execute(s.events.insert().values(**body.model_dump()).returning(s.events)).mappings().one()
    audit(connection, user["id"], "event.created", result["id"], "event")
    return dict(result)


@router.put("/admin/events/{event_id}")
def update_event(event_id: UUID, body: EventInput, user=Depends(admin_user), connection=Depends(db)):
    current = connection.execute(select(s.events).where(s.events.c.id == event_id).with_for_update()).mappings().one_or_none()
    if not current:
        raise HTTPException(404, "Concierto no encontrado")
    has_orders = connection.execute(select(s.orders.c.id).where(s.orders.c.event_id == event_id).limit(1)).first()
    if has_orders and any(current[key] != value for key, value in body.model_dump().items() if key not in ("name", "description")):
        raise HTTPException(409, "Con ventas solo puedes editar nombre y descripción; reprogramar requiere revisión")
    if current["status"] in ("cancelled", "finished"):
        raise HTTPException(409, "El concierto ya está cerrado")
    connection.execute(update(s.events).where(s.events.c.id == event_id).values(**body.model_dump()))
    audit(connection, user["id"], "event.updated", event_id, "event")
    return {"message": "Concierto actualizado"}


@router.post("/admin/events/{event_id}/cancel")
def cancel_event(event_id: UUID, user=Depends(admin_user), connection=Depends(db)):
    require_event(connection, event_id)
    connection.execute(update(s.events).where(s.events.c.id == event_id).values(status="cancelled"))
    # La cancelación contractual se sincroniza por el trabajador de blockchain.
    audit(connection, user["id"], "event.cancelled", event_id, "event")
    return {"message": "Concierto cancelado; el ingreso queda deshabilitado"}


@router.get("/admin/events/{event_id}/zones")
def admin_zones(event_id: UUID, user=Depends(admin_user), connection=Depends(db)):
    require_event(connection, event_id)
    return get_event_availability(connection, event_id)


@router.post("/admin/events/{event_id}/zones", status_code=201)
def create_zone(event_id: UUID, body: ZoneInput, user=Depends(admin_user), connection=Depends(db)):
    require_event(connection, event_id)
    values = body.model_dump(exclude={"capacity", "seats_per_row"})
    zone = connection.execute(s.zones.insert().values(event_id=event_id, **values).returning(s.zones)).mappings().one()
    units = []
    for i in range(body.capacity):
        row, seat = divmod(i, body.seats_per_row)
        # Fila numérica evita colisiones después de Z y conserva numeración estable.
        units.append(dict(event_id=event_id, zone_id=zone["id"], mode=body.mode, unit_number=i+1,
            row_label=str(row+1) if body.mode == "seated" else None,
            seat_label=str(seat+1) if body.mode == "seated" else None,
            map_x=Decimal(str(round((seat+1)/(body.seats_per_row+1), 6))) if body.mode == "seated" else None,
            map_y=Decimal(str(round((row+1)/((body.capacity-1)//body.seats_per_row+2), 6))) if body.mode == "seated" else None))
    connection.execute(s.inventory_units.insert(), units)
    audit(connection, user["id"], "zone.created", zone["id"], "zone")
    return dict(zone)


@router.delete("/admin/zones/{zone_id}")
def delete_zone(zone_id: UUID, user=Depends(admin_user), connection=Depends(db)):
    units = list(connection.execute(select(s.inventory_units.c.id).where(s.inventory_units.c.zone_id == zone_id).with_for_update()).scalars())
    if connection.execute(select(s.allocations.c.id).where(s.allocations.c.inventory_unit_id.in_(units)).limit(1)).first():
        raise HTTPException(409, "La zona tiene historial de reservas; bloquea sus lugares en vez de eliminarla")
    connection.execute(delete(s.inventory_units).where(s.inventory_units.c.zone_id == zone_id))
    connection.execute(delete(s.zones).where(s.zones.c.id == zone_id))
    return {"message": "Zona eliminada"}


@router.patch("/admin/units/{unit_id}")
def block_unit(unit_id: UUID, body: BlockInput, user=Depends(admin_user), connection=Depends(db)):
    unit = connection.execute(select(s.inventory_units).where(s.inventory_units.c.id == unit_id).with_for_update()).mappings().one_or_none()
    if not unit:
        raise HTTPException(404, "Lugar no encontrado")
    if connection.execute(select(s.allocations.c.id).where(s.allocations.c.inventory_unit_id == unit_id,
        s.allocations.c.status.in_(["held", "committed"]))).first():
        raise HTTPException(409, "No puedes bloquear un lugar reservado o vendido")
    connection.execute(update(s.inventory_units).where(s.inventory_units.c.id == unit_id).values(enabled=body.enabled))
    audit(connection, user["id"], "inventory.enabled" if body.enabled else "inventory.blocked", unit_id, "inventory")
    return {"message": "Disponibilidad actualizada"}


@router.patch("/admin/zones/{zone_id}/position")
def position(zone_id: UUID, body: PositionInput, user=Depends(admin_user), connection=Depends(db)):
    if not connection.execute(update(s.zones).where(s.zones.c.id == zone_id).values(map_x=body.x, map_y=body.y)).rowcount:
        raise HTTPException(404, "Zona no encontrada")
    return {"message": "Posición guardada"}


@router.post("/admin/events/{event_id}/staff")
def assign_staff(event_id: UUID, body: StaffInput, user=Depends(admin_user), connection=Depends(db)):
    from sqlalchemy.dialects.postgresql import insert
    require_event(connection, event_id)
    staff = connection.execute(select(s.users.c.id).where(s.users.c.email == str(body.email).lower(), s.users.c.email_verified_at.is_not(None))).scalar_one_or_none()
    if not staff:
        raise HTTPException(404, "El usuario debe estar registrado y verificado")
    connection.execute(insert(s.event_staff).values(event_id=event_id, user_id=staff).on_conflict_do_update(index_elements=["event_id", "user_id"], set_={"disabled_at": None}))
    audit(connection, user["id"], "staff.assigned", event_id, "event")
    return {"message": "Personal asignado"}


@router.get("/admin/dashboard")
def dashboard(user=Depends(admin_user), connection=Depends(db)):
    rows = []
    for event in connection.execute(select(s.events.c.id, s.events.c.name, s.events.c.status)).mappings():
        sales = connection.execute(select(s.orders.c.currency, func.count().label("orders"), func.sum(s.orders.c.total).label("total")).where(
            s.orders.c.event_id == event["id"], s.orders.c.status == "paid").group_by(s.orders.c.currency)).mappings().all()
        tickets = connection.execute(select(s.tickets.c.status, func.count().label("count")).where(s.tickets.c.event_id == event["id"]).group_by(s.tickets.c.status)).mappings().all()
        rows.append({**dict(event), "sales": list(sales), "tickets": list(tickets)})
    return rows


@router.get("/admin/audit")
def audit_log(user=Depends(admin_user), connection=Depends(db)):
    return list(connection.execute(select(s.audit_entries).order_by(s.audit_entries.c.created_at.desc()).limit(100)).mappings())


@router.post("/images/{target}/{entity_id}")
async def upload_image(target: Literal["avatar", "poster", "venue", "map", "zone"], entity_id: UUID,
                       request: Request, file: UploadFile = File(...), user=Depends(current_user), connection=Depends(db)):
    from io import BytesIO
    from pathlib import Path
    from uuid import uuid4
    from PIL import Image, ImageOps, UnidentifiedImageError
    if target == "avatar":
        if entity_id != user["id"]:
            raise HTTPException(403, "Solo puedes cambiar tu foto")
        table, field = s.users, "avatar_url"
    else:
        if "admin" not in roles_for(connection, user["id"]):
            raise HTTPException(403, "Solo administración puede cambiar esta imagen")
        table, field = {"poster": (s.events, "poster_url"), "venue": (s.venues, "image_url"),
                        "map": (s.venues, "seating_map_url"), "zone": (s.zones, "image_url")}[target]
    if not connection.execute(select(table.c.id).where(table.c.id == entity_id)).first():
        raise HTTPException(404, "Registro no encontrado")
    payload = await file.read(5 * 1024 * 1024 + 1)
    if len(payload) > 5 * 1024 * 1024:
        raise HTTPException(413, "La imagen no puede superar 5 MB")
    Image.MAX_IMAGE_PIXELS = 20000000
    try:
        image = Image.open(BytesIO(payload))
        if image.format not in ("JPEG", "PNG", "WEBP") or image.width * image.height > 20000000:
            raise ValueError()
        image.load()
        image = ImageOps.exif_transpose(image).convert("RGB")
        image.thumbnail((2400, 2400))
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise HTTPException(422, "Selecciona una imagen JPEG, PNG o WebP válida")
    folder = request.app.state.settings.data_directory / "uploads"
    folder.mkdir(parents=True, exist_ok=True)
    name = uuid4().hex + ".webp"
    image.save(folder / name, "WEBP", quality=85)
    url = "/media/" + name
    connection.execute(update(table).where(table.c.id == entity_id).values(**{field: url}))
    return {"url": url}

class ZoneEdit(InputModel):
    name: str = Field(min_length=2, max_length=120)
    price: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    benefits: str = Field(default="", max_length=2000)
    display_order: int = Field(default=0, ge=0)


class UserStatus(InputModel):
    disabled: bool


@router.put("/admin/venues/{venue_id}")
def edit_venue(venue_id: UUID, body: VenueInput, user=Depends(admin_user), connection=Depends(db)):
    from zoneinfo import ZoneInfo
    try:
        ZoneInfo(body.timezone)
    except Exception:
        raise HTTPException(422, "Zona horaria inválida")
    if not connection.execute(update(s.venues).where(s.venues.c.id == venue_id).values(**body.model_dump())).rowcount:
        raise HTTPException(404, "Recinto no encontrado")
    return {"message": "Recinto actualizado"}


@router.put("/admin/zones/{zone_id}")
def edit_zone(zone_id: UUID, body: ZoneEdit, user=Depends(admin_user), connection=Depends(db)):
    if not connection.execute(update(s.zones).where(s.zones.c.id == zone_id).values(**body.model_dump())).rowcount:
        raise HTTPException(404, "Zona no encontrada")
    audit(connection, user["id"], "zone.updated", zone_id, "zone")
    return {"message": "Zona actualizada; las órdenes existentes conservan su precio"}


@router.get("/admin/events/{event_id}/zones/{zone_id}/seats")
def admin_seats(event_id: UUID, zone_id: UUID, user=Depends(admin_user), connection=Depends(db)):
    return get_zone_seats(connection, event_id, zone_id)


@router.get("/admin/events/{event_id}/staff")
def staff_list(event_id: UUID, user=Depends(admin_user), connection=Depends(db)):
    return list(connection.execute(select(s.users.c.id, s.users.c.email, s.users.c.full_name).join(s.event_staff,
        s.event_staff.c.user_id == s.users.c.id).where(s.event_staff.c.event_id == event_id, s.event_staff.c.disabled_at.is_(None))).mappings())


@router.delete("/admin/events/{event_id}/staff/{staff_id}")
def remove_staff(event_id: UUID, staff_id: UUID, user=Depends(admin_user), connection=Depends(db)):
    if not connection.execute(update(s.event_staff).where(s.event_staff.c.event_id == event_id, s.event_staff.c.user_id == staff_id,
        s.event_staff.c.disabled_at.is_(None)).values(disabled_at=now())).rowcount:
        raise HTTPException(404, "Asignación activa no encontrada")
    audit(connection, user["id"], "staff.revoked", event_id, "event", {"staff_id": str(staff_id)})
    return {"message": "Acceso retirado; se conserva el historial de validación"}

@router.get("/admin/users")
def user_list(user=Depends(admin_user), connection=Depends(db)):
    return list(connection.execute(select(s.users.c.id, s.users.c.email, s.users.c.full_name, s.users.c.email_verified_at,
        s.users.c.disabled_at, s.users.c.created_at).order_by(s.users.c.created_at.desc()).limit(200)).mappings())


@router.patch("/admin/users/{user_id}/status")
def disable_user(user_id: UUID, body: UserStatus, user=Depends(admin_user), connection=Depends(db)):
    if user_id == user["id"] or "admin" in roles_for(connection, user_id):
        raise HTTPException(409, "Las cuentas administrativas se gestionan desde la preparación local")
    if not connection.execute(update(s.users).where(s.users.c.id == user_id).values(disabled_at=now() if body.disabled else None)).rowcount:
        raise HTTPException(404, "Usuario no encontrado")
    audit(connection, user["id"], "user.disabled" if body.disabled else "user.enabled", user_id, "user")
    return {"message": "Estado de cuenta actualizado"}
