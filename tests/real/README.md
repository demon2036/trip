# tests/real/

真实网络测试：验证的是"接真实数据源到底能不能工作"，不是构造样例。

- **`test_weather_live.py`** — 真的打 Open-Meteo 请求，不需要 cookie/浏览器，只需要
  能上网。几秒到几十秒跑完。验证城市/山地预报能拿到实时数据、30 天视野里三级
  fallback 都会出现、山地点位气温明显低于城市、显式传海拔确实会改变结果（不是
  摆设）。

- **`test_ctrip_expedia_live.py`** — 对携程/Expedia 五个 CLI 工具各发一次真实请求，
  真开浏览器、真注入 cookie。前提条件见根目录 `README.md`「前提条件」一节（本机
  真实 Chrome 需要已经登录过携程和 Expedia、装好 `patchright`/`pycryptodome`/
  `secretstorage`）。跑一次几分钟。每个工具的结果是 `PASS`/`DEGRADED`/`FAIL`
  三选一，`DEGRADED`（命令没崩但 0 条结果）算已知的正常兜底行为，只有 `FAIL`
  才会让脚本以非零退出码结束。

```bash
python3 tests/real/test_weather_live.py
python3 tests/real/test_ctrip_expedia_live.py
```

说明见上级目录 `tests/README.md`。
