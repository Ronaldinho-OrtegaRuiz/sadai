"""Carga de configuración desde variables de entorno."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[2]


def _load_env_files() -> None:
    """Carga .env desde la raíz del repo y, por si acaso, desde el cwd.

    override=True: si Windows u otra capa ya definió API_KEY vacío, el .env del
    proyecto debe poder sobrescribirlo (comportamiento típico en desarrollo).
    """
    for path in (_ROOT / ".env", Path.cwd() / ".env"):
        if path.is_file():
            load_dotenv(path, encoding="utf-8-sig", override=True)
    # Último recurso: búsqueda estándar desde el directorio de trabajo actual
    load_dotenv(encoding="utf-8-sig", override=True)


_load_env_files()

SODA_DOMAIN = os.environ.get("SODA_DOMAIN", "www.datos.gov.co")
SECOP_CONTRATOS_DATASET_ID = os.environ.get("SECOP_DATASET_ID", "jbjy-vk9h")


def soda_app_token() -> str | None:
    """Token SODA (App Token). Acepta varios nombres habituales en .env."""
    for key in ("SODA_APP_TOKEN", "API_KEY", "APP_TOKEN"):
        raw = os.environ.get(key)
        if raw is not None and str(raw).strip():
            return str(raw).strip()
    return None


def soda_token_meta() -> tuple[str | None, int]:
    """Qué variable aportó el token y su longitud (sin exponer el valor)."""
    for key in ("SODA_APP_TOKEN", "API_KEY", "APP_TOKEN"):
        raw = os.environ.get(key)
        if raw is not None and str(raw).strip():
            return (key, len(str(raw).strip()))
    return (None, 0)
