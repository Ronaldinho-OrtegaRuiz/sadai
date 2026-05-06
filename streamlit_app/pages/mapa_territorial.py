"""
Vista territorial nacional: mapa coroplético + ranking por departamento (año del lateral).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from common_setup import EXPORT_CSV, init_app

init_app()

from filtros_region import render_sidebar_filtros  # noqa: E402
from sadai.analytics.analitica_local import contratos_por_departamento_df  # noqa: E402
from sadai.geo.colombia_geo import (  # noqa: E402
    GEOJSON_URL,
    build_norm_to_dpto_cnmbr,
    choropleth_series,
    load_departamentos_geojson,
    norm_departamento_label,
    secop_departamento_to_geo_key,
)
from sadai.geo.colombia_municipios import (  # noqa: E402
    GEOJSON_MPIO_URL,
    find_municipio_feature,
    load_municipios_geojson,
)
from sadai.data_sources.export_csv_duckdb import count_contracts_filtered  # noqa: E402

st.set_page_config(page_title="Mapa territorial — SADAI", layout="wide")
st.title("Mapa territorial")
st.caption(
    "**(1)** Colombia completa; **(2)** zoom al **departamento** del lateral y, si elegiste **ciudad** "
    "(no “todas”), se remarca el **municipio** DANE encima. Año = inicio del contrato."
)

if not EXPORT_CSV.is_file():
    st.error("No se encontró `export.csv`.")
    st.stop()

dept_sel, ciudad_sel, year = render_sidebar_filtros()

_REPO_ROOT = EXPORT_CSV.parent
_LOCAL_GEO = _REPO_ROOT / "data" / "geo" / "departamentos.geojson"
_LOCAL_MPIO = _REPO_ROOT / "data" / "geo" / "municipios.geojson"


@st.cache_data(ttl=300, show_spinner=False)
def _por_depto(_csv: str, y: int) -> pd.DataFrame:
    return contratos_por_departamento_df(Path(_csv), y)


@st.cache_resource(show_spinner=False)
def _geojson_y_mapa() -> tuple[dict, dict]:
    """GeoJSON + índice normalizado → DPTO_CNMBR."""
    init_app()
    local = _LOCAL_GEO if _LOCAL_GEO.is_file() else None
    geo = load_departamentos_geojson(local_path=local)
    norm_map = build_norm_to_dpto_cnmbr(geo)
    return geo, norm_map


@st.cache_resource(show_spinner=False)
def _mpio_geo_full() -> dict:
    init_app()
    local = _LOCAL_MPIO if _LOCAL_MPIO.is_file() else None
    return load_municipios_geojson(local_path=local)


df = _por_depto(str(EXPORT_CSV.resolve()), year)
if df.empty:
    st.warning("No hay datos agregados para ese año.")
    st.stop()


def _contratos_para_departamento(tabla: pd.DataFrame, nombre_dept: str) -> int:
    nombre_dept = str(nombre_dept).strip()
    m = tabla["departamento"].astype(str).str.strip() == nombre_dept
    if m.any():
        return int(tabla.loc[m, "n_contratos"].sum())
    nk = norm_departamento_label(nombre_dept)
    for _, row in tabla.iterrows():
        if norm_departamento_label(str(row["departamento"])) == nk:
            return int(row["n_contratos"])
    return 0


st.subheader(f"Mapas — contratos por departamento ({year})")
try:
    geo, norm_map = _geojson_y_mapa()
except OSError as e:
    st.error(
        f"No se pudo cargar el GeoJSON de departamentos. "
        f"Comprueba la conexión o coloca el archivo en `{_LOCAL_GEO.as_posix()}`. "
        f"URL de respaldo: `{GEOJSON_URL}`\n\nDetalle: `{e}`"
    )
    geo, norm_map = None, None

if geo is not None and norm_map:
    order, z, sin_match = choropleth_series(
        geo,
        df["departamento"].tolist(),
        df["n_contratos"].astype(int).tolist(),
        norm_map,
    )
    df_map = pd.DataFrame({"dpto": order, "n": z})
    fig_map = px.choropleth(
        df_map,
        geojson=geo,
        locations="dpto",
        color="n",
        featureidkey="properties.DPTO_CNMBR",
        color_continuous_scale="Blues",
        labels={"dpto": "Departamento", "n": "Contratos"},
    )
    fig_map.update_traces(marker_line_width=0.4, marker_line_color="white")
    fig_map.update_layout(
        margin=dict(l=0, r=0, t=28, b=0),
        height=520,
        title="1. Colombia — todos los departamentos",
    )
    fig_map.update_geos(
        fitbounds="locations",
        visible=False,
        showcountries=True,
        countrycolor="#bdbdbd",
        bgcolor="rgba(255,255,255,0)",
    )

    geo_key_sel = secop_departamento_to_geo_key(dept_sel, norm_map)
    fig_dep = None
    mpio_warn = ""
    if geo_key_sel:
        sub_feats = [
            f
            for f in geo.get("features") or []
            if (f.get("properties") or {}).get("DPTO_CNMBR") == geo_key_sel
        ]
        if sub_feats:
            geo_one: dict = {"type": "FeatureCollection", "features": sub_feats}
            n_dep = _contratos_para_departamento(df, dept_sel)

            fig_dep = go.Figure()
            fig_dep.add_trace(
                go.Choropleth(
                    geojson=geo_one,
                    locations=[geo_key_sel],
                    z=[max(n_dep, 1)],
                    featureidkey="properties.DPTO_CNMBR",
                    colorscale=[[0, "#c8e6c9"], [1, "#43a047"]],
                    marker_line_width=1.2,
                    marker_line_color="#1b5e20",
                    showscale=True,
                    colorbar=dict(title="Contratos (dept)", len=0.55, y=0.55),
                    name="Departamento",
                    hovertemplate=(
                        f"<b>{dept_sel}</b><br>"
                        f"Contratos en el año (todo el depto): {n_dep:,}"
                        "<extra></extra>"
                    ),
                )
            )

            if ciudad_sel:
                try:
                    mpio_geo = _mpio_geo_full()
                    mpio_feat = find_municipio_feature(
                        mpio_geo,
                        dpto_cnmbr_exact=geo_key_sel,
                        secop_ciudad=ciudad_sel,
                    )
                    if mpio_feat:
                        mpio_key = str(
                            (mpio_feat.get("properties") or {}).get("MPIO_CNMBR", "")
                        ).strip()
                        n_city = int(
                            count_contracts_filtered(
                                EXPORT_CSV, dept_sel, ciudad_sel, year
                            )
                        )
                        geo_mpio_one = {
                            "type": "FeatureCollection",
                            "features": [mpio_feat],
                        }
                        fig_dep.add_trace(
                            go.Choropleth(
                                geojson=geo_mpio_one,
                                locations=[mpio_key],
                                z=[max(n_city, 1)],
                                featureidkey="properties.MPIO_CNMBR",
                                colorscale=[[0, "#ffe0b2"], [1, "#ef6c00"]],
                                marker_line_width=2.8,
                                marker_line_color="#bf360c",
                                showscale=True,
                                colorbar=dict(title="Contratos (ciudad)", len=0.45, y=0.2),
                                name="Municipio",
                                hovertemplate=(
                                    f"<b>{ciudad_sel}</b> ({mpio_key})<br>"
                                    f"Contratos (filtro ciudad): {n_city:,}"
                                    "<extra></extra>"
                                ),
                            )
                        )
                    else:
                        mpio_warn = (
                            f"No se encontró polígono municipal DANE para **{ciudad_sel}** "
                            f"en **{geo_key_sel}**. Revisa ortografía o amplía reglas en "
                            "`colombia_municipios.py`."
                        )
                except OSError as e:
                    mpio_warn = (
                        f"No se cargó el GeoJSON de municipios ({e}). "
                        f"URL: `{GEOJSON_MPIO_URL}` o archivo `{_LOCAL_MPIO.as_posix()}`."
                    )

            fig_dep.update_layout(
                margin=dict(l=0, r=0, t=36, b=0),
                height=520,
                title=(
                    f"2. {dept_sel}"
                    + (f" → **{ciudad_sel}**" if ciudad_sel else "")
                ),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
            )
            fig_dep.update_geos(
                fitbounds="locations",
                visible=False,
                showcountries=True,
                countrycolor="#bdbdbd",
                bgcolor="rgba(255,255,255,0)",
            )

    c1, c2 = st.columns(2, gap="medium")
    with c1:
        st.plotly_chart(fig_map, use_container_width=True)
    with c2:
        if fig_dep is not None:
            st.plotly_chart(fig_dep, use_container_width=True)
            if mpio_warn:
                st.caption(mpio_warn)
        else:
            st.warning(
                f"No se encontró el polígono DANE para **{dept_sel}**. "
                "Revisa alias en `colombia_geo.py` o el nombre en el catálogo API."
            )

    if sin_match:
        with st.expander(f"Departamentos del export sin emparejar al mapa ({len(sin_match)})"):
            st.caption(
                "Puedes ampliar alias en `src/sadai/colombia_geo.py` (`_MANUAL_NORM_TO_DPTO`) "
                "o añadir un GeoJSON local con otra ortografía."
            )
            st.dataframe(pd.DataFrame({"Departamento (export)": sin_match}), hide_index=True)

st.subheader("Ranking (barras)")
fig_bar = px.bar(
    df.head(40),
    x="n_contratos",
    y="departamento",
    orientation="h",
    labels={"n_contratos": "N° contratos", "departamento": "Departamento"},
)
fig_bar.update_layout(yaxis={"categoryorder": "total ascending"})
st.plotly_chart(fig_bar, use_container_width=True)

csv_bytes = df.to_csv(index=False).encode("utf-8-sig")
st.download_button(
    "Descargar tabla completa departamento × volumen (CSV)",
    data=csv_bytes,
    file_name=f"contratos_por_departamento_{year}.csv",
    mime="text/csv",
)

st.info(
    f"**Sin red:** departamentos → `{_LOCAL_GEO.as_posix()}`; "
    f"municipios (~3 MB) → `{_LOCAL_MPIO.as_posix()}` "
    f"(DANE `MPIO_CNMBR` / `DPTO_CNMBR`)."
)
