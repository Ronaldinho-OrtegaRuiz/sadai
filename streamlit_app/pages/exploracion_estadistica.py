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
from sadai.data_sources.export_csv_duckdb import (  # noqa: E402
    count_contracts_filtered,
    count_scatter_eligible_contracts,
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

# Altura base para que los gráficos no queden recortados en el contenedor de Streamlit.
_CHART_H = 520
_SCATTER_H = 560


def _fmt_cop_tick(t: float) -> str:
    if t >= 1e9:
        s = f"{t / 1e9:g}".rstrip("0").rstrip(".")
        return f"{s} MM"
    if t >= 1e6:
        s = f"{t / 1e6:g}".rstrip("0").rstrip(".")
        return f"{s} M"
    if t >= 1e3:
        s = f"{t / 1e3:g}".rstrip("0").rstrip(".")
        return f"{s} k"
    return f"{t:g}"


def _fmt_cop_hover(v: object) -> str:
    """Texto para hover: MM = miles de millones (×10⁹); evita la notación con B de Plotly."""
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return ""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return ""
    if x >= 1e9:
        s = f"{x / 1e9:.4f}".rstrip("0").rstrip(".")
        return f"{s} MM COP"
    if x >= 1e6:
        s = f"{x / 1e6:.3f}".rstrip("0").rstrip(".")
        return f"{s} M COP"
    return f"{x:,.0f} COP"


def _fmt_dias_tick(t: float) -> str:
    if t >= 1_000:
        s = f"{t / 1e3:g}".rstrip("0").rstrip(".")
        return f"{s}k d"
    return f"{t:g} d"


def _ticks_1_2_5_per_decade(lo_log: float, hi_log: float) -> list[float]:
    """Valores positivos 1·10ᵉ, 2·10ᵉ, 5·10ᵉ entre décadas lo_log..hi_log."""
    e0 = int(np.floor(lo_log)) - 1
    e1 = int(np.ceil(hi_log)) + 1
    out: list[float] = []
    for e in range(e0, e1 + 1):
        for m in (1, 2, 5):
            t = float(m) * (10.0**e)
            lt = np.log10(t)
            if lo_log - 0.02 <= lt <= hi_log + 0.02:
                out.append(t)
    return sorted(set(out))


def _scatter_axes_log(fig, df: pd.DataFrame) -> None:
    """
    Ejes log₁₀ en valor y duración: si no, un eje lineal 0–170 MM aplasta todos los millones en una línea.
    """
    v = pd.to_numeric(df["valor_num"], errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    d = pd.to_numeric(df["duracion_dias"], errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if v.empty or d.empty:
        return
    vmin = max(float(v.min()), 500.0)
    vmax = float(v.max()) * 1.2
    dmin = max(float(d.min()), 1.0)
    dmax = float(d.max()) * 1.08
    lo_y, hi_y = float(np.log10(vmin)), float(np.log10(vmax))
    lo_x, hi_x = float(np.log10(dmin)), float(np.log10(dmax))

    tickvals_y = _ticks_1_2_5_per_decade(lo_y, hi_y)
    ticktext_y = [_fmt_cop_tick(t) for t in tickvals_y]
    tickvals_x = _ticks_1_2_5_per_decade(lo_x, hi_x)
    ticktext_x = [_fmt_dias_tick(t) for t in tickvals_x]

    fig.update_yaxes(
        type="log",
        range=[lo_y, hi_y],
        tickmode="array",
        tickvals=tickvals_y,
        ticktext=ticktext_y,
        automargin=True,
        tickfont=dict(size=12),
        title="Valor del contrato (COP, escala log₁₀)",
    )
    fig.update_xaxes(
        type="log",
        range=[lo_x, hi_x],
        tickmode="array",
        tickvals=tickvals_x,
        ticktext=ticktext_x,
        automargin=True,
        title="Duración (días, escala log₁₀)",
    )


@st.cache_data(ttl=180, show_spinner=False)
def _scatter(_csv: str, d: str, c: str | None, y: int, lim: int) -> pd.DataFrame:
    return exploracion_scatter_df(Path(_csv), d, c if c else None, y, limit=lim)


@st.cache_data(ttl=180, show_spinner=False)
def _total_contratos_filtro(_csv: str, d: str, c: str | None, y: int) -> int:
    return int(count_contracts_filtered(Path(_csv), d, c if c else None, y))


@st.cache_data(ttl=180, show_spinner=False)
def _scatter_eligible_n(_csv: str, d: str, c: str | None, y: int) -> int:
    return count_scatter_eligible_contracts(Path(_csv), d, c if c else None, y)


@st.cache_data(ttl=180, show_spinner=False)
def _modalidad(_csv: str, d: str, c: str | None, y: int) -> pd.DataFrame:
    return exploracion_modalidad_stats_df(Path(_csv), d, c if c else None, y)


@st.cache_data(ttl=180, show_spinner=False)
def _serie(_csv: str, d: str, c: str | None, y: int) -> pd.DataFrame:
    return serie_mensual_df(Path(_csv), d, c if c else None, y)


@st.cache_data(ttl=180, show_spinner=False)
def _conc(_csv: str, d: str, c: str | None, y: int, n: int) -> pd.DataFrame:
    return top_concentracion_proveedor_df(Path(_csv), d, c if c else None, y, top_n=n)


n_total_filtro = _total_contratos_filtro(csv_s, dept, ciudad, year)
n_dispersion_eligible = _scatter_eligible_n(csv_s, dept, ciudad, year)

m1, m2 = st.columns(2)
m1.metric("Contratos en el filtro (año y región)", f"{n_total_filtro:,}")
m2.metric(
    "Con valor y duración > 0 (elegibles para la nube)",
    f"{n_dispersion_eligible:,}",
    help="Solo estos cumplen las condiciones del gráfico de dispersión; el total del filtro puede ser mayor.",
)

# Tope del slider: todos los elegibles o 20k si hay más (rendimiento en el navegador).
_cap_disp = max(0, min(n_dispersion_eligible, 20_000))
if _cap_disp == 0:
    n_muestra = 0
    st.warning(
        "No hay contratos elegibles para la dispersión en este filtro "
        "(hace falta **valor** y **duración** en días ambos > 0)."
    )
else:
    _default = min(2_500, _cap_disp)
    _min_sl = min(100, _cap_disp) if _cap_disp >= 100 else 1
    _step = 50 if _cap_disp >= 500 else max(1, _cap_disp // 50 or 1)
    n_muestra = st.slider(
        "Puntos mostrados en la nube de dispersión",
        min_value=_min_sl,
        max_value=_cap_disp,
        value=min(_default, _cap_disp),
        step=_step,
        help=(
            f"Hasta {_cap_disp:,} puntos (de {n_dispersion_eligible:,} elegibles). "
            f"Total en el filtro: {n_total_filtro:,} contratos."
        ),
    )

with st.spinner("Cargando datos para gráficos…"):
    sc = _scatter(csv_s, dept, ciudad, year, n_muestra) if n_muestra > 0 else pd.DataFrame()
    mod = _modalidad(csv_s, dept, ciudad, year)
    ser = _serie(csv_s, dept, ciudad, year)
    conc = _conc(csv_s, dept, ciudad, year, 35)

st.subheader("Valor del contrato vs duración (días)")
if sc.empty:
    st.info("No hay filas con valor y duración positivos para graficar en este filtro.")
else:
    if n_dispersion_eligible > 20_000:
        st.caption(
            f"**{len(sc):,}** puntos en el gráfico (tope de **20.000** por rendimiento; "
            f"**{n_dispersion_eligible:,}** elegibles; **{n_total_filtro:,}** contratos en el filtro)."
        )
    else:
        st.caption(
            f"**{len(sc):,}** puntos en el gráfico (**{n_dispersion_eligible:,}** elegibles; "
            f"**{n_total_filtro:,}** contratos totales en el filtro)."
        )
    sc_plot = sc.copy()
    sc_plot["_hv_valor"] = sc_plot["valor_num"].map(_fmt_cop_hover)
    fig_sc = px.scatter(
        sc_plot,
        x="duracion_dias",
        y="valor_num",
        color="modalidad",
        custom_data=["id_contrato", "nombre_entidad", "proveedor", "_hv_valor"],
        labels={
            "duracion_dias": "Duración (días)",
            "valor_num": "Valor (COP)",
        },
    )
    fig_sc.update_traces(
        hovertemplate=(
            "<b>%{fullData.name}</b><br>"
            "Duración: %{x:,.0f} días<br>"
            "Valor: %{customdata[3]}<br>"
            "ID contrato: %{customdata[0]}<br>"
            "Entidad: %{customdata[1]}<br>"
            "Proveedor: %{customdata[2]}<extra></extra>"
        ),
    )
    fig_sc.update_layout(
        legend_title_text="Modalidad",
        height=_SCATTER_H,
        margin=dict(t=48, b=72, l=72, r=24),
    )
    _scatter_axes_log(fig_sc, sc_plot)
    st.caption(
        "Escala **log₁₀** en ambos ejes: los contratos en **millones** y en **miles de millones** "
        "ocupan alturas distintas (con eje lineal hasta cientos de miles de millones todo queda pegado abajo)."
    )
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
        fig_cd.update_layout(height=_CHART_H, margin=dict(t=40, b=48, l=56, r=24))
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
    fig_m.update_layout(
        xaxis_tickangle=-35,
        height=_CHART_H,
        margin=dict(t=48, b=120, l=56, r=24),
    )
    st.plotly_chart(fig_m, use_container_width=True)

    fig_m2 = px.bar(
        mod.dropna(subset=["mediana_valor"]),
        x="modalidad_g",
        y="mediana_valor",
        labels={"modalidad_g": "Modalidad", "mediana_valor": "Mediana valor"},
    )
    fig_m2.update_layout(
        xaxis_tickangle=-35,
        height=_CHART_H,
        margin=dict(t=48, b=120, l=56, r=24),
    )
    st.plotly_chart(fig_m2, use_container_width=True)

st.subheader("Contratos por mes de inicio (dentro del año filtrado)")
if ser.empty:
    st.info("Sin fechas de inicio en el filtro.")
else:
    fig_s = px.line(
        ser,
        x="anio_mes",
        y="n_contratos",
        markers=True,
        labels={"anio_mes": "Mes", "n_contratos": "Contratos"},
    )
    fig_s.update_layout(height=_CHART_H, margin=dict(t=40, b=72, l=56, r=24))
    st.plotly_chart(fig_s, use_container_width=True)

st.subheader("Concentración proveedor ↔ entidad (mayor share dentro de la entidad)")
st.caption("Índice = contratos de ese par / total de contratos de la entidad en el filtro.")
st.dataframe(conc, use_container_width=True, height=360, hide_index=True)
