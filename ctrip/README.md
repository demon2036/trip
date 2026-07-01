# ctrip/

携程（Ctrip）站点的查询工具，依赖 `core/` 提供的 cookie 注入和沙箱浏览器，不重复
造轮子。每个模块都是"可以单独 `python3 -m` 跑，也可以被顶层同名 shim 脚本调用"的
CLI 入口，同时导出 `parse_*` 纯函数供测试直接调用（不需要真的开浏览器）。

## 文件

- **`hotels.py`** — 按目的地名（自动联想 `cityId`）或已知 `cityId` 搜酒店列表；
  `parse_card()` 从酒店卡片 DOM 文本里解析出名称、星级、评分、每晚价/含税总价。
  对应顶层入口 `ctrip_hotels.py`。

- **`flights.py`** — 按出发/到达三字码+日期查机票（支持往返）；`parse_flight()`
  解析航司、航班号、机型、起降时间、经停、票价。对应顶层入口 `ctrip_flights.py`。

- **`room_details.py`** — 按 `hotelId` 查具体某家酒店的房型明细和价格；
  `parse_room_block()` 解析房型名、面积、床型、吸烟政策、早餐、价格。对应顶层入口
  `ctrip_room_details.py`。

## 调用方式

不建议直接跑这里的文件——用 `cli/` 下同名的入口脚本（如
`python3 cli/ctrip_hotels.py --dest 大阪 ...`），参数和示例见根目录 `README.md`。
