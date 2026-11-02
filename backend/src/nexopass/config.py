"""Configuración explícita por entorno; nunca cargar secretos al importar."""
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NEXOPASS_", env_file=None, extra="ignore", hide_input_in_errors=True,
    )
    environment: Literal["development", "test", "production"] = "development"

    database_host: str = "127.0.0.1"
    database_port: int = Field(default=5432, ge=1, le=65535)
    database_name: str = "nexopass"
    database_user: Literal["nexopass_app"] = "nexopass_app"
    database_password: SecretStr | None = Field(default=None, repr=False)
    database_connect_timeout: int = Field(default=3, ge=1, le=10)

    @property
    def docs_enabled(self) -> bool:
        return self.environment == "development"
