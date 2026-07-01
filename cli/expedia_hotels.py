#!/usr/bin/env python3
"""expedia_hotels.py — CLI 入口，实现见 expedia/hotels.py（用法见根目录 README.md）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from expedia.hotels import main

if __name__ == "__main__":
    main()
