#!/usr/bin/env python3
"""
expedia_room_details.py — 抓取 Expedia 酒店详情页的具体房型信息（价格、床型、大小、禁烟、早餐等）
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
from expedia.common import host_suffix_from

WORK_PROFILE = work_profile_dir("expedia-details-proc")

def parse_room_block(text, nights):
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    if not lines:
        return None

    # Find price
    # In Expedia HK, prices are typically HK$1,234 or $123
    price = None
    m_prices = re.findall(r"(?:HK\$|\$)\s*([\d,]+)", text, re.I)
    if m_prices:
        # We look for the last price in the card which is usually the final booking price
        price = float(m_prices[-1].replace(",", ""))

    # Find room size (e.g. 20 平方米, 215 平方呎, 20 sq m, 237 平方英尺)
    size = None
    m_size = re.search(r"(\d+)\s*(?:平方米|平方呎|平方尺|sq m|sq ft|㎡|m²|平方英尺|平方英呎)", text, re.I)
    if m_size:
        size = f"{m_size.group(1)}平方英尺" if "英" in m_size.group(0) or "ft" in m_size.group(0) else f"{m_size.group(1)}㎡"

    # Find bed type
    bed = None
    m_bed = re.search(r"(\d+\s*张[^\n|]+床|[^\n|]+大床|[^\n|]+双人床|[^\n|]+单人床|[^\n|]+特大床)", text)
    if m_bed:
        bed = m_bed.group(1).strip()

    # Smoking policy
    smoking = "禁烟"
    if "吸烟房" in text or "吸煙房" in text:
        smoking = "吸烟"
    elif "禁烟" in text or "禁煙" in text:
        smoking = "禁烟"

    # Breakfast: Filter out paid add-on breakfasts like "全套早餐 \n + HK$213"
    paid_breakfast_pattern = r"(?:全套早餐|自助早餐|免费早餐|早餐)\s*[\r\n]*\s*(?:\+|＋)\s*(?:HK\$|\$)?\s*\d+"
    cleaned_text = re.sub(paid_breakfast_pattern, "", text, flags=re.I)

    breakfast = "无早餐"
    if "无早餐" in cleaned_text or "不含早餐" in cleaned_text:
        breakfast = "无早餐"
    elif any(x in cleaned_text for x in ["全套早餐", "自助早餐", "包含早餐", "免费早餐", "送早餐", "双早", "单早", "早餐", "breakfast"]):
        breakfast = "含早餐"

    # Nightly calculation if we got the total price
    nightly = price
    if price and nights > 1:
        nightly = price / nights

    # Standard Room name extraction: cleaning up photos string
    room_name = lines[0]
    if "的所有照片" in room_name:
        room_name = room_name.replace("的所有照片", "").replace("显示", "").strip()

    return {
        "room_name": room_name.split("|")[0].strip(),
        "total_price": price,
        "nightly_price": nightly,
        "size": size or "请在详情页确认",
        "bed_type": bed or "请在详情页确认",
        "smoking": smoking,
        "breakfast": breakfast,
        "raw_text": " | ".join(lines[:10])
    }

def run(args):
    _, co = compute_dates(args.checkin, None, args.nights)

    # Construct details URL
    url = f"https://{args.base_url}/cn/{args.hotel_slug}.h{args.hotel_id}.Hotel-Information?startDate={args.checkin}&endDate={co}&adults=1&rooms=1"

    cookie_suffix, host = host_suffix_from(args.base_url)
    ck = load_cookies(args.src_profile, cookie_suffix)
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

        # Extract room text blocks using common uitk-card prefix selector
        raw_blocks = page.evaluate("""
            () => {
                const blocks = [];
                document.querySelectorAll('[class*="uitk-card"]').forEach(el => {
                    const txt = el.innerText || '';
                    if (txt.includes('张') && (txt.includes('平方') || txt.includes('sq') || txt.includes('尺')) && txt.length < 1500) {
                        blocks.push(txt);
                    }
                });
                return blocks;
            }
        """)

        for b in raw_blocks:
            parsed = parse_room_block(b, args.nights)
            if parsed and parsed["total_price"] and parsed["room_name"]:
                rooms_data.append(parsed)

    # Sort by total price
    rooms_data.sort(key=lambda x: x["total_price"])

    # Dedup by room name
    seen = set()
    uniq_rooms = []
    for r in rooms_data:
        if r["room_name"] in seen:
            continue
        seen.add(r["room_name"])
        uniq_rooms.append(r)

    cur = "HK$" if "hk" in args.base_url else "$"

    if args.format == "md":
        print(f"# Expedia 房型信息 · {args.hotel_slug} (ID: {args.hotel_id}) (入住 {args.checkin}，{args.nights}晚)\n")
        if not uniq_rooms:
            print("_未抓取到具体房型价格信息，可能是Cookie过期或详情页结构变动。_")
        else:
            print(f"| # | 房型名称 | 床型 | 房间面积 | 禁烟政策 | 早餐政策 | 每晚起价 | 总价 ({args.nights}晚) |")
            print("|---|----------|------|----------|----------|----------|----------|-----------------|")
            for i, r in enumerate(uniq_rooms, 1):
                print(f"| {i} | {r['room_name']} | {r['bed_type']} | {r['size']} | {r['smoking']} | {r['breakfast']} | {cur}{r['nightly_price']:.0f} | {cur}{r['total_price']:.0f} |")
    else:
        print(json.dumps({"hotel_id": args.hotel_id, "checkin": args.checkin, "rooms": uniq_rooms}, ensure_ascii=False, indent=2))

    return 0

def main():
    ap = argparse.ArgumentParser(description="获取 Expedia 具体房型价格及服务详情")
    ap.add_argument("--hotel-id", required=True, help="Expedia hotelId，如 1209540 (神户全日空)")
    ap.add_argument("--hotel-slug", required=True, help="Expedia 酒店拼音/英文名称，如 KOBE-Hotels-ANA-Crowne-Plaza-Kobe")
    ap.add_argument("--checkin", required=True, help="入住日期 YYYY-MM-DD")
    ap.add_argument("--nights", type=int, default=1, help="入住晚数")
    ap.add_argument("--base-url", default="www.expedia.com.hk", help="默认使用香港站")
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
