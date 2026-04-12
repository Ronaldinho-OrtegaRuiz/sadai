"""
Explorador mínimo SECOP II: filtro Bolívar / Cartagena, año de inicio, tabla con todas
las columnas y paginación (10 por página).

Ejecutar desde la raíz del repo:
  py -3 -m pip install -r requirements.txt
  py -3 -m streamlit run streamlit_app/contratos_secop.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_ROOT / ".env", encoding="utf-8-sig", override=True)

_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from sadai.secop_soda import (  # noqa: E402
    GeoKind,
    count_contracts,
    fecha_inicio_anos_disponibles,
    fetch_contracts_page,
    where_inicio_en_ano,
)


@st.cache_data(ttl=600, show_spinner=False)
def _cached_anos(geo_kind: str) -> tuple[int, int]:
    return fecha_inicio_anos_disponibles(geo_kind)  # type: ignore[arg-type]


@st.cache_data(ttl=120, show_spinner=False)
def _cached_count(where: str) -> int:
    return count_contracts(where)


@st.cache_data(ttl=60, show_spinner=False)
def _cached_page(geo_kind: str, year: int, page: int, page_size: int) -> list[dict]:
    return fetch_contracts_page(geo_kind, year, page, page_size=page_size)  # type: ignore[arg-type]


st.set_page_config(page_title="SADAI — Contratos SECOP", layout="wide")

st.title("Contratos SECOP II (Bolívar)")
st.caption(
    "Listado paginado desde datos.gov.co. Sin análisis: solo filtros y tabla. "
    "La primera carga del min/max de fechas puede tardar ~1–2 min (agregación en la API)."
)

geo_label = st.radio(
    "Ámbito",
    options=["Bolívar (todo el departamento)", "Solo Cartagena"],
    horizontal=True,
)
geo_kind: GeoKind = "cartagena" if geo_label.startswith("Solo") else "bolivar"

with st.spinner("Consultando años disponibles (min/max fecha de inicio)…"):
    y_min, y_max = _cached_anos(geo_kind)

year_options = list(range(y_min, y_max + 1))
year = st.selectbox(
    "Año de inicio del contrato (`fecha_de_inicio_del_contrato`)",
    options=year_options,
    index=len(year_options) - 1,
)

where_year = where_inicio_en_ano(geo_kind, year)

filtro_key = (geo_kind, year)
if st.session_state.get("_filtro") != filtro_key:
    st.session_state["_filtro"] = filtro_key
    st.session_state["_page"] = 0

page_size = 10

with st.spinner("Contando contratos…"):
    total = _cached_count(where_year)

total_pages = max(1, (total + page_size - 1) // page_size)
page = int(st.session_state.get("_page", 0))
page = max(0, min(page, total_pages - 1))
st.session_state["_page"] = page

st.markdown(f"**Contratos en el año:** {total:,}  ·  **Página** {page + 1} de {total_pages}")

c1, c2, _ = st.columns([1, 1, 6])
with c1:
    if st.button("← Anterior", disabled=page <= 0):
        st.session_state["_page"] = max(0, page - 1)
        st.rerun()
with c2:
    if st.button("Siguiente →", disabled=page >= total_pages - 1):
        st.session_state["_page"] = min(total_pages - 1, page + 1)
        st.rerun()

with st.spinner("Cargando página…"):
    rows = _cached_page(geo_kind, year, page, page_size)

if not rows:
    st.info("No hay filas en esta página (prueba otro año o ámbito).")
else:
    df = pd.DataFrame(rows)
    st.subheader("Todas las columnas devueltas por la API (`$select=*`)")
    st.dataframe(df, use_container_width=True, height=480)

with st.expander("SoQL usado en esta vista"):
    st.code(
        f"$where = {where_year!r}\n"
        f"$order = id_contrato ASC\n"
        f"$limit = {page_size}\n"
        f"$offset = {page * page_size}\n"
        f"$select = *",
        language="text",
    )
