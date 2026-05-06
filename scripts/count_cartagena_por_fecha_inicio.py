"""
Cuenta contratos SECOP II por fecha_de_inicio_del_contrato, en DOS alcances independientes:

  1) Todo el departamento Bolivar (solo departamento).
  2) Solo ciudad Cartagena (departamento Bolivar + ciudad Cartagena).

En cada alcance, tres rangos de fechas (misma fecha_de_inicio_del_contrato):
  - Inicio en [2024-01-01 , 2027-01-01)  (incluye 2024, 2025 y 2026).
  - Inicio solo en 2020 (ano calendario).
  - Inicio el 31-dic-2019 o anterior (estrictamente antes de 2020-01-01).

Uso (raiz del repo):
  py -3 scripts/count_cartagena_por_fecha_inicio.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_ROOT / ".env", encoding="utf-8-sig", override=True)

_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from sadai.data_sources.secop_soda import count_contracts  # noqa: E402

_GEO_BOLIVAR_DEPTO = "departamento = 'Bolívar'"
_GEO_CARTAGENA = "departamento = 'Bolívar' AND ciudad = 'Cartagena'"

_FECHA_2024_2026 = (
    "fecha_de_inicio_del_contrato >= '2024-01-01T00:00:00.000' "
    "AND fecha_de_inicio_del_contrato < '2027-01-01T00:00:00.000'"
)

_FECHA_SOLO_2020 = (
    "fecha_de_inicio_del_contrato >= '2020-01-01T00:00:00.000' "
    "AND fecha_de_inicio_del_contrato < '2021-01-01T00:00:00.000'"
)

# 31-dic-2019 "para atras": todo inicio estrictamente antes de 2020-01-01 (incluye ese 31-dic).
_FECHA_HASTA_FIN_2019 = "fecha_de_inicio_del_contrato < '2020-01-01T00:00:00.000'"


def _where(geo: str, fecha: str) -> str:
    return f"{geo} AND {fecha}"


def main() -> None:
    bloques: tuple[tuple[str, str, tuple[tuple[str, str], ...]], ...] = (
        (
            "1) BOLIVAR (departamento completo, todas las ciudades)",
            _GEO_BOLIVAR_DEPTO,
            (
                ("Inicio en [2024-01-01 , 2027-01-01)", _FECHA_2024_2026),
                ("Inicio solo en 2020", _FECHA_SOLO_2020),
                ("Inicio hasta 31-dic-2019 inclusive (antes de 2020-01-01)", _FECHA_HASTA_FIN_2019),
            ),
        ),
        (
            "2) CARTAGENA solamente (mismo departamento, ciudad Cartagena)",
            _GEO_CARTAGENA,
            (
                ("Inicio en [2024-01-01 , 2027-01-01)", _FECHA_2024_2026),
                ("Inicio solo en 2020", _FECHA_SOLO_2020),
                ("Inicio hasta 31-dic-2019 inclusive (antes de 2020-01-01)", _FECHA_HASTA_FIN_2019),
            ),
        ),
    )

    for titulo, geo, rangos in bloques:
        print("=" * 72)
        print(titulo)
        print("Geografia (base):\n ", geo)
        print()
        for etiqueta_rango, fecha_clause in rangos:
            where = _where(geo, fecha_clause)
            n = count_contracts(where)
            print(f"  {etiqueta_rango}")
            print(f"    contratos: {n:,}")
            print(f"    where: {where}")
            print()
        print()


if __name__ == "__main__":
    main()
