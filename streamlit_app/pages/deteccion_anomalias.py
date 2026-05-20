"""
Detección de anomalías: cinco métodos, mismos filtros regionales, KPIs y ranking.
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
    AUTO_FULL_THRESHOLD,
    DEFAULT_SAMPLE_SIZE,
    METHOD_LABELS,
    DetectionMethod,
    detection_population_counts,
    run_detection,
)

st.set_page_config(page_title="Detección de anomalías — SADAI", layout="wide")
st.title("Detección de anomalías")
st.caption(
    "Capa 2: priorización por score. Los KPIs **total** y **descartados** usan todo el filtro; "
    "el modelo puede ejecutarse sobre una **muestra** si el volumen es alto."
)

if not EXPORT_CSV.is_file():
    st.error("No se encontró `export.csv`.")
    st.stop()

dept, ciudad, year = render_sidebar_filtros()
csv_s = str(EXPORT_CSV.resolve())

method_options = list(DetectionMethod)
method_labels = [METHOD_LABELS[m] for m in method_options]

st.sidebar.markdown("### Detección")
method_label = st.sidebar.selectbox("Método", method_labels, index=0)
method = method_options[method_labels.index(method_label)]

st.sidebar.markdown("### Muestra para el modelo")
sample_mode_label = st.sidebar.radio(
    "Modo",
    ["Automático", "Completo (todos los analizables)", "Muestra fija"],
    index=0,
    help=(
        f"Automático: si hay más de {AUTO_FULL_THRESHOLD:,} contratos analizables, "
        "usa muestra fija; si no, todos."
    ),
)
sample_mode_map = {
    "Automático": "automatico",
    "Completo (todos los analizables)": "completo",
    "Muestra fija": "muestra",
}
sample_mode = sample_mode_map[sample_mode_label]

sample_size = DEFAULT_SAMPLE_SIZE
if sample_mode == "muestra" or sample_mode_label == "Automático":
    sample_size = st.sidebar.slider(
        "Tamaño de muestra (si aplica)",
        5_000,
        200_000,
        DEFAULT_SAMPLE_SIZE,
        5_000,
    )

alert_pct = st.sidebar.slider(
    "Percentil mínimo para alerta (score)",
    90,
    99,
    95,
    1,
    help="Contratos con score ≥ percentil se marcan como alerta.",
)

contamination = st.sidebar.slider(
    "Contaminación esperada (Isolation Forest)",
    0.01,
    0.20,
    0.05,
    0.01,
)

min_entity = 30
window_days = 30
if method == DetectionMethod.PER_ENTITY:
    min_entity = st.sidebar.number_input(
        "Mín. contratos por entidad (modelo local)",
        10,
        200,
        30,
        5,
    )
if method == DetectionMethod.AGGREGATE_PAIR:
    window_days = st.sidebar.number_input("Ventana rolling (días)", 7, 90, 30, 1)

display_limit = st.sidebar.slider("Filas máx. en ranking", 100, 2000, 500, 50)

run_btn = st.sidebar.button("Ejecutar detección", type="primary", use_container_width=True)


@st.cache_data(ttl=120, show_spinner=False)
def _cached_counts(_csv: str, d: str, c: str | None, y: int) -> dict:
    cts = detection_population_counts(Path(_csv), d, c, y)
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

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("N total (filtro)", f"{counts['total']:,}")
c2.metric("Descartados (calidad)", f"{counts['n_discarded']:,}")
c3.metric("Analizables", f"{counts['n_analyzed']:,}")
pct_disc = 100.0 * counts["n_discarded"] / max(1, counts["total"])
c4.metric("% descartados", f"{pct_disc:.1f}%")
c5.metric("Método", method_label.split("—", 1)[0].strip())

with st.expander("Motivos de descarte (conteo, puede solaparse)"):
    d1, d2, d3, d4 = st.columns(4)
    d1.metric("Valor inválido", f"{counts['n_discard_valor']:,}")
    d2.metric("Fechas incoherentes", f"{counts['n_discard_fechas']:,}")
    d3.metric("Duración ≤ 0 / nula", f"{counts['n_discard_duracion']:,}")
    d4.metric("Objeto vacío", f"{counts['n_discard_objeto_vacio']:,}")
    st.markdown(
        """
Los **descartados** no entran al Isolation Forest (prop. 1–3 y 5): valor inválido,
fechas incoherentes, duración nula o ≤ 0, o valor ≤ 0. La propuesta **4** usa agregación
entidad–proveedor y no aplica este mismo corte fila a fila.
        """
    )

if not run_btn:
    st.info("Configura el método y pulsa **Ejecutar detección** en la barra lateral.")
    st.stop()

cache_key = (
    csv_s,
    dept,
    ciudad or "",
    year,
    method.value,
    sample_mode,
    sample_size,
    alert_pct,
    contamination,
    min_entity,
    window_days,
    display_limit,
)


@st.cache_data(ttl=300, show_spinner=True)
def _cached_detection(*key: object) -> dict:
    (
        csv_path,
        d,
        c,
        y,
        meth_val,
        s_mode,
        s_size,
        a_pct,
        cont,
        min_ent,
        win_d,
        disp_lim,
    ) = key
    meth = DetectionMethod(str(meth_val))
    ciudad_arg = c if c else None
    result = run_detection(
        meth,
        Path(str(csv_path)),
        str(d),
        ciudad_arg,
        int(y),
        sample_mode=str(s_mode),
        sample_size=int(s_size),
        contamination=float(cont),
        alert_percentile=float(a_pct),
        min_entity_contracts=int(min_ent),
        window_days=int(win_d),
        display_limit=int(disp_lim),
    )
    return {
        "n_scored": result.n_scored,
        "n_alerts": result.n_alerts,
        "used_sample": result.used_sample,
        "sample_size_requested": result.sample_size_requested,
        "meta": result.meta or {},
        "ranking": result.ranking,
    }


with st.spinner("Ejecutando detección…"):
    out = _cached_detection(*cache_key)

n_scored = out["n_scored"]
n_alerts = out["n_alerts"]
used_sample = out["used_sample"]
meta = out["meta"]
ranking: pd.DataFrame = out["ranking"]

st.subheader("Resultado de la ejecución")

if used_sample:
    st.warning(
        f"Se puntuaron **{n_scored:,}** contratos (muestra). "
        f"Umbral automático completo: ≤ {AUTO_FULL_THRESHOLD:,} analizables."
    )
else:
    st.success(f"Se puntuaron **{n_scored:,}** registros (población analizable completa).")

r1, r2, r3, r4 = st.columns(4)
r1.metric("Puntuados en esta ejecución", f"{n_scored:,}")
r2.metric("Alertas (percentil)", f"{n_alerts:,}")
pct_alert = 100.0 * n_alerts / max(1, n_scored)
r3.metric("% alertas (sobre puntuados)", f"{pct_alert:.2f}%")
r4.metric("Percentil alerta", f"P{alert_pct}")

if method == DetectionMethod.AGGREGATE_PAIR and meta.get("window_days"):
    st.caption(f"Ventana entidad–proveedor: **{meta['window_days']}** días.")

if ranking.empty:
    st.warning("No hubo alertas con el umbral elegido, o no hay datos puntuables.")
else:
    st.subheader("Ranking de sospecha")
    st.dataframe(ranking, use_container_width=True, height=440, hide_index=True)

    if "score" in ranking.columns and len(ranking) > 5:
        fig = px.histogram(ranking, x="score", nbins=30, title="Distribución de scores (alertas)")
        st.plotly_chart(fig, use_container_width=True)

    st.download_button(
        "Descargar ranking (CSV)",
        data=ranking.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"ranking_{method.value}_{dept[:12]}_{year}.csv",
        mime="text/csv",
    )

with st.expander("Referencia del método seleccionado"):
    refs = {
        DetectionMethod.GLOBAL_IF: (
            "IF sobre log(valor), duración, costo/día, riesgo modalidad y longitud objeto."
        ),
        DetectionMethod.HYBRID: (
            "60 % Isolation Forest + 40 % componente de reglas (z-score valor/costo, modalidad, objeto)."
        ),
        DetectionMethod.PER_ENTITY: (
            f"Un IF por `Nit Entidad` si hay ≥ {min_entity} contratos; si no, modelo global."
        ),
        DetectionMethod.AGGREGATE_PAIR: (
            "IF sobre pares entidad–proveedor con ≥2 contratos en ventana rolling; "
            "features: conteo, suma/ media valor, ratio contratación directa."
        ),
        DetectionMethod.TEXT_NUMERIC: (
            "IF con valor, duración, modalidad, longitud objeto y desviación vs mediana del sector."
        ),
    }
    st.markdown(refs[method])
