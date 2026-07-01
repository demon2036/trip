#!/usr/bin/env python3
"""expedia/common.py — Expedia 站点专属的共享小工具（被 hotels.py 与 room_details.py 复用）。"""

from urllib.parse import urlparse


def host_suffix_from(base_url):
    """从 --base-url 推出 cookie 域后缀；auto→expedia.com。"""
    if not base_url or base_url == "auto":
        return "expedia.com", "www.expedia.com"
    h = urlparse(base_url if "://" in base_url else "https://" + base_url).hostname or "www.expedia.com"
    parts = h.split(".")
    suffix = ".".join(parts[-3:]) if h.endswith(("co.jp", "com.hk", "com.au")) else ".".join(parts[-2:])
    return suffix, h
