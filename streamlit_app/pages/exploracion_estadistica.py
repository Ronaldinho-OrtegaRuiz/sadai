"""
Indicadores y patrones: dispersión, modalidades, serie temporal, concentración proveedor–entidad.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
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
    "Métricas derivadas (costo por día, concentración) y vistas estadísticas sobre el mismo filtro regional."
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


def _mediana_valor_y_axis_ticks(y_max: float) -> tuple[list[float], list[str]]:
    """Marcas eje Y para mediana en COP: usa MM/M/k como _fmt_cop_tick (evita 'B' de Plotly)."""
    if not np.isfinite(y_max) or y_max <= 0:
        return [0.0], ["0"]
    hi = float(y_max * 1.08)
    vals = np.linspace(0.0, hi, num=7)
    return vals.tolist(), [_fmt_cop_tick(float(v)) for v in vals]


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
    "Con valor y duración > 0",
    f"{n_dispersion_eligible:,}",
    help="Solo estos cumplen las condiciones del gráfico de dispersión; el total del filtro puede ser mayor.",
)

# Tope del slider = todos los que cumplen valor y duración > 0 (sin límite artificial).
_cap_disp = max(0, n_dispersion_eligible)
if _cap_disp == 0:
    n_muestra = 0
    st.warning(
        "No hay contratos con **valor** y **duración** (días) ambos > 0 para la dispersión en este filtro."
    )
else:
    _default = min(2_500, _cap_disp)
    _min_sl = min(100, _cap_disp) if _cap_disp >= 100 else 1
    # Rangos muy grandes: step fino evita que (max-min) no sea múltiplo del paso en Streamlit.
    if _cap_disp > 50_000:
        _step = 1
    elif _cap_disp >= 500:
        _step = 50
    else:
        _step = max(1, _cap_disp // 50 or 1)
    n_muestra = st.slider(
        "Puntos mostrados en la dispersión",
        min_value=_min_sl,
        max_value=_cap_disp,
        value=min(_default, _cap_disp),
        step=_step,
        help=(
            f"Hasta {_cap_disp:,} puntos (todos los que cumplen valor y duración > 0). "
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
    st.caption(
        f"**{len(sc):,}** puntos en el gráfico (**{n_dispersion_eligible:,}** con valor y duración > 0; "
        f"**{n_total_filtro:,}** contratos en el filtro)."
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
        sc_h = sc2[pd.to_numeric(sc2["costo_por_dia"], errors="coerce") > 0].copy()
        if sc_h.empty:
            st.info("Sin valores positivos de costo por día para graficar.")
        else:
            _nb = 48
            vals = pd.to_numeric(sc_h["costo_por_dia"], errors="coerce").dropna().to_numpy(dtype=float)
            counts, edges = np.histogram(vals, bins=_nb)
            centers = (edges[:-1] + edges[1:]) / 2.0
            bw = float(edges[1] - edges[0])
            df_b = pd.DataFrame(
                {
                    "centro_costo": centers,
                    "n": counts.astype(int),
                    "lo": edges[:-1],
                    "hi": edges[1:],
                }
            )
            def _hover_costo_bin(lo: float, hi: float, n: int) -> str:
                return (
                    f"Rango: {lo:,.0f} \u2013 {hi:,.0f} COP<br>"
                    f"Cantidad: {int(n):,}"
                )

            # Numerito arriba (solo si n < 50); el detalle completo va en hovertext (barra o número).
            df_b["texto"] = df_b["n"].apply(lambda c: f"{int(c):,}" if 0 < c < 50 else "")
            hover_texts = [
                _hover_costo_bin(float(lo), float(hi), int(n))
                for lo, hi, n in zip(df_b["lo"], df_b["hi"], df_b["n"])
            ]
            fig_cd = px.bar(
                df_b,
                x="centro_costo",
                y="n",
                text="texto",
                labels={"centro_costo": "Costo por día (COP)", "n": "Cantidad"},
            )
            fig_cd.update_traces(
                width=bw * 0.92,
                textposition="outside",
                texttemplate="%{text}",
                cliponaxis=False,
                hovertext=hover_texts,
                hovertemplate="%{hovertext}<extra></extra>",
                hoverinfo="text",
            )
            # Plotly no suele capturar hover sobre el texto externo: puntos casi invisibles
            # encima de la barra (solo n<50) con el mismo tooltip.
            m_hit = (df_b["n"] > 0) & (df_b["n"] < 50)
            if m_hit.any():
                sub = df_b.loc[m_hit]
                ymax = float(df_b["n"].max()) or 1.0
                n_sub = sub["n"].to_numpy(dtype=float)
                y_hit = n_sub + np.maximum(n_sub * 0.2, ymax * 0.04)
                ht_sub = [
                    _hover_costo_bin(float(lo), float(hi), int(n))
                    for lo, hi, n in zip(sub["lo"], sub["hi"], sub["n"])
                ]
                fig_cd.add_trace(
                    go.Scatter(
                        x=sub["centro_costo"].to_numpy(),
                        y=y_hit,
                        mode="markers",
                        marker=dict(
                            size=40,
                            color="rgba(255,255,255,0.004)",
                            line=dict(width=0),
                        ),
                        hovertext=ht_sub,
                        hovertemplate="%{hovertext}<extra></extra>",
                        hoverinfo="text",
                        showlegend=False,
                        name="",
                    )
                )
            fig_cd.update_layout(
                bargap=0.06,
                height=_CHART_H,
                margin=dict(t=64, b=56, l=56, r=24),
            )
            fig_cd.update_xaxes(
                title="Costo por día (COP)",
                showgrid=True,
                tickformat=",.0f",
            )
            fig_cd.update_yaxes(
                title_text="Cantidad",
                tickformat=",.0f",
                rangemode="tozero",
            )
            st.plotly_chart(fig_cd, use_container_width=True)

st.subheader("Contratos por modalidad y mediana de valor")
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

    mod_med = mod.dropna(subset=["mediana_valor"]).copy()
    mod_med["_hov_mediana"] = mod_med["mediana_valor"].map(_fmt_cop_hover)
    _tv, _tt = _mediana_valor_y_axis_ticks(float(mod_med["mediana_valor"].max()))
    # Primer “escalón” del eje Y: entre 0 y la primera marca > 0; si la mediana cae ahí, número arriba.
    _thr: float | None
    if len(_tv) >= 2 and float(_tv[1]) > 0:
        _thr = float(_tv[1])
    else:
        _thr = None

    def _texto_mediana_arriba(v: object) -> str:
        if _thr is None:
            return ""
        if v is None or (isinstance(v, float) and not np.isfinite(v)):
            return ""
        try:
            x = float(v)
        except (TypeError, ValueError):
            return ""
        if x <= 0 or x >= _thr:
            return ""
        return _fmt_cop_hover(x)

    mod_med["texto_mediana"] = mod_med["mediana_valor"].map(_texto_mediana_arriba)
    fig_m2 = px.bar(
        mod_med,
        x="modalidad_g",
        y="mediana_valor",
        text="texto_mediana",
        labels={"modalidad_g": "Modalidad", "mediana_valor": "Mediana valor"},
        custom_data=["_hov_mediana"],
    )
    fig_m2.update_traces(
        hovertemplate="<b>%{x}</b><br>Mediana: %{customdata[0]}<extra></extra>",
        textposition="outside",
        texttemplate="%{text}",
        cliponaxis=False,
    )
    fig_m2.update_yaxes(tickmode="array", tickvals=_tv, ticktext=_tt)
    fig_m2.update_layout(
        xaxis_tickangle=-35,
        height=_CHART_H,
        margin=dict(t=72, b=120, l=56, r=24),
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
