#!/usr/bin/env python3
"""真实测试：对携程/Expedia 五个 CLI 工具各发一次真实请求（真浏览器+真 cookie 注入+
真实网络），不是构造样例的冒烟测试。

前提条件（缺一不可，见根目录 README.md「前提条件」）：
  - 本机装好正式版 Google Chrome，且已经手动登录/浏览过携程和 Expedia、过了人机验证
  - pip install patchright pycryptodome secretstorage

跑起来会真的弹出/借用 Chrome 窗口，每个工具可能花 10-60+ 秒，五个下来几分钟：

    python3 tests/real/test_ctrip_expedia_live.py

每个工具的结果分三种：
  PASS     —— 正常拿到 >=1 条结果
  DEGRADED —— 命令本身跑成功（exit 0、JSON 能解析），但结果是 0 条——真实抓取本来就会
              受网站改版/风控/临时缺货影响，这属于已知的正常兜底行为，不算失败
  FAIL     —— 命令崩溃、超时，或输出不是合法 JSON

只有 FAIL 会让这个脚本以非零退出码结束；PASS/DEGRADED 都算跑通。
"""
import json
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
CLI = ROOT / "cli"
CHECKIN = (datetime.today() + timedelta(days=14)).strftime("%Y-%m-%d")
FLIGHT_DATE = (datetime.today() + timedelta(days=21)).strftime("%Y-%m-%d")


def _profile(tag):
    return str(Path.home() / ".config" / f"google-chrome-realtest-{tag}")


def run(tag, cmd, result_key="hotels", timeout=90):
    profile = _profile(tag)
    full_cmd = ["python3", *cmd, "--work-profile", profile, "--format", "json", "--timeout", "60"]
    print(f"--- {tag}: {' '.join(full_cmd)}")
    try:
        res = subprocess.run(full_cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        print(f"    FAIL 超时 ({timeout}s)")
        shutil.rmtree(profile, ignore_errors=True)
        return "FAIL"
    finally:
        pass

    if res.returncode != 0:
        print(f"    FAIL exit={res.returncode}, stderr 尾部: {res.stderr[-500:]}")
        shutil.rmtree(profile, ignore_errors=True)
        return "FAIL"

    try:
        data = json.loads(res.stdout)
    except json.JSONDecodeError as e:
        print(f"    FAIL 输出不是合法 JSON: {e}")
        shutil.rmtree(profile, ignore_errors=True)
        return "FAIL"

    shutil.rmtree(profile, ignore_errors=True)
    items = data.get(result_key) if isinstance(data, dict) and result_key else data
    count = len(items) if isinstance(items, list) else (1 if data else 0)
    if count > 0:
        print(f"    PASS 拿到 {count} 条结果")
        return "PASS"
    print("    DEGRADED 命令成功但 0 条结果（可能被风控/网站改版/该场次缺货）")
    return "DEGRADED"


def main():
    outcomes = {}

    outcomes["ctrip_hotels"] = run(
        "ctrip-hotels", [str(CLI / "ctrip_hotels.py"), "--city-id", "423", "--checkin", CHECKIN, "--nights", "1", "--limit", "10"],
        result_key="hotels",
    )
    outcomes["ctrip_flights"] = run(
        "ctrip-flights", [str(CLI / "ctrip_flights.py"), "--from", "hkg", "--to", "osa", "--date", FLIGHT_DATE, "--limit", "10"],
        result_key="flights",
    )
    outcomes["ctrip_room_details"] = run(
        "ctrip-room", [str(CLI / "ctrip_room_details.py"), "--hotel-id", "2107678", "--checkin", CHECKIN, "--nights", "1"],
        result_key="rooms",
    )
    outcomes["expedia_hotels"] = run(
        "expedia-hotels",
        [str(CLI / "expedia_hotels.py"), "--base-url", "www.expedia.com.hk", "--destination", "Kobe",
         "--checkin", CHECKIN, "--nights", "1", "--limit", "10"],
        result_key="hotels",
    )
    outcomes["expedia_room_details"] = run(
        "expedia-room",
        [str(CLI / "expedia_room_details.py"), "--hotel-id", "1209540", "--hotel-slug", "KOBE-Hotels-ANA-Crowne-Plaza-Kobe",
         "--checkin", CHECKIN, "--nights", "1"],
        result_key="rooms",
    )

    print("\n=== 汇总 ===")
    for name, outcome in outcomes.items():
        print(f"{outcome:10s} {name}")

    if any(v == "FAIL" for v in outcomes.values()):
        sys.exit(1)


if __name__ == "__main__":
    main()
