#!/usr/bin/env python3
"""core/cookies.py — 从真实 Chrome profile 解密读出登录/风控 cookie。

Linux 下 Chrome 用系统 keyring（Gnome Keyring，经 secretstorage 取 "Chrome Safe
Storage" 密钥）加密 cookie；v11 前缀走该密钥，取不到则退回 v10 的固定密钥
'peanuts'。解密后按 host 后缀筛选，返回可直接喂给 Playwright add_cookies 的列表。
"""

import os
import sqlite3
import sys
from hashlib import pbkdf2_hmac
from pathlib import Path

SRC_PROFILE = str(Path.home() / ".config" / "google-chrome")


def _keyring_secret():
    try:
        import secretstorage
        conn = secretstorage.dbus_init()
        for coll in secretstorage.get_all_collections(conn):
            try:
                if coll.is_locked():
                    coll.unlock()
            except Exception:
                pass
            for item in coll.get_all_items():
                try:
                    if item.get_label() == "Chrome Safe Storage":
                        return item.get_secret()
                except Exception:
                    pass
    except Exception:
        pass
    return None


def _cookie_key():
    sec = _keyring_secret() or b"peanuts"
    if isinstance(sec, str):
        sec = sec.encode()
    return pbkdf2_hmac("sha1", sec, b"saltysalt", 1, 16)


def _dec(enc, key):
    from Crypto.Cipher import AES
    if enc[:3] in (b"v10", b"v11"):
        enc = enc[3:]
    d = AES.new(key, AES.MODE_CBC, b" " * 16).decrypt(enc)
    if d:
        d = d[:-d[-1]]  # 去 PKCS7 padding
    for cand in (d[32:], d):  # 新版 Chrome 明文前 32 字节是 sha256(domain)
        try:
            s = cand.decode("utf-8")
            if s.isprintable() or s == "":
                return s
        except Exception:
            pass
    return d[32:].decode("utf-8", "replace")


def load_cookies(src_profile, host_suffix, debug=False):
    """返回可直接 add_cookies 的列表：真实会话中 host 以 host_suffix 结尾的所有 cookie。"""
    db = str(Path(src_profile) / "Default" / "Cookies")
    if not os.path.exists(db):
        if debug:
            print(f"[debug] 找不到 Cookies DB: {db}", file=sys.stderr)
        return []
    key = _cookie_key()
    con = sqlite3.connect(f"file:{db}?mode=ro&immutable=1", uri=True)
    rows = con.execute(
        "select host_key,name,encrypted_value,path,is_secure,is_httponly "
        "from cookies where host_key like ?", (f"%{host_suffix}",)).fetchall()
    con.close()
    out = []
    for hk, name, enc, path, sec, hop in rows:
        if not hk.endswith(host_suffix):
            continue
        try:
            val = _dec(enc, key)
        except Exception:
            continue
        out.append({"name": name, "value": val, "domain": hk, "path": path or "/",
                    "secure": bool(sec), "httpOnly": bool(hop), "sameSite": "Lax"})
    return out
