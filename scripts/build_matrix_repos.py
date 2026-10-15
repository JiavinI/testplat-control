"""Phase 4.0：把矩阵用的 assets/config 装进临时 git 仓库并写 TESTPLAT_REPOS_FILE。

由 ``run_real_engine_matrix.sh`` 调用。输出 JSON（stdout）供 shell 解析：
``repo_url`` / ``repos_file`` / ``data_dir`` / ``repo_key`` / ``projects``。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path


def _git(args: list[str], *, cwd: Path) -> None:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        timeout=60,
        check=False,
    )
    if result.returncode != 0:
        # 不回显 stderr（可能含路径）；只抛类别
        raise RuntimeError(f"git_failed:{args[0]}")


def _write_env(config_dir: Path, target_port: int) -> None:
    envs = config_dir / "envs"
    envs.mkdir(parents=True, exist_ok=True)
    (envs / "test.yaml").write_text(
        f"""# 矩阵临时 env：local 指向本机 target
api_hosts:
  test_server: http://127.0.0.1:9
  local: http://127.0.0.1:{target_port}
  dead: http://127.0.0.1:1
timeout:
  default: 30
""",
        encoding="utf-8",
    )


def _copy_assets(dst: Path, *sources: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for src in sources:
        if not src.is_dir():
            continue
        for item in src.iterdir():
            target = dst / item.name
            if item.is_dir():
                if target.exists():
                    shutil.copytree(item, target, dirs_exist_ok=True)
                else:
                    shutil.copytree(item, target)
            else:
                shutil.copy2(item, target)


def _add_project(
    repo: Path,
    *,
    key: str,
    name: str,
    asset_sources: list[Path],
    auth_src: Path | None,
    target_port: int,
    auth_transform=None,
) -> None:
    proj = repo / "projects" / key
    assets = proj
    config = proj / "config"
    _copy_assets(assets, *asset_sources)
    # 资产树里不应残留 config（若 fixtures 带了则去掉）
    stray = assets / "config"
    if stray.exists():
        shutil.rmtree(stray)
    config.mkdir(parents=True, exist_ok=True)
    _write_env(config, target_port)
    if auth_src is not None:
        auth_dir = config / "auth"
        auth_dir.mkdir(parents=True, exist_ok=True)
        text = auth_src.read_text(encoding="utf-8")
        if auth_transform is not None:
            text = auth_transform(text)
        (auth_dir / "test.yaml").write_text(text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work", required=True)
    parser.add_argument("--root", required=True, help="Control worktree root")
    parser.add_argument("--target-port", type=int, required=True)
    parser.add_argument("--redis-port", type=int, required=True)
    parser.add_argument("--dead-redis-port", type=int, required=True)
    args = parser.parse_args()

    work = Path(args.work)
    root = Path(args.root)
    fixtures = root / "tests" / "fixtures"
    repo = work / "matrix-assets.gitwork"
    if repo.exists():
        shutil.rmtree(repo)
    repo.mkdir(parents=True)

    base_assets = fixtures / "assets"
    auth_assets = fixtures / "auth_matrix" / "assets"
    login_assets = fixtures / "login_matrix" / "assets"
    auth_dir = fixtures / "auth_matrix" / "auth"
    login_auth = fixtures / "login_matrix" / "auth"

    def subst_redis(text: str) -> str:
        return text.replace("__MATRIX_REDIS_PORT__", str(args.redis_port)).replace(
            "__MATRIX_DEAD_REDIS_PORT__", str(args.dead_redis_port)
        )

    # --- 3.3a 鉴权 ---
    auth_keys = {
        "auth": "main.yaml",
        "noauth": None,
        "bad-yaml": "bad-yaml.yaml",
        "literal-cr": "literal-cr.yaml",
        "literal-lf": "literal-lf.yaml",
        "literal-nul": "literal-nul.yaml",
        "default-missing": "default-missing.yaml",
        "header-case-dup": "header-case-dup.yaml",
    }
    for key, fname in auth_keys.items():
        auth_src = (auth_dir / fname) if fname else None
        _add_project(
            repo,
            key=key,
            name=f"auth-{key}",
            asset_sources=[base_assets, auth_assets],
            auth_src=auth_src,
            target_port=args.target_port,
        )

    # --- 3.3b/c/d 登录 ---
    login_specs = {
        "login": ("main.yaml", False),
        "legacy": ("legacy-profiles.yaml", False),
        "static": ("static-only.yaml", False),
        "no-plugin": ("no-plugin-whitelist.yaml", False),
        "unknown": ("unknown-strategy.yaml", False),
        "vcode": ("vcode-main.yaml", True),
        "vcode-conn-missing": ("vcode-conn-missing.yaml", True),
        "vcode-no-whitelist": ("vcode-no-whitelist.yaml", True),
        "cache": ("cache-main.yaml", False),
        "cache-a": ("cache-main.yaml", False),
        "cache-b": ("cache-main.yaml", False),
        "cache-cold": ("cache-main.yaml", False),  # L43 冷启动专用，矩阵内勿先跑
    }
    for key, (fname, need_subst) in login_specs.items():
        transform = subst_redis if need_subst else None
        _add_project(
            repo,
            key=key,
            name=f"login-{key}",
            asset_sources=[base_assets, login_assets],
            auth_src=login_auth / fname,
            target_port=args.target_port,
            auth_transform=transform,
        )

    # 另加 phase3 回归用 demo 项目（无 auth）
    _add_project(
        repo,
        key="phase3",
        name="phase3-regression",
        asset_sources=[base_assets],
        auth_src=None,
        target_port=args.target_port,
    )

    # 清单
    projects_yaml = ['schema_version: "1"', "projects:"]
    all_keys = list(auth_keys) + list(login_specs) + ["phase3"]
    for key in all_keys:
        projects_yaml.extend(
            [
                f"  {key}:",
                f"    name: matrix-{key}",
                f"    assets: projects/{key}",
                f"    config: projects/{key}/config",
                "    default_env: test",
            ]
        )
    (repo / "testplat.yaml").write_text("\n".join(projects_yaml) + "\n", encoding="utf-8")

    _git(["init", "-b", "main"], cwd=repo)
    _git(["config", "user.email", "matrix@example.com"], cwd=repo)
    _git(["config", "user.name", "Matrix"], cwd=repo)
    _git(["add", "-A"], cwd=repo)
    _git(["commit", "-m", "matrix assets init"], cwd=repo)

    data_dir = work / "repos-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    repos_file = work / "repos.yaml"
    url = repo.resolve().as_uri()
    repos_file.write_text(
        f"data_dir: {data_dir.resolve()}\nrepos:\n  matrix:\n    url: {url}\n    branch: main\n",
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "repo_url": url,
                "repos_file": str(repos_file),
                "data_dir": str(data_dir),
                "repo_key": "matrix",
                "repo_path": str(repo),
                "projects": all_keys,
            }
        )
    )


if __name__ == "__main__":
    main()
