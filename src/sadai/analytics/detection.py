"""
Pipeline híbrido de priorización de riesgo contractual (entidad–proveedor).

Capa 1 — Validación/coherencia (conteos; descarte antes de agregar).
Capa 2 — Reglas de riesgo interpretables (score_reglas ∈ [0, 1]).
Capa 3 — Isolation Forest sobre agregados relacionales.
Salida — score_final = combinación ponderada + ranking explicable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

from sadai.analytics.analitica_local import _params_base, _prep_columns_sql, _where_region_anio

_READ = "read_csv_auto(?, header=true, max_line_size=2000000, ignore_errors=true)"

DEFAULT_SEED = 42
DEFAULT_CONTAMINATION = 0.05
DEFAULT_BURST_WINDOW_DAYS = 10
DEFAULT_BURST_MIN_CONTRACTS = 3
DEFAULT_WEIGHT_RULES = 0.40
DEFAULT_WEIGHT_IF = 0.60
MIN_PAIR_CONTRACTS = 2

# Pesos interpretables (Capa 2) — suma máxima teórica 0.85; se capa en 1.0
RULE_WEIGHTS: dict[str, tuple[float, str]] = {
    "contratacion_directa": (0.15, "Ratio contratación directa ≥ 50 %"),
    "frecuencia_temporal": (0.25, f"≥ {DEFAULT_BURST_MIN_CONTRACTS} contratos en ventana corta"),
    "proveedor_dominante": (0.20, "Concentración del proveedor en la entidad ≥ 25 %"),
    "objeto_generico": (0.10, "≥ 50 % de contratos con objeto muy corto (< 30 car.)"),
    "costo_dia_extremo": (0.15, "Costo/día promedio en percentil 90+ del cohorte"),
}


@dataclass(frozen=True)
class PipelineCounts:
    """Capa 1: contratos en el filtro."""

    total: int
    n_discarded: int
    n_analyzed: int
    n_discard_valor: int
    n_discard_fechas: int
    n_discard_duracion: int
    n_discard_objeto_vacio: int


@dataclass
class HybridPipelineResult:
    counts: PipelineCounts
    n_pairs: int
    n_pairs_scored: int
    n_alerts: int
    ranking: pd.DataFrame
    rule_catalog: pd.DataFrame = field(default_factory=pd.DataFrame)
    meta: dict[str, Any] = field(default_factory=dict)


def _discard_sql_extra() -> str:
    return """
    (flag_valor_invalido = 1)
    OR (flag_fin_antes_inicio = 1)
    OR (flag_duracion_negativa = 1)
    OR (duracion_dias IS NULL OR duracion_dias <= 0)
    OR (valor_num IS NULL OR valor_num <= 0)
    """


def pipeline_population_counts(
    csv_path: Path,
    departamento: str,
    ciudad: str | None,
    year: int,
) -> PipelineCounts:
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
        return PipelineCounts(0, 0, 0, 0, 0, 0, 0)
    total = int(row[0] or 0)
    n_disc = int(row[1] or 0)
    return PipelineCounts(
        total=total,
        n_discarded=n_disc,
        n_analyzed=max(0, total - n_disc),
        n_discard_valor=int(row[2] or 0),
        n_discard_fechas=int(row[3] or 0),
        n_discard_duracion=int(row[4] or 0),
        n_discard_objeto_vacio=int(row[5] or 0),
    )


def fetch_pair_aggregates_df(
    csv_path: Path,
    departamento: str,
    ciudad: str | None,
    year: int,
    *,
    burst_window_days: int = DEFAULT_BURST_WINDOW_DAYS,
) -> pd.DataFrame:
    """Agregación entidad–proveedor sobre contratos que pasan Capa 1."""
    path = str(csv_path.resolve())
    w = _where_region_anio(ciudad)
    cols = _prep_columns_sql()
    discard = _discard_sql_extra()
    bw = max(1, int(burst_window_days))
    sql = f"""
    WITH prep AS (
      SELECT
        {cols},
        t."Objeto del Contrato" AS objeto_raw,
        valor_num / NULLIF(duracion_dias, 0) AS costo_por_dia,
        CASE
          WHEN lower(coalesce(modalidad, '')) LIKE '%direct%'
            OR lower(coalesce(modalidad, '')) LIKE '%directa%' THEN 1 ELSE 0
        END AS es_directa
      FROM {_READ} t
      WHERE {w}
        AND NOT ({discard})
    ),
    ent_tot AS (
      SELECT nit_entidad AS nit_e, count(*)::BIGINT AS n_entidad_anio
      FROM prep
      GROUP BY 1
    ),
    burst AS (
      SELECT nit_entidad AS nit_e, doc_proveedor AS doc_p,
        max(n_win)::BIGINT AS max_contratos_ventana
      FROM (
        SELECT
          nit_entidad,
          doc_proveedor,
          fecha_inicio,
          count(*) OVER (
            PARTITION BY nit_entidad, doc_proveedor
            ORDER BY fecha_inicio
            RANGE BETWEEN INTERVAL '{bw}' DAY PRECEDING AND CURRENT ROW
          )::BIGINT AS n_win
        FROM prep
        WHERE fecha_inicio IS NOT NULL
      ) x
      GROUP BY 1, 2
    ),
    par AS (
      SELECT
        nit_entidad AS nit_e,
        nombre_entidad AS nombre_e,
        doc_proveedor AS doc_p,
        proveedor AS nombre_p,
        count(*)::BIGINT AS n_contratos,
        sum(valor_num) AS suma_valor,
        avg(valor_num) AS promedio_valor,
        avg(costo_por_dia) AS costo_dia_promedio,
        avg(duracion_dias) AS duracion_promedio,
        avg(es_directa::DOUBLE) AS ratio_directa,
        avg(CASE WHEN longitud_objeto < 30 THEN 1.0 ELSE 0.0 END) AS pct_objeto_corto,
        count(DISTINCT left(trim(coalesce(objeto_raw, '')), 50))::BIGINT AS diversidad_objetos,
        min(longitud_objeto) AS min_longitud_objeto
      FROM prep
      GROUP BY 1, 2, 3, 4
    )
    SELECT
      p.nit_e,
      p.nombre_e,
      p.doc_p,
      p.nombre_p,
      p.n_contratos,
      p.suma_valor,
      p.promedio_valor,
      p.costo_dia_promedio,
      p.duracion_promedio,
      p.ratio_directa,
      p.pct_objeto_corto,
      p.diversidad_objetos,
      p.min_longitud_objeto,
      coalesce(b.max_contratos_ventana, p.n_contratos) AS max_contratos_ventana,
      (p.n_contratos * 1.0 / NULLIF(e.n_entidad_anio, 0)) AS concentracion_entidad,
      e.n_entidad_anio
    FROM par p
    JOIN ent_tot e ON p.nit_e = e.nit_e
    LEFT JOIN burst b ON p.nit_e = b.nit_e AND p.doc_p = b.doc_p
  """
    con = duckdb.connect(database=":memory:")
    return con.execute(sql, _params_base(path, departamento, ciudad, year)).df()


def _is_directa_threshold(ratio: float) -> bool:
    return float(ratio) >= 0.5


def _fit_if_scores(
    X: pd.DataFrame,
    *,
    contamination: float,
    seed: int,
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
    return (-clf.decision_function(Xs)).astype(float)


def _normalize_01(s: pd.Series) -> pd.Series:
    lo, hi = float(s.min()), float(s.max())
    if hi - lo < 1e-12:
        return pd.Series(0.0, index=s.index)
    return (s - lo) / (hi - lo)


def _compute_rule_scores(
    df: pd.DataFrame,
    *,
    burst_min_contracts: int,
    costo_dia_p90: float,
) -> tuple[pd.Series, pd.DataFrame]:
    """Capa 2: score_reglas y matriz de reglas disparadas."""
    flags = pd.DataFrame(index=df.index)
    flags["contratacion_directa"] = df["ratio_directa"].map(_is_directa_threshold)
    flags["frecuencia_temporal"] = df["max_contratos_ventana"] >= burst_min_contracts
    flags["proveedor_dominante"] = df["concentracion_entidad"] >= 0.25
    flags["objeto_generico"] = df["pct_objeto_corto"] >= 0.5
    flags["costo_dia_extremo"] = df["costo_dia_promedio"].fillna(0) >= costo_dia_p90

    score = pd.Series(0.0, index=df.index)
    for key, (w, _) in RULE_WEIGHTS.items():
        score = score + flags[key].astype(float) * w
    score = score.clip(0.0, 1.0)

    active = []
    for _, row in flags.iterrows():
        parts = [RULE_WEIGHTS[k][1] for k in RULE_WEIGHTS if row[k]]
        active.append("; ".join(parts) if parts else "")
    flags["reglas_disparadas"] = active
    return score, flags


def _if_feature_matrix(df: pd.DataFrame) -> pd.DataFrame:
    """Features para Isolation Forest sobre agregados (Capa 3)."""
    out = pd.DataFrame(index=df.index)
    out["log_n_contratos"] = np.log1p(df["n_contratos"].astype(float))
    out["log_suma_valor"] = np.log1p(df["suma_valor"].astype(float))
    out["log_promedio_valor"] = np.log1p(df["promedio_valor"].astype(float))
    out["ratio_directa"] = df["ratio_directa"].astype(float)
    out["concentracion_entidad"] = df["concentracion_entidad"].astype(float)
    out["max_contratos_ventana"] = df["max_contratos_ventana"].astype(float)
    out["costo_dia_promedio"] = np.log1p(df["costo_dia_promedio"].fillna(0).astype(float))
    out["duracion_promedio"] = np.log1p(df["duracion_promedio"].fillna(0).astype(float))
    out["diversidad_objetos"] = df["diversidad_objetos"].astype(float)
    out["pct_objeto_corto"] = df["pct_objeto_corto"].astype(float)
    repeticion = 1.0 - (df["diversidad_objetos"] / df["n_contratos"].clip(lower=1)).clip(0, 1)
    out["repeticion_objeto"] = repeticion.astype(float)
    return out.replace([np.inf, -np.inf], np.nan).fillna(0)


def _build_explanation(
    row: pd.Series,
    flags_row: pd.Series,
    score_reglas: float,
    score_if: float,
) -> str:
    parts: list[str] = []
    if flags_row.get("contratacion_directa"):
        parts.append("alta contratación directa")
    if flags_row.get("frecuencia_temporal"):
        parts.append("ráfaga de contratos en ventana corta")
    if flags_row.get("proveedor_dominante"):
        parts.append("proveedor dominante en la entidad")
    if flags_row.get("objeto_generico"):
        parts.append("objetos contractuales genéricos")
    if flags_row.get("costo_dia_extremo"):
        parts.append("costo/día promedio elevado")
    if score_if >= 0.7:
        parts.append("patrón agregado atípico (Isolation Forest)")
    if not parts:
        parts.append(
            f"combinación de scores (reglas={score_reglas:.2f}, anomalía={score_if:.2f})"
        )
    return "; ".join(parts)


def rule_catalog_df() -> pd.DataFrame:
    rows = [
        {"regla": k, "peso": w, "descripcion": desc}
        for k, (w, desc) in RULE_WEIGHTS.items()
    ]
    return pd.DataFrame(rows)


def run_hybrid_pipeline(
    csv_path: Path,
    departamento: str,
    ciudad: str | None,
    year: int,
    *,
    seed: int = DEFAULT_SEED,
    contamination: float = DEFAULT_CONTAMINATION,
    alert_percentile: float = 95.0,
    weight_rules: float = DEFAULT_WEIGHT_RULES,
    weight_if: float = DEFAULT_WEIGHT_IF,
    burst_window_days: int = DEFAULT_BURST_WINDOW_DAYS,
    burst_min_contracts: int = DEFAULT_BURST_MIN_CONTRACTS,
    min_pair_contracts: int = MIN_PAIR_CONTRACTS,
    display_limit: int = 500,
) -> HybridPipelineResult:
    counts = pipeline_population_counts(csv_path, departamento, ciudad, year)
    pairs = fetch_pair_aggregates_df(
        csv_path,
        departamento,
        ciudad,
        year,
        burst_window_days=burst_window_days,
    )

    empty_rank = pd.DataFrame(
        columns=[
            "nit_entidad",
            "nombre_entidad",
            "doc_proveedor",
            "proveedor",
            "n_contratos",
            "suma_valor",
            "score_final",
            "score_reglas",
            "score_anomalia",
            "reglas_disparadas",
            "razon_priorizacion",
            "alerta",
        ]
    )

    if pairs.empty:
        return HybridPipelineResult(
            counts=counts,
            n_pairs=0,
            n_pairs_scored=0,
            n_alerts=0,
            ranking=empty_rank,
            rule_catalog=rule_catalog_df(),
            meta={"burst_window_days": burst_window_days},
        )

    scored = pairs[pairs["n_contratos"] >= min_pair_contracts].copy()
    n_pairs = len(pairs)
    n_scored = len(scored)

    if n_scored < 2:
        return HybridPipelineResult(
            counts=counts,
            n_pairs=n_pairs,
            n_pairs_scored=n_scored,
            n_alerts=0,
            ranking=empty_rank,
            rule_catalog=rule_catalog_df(),
            meta={"burst_window_days": burst_window_days, "min_pair_contracts": min_pair_contracts},
        )

    costo_p90 = float(scored["costo_dia_promedio"].quantile(0.90))
    score_reglas, flags = _compute_rule_scores(
        scored,
        burst_min_contracts=burst_min_contracts,
        costo_dia_p90=costo_p90,
    )

    X = _if_feature_matrix(scored)
    raw_if = _fit_if_scores(X, contamination=contamination, seed=seed)
    score_if = _normalize_01(pd.Series(raw_if, index=scored.index))

    wr = weight_rules / max(weight_rules + weight_if, 1e-9)
    wif = weight_if / max(weight_rules + weight_if, 1e-9)
    score_final = (wr * score_reglas + wif * score_if).clip(0.0, 1.0)

    scored = scored.assign(
        score_reglas=score_reglas,
        score_anomalia=score_if,
        score_final=score_final,
    )

    thr = float(np.percentile(score_final, alert_percentile))
    scored["alerta"] = score_final >= thr

    explanations = []
    for idx in scored.index:
        explanations.append(
            _build_explanation(
                scored.loc[idx],
                flags.loc[idx],
                float(score_reglas.loc[idx]),
                float(score_if.loc[idx]),
            )
        )
    scored["reglas_disparadas"] = flags["reglas_disparadas"].values
    scored["razon_priorizacion"] = explanations

    ranking = (
        scored.loc[scored["alerta"]]
        .sort_values("score_final", ascending=False)
        .head(display_limit)
        .rename(
            columns={
                "nit_e": "nit_entidad",
                "nombre_e": "nombre_entidad",
                "doc_p": "doc_proveedor",
                "nombre_p": "proveedor",
            }
        )[
            [
                "nit_entidad",
                "nombre_entidad",
                "doc_proveedor",
                "proveedor",
                "n_contratos",
                "suma_valor",
                "ratio_directa",
                "concentracion_entidad",
                "max_contratos_ventana",
                "score_final",
                "score_reglas",
                "score_anomalia",
                "reglas_disparadas",
                "razon_priorizacion",
                "alerta",
            ]
        ]
    )

    return HybridPipelineResult(
        counts=counts,
        n_pairs=n_pairs,
        n_pairs_scored=n_scored,
        n_alerts=int(scored["alerta"].sum()),
        ranking=ranking,
        rule_catalog=rule_catalog_df(),
        meta={
            "burst_window_days": burst_window_days,
            "burst_min_contracts": burst_min_contracts,
            "alert_percentile": alert_percentile,
            "weight_rules": wr,
            "weight_if": wif,
            "costo_dia_p90": costo_p90,
            "min_pair_contracts": min_pair_contracts,
        },
    )


# Compatibilidad con imports antiguos
detection_population_counts = pipeline_population_counts
DetectionCounts = PipelineCounts
