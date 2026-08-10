"""``python -m inkflow`` で GUI を起動する。

CLI は ``python -m inkflow.cli`` 側。
"""

import sys

from .gui.app import run

if __name__ == "__main__":
    sys.exit(run())
