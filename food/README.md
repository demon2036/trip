# food/

餐厅候选采集工具：围绕用户给定的**区域 + 日期 + 饭点**，把 Google Maps 的现实
可达性信号和 Tabelog 的日本本地口碑信号合在一起。

## 为什么同时用 Google Maps 和 Tabelog

- **Google Maps** 更适合判断"这家店现实中是否好找、评价量够不够、有没有电话/官网、
  当前列表是否显示营业、能否预约"。`--google-mode browser` 会像现有 Ctrip/Expedia
  harness 一样从你的真实 Chrome profile 注入 `google.com` cookie，不要求 API key。
  如果设置 `GOOGLE_MAPS_API_KEY`，`--google-mode api` 或 `auto` 会用官方 Places API
  拿更结构化的数据。headless 且无 API key 时，`auto` 会跳过 Google，避免完整地图页
  卡住整个采集。
- **Tabelog** 更适合日本旅行里的"本地口碑/预算/休息日/在线预约入口"。这里走低频
  公开页面解析，默认只取前 20 个，不做翻页，不做高频抓取。

## 文件

- **`discovery.py`** — 业务主体：Google Maps 浏览器 harness、可选 Places API、
  Tabelog 列表页解析、去重合并、CLI 输出。

## 调用方式

```bash
# 默认 auto：能用 Google 就合并 Google，否则至少返回 Tabelog，输出 JSON
python3 cli/food_discovery.py --area "Osaka Namba" --date 2026-08-01 --meal dinner

# 指定菜系和 Markdown 输出
python3 cli/food_discovery.py --area "Kobe Sannomiya" --date 2026-08-02 --meal dinner \
  --cuisine sushi yakiniku --format md

# 只用 Tabelog（适合先看本地榜单）
python3 cli/food_discovery.py --area "Osaka Namba" --date 2026-08-01 --meal dinner \
  --google-mode off --format md

# 使用 Google Places API（需要环境变量 GOOGLE_MAPS_API_KEY 或 --google-key）
python3 cli/food_discovery.py --area "Osaka Namba" --date 2026-08-01 --meal dinner \
  --google-mode api --format md

# 强制 Google Maps 浏览器 harness（适合有界面的本机 Chrome）
python3 cli/food_discovery.py --area "Osaka Namba" --date 2026-08-01 --meal dinner \
  --google-mode browser --format md
```

## 输出字段

核心字段包括：店名、Google/Tabelog 排名、Google 评分/评论数、Tabelog 评分/评论数、
晚餐/午餐预算、休息日、营业状态、营业置信度、预约方式、电话、官网、Google Maps
链接、Tabelog 链接。

`reservation_method` 的含义：

- `online`：页面/API 显示可在线预约或有预约入口。
- `phone`：找到电话，但没找到在线预约信号。
- `unknown`：未能判断。

`open_confidence` 的含义：

- `current_hours`：Google Places API 的当前/特殊营业时间。
- `regular_hours`：Google Places API 的常规营业时间。
- `maps_list_current`：Google Maps 列表页当前显示的营业/休息信号，不等于未来日期饭点。
- `unknown`：未能判断。

这个工具的原则是把置信度说清楚：宁愿输出 `unknown`，也不把"看起来可能营业"包装成
确定结论。
