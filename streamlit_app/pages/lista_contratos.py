"""
Contratos SECOP II: catálogo departamento/ciudad desde la API; tabla desde export.csv (DuckDB).

Ejecutar: py -3 -m streamlit run streamlit_app/app.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import requests
import streamlit as st

from common_setup import CSV_STR, EXPORT_CSV, cached_api_catalog, init_app

init_app()

from sadai.data_sources.export_csv_duckdb import (  # noqa: E402
    count_contracts_filtered,
    fecha_inicio_anos_rango,
    fetch_contracts_page_df,
)

ALL_CITIES_LABEL = "(Todas las ciudades del departamento)"
DEFAULT_DEPTO = "Bolívar"
DEFAULT_CITY = "Cartagena"


@st.cache_data(ttl=600, show_spinner=False)
def _cached_anos(_csv: str, departamento: str, ciudad_token: str) -> tuple[int, int]:
    ciudad = None if not ciudad_token else ciudad_token
    return fecha_inicio_anos_rango(Path(_csv), departamento, ciudad)


@st.cache_data(ttl=120, show_spinner=False)
def _cached_count(_csv: str, departamento: str, ciudad_token: str, year: int) -> int:
    ciudad = None if not ciudad_token else ciudad_token
    return count_contracts_filtered(Path(_csv), departamento, ciudad, year)


@st.cache_data(ttl=60, show_spinner=False)
def _cached_page(
    _csv: str, departamento: str, ciudad_token: str, year: int, page: int, page_size: int
) -> pd.DataFrame:
    ciudad = None if not ciudad_token else ciudad_token
    return fetch_contracts_page_df(
        Path(_csv), departamento, ciudad, year, page, page_size=page_size
    )


st.set_page_config(page_title="Lista de Contratos — SADAI", layout="wide")

st.title("Contratos SECOP II (export local)")
st.caption(
    "Departamentos y ciudades: **solo API** datos.gov.co. "
    "Contratos: `export.csv` con DuckDB (cada conteo o página puede tardar si el CSV es muy grande)."
)

if not EXPORT_CSV.is_file():
    st.error(f"No se encontró `{EXPORT_CSV.name}` en la raíz del proyecto.")
    st.stop()

try:
    catalog = cached_api_catalog()
except (requests.RequestException, RuntimeError, OSError) as e:
    st.error(
        "No se pudo cargar el listado de departamentos y ciudades desde la API. "
        "Revisa conexión, token en `.env` y vuelve a intentar.\n\n"
        f"Detalle: `{e}`"
    )
    st.stop()

with st.sidebar:
    st.subheader("Catálogo (API)")
    if st.button("Recargar departamentos y ciudades"):
        cached_api_catalog.clear()
        st.rerun()

depts_all: list[str] = catalog.get("departamentos") or []
if not depts_all:
    st.error("La API devolvió un catálogo vacío.")
    st.stop()

if "region_departamento" not in st.session_state and DEFAULT_DEPTO in depts_all:
    st.session_state["region_departamento"] = DEFAULT_DEPTO

def_dept = st.session_state.get("region_departamento")
idx_dept = depts_all.index(def_dept) if def_dept in depts_all else 0
dept = st.selectbox("Departamento", options=depts_all, index=idx_dept, key="sel_dept")

if st.session_state.get("_track_dept") != dept:
    st.session_state["_track_dept"] = dept
    st.session_state.pop("sel_city", None)

cities_map: dict[str, list[str]] = catalog.get("ciudades_por_departamento") or {}
cities_for_dept = cities_map.get(dept, [])

city_choices = [ALL_CITIES_LABEL] + cities_for_dept
tok = st.session_state.get("region_ciudad_token", "")
if not tok and DEFAULT_CITY in city_choices:
    st.session_state["region_ciudad_token"] = DEFAULT_CITY
    tok = DEFAULT_CITY
if tok:
    def_city = tok if tok in city_choices else ALL_CITIES_LABEL
else:
    def_city = ALL_CITIES_LABEL
idx_city = city_choices.index(def_city) if def_city in city_choices else 0
city_label = st.selectbox("Ciudad", options=city_choices, index=idx_city, key="sel_city")
ciudad_token = "" if city_label == ALL_CITIES_LABEL else city_label

y_min, y_max = _cached_anos(CSV_STR, dept, ciudad_token)
year_options = list(range(y_min, y_max + 1))
filtro_key = (dept, ciudad_token, y_min, y_max)
if st.session_state.get("_filtro_geo") != filtro_key:
    st.session_state["_filtro_geo"] = filtro_key
    st.session_state["_page"] = 0

cur_y = st.session_state.get("region_anio")
if cur_y not in year_options:
    cur_y = year_options[-1]
idx_year = year_options.index(int(cur_y))
year = st.selectbox(
    "Año de inicio del contrato (`Fecha de Inicio del Contrato` en el CSV)",
    options=year_options,
    index=idx_year,
)

if (dept, ciudad_token, year) != st.session_state.get("_filtro_page_reset"):
    st.session_state["_filtro_page_reset"] = (dept, ciudad_token, year)
    st.session_state["_page"] = 0

st.session_state["region_departamento"] = dept
st.session_state["region_ciudad_token"] = ciudad_token
st.session_state["region_anio"] = int(year)

page_size = 10

with st.spinner("Contando contratos en el CSV…"):
    total = _cached_count(CSV_STR, dept, ciudad_token, year)

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

with st.spinner("Cargando página desde el CSV…"):
    df = _cached_page(CSV_STR, dept, ciudad_token, year, page, page_size)

if df.empty:
    st.info("No hay filas en esta página (prueba otro año, ciudad o departamento).")
else:
    st.subheader("Columnas del export")
    df_show = df.copy()
    first_row_no = page * page_size + 1
    df_show.insert(
        0,
        "N°",
        list(range(first_row_no, first_row_no + len(df_show))),
    )
    st.dataframe(
        df_show,
        use_container_width=True,
        height=480,
        hide_index=True,
    )

with st.expander("Filtro aplicado (DuckDB)"):
    city_sql = "cualquier ciudad" if not ciudad_token else repr(ciudad_token)
    st.code(
        f'FROM export.csv\nWHERE "Departamento" = {dept!r}\n'
        f'  AND ciudad: {city_sql}\n'
        f'  AND year("Fecha de Inicio del Contrato") = {year}\n'
        f"ORDER BY \"ID Contrato\" ASC\n"
        f"LIMIT {page_size} OFFSET {page * page_size}",
        language="text",
    )
