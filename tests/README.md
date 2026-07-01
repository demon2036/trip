# tests/

测试代码和产品代码分开放，冒烟测试和真实网络测试也分开放，互不干扰：

```
tests/
  smoke/   合成样例，纯函数级，不需要网络/浏览器/cookie，秒级跑完，随时可以跑
  real/    真实网络请求，其中 ctrip/expedia 那一个还需要真实 Chrome cookie，
           会真的开浏览器，跑一次几分钟，仅供手动按需验证
```

## smoke/ —— 冒烟测试

验证的是"给定一段构造出来的 DOM 文本/数据，解析逻辑对不对"，不连真实网络。

```bash
python3 tests/smoke/test_parsers.py        # ctrip/expedia 各 parse_* 函数
python3 tests/smoke/test_weather_logic.py  # weather 包的地点解析优先级、分级 fallback 选择逻辑（打桩掉网络请求）
```

改了 `ctrip/`、`expedia/`、`weather/` 里的解析/编排逻辑之后，先跑这两个，几秒钟出结果，
比每次都开真浏览器/真的连 Open-Meteo 快得多。

## real/ —— 真实测试

真的发请求，验证"这套逻辑接真实数据源到底能不能工作"，不是只测函数本身对不对。

```bash
# 只需要能上网，不需要 cookie/浏览器，几秒到几十秒跑完
python3 tests/real/test_weather_live.py

# 需要先完成根目录 README.md「前提条件」——本机真实 Chrome 已登录过携程/Expedia，
# 装了 patchright/pycryptodome/secretstorage。会真的开浏览器，五个工具跑下来几分钟
python3 tests/real/test_ctrip_expedia_live.py
```

`test_ctrip_expedia_live.py` 的每个工具结果分 `PASS`（拿到 >=1 条真实数据）/
`DEGRADED`（命令本身没崩，但这次抓到 0 条——网站改版/风控/临时缺货都可能导致，
属于已知的正常兜底行为）/`FAIL`（崩溃、超时或输出不是合法 JSON）。只有 `FAIL`
才会让脚本以非零退出码结束。

如果想验证最重的并行集成路径（14 个真实浏览器会话），直接跑
`python3 cli/compare_kobe_ana.py`——这个不属于"测试脚本"，是产品脚本本身，不重复
收进 `tests/` 里。

## 什么时候该加测试

- 改了某个 `parse_*` 纯函数：在 `smoke/` 里加/改断言，不需要动 `real/`。
- 改了 `weather/forecast.py` 里地点解析/分级 fallback 这类编排逻辑：优先用
  `unittest.mock` 打桩网络调用，在 `smoke/` 里补分支覆盖（参考
  `test_weather_logic.py` 里对"实时预报缺口该不该退到历史均值"这个真实修复过的
  bug 写的回归测试）。
- 怀疑是数据源本身返回的真实数据变了（网站改版、字段变了）：去 `real/` 底下跑对应
  脚本实测，不要只看 `smoke/` 是不是绿的——合成样例测试测不出这类问题。
