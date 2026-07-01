# expedia/

Expedia 站点的查询工具，依赖 `core/` 提供的 cookie 注入和沙箱浏览器。Expedia 的
风控（DataDome + Akamai）比携程更严格，所以这里的 cookie 注入几乎是硬性前提，
不是"锦上添花"（`--no-cookies` 选项只用来调试对比，正常使用一定会被拦）。

## 文件

- **`common.py`** — `host_suffix_from(base_url)`：把 `--base-url`（如
  `www.expedia.com.hk` / `www.expedia.co.jp`）映射成对应的 cookie 域名后缀，
  `hotels.py` 和 `room_details.py` 共用，避免同样的逻辑抄两遍。

- **`hotels.py`** — 按目的地英文/罗马字名搜酒店列表，支持切换地区站点（决定币种和
  cookie 域）；`parse_prices()` / `parse_review()` / `city_from_url()` 解析价格、
  评分、所在城市。对应顶层入口 `expedia_hotels.py`。

- **`room_details.py`** — 按 `hotel-id` + `hotel-slug` 查具体某家酒店的房型明细；
  `parse_room_block()` 解析房型名、面积（自动识别㎡/平方英尺）、床型、吸烟政策、
  早餐、价格。对应顶层入口 `expedia_room_details.py`。

## 调用方式

不建议直接跑这里的文件——用 `cli/` 下同名的入口脚本（如
`python3 cli/expedia_hotels.py --base-url www.expedia.com.hk --destination Kobe ...`），
参数和示例见根目录 `README.md`。
