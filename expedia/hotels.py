#!/usr/bin/env python3
"""
expedia_hotels.py — 查 Expedia 酒店价格（个人行程比价用）。

原理（全自动、不碰你正在用的 Chrome、无需你点任何东西）：
  Expedia 用 DataDome + Akamai 反爬，任何“冷启动的自动化浏览器”都会被拦成
  “Bot or Not?”滑块验证（换引擎/关 webdriver/camoufox 都没用；根因是本机出口
  是被标记 of 机房 IP）。但你真实 Chrome 里已经有“被真人清算过”的 datadome / Akamai
  cookie（还带着你的登录态）。本工具：
    1) 从你的真实 profile 读出并解密这些 cookie（Linux v11 走 gnome-keyring 密钥）；
    2) 用 patchright（Playwright 反检测版）+ 系统真 Chrome 起一个干净浏览器；
    3) 注入这些 cookie（同一台机器→同一出口 IP，同版本 Chrome→同 UA）；
    4) DataDome/Akamai 看到有效清算 + 同 IP/UA 直接放行 → 正常拿到酒店结果。
  不使用 CDP 挂载你的浏览器，不锁你的 profile，你自己的 Chrome 照常能开能用。

  cookie 会随你日常浏览保持新鲜；若某天工具被 DataDome 拦（cookie 过期），
  只需在你自己的 Chrome 里打开一次 expedia.com（过掉验证）再重跑即可。

依赖：patchright + 系统 Google Chrome(channel="chrome") + pycryptodome + secretstorage。

用法示例：
  python3 cli/expedia_hotels.py --checkin 2026-07-10 --nights 7 --format md
  python3 cli/expedia_hotels.py --destination "神戸" --checkin 2026-07-10 --checkout 2026-07-17 --json
  python3 cli/expedia_hotels.py --checkin 2026-07-10 --screenshot ~/trip/kobe.png --debug
"""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.browser import goto_retry, sandboxed_page, work_profile_dir
from core.cookies import SRC_PROFILE, load_cookies
from core.dates import compute_dates
from expedia.common import host_suffix_from

WORK_PROFILE = work_profile_dir("expedia")


def build_search_url(host, destination, ci, co, adults, rooms, sort):
    return (f"https://{host}/Hotel-Search?destination={quote(destination)}"
            f"&startDate={ci}&endDate={co}&adults={adults}&rooms={rooms}&sort={sort}")


# ---------------------------------------------------------------------------
# 抽取
# ---------------------------------------------------------------------------
RESULTS_SELECTORS = [
    '[data-stid="lodging-card-responsive"]',
    '[data-stid="property-listing-results"]',
    '[data-stid="property-card"]',
]

EXTRACT_JS = r"""
() => {
  const pickText = (el, sels) => {
    for (const s of sels) {
      const n = el.querySelector(s);
      if (n && n.innerText && n.innerText.trim()) return n.innerText.trim();
    }
    return null;
  };
  const cardSel = '[data-stid="lodging-card-responsive"], [data-stid="property-card"], [data-stid="property-listing"]';
  let cards = Array.from(document.querySelectorAll(cardSel));
  cards = cards.filter(c => !cards.some(o => o !== c && o.contains(c)));
  return cards.map(c => {
    let name = pickText(c, ['[data-stid="content-hotel-title"]', 'h3', 'h2', '[class*="uitk-heading"]']);
    if (name) name = name.replace(/^Photo gallery for\s*/i, '').trim();
    const priceText = pickText(c, [
      '[data-stid="price-summary"]', '[data-test-id="price-summary"]',
      '[class*="uitk-lockup-price"]', '[aria-label*="price"]']);
    const reviewText = pickText(c, [
      '[data-stid="content-hotel-reviews"]', '[aria-label*="out of 10"]', '[class*="uitk-badge"]']);
    let href = null;
    const a = c.querySelector('a[href*="/hotels/"], a[data-stid="open-hotel-information"], a[href]');
    if (a) href = a.href;
    return { name, priceText, reviewText, href, raw: (c.innerText || '').slice(0, 500) };
  }).filter(x => x.name);
}
"""

CUR = r"(US\$|USD|JP¥|¥|£|€|A\$|HK\$|C\$|\$)"
PRICE_RE = re.compile(CUR + r"\s?([\d,]+)")
TOTAL_RE = re.compile(CUR + r"\s?([\d,]+)\s*total", re.I)
NIGHTLY_RE = re.compile(CUR + r"\s?([\d,]+)\s*(?:nightly|/\s*night|per night|a night)", re.I)
SCORE_RE = re.compile(r"\b(\d{1,2}(?:\.\d)?)\s*(?:/\s*10|out of 10)?\b")
REVIEWCOUNT_RE = re.compile(r"([\d,]+)\s+reviews?", re.I)


def _num(s):
    return float(s.replace(",", ""))


def parse_prices(text):
    if not text:
        return None, None, None
    total = nightly = currency = None
    mt = TOTAL_RE.search(text)
    if mt:
        currency, total = mt.group(1), _num(mt.group(2))
    mn = NIGHTLY_RE.search(text)
    if mn:
        currency = currency or mn.group(1)
        nightly = _num(mn.group(2))
    if total is None and nightly is None:
        m = PRICE_RE.search(text)
        if m:
            currency, total = m.group(1), _num(m.group(2))
    return total, nightly, currency


def city_from_url(url):
    """从酒店详情 URL 的英文 slug 解析城市（语言无关，能处理 /cn/ 等本地化前缀）。"""
    if not url:
        return None
    m = re.search(r"/([A-Za-z][A-Za-z-]*?)-Hotels?-", url)
    return m.group(1).replace("-", " ") if m else None


def parse_review(text):
    if not text:
        return None, None
    score = None
    m = SCORE_RE.search(text)
    if m:
        try:
            v = float(m.group(1))
            if 0 <= v <= 10:
                score = v
        except ValueError:
            pass
    cnt = None
    mc = REVIEWCOUNT_RE.search(text)
    if mc:
        cnt = int(mc.group(1).replace(",", ""))
    return score, cnt


def _collect_prices(node, acc):
    """递归收集节点下所有形如货币+数字的价格。"""
    if isinstance(node, dict):
        for v in node.values():
            _collect_prices(v, acc)
    elif isinstance(node, list):
        for v in node:
            _collect_prices(v, acc)
    elif isinstance(node, str):
        m = PRICE_RE.search(node)
        if m:
            acc.append((m.group(1), _num(m.group(2))))


def _first_rating(node):
    """在节点下找第一个 0~10 的评分（针对 Review Score）。"""
    if isinstance(node, bool):
        return None
    if isinstance(node, (int, float)):
        v = float(node)
        return v if 0 <= v <= 10 else None
    if isinstance(node, dict):
        for k, v in node.items():
            if re.search(r"rating|score", k, re.I):
                r = _first_rating(v)
                if r is not None:
                    return r
        for v in node.values():
            r = _first_rating(v)
            if r is not None:
                return r
    elif isinstance(node, list):
        for v in node:
            r = _first_rating(v)
            if r is not None:
                return r
    elif isinstance(node, str):
        m = re.match(r"^(10(?:\.0)?|[0-9](?:\.[0-9])?)(?:\s*/\s*10)?$", node.strip())
        if m:
            v = float(m.group(1))
            if 0 <= v <= 10:
                return v
    return None


def _find_star_rating(node):
    """递归寻找酒店星级（Star Rating / Property Rating）。"""
    if isinstance(node, dict):
        for k in ("starRating", "propertyRating"):
            v = node.get(k)
            if v is not None:
                if isinstance(v, (int, float)) and 1 <= v <= 5:
                    return v
                if isinstance(v, dict):
                    for sk in ("value", "rating", "stars"):
                        sv = v.get(sk)
                        if isinstance(sv, (int, float)) and 1 <= sv <= 5:
                            return sv
        for v in node.values():
            res = _find_star_rating(v)
            if res is not None:
                return res
    elif isinstance(node, list):
        for v in node:
            res = _find_star_rating(v)
            if res is not None:
                return res
    return None


def parse_gql(listings, nights):
    """从 Expedia GraphQL 的 propertySearchListings 解析酒店。"""
    hotels = []
    for c in listings:
        if not isinstance(c, dict) or c.get("__typename") != "LodgingCard":
            continue
        name = (c.get("headingSection") or {}).get("heading")
        if not name:
            continue
        url = (((c.get("cardLink") or {}).get("resource") or {}).get("value") or "").split("?")[0] or None
        ps = c.get("priceSection") or {}
        summary = ps.get("priceSummary") or {}
        
        # 收集星级
        star_rating = _find_star_rating(c)
        
        cand = []
        opts = summary.get("options") or []
        if opts:
            f = ((opts[0].get("displayPrice") or {}) or {}).get("formatted")
            if f:
                mm = PRICE_RE.search(f)
                if mm:
                    cand.append((mm.group(1), _num(mm.group(2))))
        for dm in (summary.get("displayMessages") or []):
            for li in (dm.get("lineItems") or []):
                val = li.get("value")
                if isinstance(val, str):
                    mm = PRICE_RE.search(val)
                    if mm:
                        cand.append((mm.group(1), _num(mm.group(2))))
        if not cand:
            _collect_prices(ps, cand)
            
        total = nightly = currency = None
        if cand:
            currency = cand[0][0]
            nums = [n for _, n in cand]
            total, nightly = max(nums), min(nums)
            if nights > 1 and total < nightly * 1.5:
                total = round(nightly * nights)
                
        review = None
        for s in (c.get("summarySections") or []):
            g = s.get("guestRatingSectionV2") or s.get("guestRatingSection") or s.get("reviewSummary")
            if g:
                review = _first_rating(g)
                if review is not None:
                    break
                    
        hotels.append({
            "name": name, "city": city_from_url(url),
            "total_price": total, "nightly_price": nightly, "currency": currency,
            "price_text": (f"{currency or ''}{nightly:.0f}/晚" if nightly is not None else None),
            "nights": nights, "review_score": review, "review_count": None, 
            "star_rating": star_rating, "url": url,
        })
    return hotels


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def run(args):
    from patchright.sync_api import TimeoutError as PWTimeout

    ci, co = compute_dates(args.checkin, args.checkout, args.nights)
    nights = (datetime.strptime(co, "%Y-%m-%d") - datetime.strptime(ci, "%Y-%m-%d")).days
    cookie_suffix, host = host_suffix_from(args.base_url)

    ck = None
    if not args.no_cookies:
        ck = load_cookies(args.src_profile, cookie_suffix, args.debug)
        has_dd = any(c["name"] == "datadome" for c in ck)
        if args.debug:
            print(f"[debug] 注入 {len(ck)} 个 {cookie_suffix} cookie（datadome={has_dd}）", file=sys.stderr)

    gql_listings = []
    raw = []
    challenged = False

    with sandboxed_page(args.work_profile, cookies=ck, headless=args.headless) as page:
        def on_response(resp):
            try:
                if "graphql" in resp.url and resp.status == 200:
                    data = resp.json()
                    lst = ((data.get("data") or {}).get("propertySearch") or {}).get("propertySearchListings")
                    if isinstance(lst, list):
                        gql_listings.extend(lst)
            except Exception:
                pass
        page.on("response", on_response)

        try:
            goto_retry(page, f"https://{host}/", args.timeout)
            h = urlparse(page.url).hostname
            if h and "expedia." in h:
                host = h
        except Exception:
            pass

        url = build_search_url(host, args.destination, ci, co, args.adults, args.rooms, args.sort)
        if args.debug:
            print(f"[debug] host={host}\n[debug] url={url}", file=sys.stderr)
        goto_retry(page, url, args.timeout)

        title = (page.title() or "")
        if "bot or not" in title.lower() or any("captcha-delivery" in (f.url or "") for f in page.frames):
            challenged = True
            print("⚠️  被 DataDome 拦截：真实会话 cookie 可能已过期。\n"
                  "   请在你自己的 Chrome 里打开一次 https://www.expedia.com/（过掉验证）再重跑本工具。",
                  file=sys.stderr)

        for sel in RESULTS_SELECTORS:
            try:
                page.wait_for_selector(sel, timeout=8000)
                break
            except PWTimeout:
                continue

        def count_cards():
            return len(page.query_selector_all(
                '[data-stid="lodging-card-responsive"], [data-stid="property-card"], a[href*="Hotel-Information"]'))

        def target_count():
            cards = [c for c in gql_listings if isinstance(c, dict) and c.get("__typename") == "LodgingCard"]
            if not args.city:
                return len(cards)
            want = args.city.strip().lower()
            return sum(1 for c in cards if (city_from_url(
                (((c.get("cardLink") or {}).get("resource") or {}).get("value")) or "") or "").lower() == want)

        stable = 0
        for _ in range(30):
            if target_count() >= args.limit:
                break
            before = len(gql_listings) + count_cards()
            try:
                btn = page.query_selector(
                    'button:has-text("Show more"), button:has-text("more results"), [data-stid="show-more-results"]')
                if btn:
                    btn.click(timeout=2000)
            except Exception:
                pass
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(1600)
            if len(gql_listings) + count_cards() == before:
                stable += 1
                if stable >= 3:
                    break
            else:
                stable = 0
        page.evaluate("window.scrollTo(0, 0)")

        if not gql_listings:
            raw = page.evaluate(EXTRACT_JS)
        if args.screenshot:
            try:
                page.screenshot(path=args.screenshot, timeout=10000)
            except Exception as e:
                print(f"[debug] 截图失败: {e!r}", file=sys.stderr)

    if gql_listings:
        seen_ids, uniq = set(), []
        for c in gql_listings:
            cid = c.get("id") if isinstance(c, dict) else None
            if cid and cid in seen_ids:
                continue
            seen_ids.add(cid)
            uniq.append(c)
        hotels = parse_gql(uniq, nights)
        source = f"graphql({len(hotels)})"
    else:
        hotels = []
        for r in raw:
            total, nightly, currency = parse_prices(r.get("priceText") or r.get("raw"))
            score, cnt = parse_review(r.get("reviewText") or r.get("raw"))
            url = (r.get("href") or "").split("?")[0] or None
            
            # 从 DOM 文本提取星级
            star_rating = None
            raw_txt = r.get("raw") or ""
            m_star = re.search(r"(\d+(?:\.\d)?)\s*(?:星级|星級|-star)", raw_txt, re.I)
            if m_star:
                try:
                    star_rating = float(m_star.group(1))
                except ValueError:
                    pass
                    
            hotels.append({
                "name": r.get("name"), "city": city_from_url(url),
                "total_price": total, "nightly_price": nightly, "currency": currency,
                "price_text": re.sub(r"\s+", " ", (r.get("priceText") or "")).strip() or None,
                "nights": nights, "review_score": score, "review_count": cnt, 
                "star_rating": star_rating, "url": url})
        source = f"dom({len(hotels)})"
        
    if args.debug:
        print(f"[debug] 抽取来源: {source}", file=sys.stderr)

    if args.city:
        want = args.city.strip().lower()
        hotels = [h for h in hotels if (h["city"] or "").lower() == want]

    seen, deduped = set(), []
    for h in hotels:
        if h["name"] in seen:
            continue
        seen.add(h["name"])
        deduped.append(h)

    def sort_val(h):
        v = h["total_price"] if h["total_price"] is not None else h["nightly_price"]
        return (v is None, v if v is not None else 0)
    deduped.sort(key=sort_val)
    deduped = deduped[: args.limit]

    meta = {
        "destination": args.destination, "site": host, "checkin": ci, "checkout": co,
        "nights": nights, "adults": args.adults, "rooms": args.rooms, "sort": args.sort,
        "count": len(deduped), "challenged": challenged,
    }

    if args.format == "md":
        cur = next((h["currency"] for h in deduped if h["currency"]), "")
        print(f"# {args.destination} 酒店（{meta['site']} · {ci} → {co} · {nights}晚 · {args.adults}人）\n")
        if not deduped:
            msg = "_被 DataDome 拦截，见上面提示。_" if challenged else "_未抓到结果，可加 --debug 排查。_"
            print(msg)
        else:
            print(f"| # | 酒店 | 星级 | 城市 | 总价({nights}晚) | 每晚 | 评分 |")
            print("|---|------|------|------|------|------|------|")
            for i, h in enumerate(deduped, 1):
                tot = f"{h['currency'] or cur}{h['total_price']:.0f}" if h["total_price"] is not None else "—"
                nig = f"{h['currency'] or cur}{h['nightly_price']:.0f}" if h["nightly_price"] is not None else "—"
                score = h["review_score"] if h["review_score"] is not None else "—"
                star = f"{h['star_rating']:.1f}星" if h.get("star_rating") else "—"
                city = h["city"] or "—"
                name = h["name"] if not h["url"] else f"[{h['name']}]({h['url']})"
                print(f"| {i} | {name} | {star} | {city} | {tot} | {nig} | {score} |")
        print(f"\n_共 {meta['count']} 家；站点 {meta['site']}；价格为页面原样({cur or '原货币'})、未换算。_")
    else:
        print(json.dumps({"meta": meta, "hotels": deduped}, ensure_ascii=False, indent=2))
    return 0


def main():
    ap = argparse.ArgumentParser(description="查 Expedia 酒店价格（注入真实会话 cookie 绕过 DataDome）")
    ap.add_argument("--destination", default="Kobe, Hyogo Prefecture, Japan", help='目的地，如 "Kobe, Hyogo Prefecture, Japan" 或 "神戸"')
    ap.add_argument("--city", default=None, help='只保留该城市的酒店（如 Kobe，过滤掉附近大阪等）；默认不过滤但会标城市列')
    ap.add_argument("--checkin", required=True, help="入住日期 YYYY-MM-DD")
    ap.add_argument("--checkout", default=None, help="退房日期 YYYY-MM-DD（与 --nights 二选一）")
    ap.add_argument("--nights", type=int, default=7, help="住几晚（默认 7）")
    ap.add_argument("--adults", type=int, default=1, help="成人数（默认 1）")
    ap.add_argument("--rooms", type=int, default=1, help="房间数（默认 1）")
    ap.add_argument("--src-profile", default=SRC_PROFILE, help="你的真实 Chrome profile（读取会话 cookie）")
    ap.add_argument("--work-profile", default=WORK_PROFILE, help="本工具用的干净 profile 目录")
    ap.add_argument("--no-cookies", action="store_true", help="不注入 cookie（调试用，会被 DataDome 拦）")
    ap.add_argument("--headless", action="store_true", help="无头模式（默认有头）")
    ap.add_argument("--base-url", default="auto", help='站点：auto=www.expedia.com；或 "www.expedia.co.jp"')
    ap.add_argument("--sort", default="PRICE_LOW_TO_HIGH", help="排序（默认按价格升序）")
    ap.add_argument("--limit", type=int, default=25, help="最多返回几家（默认 25）")
    ap.add_argument("--format", choices=["json", "md"], default="json", help="输出格式")
    ap.add_argument("--screenshot", default=None, help="结果页截图保存路径（可选）")
    ap.add_argument("--timeout", type=int, default=45, help="页面加载超时秒数（默认 45）")
    ap.add_argument("--debug", action="store_true", help="打印调试信息")
    args = ap.parse_args()
    sys.exit(run(args))


if __name__ == "__main__":
    main()
