"""Open-Meteo 数据获取：分级预报 + 历史同期均值兜底。

分级策略（为什么不是单一模型）：
  1. jma_seamless —— 日本气象厅（JMA）自有数值模式，专门按日本地形调校，
     对日本境内的短中期预报通常比通用全球模型更准。约覆盖未来 11 天。
  2. best_match —— Open-Meteo 默认的多模型综合结果，覆盖 jma_seamless 未覆盖的
     12-16 天窗口。
  3. 历史同期均值 —— 16 天之外没有任何机构能给出可信的逐日确定性预报（这是气象学
     可预报性上限，不是工具的短板），退化为最近 3 整年同期数据的均值兜底，仅供
     大致参考。

这套三级 fallback 和调研结论（为什么没有接入 tenki.jp 等日本消费级天气站爬虫做「补
充」）写在 weather/README.md。
"""
import json
import sys
import urllib.request
from datetime import datetime, timedelta

WMO_CODES = {
    0: "晴朗 (Sunny)",
    1: "晴间多云 (Mainly Clear)",
    2: "多云 (Partly Cloudy)",
    3: "阴天 (Overcast)",
    45: "雾 (Fog)",
    48: "雾凇 (Depositing Rime Fog)",
    51: "毛毛雨 (Light Drizzle)",
    53: "中度毛毛雨 (Moderate Drizzle)",
    55: "重度毛毛雨 (Heavy Drizzle)",
    56: "细冻雨 (Light Freezing Drizzle)",
    57: "冻雨 (Heavy Freezing Drizzle)",
    61: "小雨 (Light Rain)",
    63: "中雨 (Moderate Rain)",
    65: "大雨 (Heavy Rain)",
    66: "冻雨 (Light Freezing Rain)",
    67: "重冻雨 (Heavy Freezing Rain)",
    71: "小雪 (Light Snow)",
    73: "中雪 (Moderate Snow)",
    75: "大雪 (Heavy Snow)",
    77: "雪粒 (Snow Grains)",
    80: "小阵雨 (Light Showers)",
    81: "中阵雨 (Moderate Showers)",
    82: "大阵雨 (Heavy Showers)",
    85: "小阵雪 (Light Snow Showers)",
    86: "大阵雪 (Heavy Snow Showers)",
    95: "雷阵雨 (Thunderstorm)",
    96: "雷雨伴小冰雹 (Thunderstorm with Light Hail)",
    99: "雷雨伴大冰雹 (Thunderstorm with Heavy Hail)",
}

DAILY_VARS = (
    "weather_code,temperature_2m_max,temperature_2m_min,"
    "precipitation_probability_max,rain_sum,wind_speed_10m_max,uv_index_max"
)


def get_json(url):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _forecast_url(lat, lon, days, elevation=None, models=None):
    url = (
        f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
        f"&daily={DAILY_VARS}&timezone=Asia/Tokyo&forecast_days={min(days, 16)}"
    )
    if elevation is not None:
        url += f"&elevation={elevation}"
    if models:
        url += f"&models={models}"
    return url


def fetch_jma_forecast(lat, lon, elevation=None, days=16):
    """JMA 精细预报（jma_seamless 模型），日本地形专用，约覆盖未来 11 天。"""
    return get_json(_forecast_url(lat, lon, days, elevation, models="jma_seamless")).get("daily", {})


def fetch_best_match_forecast(lat, lon, elevation=None, days=16):
    """通用多模型综合预报，覆盖 jma_seamless 之外的 12-16 天窗口。"""
    return get_json(_forecast_url(lat, lon, days, elevation, models=None)).get("daily", {})


def fetch_historical_range(lat, lon, start_date_str, end_date_str, elevation=None, years=None):
    """批量获取过去几年指定日期范围的历史气象数据。

    years 默认取「今天」往前推的最近 3 个完整年份（例如今天在 2026 年，就是
    2025/2024/2023），而不是写死年份——写死年份会随真实时间推移逐年过期。
    """
    if years is None:
        this_year = datetime.today().year
        years = [this_year - 1, this_year - 2, this_year - 3]

    start_dt = datetime.strptime(start_date_str, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date_str, "%Y-%m-%d")

    hist_map = {}
    for y in years:
        hist_start = start_dt.replace(year=y).strftime("%Y-%m-%d")
        hist_end = end_dt.replace(year=y).strftime("%Y-%m-%d")
        url = (
            f"https://archive-api.open-meteo.com/v1/archive?latitude={lat}&longitude={lon}"
            f"&start_date={hist_start}&end_date={hist_end}"
            f"&daily=weather_code,temperature_2m_max,temperature_2m_min,rain_sum"
            f"&timezone=Asia/Tokyo"
        )
        if elevation is not None:
            url += f"&elevation={elevation}"
        try:
            res = get_json(url).get("daily", {})
        except Exception as e:
            print(f"[debug] 获取 {y} 历史数据失败: {e}", file=sys.stderr)
            continue
        if not res or "time" not in res:
            continue
        for i, t_str in enumerate(res["time"]):
            dt_val = datetime.strptime(t_str, "%Y-%m-%d")
            md_key = (dt_val.month, dt_val.day)
            hist_map.setdefault(md_key, []).append({
                "weather_code": res["weather_code"][i],
                "temp_max": res["temperature_2m_max"][i],
                "temp_min": res["temperature_2m_min"][i],
                "rain_sum": res["rain_sum"][i],
            })
    return hist_map


def compute_historical_avg(hist_data):
    if not hist_data:
        return {"temp_max": None, "temp_min": None, "rain_prob": 0, "weather": "未知"}

    valid_maxs = [x["temp_max"] for x in hist_data if x["temp_max"] is not None]
    valid_mins = [x["temp_min"] for x in hist_data if x["temp_min"] is not None]
    avg_max = sum(valid_maxs) / len(valid_maxs) if valid_maxs else None
    avg_min = sum(valid_mins) / len(valid_mins) if valid_mins else None

    rainy_years = sum(1 for x in hist_data if x["rain_sum"] is not None and x["rain_sum"] > 1.0)
    rain_prob = int((rainy_years / len(hist_data)) * 100)

    codes = [x["weather_code"] for x in hist_data if x["weather_code"] is not None]
    most_common_code = max(set(codes), key=codes.count) if codes else 0

    return {
        "temp_max": avg_max,
        "temp_min": avg_min,
        "rain_prob": rain_prob,
        "weather": WMO_CODES.get(most_common_code, "多云"),
    }
