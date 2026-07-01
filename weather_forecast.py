#!/usr/bin/env python3
"""
weather_forecast.py — 针对日本旅游规划的30天（1个月）天气预测工具。
结合 Open-Meteo 16天实时预报 与 3年历史气候档案（2023-2025）的日均数据，为长期旅行提供日别天气参考。
"""

import argparse
import json
import sys
import urllib.request
from datetime import datetime, timedelta

# 常用日本旅游城市坐标映射
CITIES = {
    "kobe": (34.6901, 135.1955, "神户"),
    "tokyo": (35.6762, 139.6503, "东京"),
    "osaka": (34.6937, 135.5023, "大阪"),
    "kyoto": (35.0116, 135.7681, "京都"),
    "nagoya": (35.1815, 136.9066, "名古屋"),
    "sapporo": (43.0618, 141.3545, "札幌"),
    "fukuoka": (33.5904, 130.4017, "福冈"),
    "okinawa": (26.2124, 127.6809, "那霸/冲绳"),
}

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
    99: "雷雨伴大冰雹 (Thunderstorm with Heavy Hail)"
}

def get_json(url):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))

def fetch_forecast(lat, lon):
    """获取未来 16 天的实时预报"""
    url = (
        f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
        f"&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,rain_sum"
        f"&timezone=Asia/Tokyo&forecast_days=16"
    )
    return get_json(url).get("daily", {})

def fetch_historical_range(lat, lon, start_date_str, end_date_str, years=[2025, 2024, 2023]):
    """批量获取过去几年指定日期范围的历史气象数据"""
    start_dt = datetime.strptime(start_date_str, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date_str, "%Y-%m-%d")
    
    # key: (month, day) -> list of {weather_code, temp_max, temp_min, rain_sum}
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
        try:
            res = get_json(url).get("daily", {})
            if res and "time" in res:
                for i, t_str in enumerate(res["time"]):
                    dt_val = datetime.strptime(t_str, "%Y-%m-%d")
                    md_key = (dt_val.month, dt_val.day)
                    if md_key not in hist_map:
                        hist_map[md_key] = []
                    hist_map[md_key].append({
                        "weather_code": res["weather_code"][i],
                        "temp_max": res["temperature_2m_max"][i],
                        "temp_min": res["temperature_2m_min"][i],
                        "rain_sum": res["rain_sum"][i],
                    })
        except Exception as e:
            print(f"[debug] 获取 {y} 历史数据失败: {e}", file=sys.stderr)
            
    return hist_map

def compute_historical_avg(hist_data):
    if not hist_data:
        return {"temp_max": None, "temp_min": None, "rain_prob": 0, "weather": "未知", "source": "历史均值"}
    
    valid_maxs = [x["temp_max"] for x in hist_data if x["temp_max"] is not None]
    valid_mins = [x["temp_min"] for x in hist_data if x["temp_min"] is not None]
    
    avg_max = sum(valid_maxs) / len(valid_maxs) if valid_maxs else None
    avg_min = sum(valid_mins) / len(valid_mins) if valid_mins else None
    
    # 历史降水概率：3年中有多少年下了超过 1.0mm 的雨
    rainy_years = sum(1 for x in hist_data if x["rain_sum"] is not None and x["rain_sum"] > 1.0)
    rain_prob = int((rainy_years / len(hist_data)) * 100)
    
    # 历史最常见天气类型
    codes = [x["weather_code"] for x in hist_data if x["weather_code"] is not None]
    most_common_code = max(set(codes), key=codes.count) if codes else 0
    weather_desc = WMO_CODES.get(most_common_code, "多云")
    
    return {
        "temp_max": avg_max,
        "temp_min": avg_min,
        "rain_prob": rain_prob,
        "weather": weather_desc,
        "source": "历史均值"
    }

def run(args):
    city_key = args.city.lower()
    if city_key in CITIES:
        lat, lon, city_name = CITIES[city_key]
    else:
        if args.latitude is None or args.longitude is None:
            raise SystemExit(f"未知城市 '{args.city}'。请通过 --latitude 和 --longitude 传入坐标。")
        lat, lon = args.latitude, args.longitude
        city_name = args.city
        
    start_dt = datetime.strptime(args.start_date, "%Y-%m-%d")
    forecast_days = args.days
    
    # 1. 抓取 16 天实时天气预报
    try:
        fc = fetch_forecast(lat, lon)
    except Exception as e:
        print(f"获取实时预报失败: {e}", file=sys.stderr)
        fc = {}
        
    fc_dates = fc.get("time", [])
    fc_max = fc.get("temperature_2m_max", [])
    fc_min = fc.get("temperature_2m_min", [])
    fc_prob = fc.get("precipitation_probability_max", [])
    fc_code = fc.get("weather_code", [])
    
    # 区分出需要查历史气象的日期
    hist_needed = []
    for i in range(forecast_days):
        d_str = (start_dt + timedelta(days=i)).strftime("%Y-%m-%d")
        if d_str not in fc_dates:
            hist_needed.append(d_str)
            
    # 2. 如果有需要历史均值的日期，一次性批量区间拉取
    hist_map = {}
    if hist_needed:
        min_date, max_date = min(hist_needed), max(hist_needed)
        hist_map = fetch_historical_range(lat, lon, min_date, max_date)
        
    results = []
    
    for i in range(forecast_days):
        curr_date = (start_dt + timedelta(days=i)).strftime("%Y-%m-%d")
        
        # 判断是使用实时预测还是历史均值
        if curr_date in fc_dates:
            idx = fc_dates.index(curr_date)
            results.append({
                "date": curr_date,
                "temp_max": fc_max[idx],
                "temp_min": fc_min[idx],
                "rain_prob": fc_prob[idx] if fc_prob[idx] is not None else 0,
                "weather": WMO_CODES.get(fc_code[idx], "多云"),
                "source": "实时预测"
            })
        else:
            dt_val = datetime.strptime(curr_date, "%Y-%m-%d")
            md_key = (dt_val.month, dt_val.day)
            avg = compute_historical_avg(hist_map.get(md_key, []))
            results.append({
                "date": curr_date,
                "temp_max": avg["temp_max"],
                "temp_min": avg["temp_min"],
                "rain_prob": avg["rain_prob"],
                "weather": avg["weather"],
                "source": "历史均值"
            })
            
    if args.format == "md":
        print(f"# 🌦️ {city_name} 天气预测报告 ({args.start_date} 起，共 {args.days} 天)\n")
        print("| 日期 | 最低/最高气温 | 天气情况 | 降水概率 | 数据来源 |")
        print("|---|---|---|---|---|")
        for r in results:
            t_str = f"{r['temp_min']:.1f}°C ~ {r['temp_max']:.1f}°C" if r['temp_max'] is not None else "—"
            p_str = f"{r['rain_prob']}%"
            src = "🔮 " + r['source'] if r['source'] == "实时预测" else "📜 " + r['source']
            print(f"| {r['date']} | {t_str} | {r['weather']} | {p_str} | {src} |")
        print(f"\n_数据源: Open-Meteo API；坐标 {lat}, {lon}；历史均值基于 2023-2025 年同期气象归档。_")
    else:
        print(json.dumps({"city": city_name, "latitude": lat, "longitude": lon, "forecast": results}, ensure_ascii=False, indent=2))
        
    return 0

def main():
    ap = argparse.ArgumentParser(description="日本 30 天超长天气预测比价工具")
    ap.add_argument("--city", default="kobe", help="城市拼音，如 kobe, tokyo, osaka, kyoto")
    ap.add_argument("--latitude", type=float, default=None)
    ap.add_argument("--longitude", type=float, default=None)
    ap.add_argument("--start-date", default=datetime.today().strftime("%Y-%m-%d"), help="起始日期 YYYY-MM-DD")
    ap.add_argument("--days", type=int, default=30, help="预测天数，默认 30 天")
    ap.add_argument("--format", choices=["json", "md"], default="md")
    args = ap.parse_args()
    sys.exit(run(args))

if __name__ == "__main__":
    main()
