# tests/smoke/

合成样例测试：不连网络、不开浏览器、不需要 cookie，验证的是纯函数级的解析/编排
逻辑对不对。秒级跑完，改完 `ctrip/`、`expedia/`、`weather/` 里的逻辑后应该先跑这个。

- **`test_parsers.py`** — 携程/Expedia 各 `parse_*` 函数，喂构造好的 DOM 文本样例，
  断言解析出的字段。
- **`test_weather_logic.py`** — `weather/forecast.py` 的地点解析优先级
  （`--point` > 手动坐标 > `--city`）、三级 fallback 的选择逻辑，用
  `unittest.mock` 打桩掉 `open_meteo.py` 的网络请求函数。包含一个真实修复过的
  bug 的回归测试（东京时区"今天"和本机系统时区不一致导致的实时预报缺口）。

```bash
python3 tests/smoke/test_parsers.py
python3 tests/smoke/test_weather_logic.py
```

说明见上级目录 `tests/README.md`。
