# Trip Planning Tools

## Project Structure
- `cli/` — CLI entry points (thin shims calling into package modules)
- `core/` — Shared infrastructure (cookies, browser, dates)
- `ctrip/` — 携程 scraping (hotels, flights, room details)
- `expedia/` — Expedia scraping (hotels, room details)
- `food/` — Restaurant discovery (Google Maps + Tabelog)
- `weather/` — Weather forecasts (Open-Meteo API)

## CLI Tools
All browser-based tools must use headed mode (not headless):
- `cli/ctrip_flights.py` — 携程机票查询
- `cli/ctrip_hotels.py` — 携程酒店查询
- `cli/expedia_hotels.py` — Expedia 酒店查询
- `cli/weather_forecast.py` — 天气预报
- `cli/food_discovery.py` — 餐厅发现

## Planning Workflow Protocol

When executing a trip planning task (user says "开始规划" or similar):

### Part 1（景点筛选）
1. Read `prompts/globals.md` — global rules and trip parameters
2. Read `prompts/part1/stage1_discovery.md` — execute the task, output full result table, write to `output/plan/stage1_locked.md`
3. Read `prompts/part1/stage2_weather.md` — execute, output, write to `output/plan/stage2_locked.md`
4. Continue through stage3, stage4, stage5 in order

### Part 2（机票）
5. Read `prompts/globals.md` — global rules and trip parameters
6. Read `prompts/part2/stage6_flights.md` — execute, output, write to `output/plan/stage6_locked.md`

### Part 3（酒店）
7. Read `prompts/globals.md` — global rules and trip parameters
8. Read `prompts/part3/stage7_hotels.md` — execute, output, write to `output/plan/stage7_locked.md`

### Hard Rules
- 每次只读取一个 stage 文件
- 必须先完整输出当前 stage 的结果表格，再读取下一个 stage 文件
- 不许一次读取多个 stage 文件
- 不许跳过任何 stage 的输出
- 每个 stage 的锁定输出写入 `output/plan/stageN_locked.md`
- **全程自动执行，不许停下来问用户"是否继续""是否进入下一步"——做完当前 stage 立刻继续下一个**
