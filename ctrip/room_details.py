#!/usr/bin/env python3
"""
ctrip_room_details.py — 抓取携程酒店详情页的具体房型信息（价格、床型、大小、禁烟、早餐等）
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.browser import goto_retry, sandboxed_page, work_profile_dir
from core.cookies import SRC_PROFILE, load_cookies
from core.dates import compute_dates

WORK_PROFILE = work_profile_dir("ctrip-details-proc")

def parse_room_block(text):
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    if not lines:
        return None

    # Find price (Ctrip usually displays price as ¥507)
    price = None
    # We look for the last price in the card (which is usually the booking price)
    m_prices = re.findall(r"¥\s*([\d,]+)", text)
    if m_prices:
        price = float(m_prices[-1].replace(",", ""))

    # Find room size (e.g. 15㎡, 20m², 18平米, 18平方米)
    size = None
    m_size = re.search(r"(\d+)\s*(?:㎡|m²|平米|平方)", text, re.I)
    if m_size:
        size = f"{m_size.group(1)}㎡"

    # Find bed type
    bed = None
    m_bed = re.search(r"(\d+张[^\n|]+床|[^\n|]+大床|[^\n|]+双床|[^\n|]+单人床|[^\n|]+双人床)", text)
    if m_bed:
        bed = m_bed.group(1).strip()

    # Smoking policy
    smoking = "未知"
    if "部分禁烟" in text:
        smoking = "部分禁烟"
    elif "禁烟" in text:
        smoking = "禁烟"
    elif "可吸烟" in text or "吸烟" in text:
        smoking = "可吸烟"

    # Breakfast
    breakfast = "无早餐"
    if "双早" in text or "双份早餐" in text or "包含早餐" in text or "有早餐" in text:
        breakfast = "含早餐"
    elif "单早" in text:
        breakfast = "单份早餐"
    elif "无早" in text or "无早餐" in text:
        breakfast = "无早餐"

    return {
        "room_name": lines[0].split("|")[0].strip(),
        "price": price,
        "size": size or "请在详情页确认",
        "bed_type": bed or "请在详情页确认",
        "smoking": smoking,
        "breakfast": breakfast,
        "raw_text": " | ".join(lines[:10])
    }

def run(args):
    _, co = compute_dates(args.checkin, None, args.nights)

    url = f"https://hotels.ctrip.com/hotels/detail/?hotelId={args.hotel_id}&checkin={args.checkin}&checkout={co}&adult=1"

    ck = load_cookies(args.src_profile, "ctrip.com")
    rooms_data = []

    with sandboxed_page(args.work_profile, cookies=ck, headless=args.headless) as page:
        goto_retry(page, url, args.timeout, tries=3)
        # Scroll down slowly to load rooms
        for _ in range(6):
            page.evaluate("window.scrollBy(0, 450)")
            page.wait_for_timeout(1000)
        page.wait_for_timeout(4000)

        if args.screenshot:
            page.screenshot(path=args.screenshot)

        # Extract room text blocks using commonRoomCard prefix selector
        raw_blocks = page.evaluate("""
            () => {
                const blocks = [];
                document.querySelectorAll('[class*="commonRoomCard"]').forEach(el => {
                    blocks.push(el.innerText);
                });
                return blocks;
            }
        """)

        for b in raw_blocks:
            parsed = parse_room_block(b)
            if parsed and parsed["price"] and parsed["room_name"]:
                rooms_data.append(parsed)

    # Sort by price
    rooms_data.sort(key=lambda x: x["price"])

    # Dedup by room name
    seen = set()
    uniq_rooms = []
    for r in rooms_data:
        if r["room_name"] in seen:
            continue
        seen.add(r["room_name"])
        uniq_rooms.append(r)

    if args.format == "md":
        print(f"# 携程房型信息 · 酒店 ID: {args.hotel_id} (入住 {args.checkin}，{args.nights}晚)\n")
        if not uniq_rooms:
            print("_未抓取到具体房型价格信息，可能是Cookie过期或详情页结构变动。_")
        else:
            print("| # | 房型名称 | 床型 | 房间面积 | 禁烟政策 | 早餐政策 | 起价 (含税/晚) |")
            print("|---|----------|------|----------|----------|----------|----------------|")
            for i, r in enumerate(uniq_rooms, 1):
                print(f"| {i} | {r['room_name']} | {r['bed_type']} | {r['size']} | {r['smoking']} | {r['breakfast']} | ¥{r['price']:.0f} |")
    else:
        print(json.dumps({"hotel_id": args.hotel_id, "checkin": args.checkin, "rooms": uniq_rooms}, ensure_ascii=False, indent=2))

    return 0

def main():
    ap = argparse.ArgumentParser(description="获取携程具体房型价格及服务详情")
    ap.add_argument("--hotel-id", required=True, help="携程 hotelId，如 2107678 (神户全日空)")
    ap.add_argument("--checkin", required=True, help="入住日期 YYYY-MM-DD")
    ap.add_argument("--nights", type=int, default=1, help="入住晚数")
    ap.add_argument("--src-profile", default=SRC_PROFILE, help="真实 Chrome profile 路径")
    ap.add_argument("--work-profile", default=WORK_PROFILE, help="沙箱 Chrome profile 路径")
    ap.add_argument("--headless", action="store_true", help="无头模式")
    ap.add_argument("--format", choices=["json", "md"], default="json")
    ap.add_argument("--screenshot", default=None)
    ap.add_argument("--timeout", type=int, default=45)
    args = ap.parse_args()
    sys.exit(run(args))

if __name__ == "__main__":
    main()
