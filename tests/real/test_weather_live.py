#!/usr/bin/env python3
"""真实测试：真的打 Open-Meteo 网络请求（不需要 cookie、不需要浏览器，只需要能上网），
验证城市和山地/具体地点的三级 fallback、海拔修正是否符合预期。

    python3 tests/real/test_weather_live.py
"""
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from weather.forecast import build_forecast
from weather.locations import MOUNTAIN_POINTS
from weather.open_meteo import fetch_jma_forecast


def check(label, cond):
    status = "PASS" if cond else "FAIL"
    print(f"{status} {label}")
    return cond


def main():
    ok = True
    # 用东京当地日期而不是本机系统时区的"今天"——本机时区若比东京慢（比如美西），
    # 系统时区的"今天"在东京可能已经过去，Open-Meteo 按 Asia/Tokyo 给的当天数组里
    # 会查无此日，见 weather/forecast.py 里 --start-date 默认值同样的处理。
    today = datetime.now(ZoneInfo("Asia/Tokyo")).replace(tzinfo=None)

    # 1. 城市短程预报：应该拿到真实 JMA 精细预报（tier1），温度在合理范围
    kobe_results = build_forecast(34.6901, 135.1955, None, today, forecast_days=5)
    ok &= check("神户 5 天预报有 5 条结果", len(kobe_results) == 5)
    ok &= check("神户第 1 天来自实时预报（非历史兜底）", "历史" not in kobe_results[0]["source"])
    ok &= check("神户第 1 天温度在合理范围 (0~40°C)", kobe_results[0]["temp_max"] is not None and 0 <= kobe_results[0]["temp_max"] <= 40)

    # 2. 30 天城市预报：验证三级 tier 都出现过（16 天内实时，16 天外历史）
    kobe_30 = build_forecast(34.6901, 135.1955, None, today, forecast_days=30)
    sources = {r["source"] for r in kobe_30}
    ok &= check("30 天预报里出现历史同期均值兜底", any("历史" in s for s in sources))
    ok &= check("30 天预报里出现实时预报", any("JMA" in s or "综合" in s for s in sources))

    # 3. 山地点位：室堂（2450m）应该明显比神户（海边城市）冷
    murodo_lat, murodo_lon, murodo_elev, _ = MOUNTAIN_POINTS["murodo"]
    murodo_results = build_forecast(murodo_lat, murodo_lon, murodo_elev, today, forecast_days=3)
    ok &= check(
        "室堂(2450m)第1天最高温明显低于神户(海边)第1天最高温",
        murodo_results[0]["temp_max"] is not None and kobe_results[0]["temp_max"] is not None
        and murodo_results[0]["temp_max"] < kobe_results[0]["temp_max"] - 5,
    )

    # 4. 海拔修正确实生效：显式传海拔 vs 不传，同一坐标下温度应有差异（或至少 elevation 字段被 API 采纳）
    bijodaira_lat, bijodaira_lon, bijodaira_elev, _ = MOUNTAIN_POINTS["bijodaira"]
    with_elev = fetch_jma_forecast(bijodaira_lat, bijodaira_lon, elevation=bijodaira_elev, days=1)
    without_elev = fetch_jma_forecast(bijodaira_lat, bijodaira_lon, elevation=None, days=1)
    same_temp = (
        with_elev.get("temperature_2m_max") == without_elev.get("temperature_2m_max")
    )
    ok &= check(
        "美女平传显式海拔后温度和不传海拔时不同（证明降尺度修正确实生效，不是摆设）",
        not same_temp,
    )

    # 5. 未知地点应该抛错而不是静默返回垃圾数据
    try:
        from argparse import Namespace
        from weather.forecast import resolve_location
        resolve_location(Namespace(point="not-a-real-place", city=None, latitude=None, longitude=None, elevation=None))
        ok &= check("未知 --point 应该报错退出", False)
    except SystemExit:
        ok &= check("未知 --point 正确报错退出", True)

    print(f"\n{'ALL PASS' if ok else 'SOME FAILED'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
