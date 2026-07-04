#!/usr/bin/env python3
"""餐厅候选采集：Google Places 查现实可达性，Tabelog 查日本本地口碑榜。

设计目标是"少而穿透"：用户给日期、区域、饭点；本工具收 top20 候选、营业/预约/预算/
评分这些会影响当天选择的数据，并统一成一份可比 JSON/Markdown。
"""
import argparse
import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, time as dt_time, timedelta

from core.browser import sandboxed_page, work_profile_dir
from core.cookies import SRC_PROFILE, load_cookies

GOOGLE_KEY_ENV = "GOOGLE_MAPS_API_KEY"
GOOGLE_TEXT_URL = "https://places.googleapis.com/v1/places:searchText"
GOOGLE_MAPS_SEARCH = "https://www.google.com/maps/search/"
TBLG_BASE = "https://s.tabelog.com/en/rstLst/"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"

MEAL_TIME = {
    "breakfast": dt_time(8, 0),
    "lunch": dt_time(12, 30),
    "dinner": dt_time(19, 0),
    "late": dt_time(22, 0),
}

GOOGLE_FIELDS = ",".join([
    "places.id",
    "places.displayName",
    "places.formattedAddress",
    "places.location",
    "places.rating",
    "places.userRatingCount",
    "places.priceLevel",
    "places.googleMapsUri",
    "places.websiteUri",
    "places.internationalPhoneNumber",
    "places.nationalPhoneNumber",
    "places.currentOpeningHours",
    "places.regularOpeningHours",
    "places.reservable",
    "places.types",
])


def get_json(url, payload, headers):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=25) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_text(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=25) as resp:
        return resp.read().decode("utf-8", "replace")


def norm_name(s):
    s = html.unescape(s or "").lower()
    s = re.sub(r"\([^)]*\)|\[[^]]*\]|[^\w\u3040-\u30ff\u3400-\u9fff]+", "", s)
    return s.replace("ten", "").strip()


def _int(v):
    try:
        return int(str(v).replace(",", ""))
    except Exception:
        return None


def _float(v):
    try:
        return float(v)
    except Exception:
        return None


def _google_day(dt):
    # Google opening periods use 0=Sunday.
    return (dt.weekday() + 1) % 7


def _period_open_at(period, target_dt):
    opened = period.get("open") or {}
    closed = period.get("close") or {}
    if opened.get("date"):
        od = opened["date"]
        open_dt = datetime(od["year"], od["month"], od["day"], opened.get("hour", 0), opened.get("minute", 0))
    else:
        if opened.get("day") != _google_day(target_dt):
            return False
        open_dt = datetime.combine(target_dt.date(), dt_time(opened.get("hour", 0), opened.get("minute", 0)))

    if closed.get("date"):
        cd = closed["date"]
        close_dt = datetime(cd["year"], cd["month"], cd["day"], closed.get("hour", 23), closed.get("minute", 59))
    else:
        close_day = closed.get("day", opened.get("day"))
        close_dt = datetime.combine(target_dt.date(), dt_time(closed.get("hour", 23), closed.get("minute", 59)))
        if close_day != opened.get("day") or close_dt <= open_dt:
            close_dt = close_dt + timedelta(days=1)
    return open_dt <= target_dt < close_dt


def open_for_slot(place, date_str, meal):
    """返回 (open_for_slot, confidence)。currentOpeningHours 覆盖近期特殊营业，优先使用。"""
    if not date_str or not meal:
        return None, "unknown"
    target = datetime.combine(datetime.strptime(date_str, "%Y-%m-%d").date(), MEAL_TIME[meal])
    for key, confidence in (("currentOpeningHours", "current_hours"), ("regularOpeningHours", "regular_hours")):
        hours = place.get(key) or {}
        periods = hours.get("periods") or []
        if periods:
            return any(_period_open_at(p, target) for p in periods), confidence
    return None, "unknown"


def reservation_method(has_online, phone):
    if has_online:
        return "online"
    if phone:
        return "phone"
    return "unknown"


def google_places(area, query, date_str, meal, limit, api_key=None):
    api_key = api_key or os.getenv(GOOGLE_KEY_ENV)
    if not api_key:
        return [], f"missing {GOOGLE_KEY_ENV}"

    text_query = query or f"restaurants in {area}"
    payload = {
        "textQuery": text_query,
        "includedType": "restaurant",
        "maxResultCount": max(1, min(limit, 20)),
        "languageCode": "en",
    }
    data = get_json(
        GOOGLE_TEXT_URL,
        payload,
        {"X-Goog-Api-Key": api_key, "X-Goog-FieldMask": GOOGLE_FIELDS},
    )
    out = []
    for i, p in enumerate(data.get("places") or [], 1):
        name = ((p.get("displayName") or {}).get("text") or "").strip()
        phone = p.get("internationalPhoneNumber") or p.get("nationalPhoneNumber")
        is_open, confidence = open_for_slot(p, date_str, meal)
        loc = p.get("location") or {}
        out.append({
            "name": name,
            "match_key": norm_name(name),
            "rank_google": i,
            "google_rating": p.get("rating"),
            "google_reviews": p.get("userRatingCount"),
            "google_price_level": p.get("priceLevel"),
            "address": p.get("formattedAddress"),
            "latitude": loc.get("latitude"),
            "longitude": loc.get("longitude"),
            "open_for_slot": is_open,
            "open_confidence": confidence,
            "reservation_method": reservation_method(p.get("reservable") is True, phone),
            "phone": phone,
            "website": p.get("websiteUri"),
            "google_maps_url": p.get("googleMapsUri"),
            "sources": ["google"],
        })
    return out, None


GOOGLE_MAPS_EXTRACT_JS = r"""
(limit) => {
  const rows = [];
  const seen = new Set();
  const cards = Array.from(document.querySelectorAll('div[role="article"], a[href*="/maps/place/"]'));
  for (const el of cards) {
    const a = el.matches('a[href*="/maps/place/"]') ? el : el.querySelector('a[href*="/maps/place/"]');
    const href = a ? a.href : null;
    const aria = (a && a.getAttribute('aria-label')) || el.getAttribute('aria-label') || '';
    const text = (el.innerText || aria || '').trim();
    const key = href || text.slice(0, 100);
    if (!key || seen.has(key)) continue;
    seen.add(key);
    rows.push({href, text: text.slice(0, 1200), aria});
    if (rows.length >= limit) break;
  }
  return rows;
}
"""


def parse_google_maps_card(raw, rank):
    original = raw.get("text") or raw.get("aria") or ""
    text = _clean(original)
    if not original.strip():
        return None
    lines = [x.strip() for x in re.split(r"[\n\r]+| {2,}", original) if x.strip()]
    name = lines[0] if lines else None
    if name and re.match(r"^\d+(\.\d+)?$", name) and len(lines) > 1:
        name = lines[1]
    rating = reviews = None
    m = re.search(r"\b([1-5](?:\.\d)?)\s*\(?([\d,]+)?\)?", text)
    if m:
        rating = _float(m.group(1))
        reviews = _int(m.group(2)) if m.group(2) else None
    if rating and rating > 5:
        rating = None
    phone = None
    mp = re.search(r"(\+?\d[\d\s().-]{7,}\d)", text)
    if mp:
        phone = mp.group(1).strip()
    is_open = None
    confidence = "unknown"
    if re.search(r"\bOpen\b|営業中", text, re.I):
        is_open, confidence = True, "maps_list_current"
    elif re.search(r"\bClosed\b|営業時間外|定休日", text, re.I):
        is_open, confidence = False, "maps_list_current"
    has_online = re.search(r"\bReserve|予約|Book\b", text, re.I) is not None
    return {
        "name": name,
        "match_key": norm_name(name),
        "rank_google": rank,
        "google_rating": rating,
        "google_reviews": reviews,
        "open_for_slot": is_open,
        "open_confidence": confidence,
        "reservation_method": reservation_method(has_online, phone),
        "phone": phone,
        "google_maps_url": raw.get("href"),
        "google_raw": text[:300],
        "sources": ["google_maps"],
    }


def google_maps_browser_places(area, query, date_str, meal, limit, work_profile, src_profile, headless, timeout):
    """Google Maps 浏览器 harness。列表页通常能给 top results、评分、评论数和当前营业信号。

    它不像 Places API 那样稳定给未来某天饭点营业；因此 open_confidence 会标成
    maps_list_current 或 unknown，后续由 Tabelog/官网人工确认补强。
    """
    q = query or f"restaurants in {area}"
    url = GOOGLE_MAPS_SEARCH + urllib.parse.quote_plus(q) + "?hl=en"
    rows = []
    cookies = load_cookies(src_profile, "google.com")
    with sandboxed_page(work_profile, cookies=cookies, headless=headless) as page:
        page.set_default_timeout(timeout * 1000)
        page.set_default_navigation_timeout(timeout * 1000)
        last = None
        for _ in range(2):
            try:
                page.goto(url, wait_until="commit", timeout=timeout * 1000)
                last = None
                break
            except Exception as e:
                last = e
                page.wait_for_timeout(1500)
        page.wait_for_timeout(6500)
        for sel in ['button:has-text("Accept all")', 'button:has-text("Reject all")', 'button:has-text("同意")']:
            try:
                page.click(sel, timeout=1200)
                page.wait_for_timeout(1500)
                break
            except Exception:
                pass
        for _ in range(2):
            try:
                page.mouse.wheel(0, 2200)
            except Exception:
                pass
            page.wait_for_timeout(900)
            try:
                rows = page.evaluate(GOOGLE_MAPS_EXTRACT_JS, limit)
            except Exception as e:
                last = e
                rows = []
            if len(rows) >= min(limit, 12):
                break
        if not rows and last:
            raise last
    parsed = []
    for i, raw in enumerate(rows, 1):
        item = parse_google_maps_card(raw, i)
        if item and item["name"] and item["match_key"]:
            parsed.append(item)
    return parsed[:limit], None


def tabelog_url(area, sort, keyword=None):
    if area and area.startswith(("http://", "https://")):
        return area
    q = keyword or area
    params = {"sw": q} if q else {}
    sort_map = {
        "rating": "rt",
        "local_reserved": "inbound_vacancy_net_yoyaku",
        "viewed": "inbound_access",
        "traveler_reserved": "",
    }
    srt = sort_map.get(sort, sort)
    if srt:
        params["SrtT"] = srt
    return TBLG_BASE + "?" + urllib.parse.urlencode(params)


def _clean(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def _search(pattern, text, flags=re.S):
    m = re.search(pattern, text, flags)
    return _clean(m.group(1)) if m else None


def parse_tabelog_list(page, limit=20):
    starts = [m.start() for m in re.finditer(r'<div class="list-rst[^"]*js-rst-cassette-wrap"', page)]
    blocks = [page[s:starts[i + 1]] for i, s in enumerate(starts[:-1])]
    if starts:
        blocks.append(page[starts[-1]:])
    if not blocks:
        blocks = re.findall(r'<div class="list-rst\b.*?(?=<div class="list-rst\b|</main>|</body>)', page, re.S)
    if not blocks and 'class="list-rst' in page:
        blocks = [page]
    out = []
    for i, b in enumerate(blocks, 1):
        url = _search(r'data-detail-url="([^"]+)"', b) or _search(r'href="([^"]+)"[^>]*>\s*[^<]*</a>', b)
        name = _search(r'class="[^"]*cpy-rst-name[^"]*"[^>]*>(.*?)</a>', b)
        rank = _int(_search(r'class="[^"]*list-rst__rank-badge-contents[^"]*"[^>]*>([^<]+)</i>', b)) or i
        area_genre = _search(r'class="[^"]*cpy-area-genre[^"]*"[^>]*>(.*?)</div>', b)
        price_vals = re.findall(r'class="c-rating-v3__val">([^<]+)</span>', b)
        holiday = _search(r'class="list-rst__holiday-text">([^<]*)</span>', b)
        tags = [_clean(x) for x in re.findall(r'class="list-rst__search-word-item">.*?<span>(.*?)</span>', b, re.S)]
        has_online = "list-rst__calendar" in b or "Online reservation" in b
        out.append({
            "name": name,
            "match_key": norm_name(name),
            "rank_tabelog": rank,
            "tabelog_rating": _float(_search(r'class="[^"]*list-rst__rating-val[^"]*"[^>]*>([^<]+)</span>', b)),
            "tabelog_reviews": _int(_search(r'class="[^"]*cpy-review-count[^"]*"[^>]*>([^<]+)</em>', b)),
            "tabelog_area_genre": area_genre,
            "budget_dinner": _clean(price_vals[0]) if len(price_vals) > 0 else None,
            "budget_lunch": _clean(price_vals[1]) if len(price_vals) > 1 else None,
            "regular_holiday": None if holiday in (None, "-", "") else holiday,
            "reservation_method": "online" if has_online else "unknown",
            "tabelog_url": url,
            "tags": tags,
            "sources": ["tabelog"],
        })
    return sorted([x for x in out if x["name"]], key=lambda x: x["rank_tabelog"])[:limit]


def tabelog_places(area, sort, keyword, limit):
    url = tabelog_url(area, sort, keyword)
    page = get_text(url)
    return parse_tabelog_list(page, limit), url


def merge_places(google_rows, tabelog_rows):
    merged = []
    by_key = {}
    for row in google_rows:
        item = dict(row)
        by_key[item["match_key"]] = item
        merged.append(item)

    for row in tabelog_rows:
        key = row["match_key"]
        hit = by_key.get(key)
        if not hit:
            # Small containment match catches "Branch ten" and romanization suffix noise.
            hit = next((
                x for x in merged
                if "google_maps" in x.get("sources", []) or "google" in x.get("sources", [])
                if key and (key in x["match_key"] or x["match_key"] in key)
            ), None)
        if hit:
            hit.update({k: v for k, v in row.items() if v not in (None, "", []) and k not in ("name", "match_key", "sources")})
            hit["sources"] = sorted(set(hit.get("sources", [])) | {"tabelog"})
        else:
            merged.append(dict(row))

    def score(x):
        has_both = 0 if len(x.get("sources", [])) > 1 else 1
        rank = min(x.get("rank_tabelog") or 99, x.get("rank_google") or 99)
        return (has_both, rank, -(x.get("tabelog_rating") or 0), -(x.get("google_rating") or 0))

    return sorted(merged, key=score)


def discover(args):
    query = args.query or f"{' '.join(args.cuisine)} restaurants in {args.area}".strip()
    google, google_warning = [], None
    has_google_key = bool(args.google_key or os.getenv(GOOGLE_KEY_ENV))
    try_api_first = args.google_mode == "api" or (args.google_mode == "auto" and has_google_key)
    try_browser = args.google_mode == "browser" or (args.google_mode == "auto" and not has_google_key and not args.headless)
    if args.google_mode == "auto" and args.headless and not has_google_key:
        google_warning = f"google maps browser skipped in headless auto mode; set {GOOGLE_KEY_ENV} or force --google-mode browser"

    if try_api_first:
        api_rows, api_warning = google_places(args.area, query, args.date, args.meal, args.limit, args.google_key)
        if api_rows:
            google = api_rows
        if api_warning:
            google_warning = (google_warning + "; " if google_warning else "") + api_warning
    if try_browser and not google:
        try:
            google, google_warning = google_maps_browser_places(
                args.area, query, args.date, args.meal, args.limit,
                args.work_profile, args.src_profile, args.headless, args.timeout,
            )
        except Exception as e:
            google_warning = f"google maps browser failed: {e!r}"
    tabelog, tabelog_source = [], None
    if not args.no_tabelog:
        try:
            tabelog_query = args.tabelog_keyword or " ".join([*args.cuisine, args.area]).strip()
            tabelog, tabelog_source = tabelog_places(args.tabelog_area or args.area, args.tabelog_sort, tabelog_query, args.limit)
            time.sleep(args.polite_delay)
        except Exception as e:
            google_warning = (google_warning + "; " if google_warning else "") + f"tabelog failed: {e!r}"
    rows = merge_places(google, tabelog)[:args.limit]
    return {
        "meta": {
            "area": args.area,
            "date": args.date,
            "meal": args.meal,
            "query": query,
            "count": len(rows),
            "google_warning": google_warning,
            "tabelog_source": tabelog_source,
        },
        "restaurants": rows,
    }


def print_md(data):
    m = data["meta"]
    print(f"# 餐厅候选 · {m['area']} · {m['date']} {m['meal']}\n")
    if m.get("google_warning"):
        print(f"_提示: {m['google_warning']}_\n")
    if not data["restaurants"]:
        print("_未收集到餐厅候选。_")
        return
    print("| # | 店名 | 来源 | Google | Tabelog | 晚/午预算 | 营业 | 预约 | 链接 |")
    print("|---|------|------|--------|---------|-----------|------|------|------|")
    for i, r in enumerate(data["restaurants"], 1):
        g = f"{r.get('google_rating')}({r.get('google_reviews')})" if r.get("google_rating") else "—"
        t = f"{r.get('tabelog_rating')}({r.get('tabelog_reviews')})" if r.get("tabelog_rating") else "—"
        budget = r.get("budget_dinner") or r.get("budget_lunch") or r.get("google_price_level") or "—"
        op = "开" if r.get("open_for_slot") is True else ("关" if r.get("open_for_slot") is False else "未知")
        link = r.get("tabelog_url") or r.get("google_maps_url") or r.get("website") or ""
        src = "+".join(r.get("sources", []))
        name = f"[{r['name']}]({link})" if link else r["name"]
        print(f"| {i} | {name} | {src} | {g} | {t} | {budget} | {op}/{r.get('open_confidence','unknown')} | {r.get('reservation_method','unknown')} | {link or '—'} |")
    if m.get("tabelog_source"):
        print(f"\n_Tabelog: {m['tabelog_source']}_")


def main():
    ap = argparse.ArgumentParser(description="餐厅候选采集：Google Places top20 + Tabelog top20")
    ap.add_argument("--area", required=True, help='区域或 Tabelog URL，如 "Osaka Namba"')
    ap.add_argument("--date", required=True, help="用餐日期 YYYY-MM-DD")
    ap.add_argument("--meal", choices=sorted(MEAL_TIME), default="dinner")
    ap.add_argument("--cuisine", nargs="*", default=[], help="菜系关键词，如 sushi yakiniku ramen")
    ap.add_argument("--query", default=None, help="覆盖 Google/Tabelog 搜索关键词")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--google-mode", choices=["auto", "browser", "api", "off"], default="auto",
                    help="auto=有 key 用 API；无 key 且非 headless 尝试浏览器；headless 无 key 跳过 Google")
    ap.add_argument("--google-key", default=None, help=f"Google Places API key；默认读 {GOOGLE_KEY_ENV}")
    ap.add_argument("--src-profile", default=SRC_PROFILE, help="真实 Chrome profile；Google Maps 浏览器 harness 会借用 google.com cookie")
    ap.add_argument("--work-profile", default=work_profile_dir("food-google-maps"), help="Google Maps 浏览器 harness 用的干净 profile")
    ap.add_argument("--headless", action="store_true", help="Google Maps 浏览器 harness 无头运行")
    ap.add_argument("--timeout", type=int, default=35)
    ap.add_argument("--tabelog-area", default=None, help="覆盖 Tabelog 搜索区域或 URL")
    ap.add_argument("--tabelog-keyword", default=None, help="覆盖 Tabelog sw 关键词")
    ap.add_argument("--tabelog-sort", default="rating",
                    help="rating/local_reserved/viewed/traveler_reserved，或直接传 Tabelog SrtT")
    ap.add_argument("--no-tabelog", action="store_true")
    ap.add_argument("--polite-delay", type=float, default=0.5)
    ap.add_argument("--format", choices=["json", "md"], default="json")
    args = ap.parse_args()
    args.limit = max(1, min(args.limit, 20))
    data = discover(args)
    if args.format == "md":
        print_md(data)
    else:
        print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
