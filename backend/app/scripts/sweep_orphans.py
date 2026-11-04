"""Varredura manual de objetos órfãos no armazenamento (a mesma tarefa diária do beat).

python -m app.scripts.sweep_orphans --dry-run   # só conta o que seria apagado
python -m app.scripts.sweep_orphans             # apaga
"""

import argparse
import json
import sys

from app.core.logging import configure_logging
from app.services.orphan_service import sweep_orphans


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="não apaga, só conta")
    args = parser.parse_args()
    configure_logging()
    print(json.dumps(sweep_orphans(dry_run=args.dry_run), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
