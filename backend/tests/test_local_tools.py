import os
import runpy
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql
import pytest
from sqlalchemy import select

from nexopass import schema as s
from nexopass.security import hasher
from test_integrity import engine

ROOT=Path(__file__).resolve().parents[2]


def test_admin_bootstrap_is_explicit_and_never_overwrites_password(engine,tmp_path_factory):
    module=runpy.run_path(str(ROOT/'scripts'/'local.py'))
    email=uuid4().hex+'@example.com'
    folder=tmp_path_factory.getbasetemp()/'nexopass-data'
    with engine.begin() as connection:
        user_id=module['create_admin'](connection,email,'FirstAdmin2026!',folder)
        assert module['create_admin'](connection,email,'IgnoredNew2026!',folder)==user_id
        saved=connection.execute(select(s.users.c.password_hash).where(s.users.c.id==user_id)).scalar_one()
        assert hasher.verify(saved,'FirstAdmin2026!')
        assert connection.execute(select(s.user_roles).where(s.user_roles.c.user_id==user_id,s.user_roles.c.role_code=='admin')).first()
        normal=uuid4().hex+'@example.com'
        connection.execute(s.users.insert().values(email=normal,full_name='Usuario normal',password_hash=hasher.hash('NormalAccount2026!')))
        with pytest.raises(RuntimeError):
            module['create_admin'](connection,normal,'AnotherAdmin2026!',folder)


def test_demo_seed_is_repeatable_without_fake_sales(engine):
    module=runpy.run_path(str(ROOT/'scripts'/'local.py'))
    with engine.begin() as connection:
        module['seed_demo'](connection)
        before=list(connection.execute(select(s.events.c.id).where(s.events.c.name.like('%[DEMO]%'))).scalars())
        module['seed_demo'](connection)
        after=list(connection.execute(select(s.events.c.id).where(s.events.c.name.like('%[DEMO]%'))).scalars())
        assert len(before)==3 and set(before)==set(after)
        assert not connection.execute(select(s.orders.c.id).where(s.orders.c.event_id.in_(before))).first()


def test_backup_restores_to_new_database_and_detects_tampering(engine,tmp_path):
    module=runpy.run_path(str(ROOT/'backend'/'scripts'/'backup.py'))
    from cryptography.fernet import Fernet
    key=Fernet.generate_key(); encrypted=Fernet(key).encrypt(b'recoverable-test-data')
    state=tmp_path/'state';state.mkdir();(state/'master.key').write_bytes(key);(state/'payload.bin').write_bytes(encrypted)
    backup=module['create_backup'](engine.url.password,database=engine.url.database,state_directory=state,output_directory=tmp_path/'backups')
    password=os.environ['NEXOPASS_TEST_ADMIN_PASSWORD']
    name='nexopass_test_restore_'+uuid4().hex[:10]
    try:
        restored=module['restore_backup'](backup,password,engine.url.password,database=name,output_directory=tmp_path/'restored')
        assert (restored/'master.key').read_bytes()==key
        assert Fernet((restored/'master.key').read_bytes()).decrypt((restored/'payload.bin').read_bytes())==b'recoverable-test-data'
        with pytest.raises(ValueError):module['restore_backup'](backup,password,engine.url.password,database='nexopass',output_directory=tmp_path/'forbidden')
        (backup/'state'/'master.key').write_bytes(b'tampered')
        with pytest.raises(ValueError):module['restore_backup'](backup,password,engine.url.password,database='nexopass_test_restore_bad',output_directory=tmp_path/'bad')
    finally:
        with psycopg.connect(host='127.0.0.1',user='postgres',password=password,dbname='postgres',autocommit=True) as admin:
            admin.execute(sql.SQL('DROP DATABASE IF EXISTS {} WITH (FORCE)').format(sql.Identifier(name)))
