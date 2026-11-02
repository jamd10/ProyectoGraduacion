"""Configuración explícita por entorno; nunca cargar secretos al importar."""
from typing import Literal
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
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

    data_directory: Path = Field(default_factory=lambda: Path.home() / "NexoPassData")
    public_url: str = "http://127.0.0.1:8000"
    encryption_key: SecretStr | None = Field(default=None, repr=False)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: SecretStr | None = Field(default=None, repr=False)
    smtp_sender: str = "NexoPass <no-reply@nexopass.local>"
    smtp_starttls: bool = True
    chain_rpc_url: str = "http://127.0.0.1:8545"
    chain_id: int = 31337
    contract_address: str = ""
    relayer_key: SecretStr | None = Field(default=None, repr=False)
    frontend_directory: Path = Field(default_factory=lambda: Path(__file__).resolve().parents[3] / "frontend" / "dist")
    worker_enabled: bool = True

    @field_validator("chain_id")
    @classmethod
    def test_network_only(cls, value):
        if value not in (31337, 11155111):
            raise ValueError("NexoPass solo admite la cadena local o Sepolia de pruebas")
        return value

    @property
    def docs_enabled(self) -> bool:
        return self.environment == "development"
