from __future__ import annotations

import sys

from _bootstrap import bootstrap

bootstrap()

from qmt_local_data.cli import main

if __name__ == "__main__":
    raise SystemExit(main(["storage-audit", *sys.argv[1:]]))
