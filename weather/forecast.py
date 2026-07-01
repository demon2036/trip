#!/usr/bin/env python3
"""weather_forecast 的编排层：解析命令行 → 拼出坐标/海拔 → 调用 open_meteo 分级预报 → 输出。

不需要 cookie、不需要浏览器，纯 HTTP 调 Open-Meteo 公开 API。
"""
import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from weather.locations import CITIES, MOUNTAIN_POINTS, resolve_city, resolve_point
from weather.open_meteo import (
    WMO_CODES,
    compute_historical_avg,
    fetch_best_match_forecast,
    fetch_historical_range,
    fetch_jma_forecast,
)

LIVE_TIER_LABELS = {
    "jma": "🎌 JMA精细预报",
    "best_match": "🌐 多模型综合预报",
    "history": "📜 历史同期均值",
}


def resolve_location(args):
    """返回 (lat, lon, elevation_or_None, 显示名)。优先级：--point > 手动坐标 > --city（默认 kobe）。"""
    if args.point:
        p = resolve_point(args.point)
        if not p:
            raise SystemExit(
                f"未知地点 '{args.point}'。内置: {', '.join(MOUNTAIN_POINTS)}"
                f"（也可以用 --latitude/--longitude[/--elevation] 手动指定任意坐标）"
            )
        lat, lon, elevation, name = p
        return lat, lon, elevation, name

    if args.latitude is not None and args.longitude is not None:
        return args.latitude, args.longitude, args.elevation, (args.city or "自定义坐标")

    city_key = (args.city or "kobe").lower()
    c = resolve_city(city_key)
    if not c:
        raise SystemExit(
            f"未知城市 '{city_key}'。请通过 --latitude/--longitude 传坐标，"
            f"或用 --point 选内置山地/具体地点（--list-points 查看）。"
        )
    lat, lon, name = c
    return lat, lon, None, name


def _row(date, temp_max, temp_min, rain_prob, weather, tier, wind=None, uv=None):
    return {
        "date": date,
        "temp_max": temp_max,
        "temp_min": temp_min,
        "rain_prob": rain_prob,
        "weather": weather,
        "wind_speed_max": wind,
        "uv_index_max": uv,
        "source": LIVE_TIER_LABELS[tier],
    }


def _valid_idx(tier_data, dates_list, d):
    """d 在 dates_list 里且对应 temperature_2m_max 非 None，返回下标；否则 None。"""
    if d not in dates_list:
        return None
    idx = dates_list.index(d)
    if tier_data.get("temperature_2m_max", [None] * (idx + 1))[idx] is None:
        return None
    return idx


def _pick(tier_data, idx):
    return {
        "temp_max": tier_data["temperature_2m_max"][idx],
        "temp_min": tier_data["temperature_2m_min"][idx],
        "rain_prob": (tier_data.get("precipitation_probability_max") or [0] * (idx + 1))[idx] or 0,
        "weather": WMO_CODES.get(tier_data["weather_code"][idx], "多云"),
        "wind": (tier_data.get("wind_speed_10m_max") or [None] * (idx + 1))[idx],
        "uv": (tier_data.get("uv_index_max") or [None] * (idx + 1))[idx],
    }


def build_forecast(lat, lon, elevation, start_dt, forecast_days):
    """三级 fallback：JMA 精细预报 → 多模型综合预报（两者合计最多 16 天）→ 历史同期均值。

    「日期是否落在实时预报覆盖范围内」不能只按下标 < 16 简单判断——Open-Meteo 按
    Asia/Tokyo 本地日历给「今天」定义，如果运行本工具的机器所在时区比东京晚（例如
    美西 PDT 比东京慢 16 小时），系统时钟的「今天」在东京可能已经跨入下一天，导致
    请求的第 1 天在两个实时 tier 的返回里都查无此日。所以这里对全部请求日期都做
    「有没有拿到有效实时数据」的判断，任何缺口（不管在请求范围内的第几天）统一
    退到历史同期均值兜底，而不是假定缺口只会出现在第 16 天之后。
    """
    live_days = min(forecast_days, 16)
    all_dates = [(start_dt + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(forecast_days)]

    tier1 = {}
    try:
        tier1 = fetch_jma_forecast(lat, lon, elevation, days=live_days) if live_days else {}
    except Exception as e:
        print(f"[debug] JMA 精细预报获取失败: {e}", file=sys.stderr)
    t1_dates = tier1.get("time", [])

    live_gap = [d for d in all_dates[:live_days] if _valid_idx(tier1, t1_dates, d) is None]

    tier2 = {}
    if live_gap:
        try:
            tier2 = fetch_best_match_forecast(lat, lon, elevation, days=live_days)
        except Exception as e:
            print(f"[debug] 综合预报获取失败: {e}", file=sys.stderr)
    t2_dates = tier2.get("time", [])

    plan = []  # [(date, tier, idx)]
    hist_needed = []
    for i, d in enumerate(all_dates):
        idx1 = _valid_idx(tier1, t1_dates, d) if i < live_days else None
        if idx1 is not None:
            plan.append((d, "jma", idx1))
            continue
        idx2 = _valid_idx(tier2, t2_dates, d) if i < live_days else None
        if idx2 is not None:
            plan.append((d, "best_match", idx2))
            continue
        plan.append((d, "history", None))
        hist_needed.append(d)

    hist_map = {}
    if hist_needed:
        hist_map = fetch_historical_range(lat, lon, min(hist_needed), max(hist_needed), elevation)

    results = []
    for d, tier, idx in plan:
        if tier == "jma":
            v = _pick(tier1, idx)
            results.append(_row(d, v["temp_max"], v["temp_min"], v["rain_prob"], v["weather"], "jma", v["wind"], v["uv"]))
        elif tier == "best_match":
            v = _pick(tier2, idx)
            results.append(_row(d, v["temp_max"], v["temp_min"], v["rain_prob"], v["weather"], "best_match", v["wind"], v["uv"]))
        else:
            dt_val = datetime.strptime(d, "%Y-%m-%d")
            avg = compute_historical_avg(hist_map.get((dt_val.month, dt_val.day), []))
            results.append(_row(d, avg["temp_max"], avg["temp_min"], avg["rain_prob"], avg["weather"], "history"))

    return results


def run(args):
    lat, lon, elevation, name = resolve_location(args)
    start_dt = datetime.strptime(args.start_date, "%Y-%m-%d")
    results = build_forecast(lat, lon, elevation, start_dt, args.days)

    if args.format == "md":
        elev_str = f"，海拔 {elevation:.0f}m" if elevation is not None else ""
        print(f"# 🌦️ {name} 天气预测报告 ({args.start_date} 起，共 {args.days} 天{elev_str})\n")
        print("| 日期 | 最低/最高气温 | 天气情况 | 降水概率 | 风速(km/h) | 紫外线指数 | 数据来源 |")
        print("|---|---|---|---|---|---|---|")
        for r in results:
            t_str = f"{r['temp_min']:.1f}°C ~ {r['temp_max']:.1f}°C" if r["temp_max"] is not None else "—"
            wind_str = f"{r['wind_speed_max']:.0f}" if r["wind_speed_max"] is not None else "—"
            uv_str = f"{r['uv_index_max']:.1f}" if r["uv_index_max"] is not None else "—"
            print(f"| {r['date']} | {t_str} | {r['weather']} | {r['rain_prob']}% | {wind_str} | {uv_str} | {r['source']} |")
        print(f"\n_坐标 {lat}, {lon}{elev_str}；16 天内为实时预报（JMA 精细优先，综合预报兜底），"
              f"16 天外为最近 3 整年同期历史均值参考。数据源: Open-Meteo。_")
    else:
        print(json.dumps(
            {"name": name, "latitude": lat, "longitude": lon, "elevation": elevation, "forecast": results},
            ensure_ascii=False, indent=2,
        ))
    return 0


def main():
    ap = argparse.ArgumentParser(description="日本旅游天气预测：城市 + 山地/具体地点，30 天视野")
    ap.add_argument("--city", default=None, help="城市拼音，如 kobe, tokyo, osaka, kyoto（默认 kobe；与 --point 二选一）")
    ap.add_argument("--point", default=None, help="内置山地/具体地点键名，如 murodo, bijodaira, togakushi")
    ap.add_argument("--latitude", type=float, default=None)
    ap.add_argument("--longitude", type=float, default=None)
    ap.add_argument("--elevation", type=float, default=None, help="配合 --latitude/--longitude 手动指定海拔(米)，用于山地精度修正")
    ap.add_argument(
        "--start-date",
        default=datetime.now(ZoneInfo("Asia/Tokyo")).strftime("%Y-%m-%d"),
        help="起始日期 YYYY-MM-DD（默认取东京当地日期，而不是本机系统时区——"
             "本机时区若比东京慢，用系统时区的「今天」会跟 Open-Meteo 按东京时区给的当天数据对不上）",
    )
    ap.add_argument("--days", type=int, default=30, help="预测天数，默认 30 天")
    ap.add_argument("--format", choices=["json", "md"], default="md")
    ap.add_argument("--list-points", action="store_true", help="列出内置山地/具体地点后退出")
    args = ap.parse_args()

    if args.list_points:
        for k, (lat, lon, elev, name) in MOUNTAIN_POINTS.items():
            print(f"{k:16s} {name:20s} 海拔{elev}m  ({lat}, {lon})")
        return

    sys.exit(run(args))


if __name__ == "__main__":
    main()
