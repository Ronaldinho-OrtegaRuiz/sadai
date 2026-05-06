"""GeoJSON municipios DANE y emparejamiento con ciudad SECOP (dentro de un departamento)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from sadai.geo.colombia_geo import norm_departamento_label

GEOJSON_MPIO_URL = (
    "https://raw.githubusercontent.com/caticoa3/colombia_mapa/master/"
    "co_2018_MGN_MPIO_POLITICO.geojson"
)

# Normalizado ciudad SECOP → normalizado MPIO_CNMBR DANE (cuando no alcanza el match automático)
_NORM_CIUDAD_TO_NORM_MPIO: dict[str, str] = {
    # Capital distrital
    "BOGOTA": "BOGOTA, D.C.",
    "SANTA FE DE BOGOTA": "BOGOTA, D.C.",
}


def load_municipios_geojson(
    *,
    local_path: Path | None = None,
    download_timeout: float = 120.0,
) -> dict[str, Any]:
    if local_path is not None and local_path.is_file():
        return json.loads(local_path.read_text(encoding="utf-8"))

    req = urllib.request.Request(GEOJSON_MPIO_URL, headers={"User-Agent": "SADAI/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=download_timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise OSError(f"HTTP {e.code} al descargar GeoJSON municipios: {GEOJSON_MPIO_URL}") from e
    except urllib.error.URLError as e:
        raise OSError(f"Red / URL GeoJSON municipios: {e}") from e


def find_municipio_feature(
    mpio_geo: dict[str, Any],
    *,
    dpto_cnmbr_exact: str,
    secop_ciudad: str,
) -> dict[str, Any] | None:
    """
    Devuelve el Feature del municipio que mejor coincide con `secop_ciudad`
    dentro del departamento `dpto_cnmbr_exact` (valor exacto DPTO_CNMBR).
    """
    raw_ciudad = str(secop_ciudad).strip()
    if not raw_ciudad:
        return None

    candidatos = [
        f
        for f in mpio_geo.get("features") or []
        if (f.get("properties") or {}).get("DPTO_CNMBR") == dpto_cnmbr_exact
    ]
    if not candidatos:
        return None

    nc = norm_departamento_label(raw_ciudad)
    if nc in _NORM_CIUDAD_TO_NORM_MPIO:
        objetivo = _NORM_CIUDAD_TO_NORM_MPIO[nc]
        for f in candidatos:
            nm = norm_departamento_label(str((f.get("properties") or {}).get("MPIO_CNMBR", "")))
            if nm == objetivo:
                return f

    for f in candidatos:
        nm = norm_departamento_label(str((f.get("properties") or {}).get("MPIO_CNMBR", "")))
        if nm == nc:
            return f

    for f in candidatos:
        nm = norm_departamento_label(str((f.get("properties") or {}).get("MPIO_CNMBR", "")))
        if nc in nm or nm in nc:
            if abs(len(nm) - len(nc)) <= 22:
                return f

    return None
