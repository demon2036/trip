#!/usr/bin/env python3
"""
ctrip_hotels.py — 查携程(ctrip.com)酒店价格（个人行程比价，中国站/CNY）。

原理与 expedia_hotels.py 相同（照猫画虎）：
  从你真实 Chrome profile 解密读出 .ctrip.com 的登录/风控 cookie，注入一个
  patchright + 系统真 Chrome 的干净浏览器（同机同 IP、同 UA），于是携程把它当
  正常登录用户 → 直接出结果。不挂载你的浏览器、不用你点任何东西。

城市 ID：携程按数字 cityId 检索。传 --city-id 直接用；否则用目的地名走一次
  首页联想自动解析（神户=423 已验证）。

依赖：patchright + 系统 Google Chrome + pycryptodome + secretstorage
  （cookie 解密/浏览器沙箱逻辑在 core/，与 ctrip/expedia 两个站点共用）。

用法：
  python3 cli/ctrip_hotels.py --checkin 2026-07-10 --nights 7 --format md
  python3 cli/ctrip_hotels.py --dest 大阪 --checkin 2026-08-01 --checkout 2026-08-05 --json
  python3 cli/ctrip_hotels.py --city-id 423 --checkin 2026-07-10 --nights 7 --format md
"""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.browser import goto_retry, sandboxed_page, work_profile_dir
from core.cookies import SRC_PROFILE, load_cookies
from core.dates import compute_dates

WORK_PROFILE = work_profile_dir("ctrip")
YEN = re.compile(r"¥\s*([\d,]+)")


def resolve_city_id(page, dest, debug=False):
    """首页联想解析 cityId：输入目的地→点第一个联想→搜索→从跳转 URL 读 cityId。"""
    goto_retry(page, "https://hotels.ctrip.com/", 40, tries=3)
    page.wait_for_timeout(3500)
    for sel in ['text=目的地', 'input[placeholder*="目的地"]']:
        try:
            page.click(sel, timeout=3000)
            break
        except Exception:
            continue
    page.wait_for_timeout(400)
    page.keyboard.type(dest, delay=140)
    page.wait_for_timeout(3200)
    for sel in ['[class*="dropdown"] li', '[class*="suggest"] li', 'li[class*="item"]', '[class*="list"] li']:
        try:
            page.locator(sel).first.click(timeout=2500)
            break
        except Exception:
            continue
    page.wait_for_timeout(700)
    for sel in ['text=搜索', 'button:has-text("搜索")']:
        try:
            page.click(sel, timeout=2500)
            break
        except Exception:
            continue
    page.wait_for_timeout(6000)
    m = re.search(r"[?&]cityId=(\d+)", page.url)
    mc = re.search(r"[?&]countryId=(\d+)", page.url)
    if debug:
        print(f"[debug] 解析 URL: {page.url[:90]}", file=sys.stderr)
    return (m.group(1) if m else None), (mc.group(1) if mc else "0")


def build_list_url(city_id, country_id, ci, co, adults, rooms, curr):
    return ("https://hotels.ctrip.com/hotels/list?"
            f"cityId={city_id}&countryId={country_id or 0}&checkin={ci}&checkout={co}"
            f"&crn={rooms}&adult={adults}&curr={curr}&locale=zh-CN"
            f"&searchType=CT&optionId={city_id}")


EXTRACT_JS = r"""
() => {
  const cards = Array.from(document.querySelectorAll('[class*="list-item"]'))
    .filter(el => /条点评|点评/.test(el.innerText||'') && /¥/.test(el.innerText||'') && (el.innerText||'').length < 900);
  const uniq = cards.filter(c => !cards.some(o => o !== c && o.contains(c)));
  return uniq.map(c => {
    const a = c.querySelector('a[href*="hotels/detail"], a[href*="hotelDetail"], a[href*="/hotels/"], a[href]');
    return { 
      text: c.innerText || '', 
      href: a ? a.href : null,
      exposure: c.getAttribute('data-exposure')
    };
  });
}
"""


def parse_card(text, exposure_str, nights):
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    if not lines:
        return None
    name_cn = lines[0]
    name_en = lines[1] if len(lines) > 1 and re.search(r"[A-Za-z]", lines[1]) and "点评" not in lines[1] else None
    
    # Parse star rating from exposure JSON
    star_rating = None
    if exposure_str:
        try:
            exp_data = json.loads(exposure_str)
            star_val = exp_data.get("data", {}).get("star")
            if star_val:
                star_rating = float(star_val)
        except Exception:
            pass
            
    star_desc = None
    if star_rating == 5:
        star_desc = "豪华型/5钻"
    elif star_rating == 4:
        star_desc = "高档型/4钻"
    elif star_rating == 3:
        star_desc = "舒适型/3钻"
    elif star_rating == 2:
        star_desc = "经济型/2钻"
        
    if not star_desc:
        if "豪华型" in text or "五钻" in text:
            star_rating = 5.0
            star_desc = "豪华型/5钻"
        elif "高档型" in text or "四钻" in text:
            star_rating = 4.0
            star_desc = "高档型/4钻"
        elif "舒适型" in text or "三钻" in text:
            star_rating = 3.0
            star_desc = "舒适型/3钻"
        elif "经济型" in text or "二钻" in text:
            star_rating = 2.0
            star_desc = "经济型/2钻"
            
    # 评分（携程 5 分制，如 4.7）
    score = None
    ms = re.search(r"\b([0-5](?:\.\d)?)\b", text)
    if ms:
        v = float(ms.group(1))
        if 0 < v <= 5:
            score = v
    # 点评数
    reviews = None
    mr = re.search(r"([\d,]+)\s*条点评", text)
    if mr:
        reviews = int(mr.group(1).replace(",", ""))
    # 位置
    loc = next((ln for ln in lines if "·" in ln or "查看地图" in ln), None)
    if loc:
        loc = loc.replace("查看地图", "").strip()
    # 价格：每晚“起”价、含税/费后价；总价按晚数估算
    nightly = None
    mn = re.search(r"¥\s*([\d,]+)\s*起", text) or re.search(r"¥\s*([\d,]+)[^¥]{0,6}起", text)
    if mn:
        nightly = float(mn.group(1).replace(",", ""))
    tax_incl = None
    mt = re.search(r"含税[/／]?费后\s*¥\s*([\d,]+)", text)
    if mt:
        tax_incl = float(mt.group(1).replace(",", ""))
    if nightly is None:  # 兜底：取最小的 ¥ 值当每晚起价
        nums = [float(x.replace(",", "")) for x in YEN.findall(text)]
        if nums:
            nightly = min(nums)
    total = round(nightly * nights) if nightly is not None else None
    return {
        "name": name_cn, "name_en": name_en, "location": loc,
        "nightly_price": nightly, "nightly_tax_incl": tax_incl,
        "total_price": total, "currency": "¥", "nights": nights,
        "review_score": score, "review_scale": 5, "review_count": reviews,
        "star_rating": star_rating, "star_desc": star_desc or "—",
        "url": None,
    }


def run(args):
    ci, co = compute_dates(args.checkin, args.checkout, args.nights)
    nights = (datetime.strptime(co, "%Y-%m-%d") - datetime.strptime(ci, "%Y-%m-%d")).days

    ck = load_cookies(args.src_profile, "ctrip.com")
    if args.debug:
        print(f"[debug] 注入 {len(ck)} 个 ctrip cookie（cticket={any(c['name']=='cticket' for c in ck)}）", file=sys.stderr)

    raw = []
    with sandboxed_page(args.work_profile, cookies=ck, headless=args.headless) as page:
        city_id, country_id = args.city_id, args.country_id
        if not city_id:
            city_id, country_id = resolve_city_id(page, args.dest, args.debug)
            if not city_id:
                raise SystemExit(f"无法解析目的地“{args.dest}”的 cityId，请用 --city-id 指定。")
        url = build_list_url(city_id, country_id, ci, co, args.adults, args.rooms, args.curr)
        if args.debug:
            print(f"[debug] cityId={city_id} url={url}", file=sys.stderr)
        goto_retry(page, url, args.timeout, tries=4)
        page.wait_for_timeout(7000)
        # 滚动加载更多
        stable, prev = 0, -1
        for _ in range(12):
            cnt = page.evaluate("()=>document.querySelectorAll('[class*=\"list-item\"]').length")
            if cnt >= args.limit + 3 or cnt == prev:
                stable += 1
                if stable >= 2:
                    break
            else:
                stable = 0
            prev = cnt
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(1800)
        page.evaluate("window.scrollTo(0,0)")
        title = page.title() or ""
        if "验证" in title or "captcha" in title.lower():
            print("⚠️ 被携程风控拦截；请在你自己的 Chrome 打开一次携程再重跑。", file=sys.stderr)
        raw = page.evaluate(EXTRACT_JS)
        if args.screenshot:
            try:
                page.screenshot(path=args.screenshot, timeout=10000)
            except Exception:
                pass

    hotels = []
    seen = set()
    for r in raw:
        h = parse_card(r.get("text", ""), r.get("exposure", ""), nights)
        if not h or not h["name"] or h["name"] in seen:
            continue
        seen.add(h["name"])
        h["url"] = (r.get("href") or "").split("?")[0] or None
        hotels.append(h)
    hotels.sort(key=lambda h: (h["nightly_price"] is None, h["nightly_price"] or 0))
    hotels = hotels[: args.limit]

    meta = {"dest": args.dest, "city_id": city_id, "checkin": ci, "checkout": co,
            "nights": nights, "curr": args.curr, "count": len(hotels)}

    if args.format == "md":
        print(f"# 携程 · {args.dest} 酒店（{ci} → {co} · {nights}晚 · {args.adults}人 · {args.curr}）\n")
        if not hotels:
            print("_未抓取到结果，可加 --debug 排查。_")
        else:
            print("| # | 酒店 | 星级/钻 | 每晚起 | 含税/晚 | 总价(估) | 评分/5 | 点评 |")
            print("|---|------|---------|--------|---------|----------|--------|------|")
            for i, h in enumerate(hotels, 1):
                nm = h["name"] if not h["url"] else f"[{h['name']}]({h['url']})"
                star = h.get("star_desc") or "—"
                ni = f"¥{h['nightly_price']:.0f}" if h["nightly_price"] is not None else "—"
                tx = f"¥{h['nightly_tax_incl']:.0f}" if h["nightly_tax_incl"] is not None else "—"
                to = f"¥{h['total_price']:.0f}" if h["total_price"] is not None else "—"
                sc = h["review_score"] if h["review_score"] is not None else "—"
                rv = h["review_count"] if h["review_count"] is not None else "—"
                print(f"| {i} | {nm} | {star} | {ni} | {tx} | {to} | {sc} | {rv} |")
        print(f"\n_共 {meta['count']} 家；携程 cityId={city_id}；价格 CNY、每晚“起”价，总价=每晚×{nights}(估)。_")
    else:
        print(json.dumps({"meta": meta, "hotels": hotels}, ensure_ascii=False, indent=2))
    return 0


def main():
    ap = argparse.ArgumentParser(description="查携程酒店价格（注入真实会话 cookie）")
    ap.add_argument("--dest", default="神户", help="目的地名（用于联想解析 cityId），如 神户/大阪")
    ap.add_argument("--city-id", default=None, help="携程 cityId（给了就跳过联想解析；神户=423）")
    ap.add_argument("--country-id", default="0", help="携程 countryId（可选，日本=78）")
    ap.add_argument("--checkin", required=True, help="入住 YYYY-MM-DD")
    ap.add_argument("--checkout", default=None, help="退房 YYYY-MM-DD（与 --nights 二选一）")
    ap.add_argument("--nights", type=int, default=7, help="住几晚（默认 7）")
    ap.add_argument("--adults", type=int, default=1, help="成人数（默认 1）")
    ap.add_argument("--rooms", type=int, default=1, help="房间数（默认 1）")
    ap.add_argument("--curr", default="CNY", help="货币（默认 CNY）")
    ap.add_argument("--src-profile", default=SRC_PROFILE, help="真实 Chrome profile（读 cookie）")
    ap.add_argument("--work-profile", default=WORK_PROFILE, help="本工具用的干净 profile 目录")
    ap.add_argument("--headless", action="store_true", help="无头（默认有头，更不易被风控）")
    ap.add_argument("--limit", type=int, default=25, help="最多返回几家")
    ap.add_argument("--format", choices=["json", "md"], default="json")
    ap.add_argument("--screenshot", default=None)
    ap.add_argument("--timeout", type=int, default=45)
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()
    sys.exit(run(args))


if __name__ == "__main__":
    main()
