#!/usr/bin/env python3
import subprocess
import json
import concurrent.futures
from datetime import datetime, timedelta
import sys
import os
import time

# 1 HKD = 0.93 CNY (Approximate exchange rate for comparison)
HKD_TO_CNY = 0.93

def run_ctrip(date, max_tries=3):
    for attempt in range(max_tries):
        profile = f"{os.path.expanduser('~')}/.config/google-chrome-ctrip-{date}-{attempt}"
        cmd = [
            "python3", "ctrip_hotels.py",
            "--city-id", "423",
            "--checkin", date,
            "--nights", "1",
            "--limit", "100",
            "--format", "json",
            "--work-profile", profile
        ]
        if attempt > 0:
            cmd.append("--timeout")
            cmd.append("60")
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            data = json.loads(res.stdout)
            subprocess.run(["rm", "-rf", profile])
            
            # Find ANA Crowne Plaza Kobe
            for h in data.get("hotels", []):
                name = h.get("name") or ""
                name_en = h.get("name_en") or ""
                if ("全日空" in name and "皇冠" in name) or "ANA Crowne Plaza" in name_en:
                    return {
                        "date": date,
                        "hotel_name": name,
                        "nightly_price_cny": h.get("nightly_price"),
                        "total_price_cny": h.get("nightly_tax_incl") or h.get("total_price"),
                        "currency": "CNY"
                    }
            print(f"[Ctrip] Attempt {attempt+1} for {date}: Hotel not found in results.", file=sys.stderr)
        except Exception as e:
            print(f"[Ctrip] Attempt {attempt+1} for {date} failed: {e}", file=sys.stderr)
            subprocess.run(["rm", "-rf", profile])
        time.sleep(2)
    return {"date": date, "error": True, "source": "Ctrip"}

def run_expedia(date, max_tries=3):
    for attempt in range(max_tries):
        profile = f"{os.path.expanduser('~')}/.config/google-chrome-expedia-{date}-{attempt}"
        cmd = [
            "python3", "expedia_hotels.py",
            "--base-url", "www.expedia.com.hk",
            "--destination", "Kobe",
            "--checkin", date,
            "--nights", "1",
            "--limit", "150",
            "--format", "json",
            "--work-profile", profile
        ]
        if attempt > 0:
            cmd.append("--timeout")
            cmd.append("60")
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            data = json.loads(res.stdout)
            subprocess.run(["rm", "-rf", profile])
            
            # Find ANA Crowne Plaza Kobe
            for h in data.get("hotels", []):
                name = h.get("name") or ""
                url = h.get("url") or ""
                if "ANA-Crowne-Plaza-Kobe" in url or "ANA" in name or "皇冠假日" in name or "Crowne Plaza" in name:
                    return {
                        "date": date,
                        "hotel_name": name,
                        "nightly_price_hkd": h.get("nightly_price"),
                        "total_price_hkd": h.get("total_price"),
                        "currency": "HKD"
                    }
            print(f"[Expedia] Attempt {attempt+1} for {date}: Hotel not found in results.", file=sys.stderr)
        except Exception as e:
            print(f"[Expedia] Attempt {attempt+1} for {date} failed: {e}", file=sys.stderr)
            subprocess.run(["rm", "-rf", profile])
        time.sleep(3)
    return {"date": date, "error": True, "source": "Expedia"}

def main():
    # 7 check-in dates starting from tomorrow (2026-07-02)
    start_date = datetime(2026, 7, 2)
    dates = [(start_date + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]
    
    print("Fetching prices for the next 7 days (July 2 - July 8)...")
    
    ctrip_results = {}
    expedia_results = {}
    
    # Run queries in parallel
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        ctrip_futures = {executor.submit(run_ctrip, d): d for d in dates}
        expedia_futures = {executor.submit(run_expedia, d): d for d in dates}
        
        for future in concurrent.futures.as_completed(ctrip_futures):
            d = ctrip_futures[future]
            ctrip_results[d] = future.result()
            print(f"Ctrip for {d} fetched.")
            
        for future in concurrent.futures.as_completed(expedia_futures):
            d = expedia_futures[future]
            expedia_results[d] = future.result()
            print(f"Expedia for {d} fetched.")

    # Print Comparison Table
    print("\n# 比价结果：神户全日空皇冠假日酒店 (ANA Crowne Plaza Kobe)")
    print(f"汇率基准: 1 HKD = {HKD_TO_CNY} CNY\n")
    print("| 入住日期 | 携程价 (不含税) | 携程含税总价 | Expedia HK价 (不含税) | Expedia HK含税总价 | 携程(含税) vs Expedia(折本币含税) | 哪家便宜 |")
    print("|---|---|---|---|---|---|---|")
    
    for d in dates:
        ct = ctrip_results.get(d, {})
        ex = expedia_results.get(d, {})
        
        ct_price_raw = ct.get("nightly_price_cny")
        ct_total_raw = ct.get("total_price_cny")
        
        ex_price_raw = ex.get("nightly_price_hkd")
        ex_total_raw = ex.get("total_price_hkd")
        
        if ct.get("error") or ex.get("error"):
            ct_desc = f"¥{ct_total_raw:.0f}" if ct_total_raw else "获取失败"
            ex_desc = f"HK${ex_total_raw:.0f}" if ex_total_raw else "获取失败"
            print(f"| {d} | {ct_price_raw or '—'} | {ct_desc} | {ex_price_raw or '—'} | {ex_desc} | — | 无法比较 |")
            continue
            
        # Convert Expedia HKD to CNY for comparison
        ex_total_cny = ex_total_raw * HKD_TO_CNY
        diff = ct_total_raw - ex_total_cny
        
        if diff > 0:
            winner = "**Expedia HK** 便宜"
            diff_text = f"Expedia 便宜 ¥{diff:.1f}"
        elif diff < 0:
            winner = "**携程** 便宜"
            diff_text = f"携程 便宜 ¥{-diff:.1f}"
        else:
            winner = "价格相同"
            diff_text = "等价"
            
        print(f"| {d} | ¥{ct_price_raw:.0f} | ¥{ct_total_raw:.0f} | HK${ex_price_raw:.0f} | HK${ex_total_raw:.0f} (约¥{ex_total_cny:.0f}) | {diff_text} | {winner} |")

if __name__ == "__main__":
    main()
