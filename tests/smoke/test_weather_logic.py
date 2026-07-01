#!/usr/bin/env python3
"""冒烟测试：weather/ 包里不需要网络的纯逻辑——地点解析优先级、分级 fallback 的选择
逻辑。用 unittest.mock 打桩掉 open_meteo 的网络请求函数，构造数据验证分支正确。

不需要网络，跑得快：

    python3 tests/smoke/test_weather_logic.py

真正打网络请求验证 Open-Meteo 返回是否合理，见 tests/real/test_weather_live.py。
"""
import sys
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from weather.forecast import build_forecast, resolve_location
from weather.locations import CITIES, MOUNTAIN_POINTS


def _args(**kw):
    base = dict(point=None, latitude=None, longitude=None, elevation=None, city=None)
    base.update(kw)
    return Namespace(**base)


def test_resolve_location_point_priority():
    # --point 优先于 --city，即使两个都传了
    lat, lon, elev, name = resolve_location(_args(point="murodo", city="kobe"))
    assert (lat, lon, elev) == MOUNTAIN_POINTS["murodo"][:3]
    assert name == MOUNTAIN_POINTS["murodo"][3]


def test_resolve_location_manual_coords_priority():
    # 手动坐标优先于 --city
    lat, lon, elev, name = resolve_location(_args(latitude=10.0, longitude=20.0, elevation=30.0, city="kobe"))
    assert (lat, lon, elev) == (10.0, 20.0, 30.0)


def test_resolve_location_city_default():
    # 什么都不传，默认 kobe（向后兼容原行为）
    lat, lon, elev, name = resolve_location(_args())
    assert (lat, lon) == CITIES["kobe"][:2]
    assert elev is None


def test_resolve_location_unknown_point_raises():
    try:
        resolve_location(_args(point="atlantis"))
        raise AssertionError("应该抛 SystemExit")
    except SystemExit:
        pass


def test_build_forecast_gap_within_live_window_falls_back_to_history():
    """回归测试：修复前的 bug——如果实时预报（tier1/tier2）漏掉了请求范围内下标
    < 16 的某一天（例如运行时区比东京晚导致"今天"在东京已经过去，Open-Meteo 的
    Asia/Tokyo 预报数组不包含这一天），历史兜底当时只覆盖了下标 >=16 的日期，
    导致那天既不在实时预报里、也查不到历史数据，最后温度变 None。现在应该无论
    缺口出现在第几天，都统一退到历史同期均值，正确拿到数据而不是 None。"""
    fake_tier1 = {  # 缺 2026-07-01（模拟"今天"在东京已经过去的情况）
        "time": ["2026-07-02", "2026-07-03"],
        "temperature_2m_max": [20.0, 21.0],
        "temperature_2m_min": [10.0, 11.0],
        "weather_code": [1, 1],
    }
    fake_tier2 = {"time": [], "temperature_2m_max": [], "temperature_2m_min": [], "weather_code": []}
    fake_hist = {(7, 1): [{"weather_code": 2, "temp_max": 18.0, "temp_min": 9.0, "rain_sum": 0.0}]}

    with patch("weather.forecast.fetch_jma_forecast", return_value=fake_tier1), \
         patch("weather.forecast.fetch_best_match_forecast", return_value=fake_tier2), \
         patch("weather.forecast.fetch_historical_range", return_value=fake_hist):
        from datetime import datetime
        results = build_forecast(34.0, 135.0, None, datetime(2026, 7, 1), forecast_days=3)

    assert results[0]["date"] == "2026-07-01"
    assert results[0]["temp_max"] == 18.0, "缺口日应该退到历史均值拿到真实数值，而不是 None"
    assert results[0]["source"] == "📜 历史同期均值"
    assert results[1]["source"] == "🎌 JMA精细预报"
    assert results[1]["temp_max"] == 20.0


def test_build_forecast_beyond_16_days_uses_history():
    with patch("weather.forecast.fetch_jma_forecast", return_value={}), \
         patch("weather.forecast.fetch_best_match_forecast", return_value={}), \
         patch("weather.forecast.fetch_historical_range", return_value={}):
        from datetime import datetime
        results = build_forecast(34.0, 135.0, None, datetime(2026, 7, 1), forecast_days=20)

    assert results[19]["source"] == "📜 历史同期均值"


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"OK   {t.__name__}")
        except Exception as e:
            failed += 1
            print(f"FAIL {t.__name__}: {e!r}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
