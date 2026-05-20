"""Detección de anomalías (Capa 2): cinco métodos sobre export.csv vía DuckDB + sklearn."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

from sadai.analytics.analitica_local import _params_base, _prep_columns_sql, _where_region_anio

_READ = "read_csv_auto(?, header=true, max_line_size=2000000, ignore_errors=true)"

AUTO_FULL_THRESHOLD = 80_000
DEFAULT_SAMPLE_SIZE = 50_000
DEFAULT_SEED = 42
DEFAULT_CONTAMINATION = 0.05
DEFAULT_MIN_ENTITY = 30
DEFAULT_WINDOW_DAYS = 30


class DetectionMethod(str, Enum):
    GLOBAL_IF = "p1_global_if"
    HYBRID = "p2_hybrid"
    PER_ENTITY = "p3_per_entity"
    AGGREGATE_PAIR = "p4_aggregate_pair"
    TEXT_NUMERIC = "p5_text_numeric"


METHOD_LABELS: dict[DetectionMethod, str] = {
    DetectionMethod.GLOBAL_IF: "1 — Isolation Forest global (contrato)",
    DetectionMethod.HYBRID: "2 — Híbrido (reglas + IF)",
    DetectionMethod.PER_ENTITY: "3 — IF por entidad (fallback global)",
    DetectionMethod.AGGREGATE_PAIR: "4 — Agregado entidad–proveedor (ventana)",
    DetectionMethod.TEXT_NUMERIC: "5 — Numérico + perfil de objeto",
}


@dataclass(frozen=True)
class DetectionCounts:
    total: int
    n_discarded: int
    n_analyzed: int
    n_discard_valor: int
    n_discard_fechas: int
    n_discard_duracion: int
    n_discard_objeto_vacio: int


@dataclass
class DetectionResult:
    method: DetectionMethod
    counts: DetectionCounts
    n_scored: int
    n_alerts: int
    used_sample: bool
    sample_size_requested: int | None
    ranking: pd.DataFrame
    discard_motives: pd.DataFrame | None = None
    meta: dict[str, Any] | None = None


def _discard_sql_extra() -> str:
    """Condiciones que excluyen un contrato del scoring ML (además de flags de calidad)."""
    return """
    (flag_valor_invalido = 1)
    OR (flag_fin_antes_inicio = 1)
    OR (flag_duracion_negativa = 1)
    OR (duracion_dias IS NULL OR duracion_dias <= 0)
    OR (valor_num IS NULL OR valor_num <= 0)
    """


def detection_population_counts(
    csv_path: Path,
    departamento: str,
    ciudad: str | None,
    year: int,
) -> DetectionCounts:
    path = str(csv_path.resolve())
    w = _where_region_anio(ciudad)
    cols = _prep_columns_sql()
    discard = _discard_sql_extra()
    sql = f"""
    WITH prep AS (
      SELECT {cols}
      FROM {_READ} t
      WHERE {w}
    )
    SELECT
      count(*)::BIGINT AS total,
      sum(CASE WHEN {discard} THEN 1 ELSE 0 END)::BIGINT AS n_discarded,
      sum(CASE WHEN flag_valor_invalido = 1 THEN 1 ELSE 0 END)::BIGINT AS n_discard_valor,
      sum(CASE WHEN flag_fin_antes_inicio = 1 OR flag_firma_despues_inicio = 1
               OR flag_duracion_negativa = 1 THEN 1 ELSE 0 END)::BIGINT AS n_discard_fechas,
      sum(CASE WHEN duracion_dias IS NULL OR duracion_dias <= 0 THEN 1 ELSE 0 END)::BIGINT AS n_discard_duracion,
      sum(CASE WHEN longitud_objeto = 0 THEN 1 ELSE 0 END)::BIGINT AS n_discard_objeto_vacio
    FROM prep
    """
    con = duckdb.connect(database=":memory:")
    row = con.execute(sql, _params_base(path, departamento, ciudad, year)).fetchone()
    if not row:
        return DetectionCounts(0, 0, 0, 0, 0, 0, 0)
    total = int(row[0] or 0)
    n_disc = int(row[1] or 0)
    return DetectionCounts(
        total=total,
        n_discarded=n_disc,
        n_analyzed=max(0, total - n_disc),
        n_discard_valor=int(row[2] or 0),
        n_discard_fechas=int(row[3] or 0),
        n_discard_duracion=int(row[4] or 0),
        n_discard_objeto_vacio=int(row[5] or 0),
    )


def fetch_analyzable_contracts_df(
    csv_path: Path,
    departamento: str,
    ciudad: str | None,
    year: int,
    *,
    limit: int | None,
    seed: int = DEFAULT_SEED,
) -> pd.DataFrame:
    """Contratos elegibles para ML (sin descartados), opcionalmente muestreados."""
    path = str(csv_path.resolve())
    w = _where_region_anio(ciudad)
    cols = _prep_columns_sql()
    discard = _discard_sql_extra()
    sector_expr = 'trim(coalesce(cast(t."Sector" AS VARCHAR), \'\'))'
    sql = f"""
    WITH prep AS (
      SELECT
        {cols},
        {sector_expr} AS sector,
        valor_num / NULLIF(duracion_dias, 0) AS costo_por_dia
      FROM {_READ} t
      WHERE {w}
        AND NOT ({discard})
    )
    SELECT * FROM prep
    ORDER BY hash(CAST(id_contrato AS VARCHAR) || ?)
    """
    params: list[Any] = _params_base(path, departamento, ciudad, year) + [str(seed)]
    if limit is not None and limit > 0:
        sql += "\n    LIMIT ?"
        params.append(int(limit))
    con = duckdb.connect(database=":memory:")
    return con.execute(sql, params).df()


def fetch_aggregate_pairs_df(
    csv_path: Path,
    departamento: str,
    ciudad: str | None,
    year: int,
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> pd.DataFrame:
    """Pares entidad–proveedor con ≥2 contratos en ventana rolling (días) o en el año."""
    path = str(csv_path.resolve())
    w = _where_region_anio(ciudad)
    wd = max(1, int(window_days))
    sql = f"""
    WITH base AS (
      SELECT
        t."Nit Entidad" AS nit_e,
        t."Nombre Entidad" AS nombre_e,
        t."Documento Proveedor" AS doc_p,
        t."Proveedor Adjudicado" AS nombre_p,
        t."Modalidad de Contratacion" AS modalidad,
        t."Fecha de Inicio del Contrato" AS fecha_inicio,
        try_cast(
          replace(replace(replace(trim(cast(t."Valor del Contrato" AS VARCHAR)), '$', ''), ',', ''), ' ', '')
          AS DOUBLE
        ) AS valor_num
      FROM {_READ} t
      WHERE {w}
        AND t."Nit Entidad" IS NOT NULL AND trim(cast(t."Nit Entidad" AS VARCHAR)) <> ''
        AND t."Documento Proveedor" IS NOT NULL
        AND trim(cast(t."Documento Proveedor" AS VARCHAR)) <> ''
        AND valor_num IS NOT NULL AND valor_num > 0
        AND t."Fecha de Inicio del Contrato" IS NOT NULL
    ),
    pares AS (
      SELECT
        a.nit_e,
        a.nombre_e,
        a.doc_p,
        a.nombre_p,
        count(DISTINCT b.fecha_inicio)::BIGINT AS n_contratos_ventana,
        sum(b.valor_num) AS sum_valor_ventana,
        avg(b.valor_num) AS avg_valor_ventana,
        sum(
          CASE WHEN lower(coalesce(b.modalidad, '')) LIKE '%direct%'
            OR lower(coalesce(b.modalidad, '')) LIKE '%directa%' THEN 1 ELSE 0 END
        )::DOUBLE AS n_directa_ventana
      FROM base a
      JOIN base b
        ON a.nit_e = b.nit_e AND a.doc_p = b.doc_p
       AND b.fecha_inicio BETWEEN a.fecha_inicio - INTERVAL '{wd}' DAY AND a.fecha_inicio
      GROUP BY 1, 2, 3, 4
    )
    SELECT
      nit_e,
      nombre_e,
      doc_p,
      nombre_p,
      n_contratos_ventana,
      sum_valor_ventana,
      avg_valor_ventana,
      n_directa_ventana,
      n_directa_ventana / NULLIF(n_contratos_ventana, 0) AS ratio_directa_ventana
    FROM pares
    WHERE n_contratos_ventana >= 2
  """
    con = duckdb.connect(database=":memory:")
    return con.execute(sql, _params_base(path, departamento, ciudad, year)).df()


def _modalidad_riesgo(modalidad: object) -> float:
    s = str(modalidad or "").lower()
    if "licit" in s and ("públic" in s or "publica" in s):
        return 1.0
    if "abreviad" in s:
        return 5.0
    if "direct" in s:
        return 10.0
    if "menor cuant" in s or "mínima cuant" in s or "minima cuant" in s:
        return 6.0
    return 7.0


def _enrich_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["log_valor"] = np.log1p(out["valor_num"].astype(float))
    out["log_duracion"] = np.log1p(out["duracion_dias"].astype(float))
    out["log_costo_dia"] = np.log1p(out["costo_por_dia"].astype(float).clip(lower=0))
    out["puntuacion_modalidad"] = out["modalidad"].map(_modalidad_riesgo)
    out["longitud_objeto"] = out["longitud_objeto"].fillna(0).astype(float)
    sect = out["sector"].replace("", np.nan)
    med = out.groupby(sect, dropna=False)["valor_num"].transform("median")
    out["desviacion_sector"] = (out["valor_num"] - med) / med.replace(0, np.nan)
    out["desviacion_sector"] = out["desviacion_sector"].replace([np.inf, -np.inf], np.nan).fillna(0)
    return out


def _base_feature_matrix(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    cols = [
        "log_valor",
        "log_duracion",
        "log_costo_dia",
        "puntuacion_modalidad",
        "longitud_objeto",
    ]
    X = df[cols].astype(float).replace([np.inf, -np.inf], np.nan).fillna(0)
    return X, cols


def _text_numeric_matrix(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    cols = [
        "log_valor",
        "log_duracion",
        "puntuacion_modalidad",
        "longitud_objeto",
        "desviacion_sector",
    ]
    X = df[cols].astype(float).replace([np.inf, -np.inf], np.nan).fillna(0)
    return X, cols


def _fit_isolation_scores(
    X: pd.DataFrame,
    *,
    contamination: float = DEFAULT_CONTAMINATION,
    seed: int = DEFAULT_SEED,
) -> np.ndarray:
    if len(X) < 10:
        return np.zeros(len(X), dtype=float)
    scaler = StandardScaler()
    Xs = scaler.fit_transform(X)
    clf = IsolationForest(
        n_estimators=100,
        contamination=min(0.49, max(0.01, contamination)),
        random_state=seed,
        n_jobs=-1,
    )
    clf.fit(Xs)
    raw = clf.decision_function(Xs)
    return (-raw).astype(float)


def _rule_component_scores(df: pd.DataFrame) -> pd.Series:
    z_val = (df["valor_num"] - df["valor_num"].median()) / (df["valor_num"].std() + 1e-9)
    z_costo = (df["costo_por_dia"] - df["costo_por_dia"].median()) / (df["costo_por_dia"].std() + 1e-9)
    mod = df["puntuacion_modalidad"] / 10.0
    obj = (30 - df["longitud_objeto"].clip(upper=30)) / 30.0
    comp = (
        z_val.abs().clip(0, 5) / 5 * 0.35
        + z_costo.abs().clip(0, 5) / 5 * 0.35
        + mod * 0.2
        + obj.clip(0, 1) * 0.1
    )
    return comp


def _explain_row(row: pd.Series, ref: pd.DataFrame, feature_cols: list[str]) -> str:
    parts: list[str] = []
    if row.get("puntuacion_modalidad", 0) >= 8:
        parts.append("modalidad de alto riesgo")
    if row.get("longitud_objeto", 99) < 30:
        parts.append("objeto muy corto")
    v = float(row.get("costo_por_dia", 0) or 0)
    if v > 0 and v >= ref["costo_por_dia"].quantile(0.95):
        parts.append("costo/día en percentil 95+")
    val = float(row.get("valor_num", 0) or 0)
    if val >= ref["valor_num"].quantile(0.95):
        parts.append("valor en percentil 95+")
    if abs(float(row.get("desviacion_sector", 0) or 0)) >= 1.5:
        parts.append("desviación alta vs mediana del sector")
    if not parts:
        parts.append("combinación atípica multivariable")
    return "; ".join(parts)


def _apply_alert_threshold(scores: pd.Series, alert_percentile: float) -> pd.Series:
    if scores.empty:
        return pd.Series(dtype=bool)
    thr = np.percentile(scores, alert_percentile)
    return scores >= thr


def _resolve_sample_limit(
    n_analyzed: int,
    sample_mode: str,
    sample_size: int,
) -> tuple[int | None, bool]:
    if n_analyzed <= 0:
        return None, False
    if sample_mode == "completo":
        return None, False
    if sample_mode == "muestra":
        return min(sample_size, n_analyzed), True
    if n_analyzed <= AUTO_FULL_THRESHOLD:
        return None, False
    return min(sample_size, n_analyzed), True


def run_detection(
    method: DetectionMethod,
    csv_path: Path,
    departamento: str,
    ciudad: str | None,
    year: int,
    *,
    sample_mode: str = "automatico",
    sample_size: int = DEFAULT_SAMPLE_SIZE,
    seed: int = DEFAULT_SEED,
    contamination: float = DEFAULT_CONTAMINATION,
    alert_percentile: float = 95.0,
    min_entity_contracts: int = DEFAULT_MIN_ENTITY,
    window_days: int = DEFAULT_WINDOW_DAYS,
    display_limit: int = 500,
) -> DetectionResult:
    counts = detection_population_counts(csv_path, departamento, ciudad, year)
    if method == DetectionMethod.AGGREGATE_PAIR:
        return _run_aggregate_pair(
            csv_path,
            departamento,
            ciudad,
            year,
            counts=counts,
            seed=seed,
            contamination=contamination,
            alert_percentile=alert_percentile,
            window_days=window_days,
            display_limit=display_limit,
        )

    if sample_mode == "automatico":
        eff_mode = "muestra" if counts.n_analyzed > AUTO_FULL_THRESHOLD else "completo"
    else:
        eff_mode = sample_mode
    limit, used_sample = _resolve_sample_limit(
        counts.n_analyzed,
        eff_mode,
        sample_size,
    )

    df = fetch_analyzable_contracts_df(
        csv_path,
        departamento,
        ciudad,
        year,
        limit=limit,
        seed=seed,
    )
    n_scored = len(df)
    if n_scored == 0:
        empty = pd.DataFrame(
            columns=[
                "id_contrato",
                "nombre_entidad",
                "proveedor",
                "modalidad",
                "valor_num",
                "duracion_dias",
                "anomaly_score",
                "es_alerta",
                "razon_sospecha",
            ]
        )
        return DetectionResult(
            method=method,
            counts=counts,
            n_scored=0,
            n_alerts=0,
            used_sample=used_sample,
            sample_size_requested=limit,
            ranking=empty,
            meta={"eff_sample_mode": eff_mode},
        )

    df = _enrich_features(df)

    if method == DetectionMethod.GLOBAL_IF:
        scores = _scores_global_if(df, seed=seed, contamination=contamination)
    elif method == DetectionMethod.HYBRID:
        scores = _scores_hybrid(df, seed=seed, contamination=contamination)
    elif method == DetectionMethod.PER_ENTITY:
        scores = _scores_per_entity(
            df,
            seed=seed,
            contamination=contamination,
            min_entity_contracts=min_entity_contracts,
        )
    elif method == DetectionMethod.TEXT_NUMERIC:
        scores = _scores_text_numeric(df, seed=seed, contamination=contamination)
    else:
        raise ValueError(f"Método no soportado: {method}")

    df = df.assign(anomaly_score=scores)
    es_alerta = _apply_alert_threshold(df["anomaly_score"], alert_percentile)
    df = df.assign(es_alerta=es_alerta)
    feat_cols = _base_feature_matrix(df)[1]
    df["razon_sospecha"] = df.apply(lambda r: _explain_row(r, df, feat_cols), axis=1)

    ranking = (
        df.loc[df["es_alerta"]]
        .sort_values("anomaly_score", ascending=False)
        .head(display_limit)
    )
    ranking = ranking[
        [
            "id_contrato",
            "nombre_entidad",
            "nit_entidad",
            "proveedor",
            "modalidad",
            "tipo_contrato",
            "ciudad",
            "valor_num",
            "duracion_dias",
            "costo_por_dia",
            "anomaly_score",
            "es_alerta",
            "razon_sospecha",
        ]
    ].rename(columns={"anomaly_score": "score", "es_alerta": "alerta"})

    return DetectionResult(
        method=method,
        counts=counts,
        n_scored=n_scored,
        n_alerts=int(es_alerta.sum()),
        used_sample=used_sample,
        sample_size_requested=limit,
        ranking=ranking,
        meta={"eff_sample_mode": eff_mode, "alert_percentile": alert_percentile},
    )


def _scores_global_if(
    df: pd.DataFrame,
    *,
    seed: int,
    contamination: float,
) -> pd.Series:
    X, _ = _base_feature_matrix(df)
    return pd.Series(_fit_isolation_scores(X, contamination=contamination, seed=seed), index=df.index)


def _scores_hybrid(df: pd.DataFrame, *, seed: int, contamination: float) -> pd.Series:
    X, _ = _base_feature_matrix(df)
    if_score = pd.Series(
        _fit_isolation_scores(X, contamination=contamination, seed=seed),
        index=df.index,
    )
    rule_score = _rule_component_scores(df)
    if_n = (if_score - if_score.min()) / (if_score.max() - if_score.min() + 1e-9)
    rule_n = (rule_score - rule_score.min()) / (rule_score.max() - rule_score.min() + 1e-9)
    return 0.6 * if_n + 0.4 * rule_n


def _scores_per_entity(
    df: pd.DataFrame,
    *,
    seed: int,
    contamination: float,
    min_entity_contracts: int,
) -> pd.Series:
    scores = pd.Series(0.0, index=df.index)
    X_all, _ = _base_feature_matrix(df)
    global_sc = _fit_isolation_scores(X_all, contamination=contamination, seed=seed)
    global_by_idx = pd.Series(global_sc, index=df.index)

    for nit, grp in df.groupby("nit_entidad", dropna=False):
        idx = grp.index
        if len(grp) < min_entity_contracts:
            scores.loc[idx] = global_by_idx.loc[idx]
            continue
        X, _ = _base_feature_matrix(grp)
        local = _fit_isolation_scores(X, contamination=contamination, seed=seed)
        scores.loc[idx] = local
    return scores


def _scores_text_numeric(df: pd.DataFrame, *, seed: int, contamination: float) -> pd.Series:
    X, _ = _text_numeric_matrix(df)
    return pd.Series(_fit_isolation_scores(X, contamination=contamination, seed=seed), index=df.index)


def _run_aggregate_pair(
    csv_path: Path,
    departamento: str,
    ciudad: str | None,
    year: int,
    *,
    counts: DetectionCounts,
    seed: int,
    contamination: float,
    alert_percentile: float,
    window_days: int,
    display_limit: int,
) -> DetectionResult:
    agg = fetch_aggregate_pairs_df(
        csv_path,
        departamento,
        ciudad,
        year,
        window_days=window_days,
    )
    if agg.empty:
        empty = pd.DataFrame(
            columns=[
                "nit_e",
                "nombre_e",
                "nombre_p",
                "n_contratos_ventana",
                "score",
                "alerta",
                "razon_sospecha",
            ]
        )
        return DetectionResult(
            method=DetectionMethod.AGGREGATE_PAIR,
            counts=counts,
            n_scored=0,
            n_alerts=0,
            used_sample=False,
            sample_size_requested=None,
            ranking=empty,
            meta={"window_days": window_days},
        )

    feat_cols = [
        "n_contratos_ventana",
        "sum_valor_ventana",
        "avg_valor_ventana",
        "ratio_directa_ventana",
    ]
    X = agg[feat_cols].astype(float).replace([np.inf, -np.inf], np.nan).fillna(0)
    agg = agg.assign(anomaly_score=_fit_isolation_scores(X, contamination=contamination, seed=seed))
    es_alerta = _apply_alert_threshold(agg["anomaly_score"], alert_percentile)
    agg = agg.assign(es_alerta=es_alerta)

    def _agg_reason(row: pd.Series) -> str:
        bits: list[str] = []
        if row["n_contratos_ventana"] >= agg["n_contratos_ventana"].quantile(0.95):
            bits.append("muchos contratos en ventana")
        if row["ratio_directa_ventana"] >= 0.8:
            bits.append("alta proporción contratación directa")
        if row["sum_valor_ventana"] >= agg["sum_valor_ventana"].quantile(0.95):
            bits.append("suma de valores en ventana muy alta")
        return "; ".join(bits) if bits else "patrón agregado atípico entidad–proveedor"

    agg["razon_sospecha"] = agg.apply(_agg_reason, axis=1)

    ranking = (
        agg.loc[agg["es_alerta"]]
        .sort_values("anomaly_score", ascending=False)
        .head(display_limit)
        .rename(
            columns={
                "anomaly_score": "score",
                "es_alerta": "alerta",
                "nombre_e": "nombre_entidad",
                "nombre_p": "proveedor",
            }
        )[
            [
                "nit_e",
                "nombre_entidad",
                "doc_p",
                "proveedor",
                "n_contratos_ventana",
                "sum_valor_ventana",
                "ratio_directa_ventana",
                "score",
                "alerta",
                "razon_sospecha",
            ]
        ]
    )

    return DetectionResult(
        method=DetectionMethod.AGGREGATE_PAIR,
        counts=counts,
        n_scored=len(agg),
        n_alerts=int(es_alerta.sum()),
        used_sample=False,
        sample_size_requested=None,
        ranking=ranking,
        meta={"window_days": window_days, "alert_percentile": alert_percentile},
    )
