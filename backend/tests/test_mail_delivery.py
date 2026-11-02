from uuid import uuid4
from pydantic import SecretStr
from sqlalchemy import select

from nexopass import schema as s
from nexopass.mail import queue_mail
from nexopass.worker import context, deliver_mail
from test_accounts import api, account, engine


def test_smtp_uses_tls_and_updates_delivery_without_external_mail(api,engine,monkeypatch):
    account(api)
    email=api.get('/api/v1/auth/me').json()['email']
    settings=api.app.state.settings.model_copy(update={'smtp_host':'smtp.example.com','smtp_user':'sender@example.com','smtp_password':SecretStr('smtp-test-only')})
    subject='delivery-'+uuid4().hex
    with api.app.state.database.begin() as connection:
        queue_mail(connection,context(settings),email,subject,'Contenido de prueba')
    actions=[]
    class FakeSMTP:
        def __init__(self,*args,**kwargs):actions.append('connect')
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def starttls(self,**kwargs):actions.append('tls')
        def login(self,*args):actions.append('login')
        def send_message(self,message):
            assert message['To']==email
            actions.append('send')
    monkeypatch.setattr('nexopass.worker.smtplib.SMTP',FakeSMTP)
    deliver_mail(settings,api.app.state.database)
    assert actions==['connect','tls','login','send']
    with engine.connect() as connection:
        assert connection.execute(select(s.email_messages.c.status).where(s.email_messages.c.subject==subject)).scalar_one()=='sent'


def test_smtp_failure_remains_retryable(api,engine,monkeypatch):
    account(api)
    settings=api.app.state.settings.model_copy(update={'smtp_host':'smtp.example.com'})
    subject='failed-'+uuid4().hex
    with api.app.state.database.begin() as connection:
        queue_mail(connection,context(settings),api.get('/api/v1/auth/me').json()['email'],subject,'Contenido de prueba')
    def fail(*args,**kwargs):raise OSError('unavailable')
    monkeypatch.setattr('nexopass.worker.smtplib.SMTP',fail)
    deliver_mail(settings,api.app.state.database)
    with engine.connect() as connection:
        row=connection.execute(select(s.email_messages.c.status,s.email_messages.c.attempts).where(s.email_messages.c.subject==subject)).one()
        assert row.status=='pending' and row.attempts==1
