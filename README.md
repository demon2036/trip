# Trip Pricing Harness

个人旅行比价用的自动化工具集。核心思路不是"写一个更强的爬虫"，而是一个 **harness（驾驭/复用真实会话的框架）**：把你日常真实 Chrome 里已经过检、已登录的会话原样接管过来，驱动一个独立的沙箱浏览器去问携程、Expedia 要价格，而不是从零冒充一个"看起来像人"的机器人。

它不是一个通用爬虫框架，而是**为携程 (Ctrip)、Expedia、Google Maps、Tabelog 等目标站点量身定制**的一组脚本，能查酒店、机票、具体房型、餐厅候选，外加一个天气预测工具和一个示例比价脚本。

---

## 这是什么、为什么需要 harness

Ctrip 和 Expedia 都有相当强的风控/反爬：Expedia 用 DataDome + Akamai，任何"冷启动"的自动化浏览器几乎必被拦成滑块验证；携程对高频/无登录态的访问也会弹验证码。正面硬刚这些反爬（换指纹、用代理池、模拟鼠标轨迹……）性价比很低，而且很容易把自己的真实账号也搭进去。

这套工具用的是另一条路：

1. 你自己平时用真实 Chrome 逛过 ctrip.com / expedia.com(.hk)，早就积累了一套"过检"的会话 cookie（携程的 `cticket`、Expedia 的 `datadome` 等）。
2. 工具从你的 Chrome 用户数据目录里，用系统 keyring 解密出这些 cookie（Linux 下走 Gnome Keyring）。
3. 用 [patchright](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright)（Playwright 的反检测版）+ **系统里同一份真实 Google Chrome**（`channel="chrome"`），起一个全新的、独立 profile 的沙箱浏览器。
4. 把解密出的 cookie 注入这个沙箱浏览器——同一台机器、同一个出口 IP、同一个 Chrome 版本/UA，站点看到的是"一个已经验证过的真实用户"，直接放行。

不会挂载、接管或读写你正在用的那个 Chrome；沙箱浏览器用的是完全独立的 profile 目录，你自己的浏览器该干嘛干嘛。

**代价 / 已知限制**：
- 只在 **Linux + Gnome Keyring** 下验证过（cookie 解密走 `secretstorage`）；macOS/Windows 的 Chrome 加密方案不同，`core/cookies.py` 需要相应适配才能用。
- 依赖你机器上装的是**正式版 Google Chrome**（不是 Chromium），且和沙箱浏览器共享同一个 Chrome 可执行文件。
- 所有解析都是"读页面 DOM 文本 + 正则"，站点改版会随时改坏（这是取舍：换来的是不用维护一堆指纹/代理，坏了直接肉眼看一下 `--debug` 输出改几个正则即可）。

---

## 前提条件（首次使用前必须做的事）

1. **本机装好正式版 Google Chrome**，且是你平时登录/上网用的那个 profile（默认 `~/.config/google-chrome`）。
2. **在这个真实 Chrome 里，手动打开并登录/浏览过一次目标站点**，把人机验证过掉：
   - 携程：打开 <https://hotels.ctrip.com/> 或 <https://flights.ctrip.com/>，正常登录你的携程账号，随手搜一次酒店/机票（确保 `cticket` 等 cookie 已生成）。
   - Expedia：打开 <https://www.expedia.com.hk/>（或你要用的地区站，如 `www.expedia.co.jp`），登录账号，搜一次酒店，把 DataDome 的滑块/验证过掉。
   - 这一步**只需要做一次**（或者 cookie 过期后再做一次），工具不会帮你登录、也不会帮你过验证码——它只是"借用"你已经过检的会话。
3. **Python 依赖**：
   ```bash
   pip install patchright pycryptodome secretstorage
   ```
4. 跑之前建议用 `cd` 进到本项目目录（README 里的命令都假设当前目录就是这里），因为脚本之间用的是相对导入和相对路径。

### Cookie 过期 / 突然被拦截了怎么办

工具会打印类似"⚠️ 被携程风控拦截"或"⚠️ 被 DataDome 拦截"的提示。处理方法固定就一条：**回到你真实的 Chrome，手动打开一次对应网站，正常操作过一下验证**，然后重新跑工具——不需要改任何代码或参数。

---

## 目录结构

每个代码目录下都有自己的 `README.md`，说明这个目录具体提供什么能力、文件都是干
什么的——这里只给整体地图，细节看对应目录里的 README。

```
core/                共享基础设施，不直接跑，供下面的工具 import（core/README.md）
  cookies.py           从真实 Chrome profile 解密读 cookie
  browser.py           沙箱 Chrome 启动/收尾（sandboxed_page）、goto_retry、work_profile_dir
  dates.py             入住/退房日期解析

ctrip/               携程站点工具（ctrip/README.md）
  hotels.py            酒店搜索
  flights.py           机票搜索
  room_details.py      指定酒店的具体房型/价格明细

expedia/             Expedia 站点工具（expedia/README.md）
  common.py            host_suffix_from（多地区站点 → cookie 域名映射）
  hotels.py            酒店搜索
  room_details.py      指定酒店的具体房型/价格明细

weather/             天气预测：城市 + 山地/具体地点，不需要 cookie/浏览器（weather/README.md）
  locations.py         城市 + 山地/具体地点坐标库（含海拔）
  open_meteo.py        Open-Meteo 三级 fallback 请求逻辑
  forecast.py          编排 + CLI 入口

food/                餐厅候选：Google Maps 现实信号 + Tabelog 本地口碑（food/README.md）
  discovery.py         Google Maps 浏览器 harness/可选 Places API + Tabelog 解析 + 合并输出

cli/                 命令行入口，本项目实际"运行"的地方（cli/README.md）
  ctrip_hotels.py / ctrip_flights.py / ctrip_room_details.py
  expedia_hotels.py / expedia_room_details.py / weather_forecast.py / food_discovery.py
                       顶层 CLI 入口（几行代码，直接调用上面对应的包），
                       保留这些文件名只是为了命令行调用方式不变——不是遗留代码，
                       删掉会导致下面所有调用示例失效
  compare_kobe_ana.py  示例：并行调用携程+Expedia，对同一家酒店做多日比价

legacy/              重构前的原始脚本快照，仅作参考/回滚用，不再维护（legacy/README.md）
tests/               冒烟测试（不连网络）+ 真实测试（真连网络/真开浏览器），互不混放（tests/README.md）
output/              运行时产生的截图等资产，已 gitignore，不会传到仓库
```

---

## 功能一览 / 调用方式

以下命令都在项目根目录下执行，脚本都在 `cli/` 下面。所有脚本支持 `--format md`（人类可读表格）或 `--format json`（默认，机器可读）。

### 1. 携程酒店搜索 `cli/ctrip_hotels.py`

```bash
# 按目的地名联想（会自动解析 cityId）
python3 cli/ctrip_hotels.py --dest 大阪 --checkin 2026-08-01 --checkout 2026-08-05 --format md

# 已知 cityId，跳过联想解析（更快更稳，神户=423）
python3 cli/ctrip_hotels.py --city-id 423 --checkin 2026-07-10 --nights 7 --format md
```
常用参数：`--dest` 目的地名 / `--city-id` 携程数字城市 ID / `--checkin` `--checkout`/`--nights` / `--adults` `--rooms` / `--curr`（默认 CNY）/ `--limit` / `--debug` / `--screenshot PATH`。

### 2. 携程机票搜索 `cli/ctrip_flights.py`

```bash
# 单程（三字码：香港=hkg 大阪=osa 东京=tyo 上海=sha 北京=bjs 首尔=sel，也支持机场码如 kix/nrt）
python3 cli/ctrip_flights.py --from hkg --to osa --date 2026-07-10 --format md

# 往返
python3 cli/ctrip_flights.py --from hkg --to osa --date 2026-07-10 --return 2026-07-17 --format md

# 默认只看直飞；如需中转可加 --all-flights
python3 cli/ctrip_flights.py --from can --to ngo --date 2026-12-16 --return 2026-12-22 --format md

# 批量查询：同一个浏览器会话里顺序跑多条，不重复起关 Chrome
python3 cli/ctrip_flights.py \
  --query can-nrt,2026-12-16,2026-12-22 \
  --query can-ngo,2026-12-16,2026-12-22 \
  --format md

# 也可以用逗号批量展开目的地/日期
python3 cli/ctrip_flights.py --from can --to nrt,ngo,kix --date 2026-12-16 --return 2026-12-22 --format md
```
城市码无结果时会自动 fallback 到机场码，例如 `tyo` 会继续查 `nrt` / `hnd`；如需严格只查输入的三字码，加 `--no-city-fallback`。
默认只返回 `直飞` 航班；如需把中转也带上，加 `--all-flights`。

### 3. 携程酒店房型明细 `cli/ctrip_room_details.py`

```bash
python3 cli/ctrip_room_details.py --hotel-id 2107678 --checkin 2026-07-10 --nights 1 --format md
```
`--hotel-id` 是携程酒店详情页 URL 里的 `hotelId`。

### 4. Expedia 酒店搜索 `cli/expedia_hotels.py`

```bash
# 默认香港站（HKD）
python3 cli/expedia_hotels.py --base-url www.expedia.com.hk --destination Kobe --checkin 2026-07-10 --nights 1 --format md

# 切换日本站
python3 cli/expedia_hotels.py --base-url www.expedia.co.jp --destination Kobe --checkin 2026-07-10 --nights 1 --format md
```
常用参数：`--destination`（英文/罗马字目的地名）/ `--city` 按城市名过滤结果 / `--base-url` 站点（决定币种和 cookie 域）/ `--sort` / `--no-cookies`（调试用，会被拦，别正常用）。

### 5. Expedia 酒店房型明细 `cli/expedia_room_details.py`

```bash
python3 cli/expedia_room_details.py --hotel-id 1209540 --hotel-slug KOBE-Hotels-ANA-Crowne-Plaza-Kobe --checkin 2026-07-10 --nights 1 --format md
```
`--hotel-id` 和 `--hotel-slug` 都能从 Expedia 酒店详情页 URL（`xxx.h<hotel-id>.Hotel-Information`）里拿到。

### 6. 天气预测 `cli/weather_forecast.py`

不需要 cookie、不需要浏览器，纯调 Open-Meteo 公开 API。分三级：JMA 精细预报（日本
气象厅自有模式，约覆盖 11 天）→ 多模型综合预报（补到 16 天）→ 最近 3 整年同期历史
均值兜底（16 天外）。除了城市，还支持山地/具体地点——用显式海拔做数值降尺度修正，
不会把立山室堂（2450m）之类的地点当成附近城市/山脚来预报。

```bash
# 城市
python3 cli/weather_forecast.py --city kobe --start-date 2026-07-01 --days 14 --format md

# 山地/具体地点：立山黑部室堂、美女平，户隐神社……
python3 cli/weather_forecast.py --point murodo --days 10 --format md
python3 cli/weather_forecast.py --point togakushi --days 10 --format md
python3 cli/weather_forecast.py --list-points   # 列出所有内置地点

# 任意坐标 + 手动海拔（不在内置列表里的地点）
python3 cli/weather_forecast.py --latitude 36.57 --longitude 137.57 --elevation 977 --days 10
```
内置城市：`kobe tokyo osaka kyoto nagoya sapporo fukuoka okinawa`；内置山地/具体
地点：`murodo yuki-no-otani bijodaira midagahara togakushi`。为什么这样分级、
为什么没有接入 tenki.jp 之类的日本消费级天气站爬虫、山地点位坐标是怎么核实的，
详见 `weather/README.md`。

### 7. 餐厅候选 `cli/food_discovery.py`

围绕给定的**区域 + 日期 + 饭点**，收集 Google Maps top results 和 Tabelog 前 20 个候选，
合并输出评分、评论数、预算、休息日、预约方式、电话/链接、营业状态和置信度。`auto`
模式下：有 `GOOGLE_MAPS_API_KEY` 时走 Places API；没有 key 且不是 headless 时尝试
Google Maps 浏览器 harness；headless 无 key 时跳过 Google、直接返回 Tabelog 稳定结果。

```bash
# 自动模式：能用 Google 就合并 Google，否则至少返回 Tabelog
python3 cli/food_discovery.py --area "Osaka Namba" --date 2026-08-01 --meal dinner --format md

# 指定菜系
python3 cli/food_discovery.py --area "Kobe Sannomiya" --date 2026-08-02 --meal dinner \
  --cuisine sushi yakiniku --format md

# 只看 Tabelog 本地榜单
python3 cli/food_discovery.py --area "Osaka Namba" --date 2026-08-01 --meal dinner \
  --google-mode off --format md

# 强制 Google Maps 浏览器 harness（适合有界面的本机 Chrome，会注入 google.com cookie）
python3 cli/food_discovery.py --area "Osaka Namba" --date 2026-08-01 --meal dinner \
  --google-mode browser --format md
```

详见 `food/README.md`。注意：Google Maps 浏览器列表页的营业信号主要是"当前显示"，
不是未来某天饭点的确定营业；输出会用 `open_confidence` 标明置信度。

### 8. 示例比价脚本 `cli/compare_kobe_ana.py`

并行调用携程 + Expedia HK，对**神户全日空皇冠假日酒店（ANA Crowne Plaza Kobe）**未来 7 天的价格做比价，自动按当前汇率换算、给出哪家便宜：

```bash
python3 cli/compare_kobe_ana.py
```
这个脚本里的酒店名、日期范围是写死的示例，想比别的酒店/日期需要改 `run_ctrip`/`run_expedia` 里的匹配条件和 `main()` 里的日期范围——它更像一个"如何组合前面几个工具做批量比价"的参考模板，而不是通用参数化工具。

---

## 使用须知

- 仅供个人旅行比价研究使用，不要高频/大批量调用，注意目标网站的服务条款。
- 所有价格数据来自页面实时抓取解析，不保证准确、不构成购买建议，下单前请以官网实际结算价为准。
- 不要把你的 `output/` 目录（截图）或任何真实 cookie/凭证提交到公开仓库——截图里通常能看到你的登录账号信息。
