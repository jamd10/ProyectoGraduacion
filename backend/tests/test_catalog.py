from datetime import datetime, timedelta, timezone
from uuid import UUID
from io import BytesIO

from sqlalchemy.dialects.postgresql import insert
from PIL import Image

from nexopass import schema as s
from test_accounts import api, account, engine


def administrator(api, engine):
    account(api)
    user = api.get("/api/v1/auth/me").json()
    with engine.begin() as connection:
        connection.execute(insert(s.roles).values(code="admin").on_conflict_do_nothing())
        connection.execute(s.user_roles.insert().values(user_id=UUID(user["id"]), role_code="admin"))
    return user


def create_concert(api, engine):
    administrator(api, engine)
    venue = api.post("/api/v1/admin/venues", json={"name": "Estadio de prueba", "city": "Tegucigalpa", "address": "Dirección de prueba"})
    assert venue.status_code == 201, venue.text
    now = datetime.now(timezone.utc)
    body = {"venue_id": venue.json()["id"], "name": "Concierto de prueba", "description": "Una experiencia de prueba",
        "starts_at": (now+timedelta(days=5)).isoformat(), "ends_at": (now+timedelta(days=5,hours=4)).isoformat(),
        "doors_open_at": (now+timedelta(days=5,hours=-1)).isoformat(), "sales_open_at": (now-timedelta(days=1)).isoformat(),
        "sales_close_at": (now+timedelta(days=4)).isoformat(), "transfer_deadline": (now+timedelta(days=4)).isoformat(), "status": "published"}
    event = api.post("/api/v1/admin/events", json=body)
    assert event.status_code == 201, event.text
    zone = api.post(f'/api/v1/admin/events/{event.json()["id"]}/zones', json={"name": "VIP", "mode": "seated", "price": "500.00", "capacity": 12})
    assert zone.status_code == 201, zone.text
    return event.json(), zone.json()


def test_non_admin_cannot_create_events(api):
    account(api)
    assert api.get("/api/v1/admin/venues").status_code == 403


def test_concert_seats_and_blocking(api, engine):
    event, zone = create_concert(api, engine)
    detail = api.get('/api/v1/events/' + event["id"])
    assert detail.status_code == 200
    assert detail.json()["availability"]["zones"][0]["available"] == 12
    seats = api.get(f'/api/v1/events/{event["id"]}/zones/{zone["id"]}/seats').json()
    assert len(seats) == 12 and seats[0]["row_label"] == "1" and seats[10]["row_label"] == "2"
    assert api.patch('/api/v1/admin/units/' + seats[0]["unit_id"], json={"enabled": False}).status_code == 200
    assert api.get('/api/v1/events/' + event["id"]).json()["availability"]["zones"][0]["blocked"] == 1
    assert api.delete('/api/v1/admin/venues/' + event["venue_id"]).status_code == 409


def test_invalid_image_rejected_and_valid_image_reencoded(api):
    account(api)
    user = api.get('/api/v1/auth/me').json()
    path = '/api/v1/images/avatar/' + user['id']
    assert api.post(path, files={'file': ('fake.png', b'not an image', 'image/png')}).status_code == 422
    image = Image.new('RGB', (10, 10), 'red')
    stream = BytesIO(); image.save(stream, 'PNG')
    response = api.post(path, files={'file': ('image.png', stream.getvalue(), 'image/png')})
    assert response.status_code == 200 and response.json()['url'].endswith('.webp')
    assert api.get('/api/v1/auth/me').json()['avatar_url'] == response.json()['url']
