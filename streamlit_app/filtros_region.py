"""Filtros departamento / ciudad / año compartidos (barra lateral)."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from common_setup import EXPORT_CSV, cached_api_catalog, init_app

ALL_CITIES_LABEL = "(Todas las ciudades del departamento)"


def render_sidebar_filtros() -> tuple[str, str | None, int]:
    """
    Devuelve (departamento, ciudad o None si todas, año).

    Persiste en st.session_state: region_departamento, region_ciudad_token, region_anio.
    """
    init_app()
    catalog = cached_api_catalog()
    depts: list[str] = catalog.get("departamentos") or []
    if not depts:
        st.error("Catálogo API vacío.")
        st.stop()

    st.sidebar.markdown("### Región y año")
    st.sidebar.caption(
        "Mismos criterios que en **Lista de contratos**. "
        "Cambios aquí se reflejan al volver a esa página."
    )

    cur_dept = st.session_state.get("region_departamento")
    idx_dept = depts.index(cur_dept) if cur_dept in depts else 0
    dept = st.sidebar.selectbox("Departamento", options=depts, index=idx_dept, key="filtro_sidebar_dept")

    cities_map: dict[str, list[str]] = catalog.get("ciudades_por_departamento") or {}
    cities = cities_map.get(dept, [])
    city_choices = [ALL_CITIES_LABEL] + cities

    cur_tok = st.session_state.get("region_ciudad_token", "")
    if cur_tok:
        default_city_label = cur_tok if cur_tok in city_choices else ALL_CITIES_LABEL
    else:
        default_city_label = ALL_CITIES_LABEL
    idx_city = city_choices.index(default_city_label) if default_city_label in city_choices else 0
    city_label = st.sidebar.selectbox("Ciudad", options=city_choices, index=idx_city, key="filtro_sidebar_city")
    ciudad_token: str | None = None if city_label == ALL_CITIES_LABEL else city_label

    from sadai.export_csv_duckdb import fecha_inicio_anos_rango  # noqa: PLC0415

    y_min, y_max = fecha_inicio_anos_rango(EXPORT_CSV, dept, ciudad_token)
    year_opts = list(range(y_min, y_max + 1))
    cur_y = st.session_state.get("region_anio")
    if cur_y not in year_opts:
        cur_y = year_opts[-1]
    idx_y = year_opts.index(int(cur_y))
    year = st.sidebar.selectbox("Año (inicio del contrato)", options=year_opts, index=idx_y, key="filtro_sidebar_year")

    st.session_state["region_departamento"] = dept
    st.session_state["region_ciudad_token"] = ciudad_token or ""
    st.session_state["region_anio"] = int(year)

    return dept, ciudad_token, int(year)
