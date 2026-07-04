#!/usr/bin/env python3
"""
ctrip_flights.py — 查携程(flights.ctrip.com)机票（个人行程比价）。

原理同 expedia_hotels.py / ctrip_hotels.py：解密注入你真实 profile 的 .ctrip.com
cookie 到一个 patchright+真 Chrome 的干净浏览器（同机同 IP/UA），携程当正常用户
放行；从航班列表页 DOM 抽取，输出 JSON/Markdown。不挂载/不干扰你自己的浏览器。

城市/机场用携程三字码：香港=hkg 大阪=osa 东京=tyo 上海=sha 北京=bjs 首尔=sel …
（也可用机场码，如关西=kix、成田=nrt）。

用法：
  python3 cli/ctrip_flights.py --from hkg --to osa --date 2026-07-10 --format md
  python3 cli/ctrip_flights.py --from hkg --to osa --date 2026-07-10 --return 2026-07-17 --format md
  python3 cli/ctrip_flights.py --from sha --to kix --date 2026-08-01 --json
  python3 cli/ctrip_flights.py --query can-nrt,2026-12-16,2026-12-22 --query can-ngo,2026-12-16,2026-12-22 --format md
"""

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from itertools import product
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.browser import goto_retry, sandboxed_page, work_profile_dir
from core.cookies import SRC_PROFILE, load_cookies

WORK_PROFILE = work_profile_dir("ctrip")

CITY_AIRPORTS = {
    # Ctrip's list URL sometimes returns no cards for metro/city IATA codes.
    # Keep the city-code request first, then fall back to concrete airports.
    "tyo": ("nrt", "hnd"),
    "osa": ("kix", "itm", "ukb"),
    "bjs": ("pek", "pkx"),
    "sha": ("sha", "pvg"),
    "sel": ("icn", "gmp"),
}


@dataclass(frozen=True)
class FlightQuery:
    frm: str
    to: str
    date: str
    ret: Optional[str] = None
    requested_route: Optional[str] = None


def build_url(frm, to, date, ret, cabin, adult, child):
    frm, to = frm.lower(), to.lower()
    if ret:
        base = f"https://flights.ctrip.com/online/list/round-{frm}-{to}?depdate={date}_{ret}"
    else:
        base = f"https://flights.ctrip.com/online/list/oneway-{frm}-{to}?depdate={date}"
    return base + f"&cabin={cabin}&adult={adult}&child={child}&infant=0"


EXTRACT_JS = r"""
() => {
  const cards = Array.from(document.querySelectorAll('[class*="flight-item"]'))
    .filter(el => /\d{2}:\d{2}/.test(el.innerText||'') && /¥/.test(el.innerText||''));
  const uniq = cards.filter(c => !cards.some(o => o !== c && o.contains(c)));
  return uniq.map(c => (c.innerText || ''));
}
"""


def _validate_date(value, label):
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as e:
        raise ValueError(f"{label} 必须是 YYYY-MM-DD：{value}") from e
    return value


def _normalize_code(value, label):
    code = value.strip().lower()
    if not re.fullmatch(r"[a-z]{3}", code):
        raise ValueError(f"{label} 必须是三字码：{value}")
    return code


def parse_query_spec(spec):
    """Parse FROM-TO,DATE[,RETURN] or FROM-TO:DATE[:RETURN] into FlightQuery."""
    raw = spec.strip()
    if not raw:
        raise ValueError("空 query")
    clean = raw.replace("，", ",").replace("：", ":").replace("；", ";")
    parts = [p.strip() for p in re.split(r"[:,\s]+", clean) if p.strip()]
    if len(parts) == 2:
        route, date_part = parts
        mdate = re.fullmatch(
            r"(\d{4}-\d{2}-\d{2})(?:\.\.|~|/)(\d{4}-\d{2}-\d{2})",
            date_part,
        )
        if mdate:
            date, ret = mdate.groups()
        else:
            date, ret = date_part, None
    elif len(parts) == 3:
        route, date, ret = parts
    else:
        raise ValueError(f"query 格式应为 FROM-TO,DATE[,RETURN]：{spec}")

    mroute = re.fullmatch(r"([A-Za-z]{3})(?:->|→|>|-)([A-Za-z]{3})", route)
    if not mroute:
        raise ValueError(f"query 路线格式应为 FROM-TO：{spec}")

    frm, to = mroute.groups()
    frm = _normalize_code(frm, "出发地")
    to = _normalize_code(to, "到达地")
    date = _validate_date(date, "去程日期")
    if ret:
        ret = _validate_date(ret, "回程日期")
    return FlightQuery(frm=frm, to=to, date=date, ret=ret)


def _split_values(value):
    if not value:
        return []
    return [p.strip() for p in re.split(r"[,，\s]+", value) if p.strip()]


def _iter_query_specs(values):
    for value in values or []:
        for spec in re.split(r"[;；\n]+", value):
            spec = spec.strip()
            if spec:
                yield spec


def queries_from_args(args):
    specs = list(_iter_query_specs(args.queries))
    if specs:
        return [parse_query_spec(spec) for spec in specs]

    if not args.frm or not args.to or not args.date:
        raise ValueError("请使用 --from/--to/--date，或传入一个或多个 --query")

    frms = [_normalize_code(v, "出发地") for v in _split_values(args.frm)]
    tos = [_normalize_code(v, "到达地") for v in _split_values(args.to)]
    dates = [_validate_date(v, "去程日期") for v in _split_values(args.date)]
    rets = [_validate_date(v, "回程日期") for v in _split_values(args.ret)]
    if not rets:
        rets = [None]
    elif len(rets) not in (1, len(dates)):
        raise ValueError("--return 可以给 1 个值，或与 --date 数量一致")

    queries = []
    for frm, to in product(frms, tos):
        for i, date in enumerate(dates):
            ret = rets[0] if len(rets) == 1 else rets[i]
            queries.append(FlightQuery(frm=frm, to=to, date=date, ret=ret))
    return queries


def city_fallback_queries(query):
    frms = CITY_AIRPORTS.get(query.frm, (query.frm,))
    tos = CITY_AIRPORTS.get(query.to, (query.to,))
    if frms == (query.frm,) and tos == (query.to,):
        return []

    requested = route_label(query)
    expanded = []
    for frm, to in product(frms, tos):
        if frm == query.frm and to == query.to:
            continue
        expanded.append(FlightQuery(
            frm=frm,
            to=to,
            date=query.date,
            ret=query.ret,
            requested_route=requested,
        ))
    return expanded


def route_label(query):
    trip = f"{query.frm.upper()}→{query.to.upper()}"
    if query.ret:
        trip += f"→{query.frm.upper()}"
    return trip


def parse_flight(text):
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    times = re.findall(r"\b(\d{2}:\d{2})\b", text)
    airports = re.findall(r"([一-龥A-Za-z][一-龥A-Za-z·]*机场[A-Z0-9]*)", text)
    mprice = re.search(r"¥\s*([\d,]+)", text)
    mfn = re.search(r"\b([A-Z0-9]{2}\d{2,4})\b", text)
    duration_pattern = r"((?:\d+\s*天\s*)?\d+\s*小时\s*\d*\s*分?|(?:\d+\s*天\s*)?\d+\s*分钟?)"
    mdur = re.search(duration_pattern + r"\s*航班详情", text)
    if not mdur:
        durations = re.findall(duration_pattern, text)
        mdur = durations[-1] if durations else None
    mac = re.search(r"((?:空客|波音|Airbus|Boeing)[^\s|]*)", text)
    mtransfer = re.search(r"转(\d+)次", text)
    transfer_cities = re.findall(r"转([^\d\n]+)(?:\d+h\d*m?|\d+\s*小时\s*\d*\s*分?)", text)
    if mtransfer:
        via = "、".join(dict.fromkeys(city.strip() for city in transfer_cities if city.strip()))
        stops = f"中转(经{via or 'unknown'}, {mtransfer.group(1)}次)"
    elif "中转" in text:
        stops = "中转(经unknown, unknown次)"
    else:
        stops = "直飞"
    if not times or not mprice:
        return None
    return {
        "airline": lines[0] if lines else None,
        "flight_no": mfn.group(1) if mfn else None,
        "aircraft": mac.group(1) if mac else None,
        "depart_time": times[0],
        "arrive_time": times[1] if len(times) > 1 else None,
        "arrive_day_offset": 1 if "+1天" in text else 0,
        "depart_airport": airports[0] if airports else None,
        "arrive_airport": airports[1] if len(airports) > 1 else None,
        "duration": ((mdur.group(1) if hasattr(mdur, "group") else mdur).replace(" ", "") if mdur else None),
        "stops": stops,
        "price_tax_incl": float(mprice.group(1).replace(",", "")),
        "currency": "¥",
    }


def _collect_flights(raw, limit, direct_only=True):
    flights, seen = [], set()
    for text in raw:
        flight = parse_flight(text)
        if not flight:
            continue
        if direct_only and flight["stops"] != "直飞":
            continue
        key = (
            flight["flight_no"],
            flight["airline"],
            flight["depart_time"],
            flight["depart_airport"],
            flight["arrive_airport"],
        )
        if key in seen:
            continue
        seen.add(key)
        flights.append(flight)
    flights.sort(key=lambda f: f["price_tax_incl"])
    return flights[:limit]


def _screenshot_path(base, query, index, total):
    if not base or total == 1:
        return base
    path = Path(base)
    suffix = path.suffix or ".png"
    stem = path.stem if path.suffix else path.name
    ret = f"-{query.ret}" if query.ret else ""
    filename = f"{stem}-{index:02d}-{query.frm}-{query.to}-{query.date}{ret}{suffix}"
    return str(path.with_name(filename))


def fetch_query(page, query, args, screenshot_path=None):
    url = build_url(query.frm, query.to, query.date, query.ret, args.cabin, args.adults, args.child)
    if args.debug:
        print(f"[debug] url={url}", file=sys.stderr)

    goto_retry(page, url, args.timeout, tries=4)
    page.wait_for_timeout(9000)
    stable, prev = 0, -1
    for _ in range(12):
        cnt = page.evaluate("()=>document.querySelectorAll('[class*=\"flight-item\"]').length")
        if cnt >= args.limit + 3 or cnt == prev:
            stable += 1
            if stable >= 2:
                break
        else:
            stable = 0
        prev = cnt
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(1600)
    page.evaluate("window.scrollTo(0,0)")
    if "验证" in (page.title() or ""):
        print("⚠️ 被携程风控拦截；在你自己的 Chrome 打开一次携程再重跑。", file=sys.stderr)
    raw = page.evaluate(EXTRACT_JS)
    if screenshot_path:
        try:
            page.screenshot(path=screenshot_path, timeout=10000)
        except Exception:
            pass

    flights = _collect_flights(raw, args.limit, direct_only=args.direct_only)
    meta = {
        "route": route_label(query),
        "date": query.date,
        "return": query.ret,
        "adults": args.adults,
        "count": len(flights),
        "url": url,
    }
    if query.requested_route:
        meta["requested_route"] = query.requested_route
    if args.debug:
        meta["raw_cards"] = len(raw)
        if args.dump_raw:
            meta["raw_texts"] = raw
    return {"meta": meta, "flights": flights}


def fetch_with_fallback(page, query, args, screenshot_index, screenshot_total):
    result = fetch_query(
        page,
        query,
        args,
        screenshot_path=_screenshot_path(args.screenshot, query, screenshot_index, screenshot_total),
    )
    if result["flights"]:
        return [result]

    if args.no_city_fallback:
        return [result]

    fallback = city_fallback_queries(query)
    if not fallback:
        return [result]

    if args.debug:
        expanded = ", ".join(route_label(q) for q in fallback)
        print(f"[debug] {route_label(query)} 未抓到结果，fallback 到机场码：{expanded}", file=sys.stderr)

    results = []
    for offset, fallback_query in enumerate(fallback, 1):
        results.append(fetch_query(
            page,
            fallback_query,
            args,
            screenshot_path=_screenshot_path(
                args.screenshot,
                fallback_query,
                screenshot_index + offset,
                screenshot_total + len(fallback),
            ),
        ))
    return results


def print_md(results, adults):
    for block_index, result in enumerate(results, 1):
        meta = result["meta"]
        details = []
        if meta.get("requested_route"):
            details.append(f"请求 {meta['requested_route']}")
        requested = f"（{' · '.join(details)}）" if details else ""
        rng = meta["date"] + (f" / 返 {meta['return']}" if meta["return"] else "")
        print(f"# 携程机票 · {meta['route']}{requested}（{rng} · {adults}人）\n")
        flights = result["flights"]
        if not flights:
            print("_未抓到结果，可加 --debug 排查。_")
        else:
            print("| # | 航司 | 航班 | 出发 | 到达 | 时长 | 中转 | 含税价 |")
            print("|---|------|------|------|------|------|------|------|")
            for i, f in enumerate(flights, 1):
                dep = f"{f['depart_time']} {f['depart_airport'] or ''}"
                arr = f"{f['arrive_time'] or ''} {f['arrive_airport'] or ''}"
                print(f"| {i} | {f['airline'] or '—'} | {f['flight_no'] or '—'} | {dep} | {arr} | "
                      f"{f['duration'] or '—'} | {f['stops'] or '—'} | ¥{f['price_tax_incl']:.0f} |")
        print(f"\n_共 {meta['count']} 个航班；含税起价；当地时间。_")
        if block_index < len(results):
            print()


def run(args):
    queries = queries_from_args(args)
    ck = load_cookies(args.src_profile, "ctrip.com")
    if args.debug:
        print(f"[debug] 注入 {len(ck)} 个 ctrip cookie；queries={len(queries)}", file=sys.stderr)

    results = []
    with sandboxed_page(args.work_profile, cookies=ck, headless=args.headless) as page:
        for i, query in enumerate(queries, 1):
            results.extend(fetch_with_fallback(page, query, args, i, len(queries)))

    if args.format == "md":
        print_md(results, args.adults)
    else:
        if len(results) == 1:
            print(json.dumps(results[0], ensure_ascii=False, indent=2))
        else:
            print(json.dumps({"meta": {"queries": len(queries), "results": len(results)}, "results": results},
                             ensure_ascii=False, indent=2))
    return 0


def main():
    ap = argparse.ArgumentParser(description="查携程机票（注入真实会话 cookie）")
    ap.add_argument("--from", dest="frm", default=None, help="出发地三字码，如 hkg/sha/bjs；可逗号分隔多个")
    ap.add_argument("--to", default=None, help="到达地三字码，如 osa/tyo/kix；可逗号分隔多个")
    ap.add_argument("--date", default=None, help="去程日期 YYYY-MM-DD；可逗号分隔多个")
    ap.add_argument("--return", dest="ret", default=None, help="返程日期 YYYY-MM-DD（给了=往返）")
    ap.add_argument("--query", dest="queries", action="append",
                    help="批量查询：FROM-TO,DATE[,RETURN]；可重复，也可用分号分隔多条")
    ap.add_argument("--adults", type=int, default=1, help="成人数（默认 1）")
    ap.add_argument("--child", type=int, default=0, help="儿童数（默认 0）")
    ap.add_argument("--cabin", default="Y_S", help="舱位：Y_S 经济/超经、C_F 公务/头等（默认 Y_S）")
    ap.add_argument("--src-profile", default=SRC_PROFILE, help="真实 Chrome profile（读 cookie）")
    ap.add_argument("--work-profile", default=WORK_PROFILE, help="本工具用的干净 profile 目录")
    ap.add_argument("--no-city-fallback", action="store_true",
                    help="城市码无结果时不自动展开到机场码（如 tyo→nrt/hnd）")
    ap.add_argument("--all-flights", dest="direct_only", action="store_false",
                    help="不过滤中转，返回全部航班（默认只看直飞）")
    ap.set_defaults(direct_only=True)
    ap.add_argument("--headless", action="store_true", help="无头（默认有头）")
    ap.add_argument("--limit", type=int, default=25, help="最多返回几个航班")
    ap.add_argument("--format", choices=["json", "md"], default="json")
    ap.add_argument("--screenshot", default=None)
    ap.add_argument("--timeout", type=int, default=50)
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--dump-raw", action="store_true",
                    help="调试用：在 JSON meta 中输出抓到的原始航班卡片文本")
    args = ap.parse_args()
    try:
        queries_from_args(args)
    except ValueError as e:
        ap.error(str(e))
    sys.exit(run(args))


if __name__ == "__main__":
    main()
