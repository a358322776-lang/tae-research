"""围栏检查：验证前向观察系统未触碰任何禁区。

静态检查（对 observer.py / dryrun_compare.py）：
1. 网络目标：全部 URL 必须只含镜像域名 www.binance.com/fapi/v1/klines。
2. 禁用令牌：交易接口路径、密钥文件、消息渠道、扫描器/执行器/VPS
   地址、API 密钥字样一律不得出现。
3. 写路径：全部写操作目标必须落在 forward-observer/ 内；除两条
   只读 import 用 sys.path 外，不得出现其它 /home/hatch 绝对路径。
4. import 白名单：只允许标准库、numpy、b1_lib、key_levels。
动态检查（运行时证据）：
5. 最近 15 分钟内 ~/workspace/goals/100u-200u 下被修改的文件必须
   全部位于 forward-observer/ 内；B1 哨兵文件（candidates.jsonl、
   stitched 缓存、扫描器）mtime 不得落在最近 1 小时内。
任一项 FAIL 即整体 FAIL。只读检查本身，不写 B1、不改生产代码。
"""

import os
import re
import subprocess
import sys
import time

FO = "/home/hatch/workspace/goals/100u-200u/files/tae-b1/forward-observer"
GOALS = "/home/hatch/workspace/goals/100u-200u"
BANNED_TOKENS = [
    "fapi/v1/order", "algoOrder", "fapi/v1/account", "fapi/v1/position",
    "fapi/v1/leverage", "listenKey", ".env", "whatsapp", "WhatsApp",
    "tae-scanner", "tae-executor", "tw-ssh", "104.192.82.6",
    "api_key", "API_KEY", "apikey", "SECRET_KEY",
]
ALLOWED_IMPORT_ROOTS = ("csv", "json", "os", "sys", "urllib", "datetime",
                        "collections", "numpy", "np", "b1_lib", "key_levels")


def strip_docs_comments(src):
    """去掉三引号 docstring 与 # 行注释，得到可执行代码部分。
    围栏针对的是实际执行行为；在 fence 说明文字里提到“.env /
    WhatsApp”不等于读取或发送——这类出现单独列为 INFO，不算 FAIL。"""
    src = re.sub(r'"""[\s\S]*?"""', '""', src)
    src = re.sub(r"'''[\s\S]*?'''", "''", src)
    lines = []
    for ln in src.splitlines():
        if "#" in ln:
            ln = ln.split("#", 1)[0]
        lines.append(ln)
    return "\n".join(lines)


def check_file(path):
    fails = []
    infos = []
    with open(path, encoding="utf-8") as fh:
        raw = fh.read()
    src = strip_docs_comments(raw)
    for tok in BANNED_TOKENS:
        if tok in src:
            fails.append(f"banned token in executable code: {tok}")
        elif tok in raw:
            infos.append(f"token only in docstring/comment (INFO): {tok}")
    for m in re.finditer(r"https?://[^\s\"']+", src):
        url = m.group(0)
        if "www.binance.com/fapi/v1/klines" not in url:
            fails.append(f"non-mirror URL: {url}")
    for m in re.finditer(r"^(?:from|import)\s+([a-zA-Z0-9_\.]+)", src, re.M):
        root = m.group(1).split(".")[0]
        if root not in ALLOWED_IMPORT_ROOTS:
            fails.append(f"import outside whitelist: {m.group(1)}")
    for m in re.finditer(r"/home/hatch/[^\s\"']+", src):
        p = m.group(0).rstrip(".,);:]")
        if p.startswith(FO):
            continue
        if p in ("/home/hatch/workspace/goals/100u-200u/files/tae-b1",
                 "/home/hatch/workspace/goals/100u-200u/hidden_files"):
            continue  # 两条只读 import 用 sys.path
        fails.append(f"absolute path outside forward-observer: {p}")
    return fails, infos


def snapshot_mtimes(roots):
    snap = {}
    for base in roots:
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for fn in files:
                p = os.path.join(root, fn)
                try:
                    snap[p] = (os.path.getmtime(p), os.path.getsize(p))
                except OSError:
                    pass
    return snap


def main():
    all_fails = []
    for name in ("observer.py", "dryrun_compare.py"):
        fails, infos = check_file(os.path.join(FO, name))
        print(f"static {name}: {'PASS' if not fails else 'FAIL'}")
        for f in fails:
            print(f"  - {f}")
        for f in infos:
            print(f"  - {f}")
        all_fails += fails
    # 动态：精确归因——在一次 observer 实际运行前后对交易相关树
    # （tae-b1 除 forward-observer 外、hidden_files）做 mtime 快照
    # 对比；只有在该运行窗口内发生变化的外部文件才算违规。
    # （此前“最近 15 分钟”启发式会把独立 cron 如 live-close-seen.json
    # 的写入误算到观察系统头上，已废弃。）
    watch_roots = [
        "/home/hatch/workspace/goals/100u-200u/files/tae-b1",
        "/home/hatch/workspace/goals/100u-200u/hidden_files",
    ]
    before = snapshot_mtimes(watch_roots)
    subprocess.run([sys.executable, os.path.join(FO, "observer.py"), "--run"],
                   capture_output=True, text=True, timeout=600)
    after = snapshot_mtimes(watch_roots)
    changed_outside = []
    for p, (mt, sz) in after.items():
        if p.startswith(FO):
            continue
        if p not in before or before[p] != (mt, sz):
            changed_outside.append(p)
    for p in before:
        if p not in after and not p.startswith(FO):
            changed_outside.append(p + " (deleted)")
    print(f"dynamic changed-outside-during-run: {len(changed_outside)}")
    for p in changed_outside:
        print(f"  - {p}")
    if changed_outside:
        all_fails.append(f"{len(changed_outside)} files changed outside "
                         "forward-observer during observer run")
    now = time.time()
    sentinels = [
        "/home/hatch/workspace/goals/100u-200u/files/tae-b1/data_cache/candidates.jsonl",
        "/home/hatch/workspace/goals/100u-200u/files/tae-b1/data_cache/stitched_15m.npz",
        "/home/hatch/workspace/goals/100u-200u/hidden_files/tae-scanner.py",
        "/home/hatch/workspace/goals/100u-200u/hidden_files/tae-scanner-tradfi.py",
    ]
    for s in sentinels:
        if os.path.exists(s):
            age = now - os.path.getmtime(s)
            ok = age > 3600
            print(f"sentinel {os.path.basename(s)}: age={age/3600:.1f}h "
                  f"{'PASS' if ok else 'FAIL'}")
            if not ok:
                all_fails.append(f"sentinel modified recently: {s}")
    print("VERDICT:", "PASS" if not all_fails else "FAIL")
    return 0 if not all_fails else 1


if __name__ == "__main__":
    sys.exit(main())
