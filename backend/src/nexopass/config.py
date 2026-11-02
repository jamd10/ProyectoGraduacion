"""Configuración explícita por entorno; nunca cargar secretos al importar."""
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NEXOPASS_", env_file=None, extra="ignore", hide_input_in_errors=True,
    )
    environment: Literal["development", "test", "production"] = "development"

    @property
    def docs_enabled(self) -> bool:
        return self.environment == "development"
