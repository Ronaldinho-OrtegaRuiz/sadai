"""
Lista ciudades en SECOP II con contratos en el departamento Bolívar (conteo por ciudad).

También imprime ejemplos de $where para Cartagena (copiar a sodapy o API).

Uso (raíz del repo):
  py -3 scripts/list_ciudades_bolivar.py
  py -3 scripts/list_ciudades_bolivar.py --solo-cartagena
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_ROOT / ".env", encoding="utf-8-sig", override=True)

_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from sadai.secop_soda import contracts_grouped_by_ciudad, count_contracts  # noqa: E402

# En SECOP II este dataset suele traer la ciudad como "Cartagena" (no el nombre oficial largo).
_CARTAGENA_WHERE_EXAMPLES = (
    "departamento = 'Bolívar' AND ciudad = 'Cartagena'",
    "departamento = 'Bolívar' AND upper(ciudad) = 'CARTAGENA'",
    "departamento = 'Bolívar' AND ciudad like '%Cartagena%'",
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ciudades con contratos en Bolívar (SECOP II) y ejemplos SoQL para Cartagena.",
    )
    parser.add_argument(
        "--solo-cartagena",
        action="store_true",
        help="Solo muestra ejemplos SoQL y conteos para Cartagena (no tabla completa).",
    )
    parser.add_argument(
        "--departamento",
        default="Bolívar",
        help="Nombre del departamento en el campo departamento (default: Bolívar).",
    )
    args = parser.parse_args()

    if args.solo_cartagena:
        print("Ejemplos de clausula $where (Cartagena + Bolivar):\n")
        for w in _CARTAGENA_WHERE_EXAMPLES:
            print(f"  {w}")
        print()
        for w in _CARTAGENA_WHERE_EXAMPLES:
            try:
                n = count_contracts(w)
                print(f"  count -> {n:>8}  where={w!r}")
            except Exception as e:  # noqa: BLE001
                print(f"  error -> {e!s}  where={w!r}")
        return

    print(f"Ciudades con contratos en departamento = {args.departamento!r}\n")
    rows = contracts_grouped_by_ciudad(args.departamento)
    # total por fila puede venir como str desde JSON
    parsed: list[tuple[str, int]] = []
    for r in rows:
        ciudad = (r.get("ciudad") or "").strip() or "(vacío / null)"
        raw = r.get("total")
        n = int(raw) if raw is not None else 0
        parsed.append((ciudad, n))

    parsed.sort(key=lambda x: (-x[1], x[0]))
    print(f"{'Ciudad':<45} {'Contratos':>12}")
    print("-" * 58)
    for ciudad, n in parsed:
        print(f"{ciudad:<45} {n:>12,}")
    print("-" * 58)
    print(f"{'TOTAL ciudades listadas':<45} {len(parsed):>12,}")

    print("\n--- Cartagena: copiar en count_bolivar_contracts.py --where \"...\" ---\n")
    for w in _CARTAGENA_WHERE_EXAMPLES:
        print(f'  py -3 scripts/count_bolivar_contracts.py --where "{w}"')


if __name__ == "__main__":
    main()
