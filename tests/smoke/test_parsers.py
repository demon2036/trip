#!/usr/bin/env python3
"""冒烟测试：用构造样例文本验证各 parse_* 函数的解析逻辑。

不需要网络、不需要浏览器、不需要真实 cookie，跑得快，随时可以跑：

    python3 tests/smoke/test_parsers.py

只验证"给定这段 DOM 文本，字段解析对不对"，不验证"能不能真的连上携程/Expedia
拿到这段文本"——那是 tests/real/ 底下脚本的职责。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from ctrip.hotels import parse_card
from ctrip.flights import parse_flight
from ctrip.room_details import parse_room_block as ctrip_parse_room
from expedia.hotels import parse_prices, parse_review, city_from_url
from expedia.room_details import parse_room_block as expedia_parse_room


def test_ctrip_hotel_card():
    text = "\n".join([
        "神户全日空皇冠假日酒店",
        "ANA Crowne Plaza Kobe",
        "4.7",
        "1234条点评",
        "公园口·近三宫站",
        "豪华型/5钻",
        "¥507起",
        "含税/费后¥620",
    ])
    r = parse_card(text, '{"data": {"star": 5}}', nights=1)
    assert r["name"] == "神户全日空皇冠假日酒店"
    assert r["name_en"] == "ANA Crowne Plaza Kobe"
    assert r["nightly_price"] == 507.0
    assert r["nightly_tax_incl"] == 620.0
    assert r["total_price"] == 507
    assert r["review_count"] == 1234
    assert r["star_rating"] == 5.0
    assert r["star_desc"] == "豪华型/5钻"


def test_ctrip_flight():
    text = "\n".join([
        "中国东方航空",
        "MU5678",
        "空客A320",
        "08:30",
        "10:45",
        "上海虹桥国际机场T2",
        "大阪关西国际机场T1",
        "2小时15分",
        "直飞",
        "¥1580",
    ])
    f = parse_flight(text)
    assert f["airline"] == "中国东方航空"
    assert f["flight_no"] == "MU5678"
    assert f["aircraft"] == "空客A320"
    assert f["depart_time"] == "08:30"
    assert f["arrive_time"] == "10:45"
    assert f["stops"] == "直飞"
    assert f["price_tax_incl"] == 1580.0


def test_ctrip_room_block():
    text = "豪华双床房 | 25㎡ | 2张单人床 | 部分禁烟 | 双早\n¥899\n¥950"
    r = ctrip_parse_room(text)
    assert r["room_name"] == "豪华双床房"
    assert r["size"] == "25㎡"
    assert r["smoking"] == "部分禁烟"
    assert r["breakfast"] == "含早餐"
    assert r["price"] == 950.0


def test_expedia_hotel_helpers():
    total, nightly, currency = parse_prices("HK$1,234 total HK$617 nightly")
    assert currency == "HK$" and total == 1234.0 and nightly == 617.0

    score, cnt = parse_review("9.2 1,500 reviews")
    assert score == 9.2 and cnt == 1500

    city = city_from_url("https://www.expedia.com/Kobe-Hotels-ANA-Crowne-Plaza-Kobe.h1209540.Hotel-Information")
    assert city == "Kobe"


def test_expedia_room_block():
    text = "豪华双人房的所有照片\n215平方呎\n1张特大床\n禁烟\n全套早餐\nHK$1,234"
    r = expedia_parse_room(text, nights=2)
    assert r["room_name"] == "豪华双人房"
    # 原逻辑：只有单位文本里带"英"或"ft"才标"平方英尺"，"呎"不算，落到默认㎡分支
    assert r["size"] == "215㎡"
    assert r["smoking"] == "禁烟"
    assert r["breakfast"] == "含早餐"
    assert r["total_price"] == 1234.0
    assert r["nightly_price"] == 617.0


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"OK   {t.__name__}")
        except Exception as e:
            failed += 1
            print(f"FAIL {t.__name__}: {e!r}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
