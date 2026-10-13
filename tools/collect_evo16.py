#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 EVOLINUX contributors
"""Run the packaged read-only collector directly from an existing checkout."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from evolinux.diagnostics import collect, main
if __name__ == "__main__":
    sys.exit(main())
