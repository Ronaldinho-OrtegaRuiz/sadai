"""GeoJSON departamentos Colombia (DANE) y emparejamiento con texto SECOP/export."""

from __future__ import annotations

import json
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

# Marco Geoestadístico Nacional (DANE), vía repositorio público.
GEOJSON_URL = (
    "https://raw.githubusercontent.com/caticoa3/colombia_mapa/master/"
    "co_2018_MGN_DPTO_POLITICO.geojson"
)

# Normalizado (sin tildes, mayúsculas) → nombre oficial en GeoJSON (properties.DPTO_CNMBR)
_MANUAL_NORM_TO_DPTO: dict[str, str] = {
    # SECOP suele usar nombre largo; DANE usa "BOGOTÁ, D.C."
    "DISTRITO CAPITAL DE BOGOTA": "BOGOTÁ, D.C.",
    "DISTRITO CAPITAL": "BOGOTÁ, D.C.",
    # Variantes cortas
    "SAN ANDRES": "ARCHIPIÉLAGO DE SAN ANDRÉS, PROVIDENCIA Y SANTA CATALINA",
    "ARCHIPIELAGO DE SAN ANDRES": "ARCHIPIÉLAGO DE SAN ANDRÉS, PROVIDENCIA Y SANTA CATALINA",
}


def norm_departamento_label(s: str) -> str:
    s = unicodedata.normalize("NFD", str(s).strip())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return " ".join(s.upper().split())


def load_departamentos_geojson(
    *,
    local_path: Path | None = None,
    download_timeout: float = 90.0,
) -> dict[str, Any]:
    """
    Carga FeatureCollection desde `local_path` si existe; si no, descarga GEOJSON_URL.
    """
    if local_path is not None and local_path.is_file():
        return json.loads(local_path.read_text(encoding="utf-8"))

    req = urllib.request.Request(GEOJSON_URL, headers={"User-Agent": "SADAI/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=download_timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise OSError(f"HTTP {e.code} al descargar GeoJSON: {GEOJSON_URL}") from e
    except urllib.error.URLError as e:
        raise OSError(f"Red / URL GeoJSON: {e}") from e


def build_norm_to_dpto_cnmbr(geojson: dict[str, Any]) -> dict[str, str]:
    """Mapa normalizado → valor exacto DPTO_CNMBR (para featureidkey)."""
    out: dict[str, str] = {}
    for feat in geojson.get("features") or []:
        props = feat.get("properties") or {}
        nm = props.get("DPTO_CNMBR")
        if not nm:
            continue
        nk = norm_departamento_label(str(nm))
        out[nk] = str(nm).strip()
    return out


def secop_departamento_to_geo_key(
    secop_name: str,
    norm_to_dpto: dict[str, str],
) -> str | None:
    """Devuelve DPTO_CNMBR del GeoJSON o None si no hay match."""
    raw = str(secop_name).strip()
    if not raw:
        return None
    n = norm_departamento_label(raw)
    if n in _MANUAL_NORM_TO_DPTO:
        return _MANUAL_NORM_TO_DPTO[n]
    if n in norm_to_dpto:
        return norm_to_dpto[n]
    return None


def choropleth_series(
    geojson: dict[str, Any],
    departamentos: list[str],
    valores: list[int],
    norm_to_dpto: dict[str, str],
) -> tuple[list[str], list[float], list[str]]:
    """
    Devuelve (locations, z, sin_match) donde locations son DPTO_CNMBR en orden del GeoJSON.
    """
    acc: dict[str, float] = {}
    sin_match: list[str] = []
    seen_unmatched: set[str] = set()
    for dep, val in zip(departamentos, valores):
        key = secop_departamento_to_geo_key(dep, norm_to_dpto)
        if key is None:
            if dep not in seen_unmatched:
                seen_unmatched.add(dep)
                sin_match.append(dep)
            continue
        acc[key] = acc.get(key, 0.0) + float(val)

    order: list[str] = []
    for feat in geojson.get("features") or []:
        props = feat.get("properties") or {}
        nm = props.get("DPTO_CNMBR")
        if nm:
            order.append(str(nm).strip())

    z = [acc.get(k, 0.0) for k in order]
    return order, z, sin_match
