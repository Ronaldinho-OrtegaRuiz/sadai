"""
Cuenta contratos SECOP II cuyo departamento coincide con Bolívar.

Uso (desde la raíz del repo):
  py -3 -m pip install -r requirements.txt
  py -3 scripts/count_bolivar_contracts.py

Requiere API_KEY o SODA_APP_TOKEN en .env (recomendado para límites de API).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import requests

from dotenv import load_dotenv

# Raíz del proyecto (mismo nivel que .gitignore y .env)
_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_ROOT / ".env", encoding="utf-8-sig", override=True)

_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from sadai.config import soda_app_token, soda_token_meta  # noqa: E402
from sadai.secop_soda import count_contracts  # noqa: E402

# Valores frecuentes en datos abiertos (acento / mayúsculas). Se prueba en orden.
_DEFAULT_CANDIDATES = (
    "departamento = 'Bolívar'",
    "departamento = 'BOLÍVAR'",
    "departamento = 'Bolivar'",
    "departamento = 'BOLIVAR'",
    "upper(departamento) = 'BOLÍVAR'",
    "upper(departamento) = 'BOLIVAR'",
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Cuenta contratos por filtro departamento.")
    parser.add_argument(
        "--where",
        default=None,
        help="Cláusula SoQL completa para $where (si se omite, se prueban variantes de Bolívar).",
    )
    parser.add_argument(
        "--omit-token",
        action="store_true",
        help="No envía App Token (útil si el token da 403 y quieres comprobar el resto).",
    )
    parser.add_argument(
        "--token-debug",
        action="store_true",
        help="Muestra qué variable aporta el token y su longitud (no muestra el secreto).",
    )
    parser.add_argument(
        "--show-soda-response",
        action="store_true",
        help="Si hay error HTTP, imprime URL, cabeceras y cuerpo tal cual (stderr) y termina.",
    )
    args = parser.parse_args()

    if args.omit_token:
        for k in ("SODA_APP_TOKEN", "API_KEY", "APP_TOKEN"):
            os.environ.pop(k, None)

    if args.token_debug:
        key, n = soda_token_meta()
        env_path = _ROOT / ".env"
        print(
            f"token_debug: variable={key!r}, longitud={n}, "
            f".env_existe={env_path.is_file()}, ruta_env={env_path}",
            file=sys.stderr,
        )

    if not soda_app_token():
        print(
            "Aviso: no hay token en .env (API_KEY o SODA_APP_TOKEN). "
            "La petición puede fallar o ir muy lenta por throttling.\n",
            file=sys.stderr,
        )

    raw = args.show_soda_response

    if args.where:
        try:
            n = count_contracts(args.where, show_soda_response=raw)
        except requests.HTTPError:
            sys.exit(1)
        except RuntimeError as e:
            print(e, file=sys.stderr)
            sys.exit(2)
        print(f"Contratos (where={args.where!r}): {n}")
        return

    auth_error: RuntimeError | None = None
    for clause in _DEFAULT_CANDIDATES:
        try:
            n = count_contracts(clause, show_soda_response=raw)
        except requests.HTTPError:
            sys.exit(1)
        except RuntimeError as e:
            if not raw and ("403" in str(e) or "token" in str(e).lower()):
                auth_error = e
                break
            raise
        except Exception as e:  # noqa: BLE001 — script CLI
            print(f"Fallo con {clause!r}: {e}", file=sys.stderr)
            continue
        if n > 0:
            print(f"Contratos en Bolívar ({clause}): {n}")
            return

    if auth_error is not None:
        print(auth_error, file=sys.stderr)
        sys.exit(2)

    print(
        "No hubo coincidencias con las variantes por defecto. "
        "Pasa una cláusula explícita, por ejemplo:\n"
        "  py -3 scripts/count_bolivar_contracts.py --where \"departamento = 'TuValor'\"",
        file=sys.stderr,
    )
    sys.exit(1)


if __name__ == "__main__":
    main()
