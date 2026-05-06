"""
Reglas de negocio determinísticas sobre el export: coherencia de fechas, valor, objeto.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from common_setup import EXPORT_CSV, init_app

init_app()

from filtros_region import render_sidebar_filtros  # noqa: E402
from sadai.analitica_local import reglas_muestra_df, reglas_resumen  # noqa: E402

st.set_page_config(page_title="Reglas y coherencia — SADAI", layout="wide")
st.title("Reglas y coherencia")
st.caption(
    "Filtros iguales que en **Lista de contratos**. "
    "Se evalúan reglas sobre fechas, valor numérico parseado y longitud del objeto del contrato."
)

if not EXPORT_CSV.is_file():
    st.error("No se encontró `export.csv`.")
    st.stop()

dept, ciudad, year = render_sidebar_filtros()


@st.cache_data(ttl=120, show_spinner=False)
def _cached_resumen(_csv: str, d: str, c: str | None, y: int) -> dict:
    c_tok = "" if c is None else c
    return reglas_resumen(Path(_csv), d, c if c else None, y)


@st.cache_data(ttl=120, show_spinner=False)
def _cached_muestra(_csv: str, d: str, c: str | None, y: int, lim: int) -> pd.DataFrame:
    return reglas_muestra_df(Path(_csv), d, c if c else None, y, limit=lim)


res = _cached_resumen(str(EXPORT_CSV.resolve()), dept, ciudad, year)
total = max(1, res["total"])

c1, c2, c3, c4 = st.columns(4)
c1.metric("Contratos evaluados", f"{res['total']:,}")
c2.metric("Con alguna alerta", f"{res['n_con_alguna_alerta']:,}")
c3.metric("% con alerta", f"{100.0 * res['n_con_alguna_alerta'] / total:.1f}%")
c4.metric("Fin antes de inicio", f"{res['n_fin_antes_inicio']:,}")

c5, c6, c7, c8 = st.columns(4)
c5.metric("Firma después de inicio", f"{res['n_firma_despues_inicio']:,}")
c6.metric("Valor inválido / ≤0", f"{res['n_valor_invalido']:,}")
c7.metric("Objeto muy corto (<30)", f"{res['n_objeto_muy_corto']:,}")
c8.metric("Duración negativa (flags)", f"{res['n_duracion_negativa']:,}")

pie_labels = [
    "Fin antes de inicio",
    "Firma después de inicio",
    "Valor inválido",
    "Objeto muy corto",
    "Duración negativa",
]
pie_vals = [
    res["n_fin_antes_inicio"],
    res["n_firma_despues_inicio"],
    res["n_valor_invalido"],
    res["n_objeto_muy_corto"],
    res["n_duracion_negativa"],
]
pie_df = pd.DataFrame({"regla": pie_labels, "n": pie_vals})
pie_df = pie_df[pie_df["n"] > 0]
if not pie_df.empty:
    st.subheader("Distribución de alertas (conteos por tipo)")
    fig = px.pie(pie_df, names="regla", values="n", hole=0.35)
    st.plotly_chart(fig, use_container_width=True)

st.subheader("Muestra enriquecida (orden por ID contrato)")
lim = st.slider("Filas máximas a traer del CSV", 100, 2000, 500, 100)
with st.spinner("Consultando DuckDB…"):
    muestra = _cached_muestra(str(EXPORT_CSV.resolve()), dept, ciudad, year, lim)

st.dataframe(muestra, use_container_width=True, height=420, hide_index=True)
csv_bytes = muestra.to_csv(index=False).encode("utf-8-sig")
st.download_button(
    "Descargar muestra como CSV",
    data=csv_bytes,
    file_name=f"reglas_muestra_{dept[:20]}_{year}.csv",
    mime="text/csv",
)

with st.expander("Definición de reglas (referencia)"):
    st.markdown(
        """
- **Fin antes de inicio:** `Fecha de Fin del Contrato` < `Fecha de Inicio del Contrato`.
- **Firma después de inicio:** `Fecha de Firma` > `Fecha de Inicio del Contrato` (cuando ambas existen).
- **Valor inválido:** no se pudo parsear a número o valor ≤ 0 (se limpia `$`, comas y espacios en `Valor del Contrato`).
- **Objeto muy corto:** menos de 30 caracteres en texto del objeto.
- **Duración negativa:** `date_diff` días entre inicio y fin < 0 (coherente con la primera regla; se expone aparte para tablero).
- **duracion_dias:** días entre inicio y fin cuando ambas fechas existen.
- **longitud_objeto:** longitud del texto del objeto.
        """
    )
