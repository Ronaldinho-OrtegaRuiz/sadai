"""Consultas locales sobre export.csv (SECOP) con DuckDB — sin cargar el archivo entero en RAM."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd


def _csv_read_expr() -> str:
    return """read_csv_auto(?, header=true, max_line_size=2000000, ignore_errors=true) AS t"""


def fecha_inicio_anos_rango(
    csv_path: Path,
    departamento: str,
    ciudad: str | None,
) -> tuple[int, int]:
    """
    (año_mín, año_máx) de `Fecha de Inicio del Contrato` filtrando por depto y opcionalmente ciudad.
    """
    path = str(csv_path.resolve())
    con = duckdb.connect(database=":memory:")

    if ciudad:
        sql = f"""
        SELECT
          min(year(t."Fecha de Inicio del Contrato")) AS y0,
          max(year(t."Fecha de Inicio del Contrato")) AS y1
        FROM {_csv_read_expr()}
        WHERE t."Departamento" = ?
          AND t."Ciudad" = ?
          AND t."Fecha de Inicio del Contrato" IS NOT NULL
        """
        row = con.execute(sql, [path, departamento, ciudad]).fetchone()
    else:
        sql = f"""
        SELECT
          min(year(t."Fecha de Inicio del Contrato")) AS y0,
          max(year(t."Fecha de Inicio del Contrato")) AS y1
        FROM {_csv_read_expr()}
        WHERE t."Departamento" = ?
          AND t."Fecha de Inicio del Contrato" IS NOT NULL
        """
        row = con.execute(sql, [path, departamento]).fetchone()

    fallback = (2000, 2030)
    if not row or row[0] is None or row[1] is None:
        return fallback
    y0, y1 = int(row[0]), int(row[1])
    if y0 > y1:
        return fallback
    return (y0, y1)


def count_contracts_filtered(
    csv_path: Path,
    departamento: str,
    ciudad: str | None,
    year: int,
) -> int:
    path = str(csv_path.resolve())
    con = duckdb.connect(database=":memory:")

    if ciudad:
        sql = f"""
        SELECT count(*)::BIGINT AS n
        FROM {_csv_read_expr()}
        WHERE t."Departamento" = ?
          AND t."Ciudad" = ?
          AND year(t."Fecha de Inicio del Contrato") = ?
        """
        n = con.execute(sql, [path, departamento, ciudad, year]).fetchone()[0]
    else:
        sql = f"""
        SELECT count(*)::BIGINT AS n
        FROM {_csv_read_expr()}
        WHERE t."Departamento" = ?
          AND year(t."Fecha de Inicio del Contrato") = ?
        """
        n = con.execute(sql, [path, departamento, year]).fetchone()[0]
    return int(n)


def fetch_contracts_page_df(
    csv_path: Path,
    departamento: str,
    ciudad: str | None,
    year: int,
    page: int,
    page_size: int,
) -> pd.DataFrame:
    path = str(csv_path.resolve())
    offset = max(0, page) * page_size
    con = duckdb.connect(database=":memory:")

    if ciudad:
        sql = f"""
        SELECT *
        FROM {_csv_read_expr()}
        WHERE t."Departamento" = ?
          AND t."Ciudad" = ?
          AND year(t."Fecha de Inicio del Contrato") = ?
        ORDER BY t."ID Contrato" ASC
        LIMIT ? OFFSET ?
        """
        return con.execute(
            sql, [path, departamento, ciudad, year, page_size, offset]
        ).df()
    sql = f"""
    SELECT *
    FROM {_csv_read_expr()}
    WHERE t."Departamento" = ?
      AND year(t."Fecha de Inicio del Contrato") = ?
    ORDER BY t."ID Contrato" ASC
    LIMIT ? OFFSET ?
    """
    return con.execute(sql, [path, departamento, year, page_size, offset]).df()
