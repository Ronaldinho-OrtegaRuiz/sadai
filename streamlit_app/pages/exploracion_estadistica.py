"""
Indicadores y patrones: dispersión, modalidades, serie temporal, concentración proveedor–entidad.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

from common_setup import EXPORT_CSV, init_app

init_app()

from filtros_region import render_sidebar_filtros  # noqa: E402
from sadai.analytics.analitica_local import (  # noqa: E402
    exploracion_modalidad_stats_df,
    exploracion_scatter_df,
    serie_mensual_df,
    top_concentracion_proveedor_df,
)

st.set_page_config(page_title="Indicadores y patrones — SADAI", layout="wide")
st.title("Indicadores y patrones")
st.caption(
    "Métricas derivadas (costo por día, concentración) y vistas estadísticas sobre el mismo filtro regional. "
    "**Antigüedad del contratista** no está implementada (requiere datos externos enlazados por NIT)."
)

if not EXPORT_CSV.is_file():
    st.error("No se encontró `export.csv`.")
    st.stop()

dept, ciudad, year = render_sidebar_filtros()
csv_s = str(EXPORT_CSV.resolve())


@st.cache_data(ttl=180, show_spinner=False)
def _scatter(_csv: str, d: str, c: str | None, y: int, lim: int) -> pd.DataFrame:
    return exploracion_scatter_df(Path(_csv), d, c if c else None, y, limit=lim)


@st.cache_data(ttl=180, show_spinner=False)
def _modalidad(_csv: str, d: str, c: str | None, y: int) -> pd.DataFrame:
    return exploracion_modalidad_stats_df(Path(_csv), d, c if c else None, y)


@st.cache_data(ttl=180, show_spinner=False)
def _serie(_csv: str, d: str, c: str | None, y: int) -> pd.DataFrame:
    return serie_mensual_df(Path(_csv), d, c if c else None, y)


@st.cache_data(ttl=180, show_spinner=False)
def _conc(_csv: str, d: str, c: str | None, y: int, n: int) -> pd.DataFrame:
    return top_concentracion_proveedor_df(Path(_csv), d, c if c else None, y, top_n=n)


n_muestra = st.slider("Puntos en dispersión (máx.)", 500, 8000, 2500, 250)

with st.spinner("Cargando datos para gráficos…"):
    sc = _scatter(csv_s, dept, ciudad, year, n_muestra)
    mod = _modalidad(csv_s, dept, ciudad, year)
    ser = _serie(csv_s, dept, ciudad, year)
    conc = _conc(csv_s, dept, ciudad, year, 35)

st.subheader("Valor del contrato vs duración (días)")
if sc.empty:
    st.info("No hay filas con valor y duración positivos para graficar en este filtro.")
else:
    fig_sc = px.scatter(
        sc,
        x="duracion_dias",
        y="valor_num",
        color="modalidad",
        hover_data=["id_contrato", "nombre_entidad", "proveedor"],
        labels={"duracion_dias": "Duración (días)", "valor_num": "Valor (parseado)"},
    )
    fig_sc.update_layout(legend_title_text="Modalidad")
    st.plotly_chart(fig_sc, use_container_width=True)

    st.subheader("Costo por día (valor / duración)")
    v_cd = pd.to_numeric(sc["costo_por_dia"], errors="coerce")
    mask = v_cd.notna() & np.isfinite(v_cd.to_numpy(dtype=float, copy=False))
    sc2 = sc[mask].copy()
    if not sc2.empty and sc2["costo_por_dia"].notna().any():
        hi = sc2["costo_por_dia"].quantile(0.99)
        sc2 = sc2[sc2["costo_por_dia"] <= hi]
    if not sc2.empty:
        fig_cd = px.histogram(sc2, x="costo_por_dia", nbins=40, labels={"costo_por_dia": "Costo por día"})
        st.plotly_chart(fig_cd, use_container_width=True)

st.subheader("Contratos por modalidad (top) y mediana de valor")
if mod.empty:
    st.info("Sin datos agregados por modalidad.")
else:
    fig_m = px.bar(
        mod,
        x="modalidad_g",
        y="n",
        labels={"modalidad_g": "Modalidad", "n": "N° contratos"},
        text="n",
    )
    fig_m.update_traces(textposition="outside")
    fig_m.update_layout(xaxis_tickangle=-35)
    st.plotly_chart(fig_m, use_container_width=True)

    fig_m2 = px.bar(
        mod.dropna(subset=["mediana_valor"]),
        x="modalidad_g",
        y="mediana_valor",
        labels={"modalidad_g": "Modalidad", "mediana_valor": "Mediana valor"},
    )
    fig_m2.update_layout(xaxis_tickangle=-35)
    st.plotly_chart(fig_m2, use_container_width=True)

st.subheader("Contratos por mes de inicio (dentro del año filtrado)")
if ser.empty:
    st.info("Sin fechas de inicio en el filtro.")
else:
    fig_s = px.line(ser, x="anio_mes", y="n_contratos", markers=True, labels={"anio_mes": "Mes", "n_contratos": "Contratos"})
    st.plotly_chart(fig_s, use_container_width=True)

st.subheader("Concentración proveedor ↔ entidad (mayor share dentro de la entidad)")
st.caption("Índice = contratos de ese par / total de contratos de la entidad en el filtro.")
st.dataframe(conc, use_container_width=True, height=360, hide_index=True)
