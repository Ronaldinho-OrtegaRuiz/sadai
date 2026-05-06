"""Catálogo departamento → ciudades (SECOP): API SODA, respaldo JSON y extracción desde export.csv."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb
import requests

from sadai.config import SECOP_CONTRATOS_DATASET_ID
from sadai.secop_soda import secop_client

GEO_CATALOG_FILENAME = "secop_geo_catalog.json"


def default_catalog_path(repo_root: Path) -> Path:
    return repo_root / "data" / GEO_CATALOG_FILENAME


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def fetch_dept_ciudad_catalog_via_api(
    *,
    timeout: float = 180.0,
    page_size: int = 50_000,
    max_rows: int = 5_000_000,
) -> dict[str, Any]:
    """
    Pares (departamento, ciudad) vía SoQL GROUP BY, paginado por offset.

    Devuelve dict con keys: departamentos (list[str]), ciudades_por_departamento (dict[str, list[str]]).
    """
    client = secop_client(timeout=timeout)
    pairs: dict[str, set[str]] = {}
    offset = 0
    while offset < max_rows:
        try:
            rows = client.get(
                SECOP_CONTRATOS_DATASET_ID,
                select="departamento, ciudad",
                where="departamento IS NOT NULL AND ciudad IS NOT NULL",
                group="departamento, ciudad",
                order="departamento ASC, ciudad ASC",
                limit=page_size,
                offset=offset,
            )
        except requests.HTTPError:
            raise
        if not rows:
            break
        for r in rows:
            d = str(r.get("departamento") or "").strip()
            c = str(r.get("ciudad") or "").strip()
            if d and c:
                pairs.setdefault(d, set()).add(c)
        if len(rows) < page_size:
            break
        offset += page_size

    if not pairs:
        raise RuntimeError("La API no devolvió pares departamento/ciudad (resultado vacío).")

    departamentos = sorted(pairs.keys(), key=str.casefold)
    ciudades_por_departamento = {d: sorted(pairs[d], key=str.casefold) for d in departamentos}
    return {
        "source": "api",
        "generated_at": _utc_now_iso(),
        "departamentos": departamentos,
        "ciudades_por_departamento": ciudades_por_departamento,
    }


def build_dept_ciudad_catalog_from_csv(csv_path: Path) -> dict[str, Any]:
    """
    DISTINCT Departamento, Ciudad desde export.csv (puede tardar en archivos muy grandes).
    """
    path = csv_path.resolve()
    if not path.is_file():
        raise FileNotFoundError(f"No existe el CSV: {path}")

    con = duckdb.connect(database=":memory:")

    sql = """
    SELECT DISTINCT
      trim(cast("Departamento" AS VARCHAR)) AS d,
      trim(cast("Ciudad" AS VARCHAR)) AS c
    FROM read_csv_auto(?, header=true, max_line_size=2000000, ignore_errors=true)
    WHERE "Departamento" IS NOT NULL AND trim(cast("Departamento" AS VARCHAR)) <> ''
      AND "Ciudad" IS NOT NULL AND trim(cast("Ciudad" AS VARCHAR)) <> ''
    """
    rows = con.execute(sql, [str(path)]).fetchall()
    pairs: dict[str, set[str]] = {}
    for d, c in rows:
        if d and c:
            pairs.setdefault(d, set()).add(c)
    departamentos = sorted(pairs.keys(), key=str.casefold)
    ciudades_por_departamento = {dep: sorted(pairs[dep], key=str.casefold) for dep in departamentos}
    return {
        "source": "csv",
        "generated_at": _utc_now_iso(),
        "departamentos": departamentos,
        "ciudades_por_departamento": ciudades_por_departamento,
    }


def save_geo_catalog(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_geo_catalog(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def resolve_geo_catalog(
    repo_root: Path,
    csv_path: Path,
    *,
    prefer_api: bool = True,
    catalog_path: Path | None = None,
) -> tuple[dict[str, Any], str]:
    """
    Intenta API; si falla, JSON guardado; si no hay JSON, DISTINCT sobre CSV.

    Returns:
        (catalog_dict, origin_label) donde origin_label es 'api' | 'json' | 'csv'.
    """
    out_path = catalog_path or default_catalog_path(repo_root)

    if prefer_api:
        try:
            data = fetch_dept_ciudad_catalog_via_api()
            save_geo_catalog(out_path, data)
            return data, "api"
        except (requests.HTTPError, requests.RequestException, OSError, RuntimeError) as e:
            print(f"[geo_catalog] API no disponible, se usan respaldos: {e}", file=sys.stderr)

    loaded = load_geo_catalog(out_path)
    if loaded and loaded.get("departamentos"):
        return loaded, "json"

    data = build_dept_ciudad_catalog_from_csv(csv_path)
    save_geo_catalog(out_path, data)
    return data, "csv"
