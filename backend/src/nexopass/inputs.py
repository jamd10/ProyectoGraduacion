"""Contratos de entrada: espacios normalizados y campos desconocidos rechazados."""
from pydantic import BaseModel, ConfigDict


class InputModel(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
