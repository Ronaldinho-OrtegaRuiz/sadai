"""Cliente SODA (sodapy) para SECOP II — contratos electrónicos."""

from __future__ import annotations

import sys
from datetime import datetime
from typing import Literal

import requests
from sodapy import Socrata

from sadai.config import SECOP_CONTRATOS_DATASET_ID, SODA_DOMAIN, soda_app_token


def _print_raw_http_error(exc: requests.HTTPError) -> None:
    """Escribe en stderr status, URL y cuerpo tal cual devuelve el servidor."""
    print("--- Respuesta HTTP SODA (tal cual) ---", file=sys.stderr)
    req = exc.request
    if req is not None:
        print(f"request_method: {req.method}", file=sys.stderr)
        print(f"request_url: {req.url}", file=sys.stderr)
    resp = exc.response
    if resp is not None:
        print(f"status_code: {resp.status_code}", file=sys.stderr)
        print(f"reason: {resp.reason}", file=sys.stderr)
        print("response_headers:", file=sys.stderr)
        for hk, hv in resp.headers.items():
            print(f"  {hk}: {hv}", file=sys.stderr)
        print("response_body:", file=sys.stderr)
        print(resp.text or "", file=sys.stderr)
    else:
        print("(sin objeto response)", file=sys.stderr)


def secop_client(timeout: float = 120.0) -> Socrata:
    token = soda_app_token()
    client = Socrata(SODA_DOMAIN, token, timeout=timeout)
    # Cabecera canónica (sodapy usa X-App-token; algunos proxies son quisquillosos)
    if token:
        client.session.headers.pop("X-App-token", None)
        client.session.headers["X-App-Token"] = token
    return client


def count_contracts(
    where: str,
    timeout: float = 120.0,
    *,
    show_soda_response: bool = False,
) -> int:
    """
    Cuenta filas del dataset SECOP II que cumplan el filtro SoQL en $where.

    Ejemplo de where: "departamento = 'Bolívar'"

    show_soda_response: si True, ante error HTTP imprime cuerpo/cabeceras crudos
    y relanza la misma excepción (no envuelve en RuntimeError).
    """
    client = secop_client(timeout=timeout)
    get_kw: dict = {
        "select": "count(*) as total",
        "where": where,
        "limit": 1,
    }
    # Token solo por cabecera X-App-Token (doc SODA 2.x/3.x). No app_token en URL:
    # evita filtrar el secreto en logs y en --show-soda-response.

    try:
        rows = client.get(SECOP_CONTRATOS_DATASET_ID, **get_kw)
    except requests.HTTPError as e:
        if show_soda_response:
            _print_raw_http_error(e)
            raise
        body = (e.response.text or "") if e.response is not None else ""
        if "Invalid app_token" in body or "invalid app_token" in body.lower():
            raise RuntimeError(
                "SODA 403: token no válido para X-App-Token / app_token. "
                "Debe ser un Application Token creado desde tu perfil en "
                "www.datos.gov.co (no el par API Key de publicación). "
                "Deja solo SODA_APP_TOKEN en .env (sin API_KEY vieja). "
                "Prueba: py -3 scripts/count_bolivar_contracts.py --omit-token"
            ) from e
        raise
    if not rows:
        return 0
    raw = rows[0].get("total")
    if raw is None:
        raw = rows[0].get("count")
    if raw is None:
        return int(next(iter(rows[0].values())))
    return int(raw)


def contracts_grouped_by_ciudad(
    departamento: str = "Bolívar",
    *,
    timeout: float = 180.0,
    show_soda_response: bool = False,
) -> list[dict[str, object]]:
    """
    Lista ciudades con número de contratos SECOP II en ese departamento.

    Usa SoQL: SELECT ciudad, count(*) ... GROUP BY ciudad.
    """
    client = secop_client(timeout=timeout)
    where = f"departamento = '{departamento}'"
    try:
        rows = client.get(
            SECOP_CONTRATOS_DATASET_ID,
            select="ciudad, count(*) as total",
            where=where,
            group="ciudad",
            order="ciudad ASC",
            limit=50000,
        )
    except requests.HTTPError as e:
        if show_soda_response:
            _print_raw_http_error(e)
            raise
        raise
    return rows or []


GeoKind = Literal["bolivar", "cartagena"]


def geo_where_clause(kind: GeoKind) -> str:
    """Filtro SoQL de ubicación: todo Bolívar o solo Cartagena."""
    if kind == "cartagena":
        return "departamento = 'Bolívar' AND ciudad = 'Cartagena'"
    return "departamento = 'Bolívar'"


def where_inicio_en_ano(geo_kind: GeoKind, year: int) -> str:
    """Contratos con fecha_de_inicio_del_contrato en el año calendario `year`."""
    geo = geo_where_clause(geo_kind)
    y0 = f"{year:04d}-01-01T00:00:00.000"
    y1 = f"{year + 1:04d}-01-01T00:00:00.000"
    return (
        f"{geo} AND fecha_de_inicio_del_contrato >= '{y0}' "
        f"AND fecha_de_inicio_del_contrato < '{y1}'"
    )


def _parse_soda_timestamp(value: object) -> datetime | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1]
    s = s.replace(" ", "T", 1)
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        try:
            return datetime.strptime(s[:10], "%Y-%m-%d")
        except ValueError:
            return None


def fecha_inicio_anos_disponibles(
    geo_kind: GeoKind,
    *,
    timeout: float = 180.0,
) -> tuple[int, int]:
    """
    (año_mínimo, año_máximo) según min/max de fecha_de_inicio_del_contrato con datos no nulos.
    Si falla la agregación, devuelve (2000, 2030) como respaldo conservador.
    """
    base = geo_where_clause(geo_kind)
    where = f"{base} AND fecha_de_inicio_del_contrato IS NOT NULL"
    client = secop_client(timeout=timeout)
    fallback = (2000, 2030)
    try:
        rows = client.get(
            SECOP_CONTRATOS_DATASET_ID,
            select="min(fecha_de_inicio_del_contrato) as mn, max(fecha_de_inicio_del_contrato) as mx",
            where=where,
            limit=1,
        )
    except requests.HTTPError:
        return fallback
    if not rows:
        return fallback
    row = rows[0]
    mn = _parse_soda_timestamp(row.get("mn"))
    mx = _parse_soda_timestamp(row.get("mx"))
    if mn is None or mx is None:
        return fallback
    y_lo, y_hi = mn.year, mx.year
    if y_lo > y_hi:
        return fallback
    return (y_lo, y_hi)


def fetch_contracts_page(
    geo_kind: GeoKind,
    year: int,
    page: int,
    *,
    page_size: int = 10,
    timeout: float = 120.0,
) -> list[dict[str, object]]:
    """
    Una página de contratos ($select=*), orden estable por id_contrato.
    `page` en base 0.
    """
    where = where_inicio_en_ano(geo_kind, year)
    offset = max(0, page) * page_size
    client = secop_client(timeout=timeout)
    rows = client.get(
        SECOP_CONTRATOS_DATASET_ID,
        select="*",
        where=where,
        limit=page_size,
        offset=offset,
        order="id_contrato ASC",
    )
    return list(rows) if rows else []
