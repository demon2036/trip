# legacy/

重构前 7 个脚本的原始快照（`ctrip_hotels.py`、`ctrip_flights.py`、
`ctrip_room_details.py`、`expedia_hotels.py`、`expedia_room_details.py`、
`compare_kobe_ana.py`、`weather_forecast.py`），一字未改。

只作为回滚/对照参考，**不再维护、不要在这里改代码**。当前实际使用的版本在项目
根目录（顶层薄 shim）+ `core/` / `ctrip/` / `expedia/` / `weather/` 包里，功能和这里
的原始版本等价，只是拆分了共享逻辑。如果怀疑重构引入了行为差异，可以拿这里的
版本跑同样的输入做对比。
