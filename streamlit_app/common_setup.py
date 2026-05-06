"""Rutas del proyecto, .env y caché compartida para todas las páginas Streamlit."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
EXPORT_CSV = _ROOT / "export.csv"
CSV_STR = str(EXPORT_CSV.resolve())


def init_app() -> None:
    if str(_SRC) not in sys.path:
        sys.path.insert(0, str(_SRC))
    load_dotenv(_ROOT / ".env", encoding="utf-8-sig", override=True)


@st.cache_data(ttl=3600, show_spinner=True)
def cached_api_catalog() -> dict:
    init_app()
    from sadai.data_sources.geo_catalog import fetch_dept_ciudad_catalog_via_api

    return fetch_dept_ciudad_catalog_via_api()
