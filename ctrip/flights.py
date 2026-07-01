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

WORK_PROFILE = work_profile_dir("ctrip")


def build_url(frm, to, date, ret, cabin, adult, child):
    frm, to = frm.lower(), to.lower()
    if ret:
        base = f"https://flights.ctrip.com/online/list/roundtrip-{frm}-{to}?depdate={date}_{ret}"
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


def parse_flight(text):
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    times = re.findall(r"\b(\d{2}:\d{2})\b", text)
    airports = re.findall(r"([一-龥A-Za-z][一-龥A-Za-z·]*机场[A-Z0-9]*)", text)
    mprice = re.search(r"¥\s*([\d,]+)", text)
    mfn = re.search(r"\b([A-Z0-9]{2}\d{2,4})\b", text)
    mdur = re.search(r"(\d+\s*小时\s*\d*\s*分?|\d+\s*分钟?)", text)
    mac = re.search(r"((?:空客|波音|Airbus|Boeing)[^\s|]*)", text)
    stops = "中转" if "中转" in text else ("直飞" if "直飞" in text else None)
    if not times or not mprice:
        return None
    return {
        "airline": lines[0] if lines else None,
        "flight_no": mfn.group(1) if mfn else None,
        "aircraft": mac.group(1) if mac else None,
        "depart_time": times[0],
        "arrive_time": times[1] if len(times) > 1 else None,
        "depart_airport": airports[0] if airports else None,
        "arrive_airport": airports[1] if len(airports) > 1 else None,
        "duration": (mdur.group(1).replace(" ", "") if mdur else None),
        "stops": stops,
        "price_tax_incl": float(mprice.group(1).replace(",", "")),
        "currency": "¥",
    }


def run(args):
    datetime.strptime(args.date, "%Y-%m-%d")
    if args.ret:
        datetime.strptime(args.ret, "%Y-%m-%d")

    ck = load_cookies(args.src_profile, "ctrip.com")
    url = build_url(args.frm, args.to, args.date, args.ret, args.cabin, args.adults, args.child)
    if args.debug:
        print(f"[debug] 注入 {len(ck)} 个 ctrip cookie；url={url}", file=sys.stderr)

    raw = []
    with sandboxed_page(args.work_profile, cookies=ck, headless=args.headless) as page:
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
        if args.screenshot:
            try:
                page.screenshot(path=args.screenshot, timeout=10000)
            except Exception:
                pass

    flights, seen = [], set()
    for t in raw:
        f = parse_flight(t)
        if not f:
            continue
        key = (f["flight_no"], f["depart_time"])
        if key in seen:
            continue
        seen.add(key)
        flights.append(f)
    flights.sort(key=lambda f: f["price_tax_incl"])
    flights = flights[: args.limit]

    trip = f"{args.frm.upper()}→{args.to.upper()}" + (f"→{args.frm.upper()}" if args.ret else "")
    meta = {"route": trip, "date": args.date, "return": args.ret,
            "adults": args.adults, "count": len(flights)}

    if args.format == "md":
        rng = args.date + (f" / 返 {args.ret}" if args.ret else "")
        print(f"# 携程机票 · {trip}（{rng} · {args.adults}人）\n")
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
    else:
        print(json.dumps({"meta": meta, "flights": flights}, ensure_ascii=False, indent=2))
    return 0


def main():
    ap = argparse.ArgumentParser(description="查携程机票（注入真实会话 cookie）")
    ap.add_argument("--from", dest="frm", required=True, help="出发地三字码，如 hkg/sha/bjs")
    ap.add_argument("--to", required=True, help="到达地三字码，如 osa/tyo/kix")
    ap.add_argument("--date", required=True, help="去程日期 YYYY-MM-DD")
    ap.add_argument("--return", dest="ret", default=None, help="返程日期 YYYY-MM-DD（给了=往返）")
    ap.add_argument("--adults", type=int, default=1, help="成人数（默认 1）")
    ap.add_argument("--child", type=int, default=0, help="儿童数（默认 0）")
    ap.add_argument("--cabin", default="Y_S", help="舱位：Y_S 经济/超经、C_F 公务/头等（默认 Y_S）")
    ap.add_argument("--src-profile", default=SRC_PROFILE, help="真实 Chrome profile（读 cookie）")
    ap.add_argument("--work-profile", default=WORK_PROFILE, help="本工具用的干净 profile 目录")
    ap.add_argument("--headless", action="store_true", help="无头（默认有头）")
    ap.add_argument("--limit", type=int, default=25, help="最多返回几个航班")
    ap.add_argument("--format", choices=["json", "md"], default="json")
    ap.add_argument("--screenshot", default=None)
    ap.add_argument("--timeout", type=int, default=50)
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()
    sys.exit(run(args))


if __name__ == "__main__":
    main()
