"""
Priorización de riesgo contractual — pipeline híbrido multicapa (entidad–proveedor).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from common_setup import EXPORT_CSV, init_app

init_app()

from filtros_region import render_sidebar_filtros  # noqa: E402
from sadai.analytics.detection import (  # noqa: E402
    DEFAULT_BURST_WINDOW_DAYS,
    DEFAULT_WEIGHT_IF,
    DEFAULT_WEIGHT_RULES,
    RULE_WEIGHTS,
    pipeline_population_counts,
    rule_catalog_df,
    run_hybrid_pipeline,
)

st.set_page_config(page_title="Priorización de riesgo — SADAI", layout="wide")
st.title("Priorización de riesgo contractual")
st.caption(
    "Sistema híbrido: **validación** → **reglas interpretables** → **Isolation Forest** "
    "sobre agregados **entidad–proveedor**. No sustituye juicio legal; prioriza revisión."
)

if not EXPORT_CSV.is_file():
    st.error("No se encontró `export.csv`.")
    st.stop()

dept, ciudad, year = render_sidebar_filtros()
csv_s = str(EXPORT_CSV.resolve())

st.sidebar.markdown("### Pipeline")
burst_days = st.sidebar.number_input(
    "Ventana frecuencia (días)",
    5,
    60,
    DEFAULT_BURST_WINDOW_DAYS,
    help="Ventana para detectar ráfagas de contratos al mismo proveedor.",
)
burst_min = st.sidebar.number_input("Mín. contratos en ventana (regla)", 2, 10, 3, 1)
min_pair = st.sidebar.number_input(
    "Mín. contratos por par entidad–proveedor",
    1,
    10,
    2,
    1,
    help="Solo se puntúan pares con al menos esta cantidad en el año del filtro.",
)

st.sidebar.markdown("### Combinación final")
w_reglas = st.sidebar.slider("Peso reglas (Capa 2)", 0.1, 0.9, DEFAULT_WEIGHT_RULES, 0.05)
w_if = st.sidebar.slider("Peso anomalía IF (Capa 3)", 0.1, 0.9, DEFAULT_WEIGHT_IF, 0.05)

alert_pct = st.sidebar.slider("Percentil mínimo alerta (score final)", 90, 99, 95, 1)
contamination = st.sidebar.slider("Contaminación IF", 0.01, 0.20, 0.05, 0.01)
display_limit = st.sidebar.slider("Filas máx. en ranking", 100, 2000, 500, 50)

run_btn = st.sidebar.button("Ejecutar priorización", type="primary", use_container_width=True)

with st.expander("Arquitectura del pipeline", expanded=False):
    st.markdown(
        """
| Capa | Qué hace | ¿Es IA? |
|------|----------|---------|
| **1 — Validación** | Descarta incoherencias (valor, fechas, duración). Misma lógica que *Reglas y coherencia*. | No |
| **2 — Reglas de riesgo** | Score interpretable por par entidad–proveedor (pesos fijos). | No |
| **3 — Anomalías** | Un solo **Isolation Forest** sobre features agregadas. | Sí |
| **Salida** | `score_final` = combinación ponderada Capa 2 + Capa 3. | Híbrido |

**Unidad de análisis:** par (`Nit Entidad`, `Documento Proveedor`) en el año del filtro.
        """
    )

with st.expander("Catálogo de reglas (Capa 2)", expanded=False):
    cat = rule_catalog_df()
    cat["peso"] = cat["peso"].map(lambda x: f"{float(x):.0%}")
    st.dataframe(cat, use_container_width=True, hide_index=True)
    st.caption(
        f"La regla de frecuencia usa ≥ **{burst_min}** contratos en **{burst_days}** días. "
        f"Suma máxima teórica de pesos: {sum(w for w, _ in RULE_WEIGHTS.values()):.0%} (cap en 100 %)."
    )


@st.cache_data(ttl=120, show_spinner=False)
def _cached_counts(_csv: str, d: str, c: str | None, y: int) -> dict:
    cts = pipeline_population_counts(Path(_csv), d, c, y)
    return {
        "total": cts.total,
        "n_discarded": cts.n_discarded,
        "n_analyzed": cts.n_analyzed,
        "n_discard_valor": cts.n_discard_valor,
        "n_discard_fechas": cts.n_discard_fechas,
        "n_discard_duracion": cts.n_discard_duracion,
        "n_discard_objeto_vacio": cts.n_discard_objeto_vacio,
    }


counts = _cached_counts(csv_s, dept, ciudad, year)

st.subheader("Capa 1 — Validación (filtro completo)")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Contratos (N total)", f"{counts['total']:,}")
c2.metric("Descartados calidad", f"{counts['n_discarded']:,}")
c3.metric("Elegibles para agregar", f"{counts['n_analyzed']:,}")
c4.metric("% descartados", f"{100.0 * counts['n_discarded'] / max(1, counts['total']):.1f}%")

with st.expander("Detalle descartes Capa 1"):
    d1, d2, d3, d4 = st.columns(4)
    d1.metric("Valor inválido", f"{counts['n_discard_valor']:,}")
    d2.metric("Fechas incoherentes", f"{counts['n_discard_fechas']:,}")
    d3.metric("Duración ≤ 0 / nula", f"{counts['n_discard_duracion']:,}")
    d4.metric("Objeto vacío", f"{counts['n_discard_objeto_vacio']:,}")

if not run_btn:
    st.info("Pulsa **Ejecutar priorización** en la barra lateral.")
    st.stop()

cache_key = (
    csv_s,
    dept,
    ciudad or "",
    year,
    burst_days,
    burst_min,
    min_pair,
    w_reglas,
    w_if,
    alert_pct,
    contamination,
    display_limit,
)


@st.cache_data(ttl=300, show_spinner=True)
def _cached_pipeline(*key: object) -> dict:
    (
        csv_path,
        d,
        c,
        y,
        b_days,
        b_min,
        m_pair,
        wr,
        wif,
        a_pct,
        cont,
        disp,
    ) = key
    res = run_hybrid_pipeline(
        Path(str(csv_path)),
        str(d),
        c if c else None,
        int(y),
        burst_window_days=int(b_days),
        burst_min_contracts=int(b_min),
        min_pair_contracts=int(m_pair),
        weight_rules=float(wr),
        weight_if=float(wif),
        alert_percentile=float(a_pct),
        contamination=float(cont),
        display_limit=int(disp),
    )
    return {
        "n_pairs": res.n_pairs,
        "n_pairs_scored": res.n_pairs_scored,
        "n_alerts": res.n_alerts,
        "meta": res.meta,
        "ranking": res.ranking,
    }


with st.spinner("Agregando pares, aplicando reglas y Isolation Forest…"):
    out = _cached_pipeline(*cache_key)

meta = out["meta"]
ranking: pd.DataFrame = out["ranking"]

st.subheader("Resultado — Capas 2 y 3")
r1, r2, r3, r4, r5 = st.columns(5)
r1.metric("Pares entidad–proveedor", f"{out['n_pairs']:,}")
r2.metric("Pares puntuados (≥ mín.)", f"{out['n_pairs_scored']:,}")
r3.metric("Alertas prioritarias", f"{out['n_alerts']:,}")
pct = 100.0 * out["n_alerts"] / max(1, out["n_pairs_scored"])
r4.metric("% alertas (sobre puntuados)", f"{pct:.2f}%")
r5.metric("Umbral", f"P{alert_pct} score final")

st.caption(
    f"Combinación: **{meta.get('weight_rules', w_reglas):.0%}** reglas + "
    f"**{meta.get('weight_if', w_if):.0%}** Isolation Forest · "
    f"Ventana frecuencia: **{meta.get('burst_window_days', burst_days)}** días."
)

if ranking.empty:
    st.warning(
        "No hay alertas con el umbral actual, o no hay pares con suficientes contratos. "
        "Prueba bajar el percentil o el mínimo de contratos por par."
    )
else:
    st.subheader("Ranking prioritario (pares entidad–proveedor)")
    st.dataframe(ranking, use_container_width=True, height=460, hide_index=True)

    chart_df = ranking.head(200)
    if len(chart_df) > 3:
        fig = px.scatter(
            chart_df,
            x="score_reglas",
            y="score_anomalia",
            size="n_contratos",
            hover_name="proveedor",
            color="score_final",
            title="Reglas vs anomalía (tamaño = nº contratos del par)",
            labels={
                "score_reglas": "Score reglas (Capa 2)",
                "score_anomalia": "Score IF (Capa 3)",
            },
        )
        st.plotly_chart(fig, use_container_width=True)

    st.download_button(
        "Descargar ranking (CSV)",
        data=ranking.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"priorizacion_{dept[:12]}_{year}.csv",
        mime="text/csv",
    )
