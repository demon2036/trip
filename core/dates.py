#!/usr/bin/env python3
"""core/dates.py — 入住/退房日期解析与校验（--checkout 与 --nights 二选一）。"""

from datetime import datetime, timedelta


def compute_dates(checkin, checkout, nights):
    ci = datetime.strptime(checkin, "%Y-%m-%d").date()
    co = datetime.strptime(checkout, "%Y-%m-%d").date() if checkout else ci + timedelta(days=nights)
    if co <= ci:
        raise SystemExit("退房日期必须晚于入住日期。")
    return ci.isoformat(), co.isoformat()
