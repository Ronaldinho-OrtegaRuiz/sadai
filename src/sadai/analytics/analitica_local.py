"""Analítica y reglas de coherencia sobre export.csv (DuckDB), acotada a región y año."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

_READ = "read_csv_auto(?, header=true, max_line_size=2000000, ignore_errors=true)"


def _where_region_anio(ciudad: str | None) -> str:
    if ciudad:
        return (
            't."Departamento" = ? AND t."Ciudad" = ? '
            'AND year(t."Fecha de Inicio del Contrato") = ?'
        )
    return 't."Departamento" = ? AND year(t."Fecha de Inicio del Contrato") = ?'


def _params_base(csv_path: str, departamento: str, ciudad: str | None, year: int) -> list:
    if ciudad:
        return [csv_path, departamento, ciudad, year]
    return [csv_path, departamento, year]


def _prep_columns_sql() -> str:
    """Columnas derivadas y banderas (Capa reglas / exploración)."""
    return """
    t."ID Contrato" AS id_contrato,
    t."Nombre Entidad" AS nombre_entidad,
    t."Nit Entidad" AS nit_entidad,
    t."Proveedor Adjudicado" AS proveedor,
    t."Documento Proveedor" AS doc_proveedor,
    t."Modalidad de Contratacion" AS modalidad,
    t."Tipo de Contrato" AS tipo_contrato,
    t."Departamento" AS departamento,
    t."Ciudad" AS ciudad,
    t."Fecha de Firma" AS fecha_firma,
    t."Fecha de Inicio del Contrato" AS fecha_inicio,
    t."Fecha de Fin del Contrato" AS fecha_fin,
    try_cast(
      replace(replace(replace(trim(cast(t."Valor del Contrato" AS VARCHAR)), '$', ''), ',', ''), ' ', '')
      AS DOUBLE
    ) AS valor_num,
    length(trim(coalesce(t."Objeto del Contrato", '')))::BIGINT AS longitud_objeto,
    CASE
      WHEN t."Fecha de Inicio del Contrato" IS NOT NULL
       AND t."Fecha de Fin del Contrato" IS NOT NULL
      THEN date_diff('day', t."Fecha de Inicio del Contrato", t."Fecha de Fin del Contrato")
      ELSE NULL
    END AS duracion_dias,
    CASE
      WHEN t."Fecha de Inicio del Contrato" IS NOT NULL
       AND t."Fecha de Fin del Contrato" IS NOT NULL
       AND t."Fecha de Fin del Contrato" < t."Fecha de Inicio del Contrato"
      THEN 1 ELSE 0
    END AS flag_fin_antes_inicio,
    CASE
      WHEN t."Fecha de Firma" IS NOT NULL AND t."Fecha de Inicio del Contrato" IS NOT NULL
       AND t."Fecha de Firma" > t."Fecha de Inicio del Contrato"
      THEN 1 ELSE 0
    END AS flag_firma_despues_inicio,
    CASE
      WHEN try_cast(
        replace(replace(replace(trim(cast(t."Valor del Contrato" AS VARCHAR)), '$', ''), ',', ''), ' ', '')
        AS DOUBLE
      ) IS NULL
       OR try_cast(
        replace(replace(replace(trim(cast(t."Valor del Contrato" AS VARCHAR)), '$', ''), ',', ''), ' ', '')
        AS DOUBLE
      ) <= 0
      THEN 1 ELSE 0
    END AS flag_valor_invalido,
    CASE
      WHEN length(trim(coalesce(t."Objeto del Contrato", ''))) < 30 THEN 1 ELSE 0
    END AS flag_objeto_muy_corto,
    CASE
      WHEN t."Fecha de Inicio del Contrato" IS NOT NULL
       AND t."Fecha de Fin del Contrato" IS NOT NULL
       AND date_diff('day', t."Fecha de Inicio del Contrato", t."Fecha de Fin del Contrato") < 0
      THEN 1 ELSE 0
    END AS flag_duracion_negativa
    """


def reglas_resumen(
    csv_path: Path,
    departamento: str,
    ciudad: str | None,
    year: int,
) -> dict[str, int]:
    path = str(csv_path.resolve())
    w = _where_region_anio(ciudad)
    cols = _prep_columns_sql()
    sql = f"""
    WITH prep AS (
      SELECT {cols}
      FROM {_READ} t
      WHERE {w}
    )
    SELECT
      count(*)::BIGINT AS total,
      sum(flag_fin_antes_inicio)::BIGINT AS n_fin_antes_inicio,
      sum(flag_firma_despues_inicio)::BIGINT AS n_firma_despues_inicio,
      sum(flag_valor_invalido)::BIGINT AS n_valor_invalido,
      sum(flag_objeto_muy_corto)::BIGINT AS n_objeto_muy_corto,
      sum(flag_duracion_negativa)::BIGINT AS n_duracion_negativa,
      sum(
        CASE WHEN
          flag_fin_antes_inicio + flag_firma_despues_inicio + flag_valor_invalido
          + flag_objeto_muy_corto + flag_duracion_negativa > 0
        THEN 1 ELSE 0 END
      )::BIGINT AS n_con_alguna_alerta
    FROM prep
    """
    con = duckdb.connect(database=":memory:")
    row = con.execute(sql, _params_base(path, departamento, ciudad, year)).fetchone()
    if not row:
        return {k: 0 for k in _resumen_keys()}
    return dict(zip(_resumen_keys(), (int(x or 0) for x in row)))


def _resumen_keys() -> list[str]:
    return [
        "total",
        "n_fin_antes_inicio",
        "n_firma_despues_inicio",
        "n_valor_invalido",
        "n_objeto_muy_corto",
        "n_duracion_negativa",
        "n_con_alguna_alerta",
    ]


def reglas_muestra_df(
    csv_path: Path,
    departamento: str,
    ciudad: str | None,
    year: int,
    *,
    limit: int = 500,
) -> pd.DataFrame:
    path = str(csv_path.resolve())
    w = _where_region_anio(ciudad)
    cols = _prep_columns_sql()
    params = _params_base(path, departamento, ciudad, year) + [limit]
    sql = f"""
    WITH prep AS (
      SELECT {cols}
      FROM {_READ} t
      WHERE {w}
    )
    SELECT * FROM prep
    ORDER BY id_contrato
    LIMIT ?
    """
    con = duckdb.connect(database=":memory:")
    return con.execute(sql, params).df()


def exploracion_scatter_df(
    csv_path: Path,
    departamento: str,
    ciudad: str | None,
    year: int,
    *,
    limit: int = 2500,
) -> pd.DataFrame:
    path = str(csv_path.resolve())
    w = _where_region_anio(ciudad)
    cols = _prep_columns_sql()
    params = _params_base(path, departamento, ciudad, year) + [limit]
    sql = f"""
    WITH prep AS (
      SELECT {cols},
        valor_num / NULLIF(abs(duracion_dias), 0) AS costo_por_dia
      FROM {_READ} t
      WHERE {w}
        AND duracion_dias IS NOT NULL AND duracion_dias > 0
        AND valor_num IS NOT NULL AND valor_num > 0
    )
    SELECT id_contrato, valor_num, duracion_dias, costo_por_dia, modalidad, tipo_contrato,
           nombre_entidad, proveedor
    FROM prep
    ORDER BY id_contrato
    LIMIT ?
    """
    con = duckdb.connect(database=":memory:")
    return con.execute(sql, params).df()


def exploracion_modalidad_stats_df(
    csv_path: Path,
    departamento: str,
    ciudad: str | None,
    year: int,
) -> pd.DataFrame:
    path = str(csv_path.resolve())
    w = _where_region_anio(ciudad)
    cols = _prep_columns_sql()
    params = _params_base(path, departamento, ciudad, year)
    sql = f"""
    WITH prep AS (
      SELECT {cols}
      FROM {_READ} t
      WHERE {w}
    )
    SELECT
      coalesce(nullif(trim(modalidad), ''), '(sin modalidad)') AS modalidad_g,
      count(*)::BIGINT AS n,
      median(valor_num) FILTER (WHERE valor_num IS NOT NULL AND valor_num > 0) AS mediana_valor
    FROM prep
    GROUP BY 1
    ORDER BY n DESC
    LIMIT 15
    """
    con = duckdb.connect(database=":memory:")
    return con.execute(sql, params).df()


def serie_mensual_df(
    csv_path: Path,
    departamento: str,
    ciudad: str | None,
    year: int,
) -> pd.DataFrame:
    path = str(csv_path.resolve())
    w = _where_region_anio(ciudad)
    cols = _prep_columns_sql()
    params = _params_base(path, departamento, ciudad, year)
    sql = f"""
    WITH prep AS (
      SELECT {cols}
      FROM {_READ} t
      WHERE {w}
    )
    SELECT
      strftime(fecha_inicio, '%Y-%m') AS anio_mes,
      count(*)::BIGINT AS n_contratos
    FROM prep
    WHERE fecha_inicio IS NOT NULL
    GROUP BY 1
    ORDER BY 1
    """
    con = duckdb.connect(database=":memory:")
    return con.execute(sql, params).df()


def top_concentracion_proveedor_df(
    csv_path: Path,
    departamento: str,
    ciudad: str | None,
    year: int,
    *,
    top_n: int = 30,
) -> pd.DataFrame:
    path = str(csv_path.resolve())
    w = _where_region_anio(ciudad)
    params = _params_base(path, departamento, ciudad, year) + [top_n]
    sql = f"""
    WITH base AS (
      SELECT
        t."Nit Entidad" AS nit_e,
        t."Nombre Entidad" AS nombre_e,
        t."Documento Proveedor" AS doc_p,
        t."Proveedor Adjudicado" AS nombre_p
      FROM {_READ} t
      WHERE {w}
        AND t."Nit Entidad" IS NOT NULL AND trim(cast(t."Nit Entidad" AS VARCHAR)) <> ''
        AND t."Documento Proveedor" IS NOT NULL
        AND trim(cast(t."Documento Proveedor" AS VARCHAR)) <> ''
    ),
    ent_tot AS (
      SELECT nit_e, count(*)::BIGINT AS contratos_entidad FROM base GROUP BY 1
    ),
    ent_prov AS (
      SELECT nit_e, nombre_e, doc_p, nombre_p, count(*)::BIGINT AS contratos_par
      FROM base
      GROUP BY 1, 2, 3, 4
    )
    SELECT
      e.nombre_e,
      e.nit_e,
      e.nombre_p,
      e.doc_p,
      e.contratos_par,
      t.contratos_entidad,
      (e.contratos_par * 1.0 / NULLIF(t.contratos_entidad, 0)) AS indice_concentracion
    FROM ent_prov e
    JOIN ent_tot t ON e.nit_e = t.nit_e
    ORDER BY indice_concentracion DESC NULLS LAST, e.contratos_par DESC
    LIMIT ?
    """
    con = duckdb.connect(database=":memory:")
    return con.execute(sql, params).df()


def contratos_por_departamento_df(csv_path: Path, year: int) -> pd.DataFrame:
    path = str(csv_path.resolve())
    sql = f"""
    SELECT
      trim(cast(t."Departamento" AS VARCHAR)) AS departamento,
      count(*)::BIGINT AS n_contratos
    FROM {_READ} t
    WHERE t."Departamento" IS NOT NULL
      AND trim(cast(t."Departamento" AS VARCHAR)) <> ''
      AND year(t."Fecha de Inicio del Contrato") = ?
    GROUP BY 1
    ORDER BY n_contratos DESC
    """
    con = duckdb.connect(database=":memory:")
    return con.execute(sql, [path, year]).df()
