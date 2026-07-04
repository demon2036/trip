# cli/

命令行入口，本项目实际"运行"的地方。项目根目录不放任何 `.py` 文件——所有可执行
脚本都在这里，真正的业务逻辑在 `core/` / `ctrip/` / `expedia/` / `weather/` /
`food/` 包里。

## 文件

- **`ctrip_hotels.py` / `ctrip_flights.py` / `ctrip_room_details.py`** — 携程工具的
  薄 shim，转发到 `ctrip/` 包对应模块的 `main()`。
- **`expedia_hotels.py` / `expedia_room_details.py`** — Expedia 工具的薄 shim，转发
  到 `expedia/` 包对应模块的 `main()`。
- **`weather_forecast.py`** — 天气预测工具的薄 shim，转发到 `weather/forecast.py`
  的 `main()`。
- **`food_discovery.py`** — 餐厅候选工具的薄 shim，转发到 `food/discovery.py`
  的 `main()`。
- **`compare_kobe_ana.py`** — 唯一一个不是 shim、有实际逻辑的脚本：并行调用同目录
  下的 `ctrip_hotels.py` / `expedia_hotels.py`（用子进程），对同一家酒店做多日
  比价。

## 为什么这些文件都只有几行

每个 shim 都只做两件事：把项目根目录塞进 `sys.path`（这样不管从哪个目录、用什么
方式调用，`import ctrip` / `import expedia` / `import weather` / `import food`
都能解析到），然后
`from 包.模块 import main` 再调用。这样命令行调用方式（文件名、参数）完全不变，
但实现细节都在对应的包里，不用在每个入口脚本里重复一遍 cookie/浏览器/日期这些
样板逻辑。

`compare_kobe_ana.py` 调用 `ctrip_hotels.py`/`expedia_hotels.py` 时，用的是基于
自己文件位置算出的绝对路径（`Path(__file__).resolve().parent / "ctrip_hotels.py"`），
不依赖调用者当前所在目录恰好是 `cli/`。

## 调用方式

始终从**项目根目录**调用，加 `cli/` 前缀，例如：

```bash
python3 cli/ctrip_hotels.py --dest 大阪 --checkin 2026-08-01 --checkout 2026-08-05 --format md
python3 cli/weather_forecast.py --point murodo --days 10 --format md
python3 cli/food_discovery.py --area "Osaka Namba" --date 2026-08-01 --meal dinner --format md
python3 cli/compare_kobe_ana.py
```

完整参数和每个工具的说明见根目录 `README.md`「功能一览 / 调用方式」。
