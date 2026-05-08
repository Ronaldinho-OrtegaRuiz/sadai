"""
Vista territorial nacional: mapa coroplético + ranking por departamento (año del lateral).
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from common_setup import EXPORT_CSV, cached_api_catalog, init_app

init_app()

from filtros_region import ALL_CITIES_LABEL, render_sidebar_filtros  # noqa: E402
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

if not EXPORT_CSV.is_file():
    st.error("No se encontró `export.csv`.")
    st.stop()


def _plotly_selection_points(chart_key: str) -> list[dict]:
    if chart_key not in st.session_state:
        return []
    raw = st.session_state[chart_key]
    if raw is None:
        return []
    sel = getattr(raw, "selection", None)
    if sel is None and isinstance(raw, dict):
        sel = raw.get("selection")
    if sel is None:
        return []
    pts = getattr(sel, "points", None)
    if pts is None and isinstance(sel, dict):
        pts = sel.get("points")
    if not pts:
        return []
    return list(pts)


def _apply_mpio_map_selection_from_state() -> bool:
    """
    Clic en un municipio del mapa 2: fija ciudad en session (sincroniza el select del lateral)
    o quita el filtro si se vuelve a elegir la misma ciudad. Incrementa `_map_chart_rev` para
    remontar el gráfico y no re-disparar la misma selección en cada rerun.

    Devuelve True si hubo cambio por el mapa (el caller debe hacer `st.rerun()` antes del sidebar).
    """
    rev = int(st.session_state.get("_map_chart_rev", 0))
    chart_key = f"mapa_territorio_depto_mpio_{rev}"
    pts = _plotly_selection_points(chart_key)
    if not pts:
        return False

    pt = pts[0]
    cd = pt.get("customdata")
    secop_c = ""
    if isinstance(cd, (list, tuple)):
        if len(cd) > 0 and cd[0] is not None:
            secop_c = str(cd[0]).strip()
        elif len(cd) > 0 and isinstance(cd[0], (list, tuple)) and len(cd[0]) > 0:
            secop_c = str(cd[0][0]).strip()
    if not secop_c:
        return False

    cur = (st.session_state.get("region_ciudad_token") or "").strip()
    if secop_c == cur:
        st.session_state["region_ciudad_token"] = ""
        st.session_state["filtro_sidebar_city"] = ALL_CITIES_LABEL
    else:
        st.session_state["region_ciudad_token"] = secop_c
        st.session_state["filtro_sidebar_city"] = secop_c

    st.session_state["_map_chart_rev"] = rev + 1
    return True


if _apply_mpio_map_selection_from_state():
    st.rerun()

dept_sel, ciudad_sel, year = render_sidebar_filtros()


def _reset_map_chart_rev_if_depto_year_changed(dept: str, year: int) -> None:
    snap = (dept, int(year))
    if st.session_state.get("_map_filter_snap") != snap:
        st.session_state["_map_chart_rev"] = 0
        st.session_state["_map_filter_snap"] = snap


_reset_map_chart_rev_if_depto_year_changed(dept_sel, year)

_REPO_ROOT = EXPORT_CSV.parent
_LOCAL_GEO = _REPO_ROOT / "data" / "geo" / "departamentos.geojson"
_LOCAL_MPIO = _REPO_ROOT / "data" / "geo" / "municipios.geojson"


def _dept_label_ranking(nombre: str) -> str:
    """Etiqueta corta en el ranking para nombres muy largos (p. ej. Bogotá D.C.)."""
    s = str(nombre).strip()
    if not s or s.lower() in ("nan", "none"):
        return "(Sin nombre)"
    low = s.lower()
    if "distrito capital" in low or "bogot" in low:
        return "Bogotá (D.C.)"
    return s


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


@st.cache_data(ttl=300, show_spinner=False)
def _df_contratos_por_ciudad_depto(csv: str, dept: str, y: int) -> pd.DataFrame:
    """
    Agregado ciudad × volumen (mismo criterio que `contratos_por_ciudad_en_departamento_df`
    en export_csv_duckdb). Import perezoso + respaldo local por si el repo quedó a medias tras un pull.
    """
    try:
        from sadai.data_sources.export_csv_duckdb import (  # noqa: PLC0415
            contratos_por_ciudad_en_departamento_df as _por_ciudad_fn,
        )

        return _por_ciudad_fn(Path(csv), dept, y)
    except ImportError:
        path = str(Path(csv).resolve())
        read_t = (
            "read_csv_auto(?, header=true, max_line_size=2000000, ignore_errors=true) AS t"
        )
        sql = f"""
        SELECT
          trim(cast(t."Ciudad" AS VARCHAR)) AS ciudad,
          count(*)::BIGINT AS n_contratos
        FROM {read_t}
        WHERE t."Departamento" = ?
          AND year(t."Fecha de Inicio del Contrato") = ?
          AND t."Ciudad" IS NOT NULL
          AND trim(cast(t."Ciudad" AS VARCHAR)) <> ''
        GROUP BY 1
        ORDER BY n_contratos DESC
        """
        con = duckdb.connect(database=":memory:")
        return con.execute(sql, [path, dept, y]).df()


def _aggregate_contratos_by_mpio_key(
    mpio_geo: dict,
    dpto_key: str,
    df_ciudad: pd.DataFrame,
) -> dict[str, tuple[str, int]]:
    agg: dict[str, tuple[str, int]] = {}
    for _, row in df_ciudad.iterrows():
        ciudad = str(row["ciudad"]).strip()
        n = int(row["n_contratos"])
        if not ciudad:
            continue
        f = find_municipio_feature(mpio_geo, dpto_cnmbr_exact=dpto_key, secop_ciudad=ciudad)
        if not f:
            continue
        k = str((f.get("properties") or {}).get("MPIO_CNMBR", "")).strip()
        if not k:
            continue
        if k not in agg:
            agg[k] = (ciudad, n)
        else:
            rep, prev_n = agg[k]
            total = prev_n + n
            rep_out = ciudad if n >= prev_n else rep
            agg[k] = (rep_out, total)
    return agg


def _secop_ciudad_for_mpio_feature(
    mpio_geo: dict,
    dpto_key: str,
    feat: dict,
    catalog_ciudades: list[str],
) -> str:
    k_feat = str((feat.get("properties") or {}).get("MPIO_CNMBR", "")).strip()
    if not k_feat:
        return ""
    for ciudad in catalog_ciudades:
        f2 = find_municipio_feature(mpio_geo, dpto_cnmbr_exact=dpto_key, secop_ciudad=ciudad)
        if not f2:
            continue
        k2 = str((f2.get("properties") or {}).get("MPIO_CNMBR", "")).strip()
        if k2 == k_feat:
            return str(ciudad).strip()
    return ""


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
        coloraxis_colorbar=dict(
            title="Contratos",
            tickformat=",.0f",
            outlinecolor="#ccc",
            outlinewidth=1,
            len=0.82,
            thickness=16,
        ),
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
    chart_key_depto: str | None = None
    if geo_key_sel:
        sub_feats = [
            f
            for f in geo.get("features") or []
            if (f.get("properties") or {}).get("DPTO_CNMBR") == geo_key_sel
        ]
        if sub_feats:
            geo_one: dict = {"type": "FeatureCollection", "features": sub_feats}
            n_dep = _contratos_para_departamento(df, dept_sel)
            n_city_leyenda: int | None = None
            if ciudad_sel:
                try:
                    n_city_leyenda = int(
                        count_contracts_filtered(EXPORT_CSV, dept_sel, ciudad_sel, year)
                    )
                except (OSError, TypeError, ValueError):
                    n_city_leyenda = None

            fig_dep = go.Figure()
            chart_key_depto = f"mapa_territorio_depto_mpio_{int(st.session_state.get('_map_chart_rev', 0))}"
            mpio_layer_ok = False

            try:
                mpio_geo = _mpio_geo_full()
                catalog = cached_api_catalog()
                ciu_cat = (catalog.get("ciudades_por_departamento") or {}).get(dept_sel, []) or []

                mpio_feats = [
                    f
                    for f in mpio_geo.get("features") or []
                    if (f.get("properties") or {}).get("DPTO_CNMBR") == geo_key_sel
                ]
                mpio_feats.sort(
                    key=lambda f: str((f.get("properties") or {}).get("MPIO_CNMBR", "")),
                )

                if mpio_feats:
                    df_ciu = _df_contratos_por_ciudad_depto(
                        str(EXPORT_CSV.resolve()), dept_sel, year
                    )
                    agg = _aggregate_contratos_by_mpio_key(mpio_geo, geo_key_sel, df_ciu)

                    locs: list[str] = []
                    zs: list[float] = []
                    customdata: list[list[object]] = []

                    for feat in mpio_feats:
                        props = feat.get("properties") or {}
                        k = str(props.get("MPIO_CNMBR", "")).strip()
                        if not k:
                            continue
                        rep, n_loc = agg.get(k, ("", 0))
                        secop_filter = rep.strip() if rep else ""
                        if not secop_filter:
                            secop_filter = _secop_ciudad_for_mpio_feature(
                                mpio_geo, geo_key_sel, feat, ciu_cat
                            )
                        dane_lbl = str(props.get("MPIO_CNMBR", "")).strip()
                        hover_lbl = secop_filter or dane_lbl or k
                        locs.append(k)
                        zs.append(float(n_loc))
                        customdata.append([secop_filter, hover_lbl, int(n_loc)])

                    geo_mpio_dept = {"type": "FeatureCollection", "features": mpio_feats}
                    fig_dep.add_trace(
                        go.Choropleth(
                            geojson=geo_mpio_dept,
                            locations=locs,
                            z=zs,
                            featureidkey="properties.MPIO_CNMBR",
                            colorscale=[
                                [0.0, "rgba(220, 235, 255, 0.38)"],
                                [1.0, "rgba(25, 70, 150, 0.58)"],
                            ],
                            zmin=0,
                            zmax=max(max(zs), 1.0) if zs else 1.0,
                            showscale=True,
                            colorbar=dict(
                                title="Contratos",
                                tickformat=",.0f",
                                len=0.55,
                                thickness=12,
                            ),
                            marker=dict(
                                line=dict(width=0.35, color="rgba(255,255,255,0.85)"),
                                opacity=0.78,
                            ),
                            customdata=customdata,
                            hovertemplate=(
                                "<b>%{customdata[1]}</b><br>"
                                "Código DANE: %{location}<br>"
                                "Contratos (año, depto): %{customdata[2]:,.0f}<br>"
                                "<sub>Clic: filtrar ciudad en el lateral</sub>"
                                "<extra></extra>"
                            ),
                            name="Municipios",
                        )
                    )
                    mpio_layer_ok = True

                    if ciudad_sel:
                        mpio_feat_hi = find_municipio_feature(
                            mpio_geo,
                            dpto_cnmbr_exact=geo_key_sel,
                            secop_ciudad=ciudad_sel,
                        )
                        if mpio_feat_hi:
                            mk = str(
                                (mpio_feat_hi.get("properties") or {}).get("MPIO_CNMBR", "")
                            ).strip()
                            n_hi = int(
                                count_contracts_filtered(
                                    EXPORT_CSV, dept_sel, ciudad_sel, year
                                )
                            )
                            fig_dep.add_trace(
                                go.Choropleth(
                                    geojson={
                                        "type": "FeatureCollection",
                                        "features": [mpio_feat_hi],
                                    },
                                    locations=[mk],
                                    z=[max(n_hi, 1)],
                                    featureidkey="properties.MPIO_CNMBR",
                                    colorscale=[[0, "#ffe0b2"], [1, "#ef6c00"]],
                                    marker_line_width=2.6,
                                    marker_line_color="#bf360c",
                                    showscale=False,
                                    name="Ciudad activa",
                                    hovertemplate=(
                                        f"<b>{ciudad_sel}</b> ({mk})<br>"
                                        f"Contratos (filtro): {n_hi:,}<extra></extra>"
                                    ),
                                )
                            )
                        else:
                            mpio_warn = (
                                f"No se encontró polígono DANE para **{ciudad_sel}** "
                                f"en **{geo_key_sel}**. Revisa `colombia_municipios.py`."
                            )

            except (OSError, RuntimeError, ValueError, TypeError) as e:
                mpio_warn = (
                    f"No se cargó o procesó el mapa municipal ({type(e).__name__}: {e}). "
                    f"GeoJSON: `{GEOJSON_MPIO_URL}` o `{_LOCAL_MPIO.as_posix()}`."
                )

            if not mpio_layer_ok:
                fig_dep.add_trace(
                    go.Choropleth(
                        geojson=geo_one,
                        locations=[geo_key_sel],
                        z=[max(n_dep, 1)],
                        featureidkey="properties.DPTO_CNMBR",
                        colorscale=[[0, "#c8e6c9"], [1, "#43a047"]],
                        marker_line_width=1.2,
                        marker_line_color="#1b5e20",
                        showscale=False,
                        name="Departamento",
                        hovertemplate=(
                            f"<b>{dept_sel}</b><br>"
                            f"Contratos en el año (todo el depto): {n_dep:,}"
                            "<extra></extra>"
                        ),
                    )
                )
                chart_key_depto = None

            leyenda_parts = [
                f"<span style='color:#1565c0'>■</span> Municipios (año {year}): volumen por ciudad SECOP",
                f"<span style='color:#2e7d32'>●</span> Total departamento: <b>{n_dep:,}</b> contratos",
            ]
            if n_city_leyenda is not None and ciudad_sel:
                leyenda_parts.append(
                    f"<span style='color:#e65100'>■</span> Ciudad activa <b>{ciudad_sel}</b>: "
                    f"<b>{n_city_leyenda:,}</b> contratos"
                )
            leyenda_parts.append(
                "<sub>Clic en un municipio con nombre SECOP: aplica ciudad; "
                "repite el mismo clic para quitar (o «Todas las ciudades» en el lateral).</sub>"
            )
            fig_dep.update_layout(
                margin=dict(l=0, r=0, t=36, b=104),
                height=520,
                title=(
                    f"2. {dept_sel}"
                    + (f" → **{ciudad_sel}**" if ciudad_sel else "")
                ),
                annotations=[
                    dict(
                        text="<br>".join(leyenda_parts),
                        xref="paper",
                        yref="paper",
                        x=0,
                        y=-0.06,
                        xanchor="left",
                        yanchor="top",
                        align="left",
                        showarrow=False,
                        font=dict(size=12),
                    )
                ],
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
            if chart_key_depto:
                st.plotly_chart(
                    fig_dep,
                    key=chart_key_depto,
                    on_select="rerun",
                    selection_mode="points",
                    width="stretch",
                )
            else:
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

st.subheader("Ranking")
df_rank = df.head(40).copy()
df_rank["departamento_rank"] = (
    df_rank["departamento"].fillna("").astype(str).str.strip().map(_dept_label_ranking)
)
fig_bar = px.bar(
    df_rank,
    x="n_contratos",
    y="departamento_rank",
    orientation="h",
    labels={"n_contratos": "N° contratos", "departamento_rank": "Departamento"},
    custom_data=["departamento"],
)
fig_bar.update_traces(
    hovertemplate=(
        "<b>%{customdata[0]}</b><br>"
        "N° contratos: %{x:,.0f}<extra></extra>"
    ),
)
fig_bar.update_layout(
    yaxis={
        "categoryorder": "total ascending",
        "automargin": True,
        "tickfont": {"size": 11},
        "side": "left",
    },
    # Margen izquierdo amplio: si es muy pequeño, Plotly recorta las etiquetas hasta un zoom/relayout.
    margin={
        "l": max(200, 8 + 7 * int(df_rank["departamento_rank"].str.len().max() or 10)),
        "r": 20,
        "t": 36,
        "b": 52,
    },
    height=max(420, 15 * len(df_rank)),
)
max_rank = int(df_rank["n_contratos"].max())
x_cap = 150_000 if max_rank <= 150_000 else int(((max_rank + 9_999) // 10_000) * 10_000)
tick_x = list(range(0, x_cap + 1, 10_000))
fig_bar.update_xaxes(
    range=[0, x_cap],
    tickmode="array",
    tickvals=tick_x,
    tickformat=",.0f",
    title="N° contratos",
)
st.plotly_chart(fig_bar, use_container_width=True)

csv_bytes = df.to_csv(index=False).encode("utf-8-sig")
st.download_button(
    "Descargar tabla completa departamento × volumen (CSV)",
    data=csv_bytes,
    file_name=f"contratos_por_departamento_{year}.csv",
    mime="text/csv",
)
