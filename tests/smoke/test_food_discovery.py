#!/usr/bin/env python3
"""food/ 餐厅 harness 的纯函数冒烟测试：不连 Google/Tabelog，不开浏览器。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from food.discovery import merge_places, parse_google_maps_card, parse_tabelog_list


def test_parse_google_maps_card():
    raw = {
        "href": "https://www.google.com/maps/place/Sushi+Foo/",
        "text": "Sushi Foo\n4.5 (1,234)\nSushi restaurant\nOpen ⋅ Closes 10 PM\n+81 6-1234-5678",
    }
    r = parse_google_maps_card(raw, 2)
    assert r["name"] == "Sushi Foo"
    assert r["rank_google"] == 2
    assert r["google_rating"] == 4.5
    assert r["google_reviews"] == 1234
    assert r["open_for_slot"] is True
    assert r["reservation_method"] == "phone"


def test_parse_tabelog_list():
    html = """
    <div class="list-rst js-bookmark" data-detail-url="https://tabelog.com/en/osaka/foo/" data-rst-id="1">
      <a class="list-rst__rst-name-target cpy-rst-name" href="https://tabelog.com/en/osaka/foo/">Sushi Foo</a>
      <div class="list-rst__area-genre cpy-area-genre">Namba / Sushi</div>
      <span class="c-rating__val c-rating__val--strong list-rst__rating-val">3.72</span>
      <em class="list-rst__rvw-count-num cpy-review-count">456</em>
      <span class="c-rating-v3__val">JPY 8,000 - JPY 9,999</span>
      <span class="c-rating-v3__val">JPY 1,000 - JPY 1,999</span>
      <span class="list-rst__holiday-text">Monday</span>
      <div class="js-rstlist-calendar-wrap list-rst__calendar"></div>
    </div>
    """
    rows = parse_tabelog_list(html)
    assert len(rows) == 1
    r = rows[0]
    assert r["name"] == "Sushi Foo"
    assert r["tabelog_rating"] == 3.72
    assert r["tabelog_reviews"] == 456
    assert r["budget_dinner"] == "JPY 8,000 - JPY 9,999"
    assert r["regular_holiday"] == "Monday"
    assert r["reservation_method"] == "online"


def test_merge_places_combines_sources():
    google = [{
        "name": "Sushi Foo",
        "match_key": "sushifoo",
        "rank_google": 1,
        "google_rating": 4.6,
        "sources": ["google_maps"],
    }]
    tabelog = [{
        "name": "Sushi Foo",
        "match_key": "sushifoo",
        "rank_tabelog": 3,
        "tabelog_rating": 3.7,
        "sources": ["tabelog"],
    }]
    rows = merge_places(google, tabelog)
    assert len(rows) == 1
    assert rows[0]["google_rating"] == 4.6
    assert rows[0]["tabelog_rating"] == 3.7
    assert rows[0]["sources"] == ["google_maps", "tabelog"]


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

