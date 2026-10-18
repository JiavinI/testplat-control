#!/usr/bin/env python3
"""只读生成共享环境 case_params 消费者和迁移影响报告。"""

from __future__ import annotations

import argparse
from pathlib import Path

from testplat_control.services.shared_parameter_audit import build_audit, to_markdown


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True, help="Control SQLite 数据库")
    parser.add_argument("--data-dir", type=Path, required=True, help="现有仓库快照目录")
    parser.add_argument(
        "--output", type=Path,
        default=Path("docs/audits/shared-case-params-2026-10-18.md"),
    )
    args = parser.parse_args()
    output = args.output.resolve()
    if output == args.database.resolve() or output.is_relative_to(args.data_dir.resolve()):
        parser.error("报告不能覆盖数据库或写入快照目录")
    report = build_audit(args.database, args.data_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(to_markdown(report), encoding="utf-8")
    print(
        f"read_only=true shared_environments={len(report['shared_environments'])} "
        f"analysis_gaps={len(report['analysis_gaps'])} output={args.output}"
    )


if __name__ == "__main__":
    main()
