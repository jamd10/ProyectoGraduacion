"""Permisos reales del rol de ejecución sobre una base aislada."""
import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from test_integrity import engine


@pytest.fixture
def runtime_connection(engine):
    password = os.environ.get("NEXOPASS_TEST_RUNTIME_PASSWORD")
    if not password:
        pytest.fail("Falta NEXOPASS_TEST_RUNTIME_PASSWORD para el rol de pruebas.")
    runtime_engine = create_engine(engine.url.set(username="nexopass_app", password=password), hide_parameters=True)
    try:
        with runtime_engine.connect() as connection:
            transaction = connection.begin()
            try:
                yield connection
            finally:
                transaction.rollback()
    finally:
        runtime_engine.dispose()


def test_runtime_reads_revision_without_using_migrator(runtime_connection):
    assert runtime_connection.execute(text("SELECT current_user")).scalar_one() == "nexopass_app"
    assert runtime_connection.execute(text("SELECT version_num FROM public.alembic_version")).scalar_one()


@pytest.mark.parametrize("statement", [
    "INSERT INTO public.roles(code) VALUES ('forbidden')",
    "UPDATE public.audit_entries SET action='forbidden'",
    "CREATE TABLE public.runtime_forbidden (id integer)",
    "CREATE TEMP TABLE runtime_forbidden (id integer)",
    "CREATE ROLE nexopass_forbidden NOLOGIN",
    "SET ROLE nexopass_migrator",
])
def test_runtime_denied_privileged_actions(runtime_connection, statement):
    with pytest.raises(DBAPIError) as error:
        runtime_connection.execute(text(statement))
    assert error.value.orig.sqlstate == "42501"
