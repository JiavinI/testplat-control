"""Phase 3.3a/3.3b/3.3c 泄密全文搜索（手册 §7-3）：把各公开面/落盘面对假秘密的命中次数写入证据文件。

搜索面：Control/Engine 后端日志（同一进程，DEBUG 级）、target 与前端 dev server 日志、
SQLite 文件原始字节（含 -wal/-journal）与逐表逐行的单元格、截图目录下的矩阵/浏览器报告 JSON、
逐张截图的 DOM 搜索证据、``docs/`` 与 README。
另外列出仓库已跟踪文件中**按设计**含假秘密的位置（测试常量、矩阵脚本），这些不计入失败。

Phase 3.3c：读取 ``LEAK_ISSUED_SECRETS_PATH``（目标服务签发的 token/session/uuid/验证码），
并入搜索目标；证据只记动态目标数量，不记秘密原文；动态目标为 0 时失败。

证据只记录路径与命中次数，从不记录命中的上下文。
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

STATIC_SECRETS = (
    "tp-fake-secret-9f31c2a7",
    "tp-fake-partner-4c8e11d0",
    "tp-fake-aws-7d2e9b10",
    # Phase 3.3b 登录秘密
    "tp-fake-buyer-pass-71c2",
    "tp-fake-seller-pass-93ab",
    "tp-fake-redis-pass-5e0d",
    "tp-fake-plugin-key-11aa",
    "plug-token-5f5f5f5f5f",
    "csrf-ff00ee11dd22",
    "seed-0a0b0c0d0e",
    "detail-0123456789abcdefghij",
    # Phase 3.3c
    "tp-fake-df-admin-pass-9f3a",
)
ROOT = Path(__file__).resolve().parents[1]


def _load_dynamic_secrets(path: Path | None) -> tuple[str, ...]:
    if path is None or not path.is_file():
        return ()
    values: list[str] = []
    seen: set[str] = set()
    for line in path.read_text("utf-8").splitlines():
        item = line.strip()
        if not item or item in seen:
            continue
        seen.add(item)
        values.append(item)
    return tuple(values)


def count_bytes(data: bytes, secrets: tuple[str, ...]) -> int:
    """长秘密（≥8）按子串计数。

    短验证码（<8）只匹配 JSON/文本里的引号包裹形式，避免 SQLite 二进制里的
    整数行号、端口、时间戳造成误报；若验证码以字符串字段落盘，仍能命中。
    """
    import re

    total = 0
    decoded: str | None = None
    for secret in secrets:
        raw = secret.encode("utf-8")
        if len(raw) >= 8:
            total += data.count(raw)
            continue
        if decoded is None:
            decoded = data.decode("utf-8", errors="replace")
        pattern = "['\"]" + re.escape(secret) + "['\"]"
        total += len(re.findall(pattern, decoded))
    return total


def classify_secret(secret: str) -> str:
    if secret in STATIC_SECRETS:
        return "static"
    if secret.startswith("tok-"):
        return "token"
    if secret.startswith("sess-"):
        return "session"
    if len(secret) == 36 and secret.count("-") == 4:
        return "uuid"
    if secret.isdigit() and len(secret) <= 6:
        return "captcha"
    return "other"


def count_bytes_by_kind(data: bytes, secrets: tuple[str, ...]) -> dict[str, int]:
    """按秘密类别汇总命中次数（不暴露秘密原文）。"""
    out: dict[str, int] = {}
    # 逐个计数以归类
    for secret in secrets:
        n = count_bytes(data, (secret,))
        if n:
            kind = classify_secret(secret)
            out[kind] = out.get(kind, 0) + n
    return out


def count_file(path: Path, secrets: tuple[str, ...]) -> int:
    return count_bytes(path.read_bytes(), secrets)


def sqlite_rows(db: Path, secrets: tuple[str, ...]) -> dict[str, int]:
    """逐表逐行把每个单元格转成字符串后搜索（原始行，不经 API 反序列化）。"""
    out: dict[str, int] = {}
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        for table in tables:
            hits = rows = 0
            for row in conn.execute(f'SELECT * FROM "{table}"'):  # noqa: S608
                rows += 1
                for cell in row:
                    if cell is None:
                        continue
                    raw = cell if isinstance(cell, bytes) else str(cell).encode("utf-8")
                    hits += count_bytes(raw, secrets)
            out[table] = hits
            out[f"{table}__rows"] = rows
    finally:
        conn.close()
    return out


def main() -> int:
    out_dir = Path(os.environ["LEAK_OUT_DIR"])
    db = Path(os.environ["LEAK_DB_PATH"])
    log_dir = Path(os.environ.get("LEAK_LOG_DIR", out_dir))
    issued_path_raw = os.environ.get("LEAK_ISSUED_SECRETS_PATH", "").strip()
    issued_path = Path(issued_path_raw) if issued_path_raw else None
    dynamic = _load_dynamic_secrets(issued_path)
    if not dynamic:
        print("LEAK SEARCH dynamic targets empty (issued-secrets missing or blank)")
        return 1
    secrets = STATIC_SECRETS + dynamic
    # 阳性对照：确认搜索本身能命中（临时文件写入后立即删除，不留在任何证据目录）
    with tempfile.NamedTemporaryFile("wb", delete=False) as tmp:
        lines = [s if len(s.encode("utf-8")) >= 8 else f'"{s}"' for s in secrets]
        tmp.write("\n".join(lines).encode("utf-8"))
    control_hits = count_file(Path(tmp.name), secrets)
    Path(tmp.name).unlink()
    if control_hits < len(secrets):
        print("LEAK SEARCH positive control failed")
        return 1
    evidence: dict[str, object] = {
        "search_targets": len(STATIC_SECRETS),
        "dynamic_search_targets": len(dynamic),
        "positive_control_hits": control_hits,
        "sources": [],
    }
    failures = 0

    def add(kind: str, path: Path, hits: int, **extra: object) -> None:
        nonlocal failures
        failures += hits
        try:
            shown = str(path.relative_to(ROOT))
        except ValueError:
            shown = str(path)  # 临时目录（SQLite）保留绝对路径，运行结束即删除
        evidence["sources"].append(  # type: ignore[union-attr]
            {"kind": kind, "path": shown, "hits": hits, **extra}
        )

    for log in sorted(log_dir.glob("*.log")):
        raw = log.read_bytes()
        add(
            "log",
            log,
            count_bytes(raw, secrets),
            bytes=log.stat().st_size,
            hit_kinds=count_bytes_by_kind(raw, secrets),
        )
    # 3.3c 截图目录日志也纳入（若与 LEAK_LOG_DIR 不同）
    extra_log_dir = os.environ.get("LEAK_EXTRA_LOG_DIR", "").strip()
    if extra_log_dir:
        extra = Path(extra_log_dir)
        if extra.is_dir() and extra.resolve() != log_dir.resolve():
            for log in sorted(extra.glob("*.log")):
                add("log", log, count_file(log, secrets), bytes=log.stat().st_size)
    for suffix in ("", "-wal", "-journal", "-shm"):
        candidate = Path(f"{db}{suffix}")
        if candidate.exists():
            kinds = count_bytes_by_kind(candidate.read_bytes(), secrets)
            add(
                "sqlite_file_bytes",
                candidate,
                count_file(candidate, secrets),
                hit_kinds=kinds,
            )
    if not db.exists():
        print("LEAK SEARCH sqlite file missing")
        return 1
    if db.exists():
        per_table = sqlite_rows(db, secrets)
        add(
            "sqlite_raw_rows",
            db,
            sum(v for k, v in per_table.items() if not k.endswith("__rows")),
            tables=per_table,
        )
    report_dirs = [out_dir]
    extra_out = os.environ.get("LEAK_EXTRA_OUT_DIR", "").strip()
    if extra_out:
        report_dirs.append(Path(extra_out))
    seen_reports: set[Path] = set()
    for report_dir in report_dirs:
        if not report_dir.is_dir():
            continue
        for report in sorted(report_dir.glob("*.json")):
            if report.name == "leak-search-evidence.json":
                continue
            resolved = report.resolve()
            if resolved in seen_reports:
                continue
            seen_reports.add(resolved)
            add("report", report, count_file(report, secrets))
        for dom in sorted(report_dir.glob("dom-secret-search*.json")):
            resolved = dom.resolve()
            if resolved in seen_reports:
                continue
            seen_reports.add(resolved)
            data = json.loads(dom.read_text("utf-8"))
            add(
                "dom_per_screenshot",
                dom,
                int(data.get("total_hits", 0)),
                screenshots=len(data.get("screenshots", [])),
            )
    docs_hits = {
        str(p.relative_to(ROOT)): count_file(p, secrets)
        for p in (ROOT / "docs").rglob("*")
        if p.is_file()
    }
    add("docs", ROOT / "docs", sum(docs_hits.values()), files=len(docs_hits))
    readme_hits = sum(count_file(p, secrets) for p in ROOT.glob("README*.md"))
    add("readme", ROOT, readme_hits)

    # 已跟踪文件中按设计出现的位置（测试常量/搜索目标），仅列出，不计入失败
    tracked = subprocess.run(
        ["git", "grep", "-c", "-F", *sum((["-e", s] for s in STATIC_SECRETS), []), "--", "."],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.splitlines()
    evidence["tracked_by_design"] = tracked

    evidence["total_unexpected_hits"] = failures
    target = out_dir / "leak-search-evidence.json"
    target.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"LEAK SEARCH unexpected_hits={failures} dynamic_targets={len(dynamic)} evidence={target}"
    )
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
