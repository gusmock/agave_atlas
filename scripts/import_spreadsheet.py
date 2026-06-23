from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.importer import import_spreadsheet


def main() -> None:
    parser = argparse.ArgumentParser(description="Importa planilha para SQLite.")
    parser.add_argument("path", help="Caminho para .xlsm, .xlsx ou .csv")
    parser.add_argument("--db", help="Caminho do SQLite de destino")
    args = parser.parse_args()
    result = import_spreadsheet(args.path, args.db)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
