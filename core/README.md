# core/

携程和 Expedia 工具共用的基础设施。这一层不含任何"业务"逻辑（不知道什么是酒店、
机票），只解决三个和具体网站无关的通用问题：怎么拿到能过风控的会话、怎么起一个
干净的沙箱浏览器、怎么算入住/退房日期。`ctrip/` 和 `expedia/` 都依赖这一层，反过来
不成立——这里不 import 任何 `ctrip.*` / `expedia.*`。

## 文件

- **`cookies.py`** — 从你真实的 Chrome 用户数据目录（默认 `~/.config/google-chrome`）
  解密读取指定域名的 cookie。Linux 下走 Gnome Keyring（`secretstorage`）拿到 Chrome
  用来加密 cookie 的密钥，再用 `pycryptodome` 做 AES-CBC 解密。这是整个 harness
  能绕开 DataDome/携程风控的根本原因：拿到的是你自己浏览器里已经过检的真实 cookie。

- **`browser.py`** — `sandboxed_page(profile_dir, cookies, headless)`：一个
  contextmanager，负责启动一个独立 profile 的沙箱 Chrome（用 `patchright` + 系统里
  同一份正式版 Google Chrome，`channel="chrome"`）、注入 cookie、`yield page`，退出
  `with` 块时自动关闭 context。调用方不需要关心浏览器生命周期或者 Singleton 锁文件
  这些细节。另外提供 `goto_retry()`（跳转遇到瞬时网络错误自动重试）和
  `work_profile_dir(tag)`（生成本工具专用的 profile 路径，不会碰到你日常用的那个
  Chrome profile）。

- **`dates.py`** — `compute_dates(checkin, checkout, nights)`：三选二算出完整的
  入住/退房日期，各个查询脚本的 `--checkin/--checkout/--nights` 参数都靠它统一解析。

## 使用方式

这里的模块不直接跑，只被 `ctrip/`、`expedia/` 的模块以及顶层 CLI 脚本 import。
