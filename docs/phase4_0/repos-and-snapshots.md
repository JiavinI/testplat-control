# Phase 4.0：仓库同步与快照

## 服务端配置

环境变量 `TESTPLAT_REPOS_FILE` 指向**服务端本地** YAML（不进任何 Git 仓库）：

```yaml
data_dir: /var/lib/testplat/repos
repos:
  main:
    url: git@github.com:<org>/testplat-assets.git   # 或 file:///path/to/repo
    branch: main
```

- 仓库键 / 项目键：`[a-z0-9_-]{1,64}`。
- Web **不能**增删改仓库；未配置时启动正常，`GET /repos` 为空。
- 配置里的 URL 视为敏感：API 响应只返回键与分支，永不返回 URL。

## 同步语义

- `POST /repos/{repo}/sync`：mirror `fetch` → 解析分支 SHA → 校验 `testplat.yaml` → 物化快照 → upsert 项目。
- 启动时对每个已配置仓库同步一次；单个失败不阻塞启动，只记结果类别。
- 同一仓库进程内串行（`asyncio.Lock`）；超时 60 秒。
- 失败类别：`network` / `auth` / `invalid_manifest` / `timeout`（成功为 `ok`）。
- 失败时**保留**旧 `current_sha`；Git stdout/stderr 不进 HTTP、不进日志、不进异常消息。

## 快照与并发

- 路径：`{data_dir}/{repo}/snap/{sha}/`。
- 方案：`git archive --format=tar <sha>` 产出字节，再 `tar -x` 解压（均为参数列表 subprocess，无 `shell=True`）。
- 选择理由：快照无 `.git`、天然只读树、不占用 worktree 槽位；与进行中的执行解耦。
- 一次执行在开始时固定 SHA，全程读该快照；同步只影响**后续**执行。
- 保留最近 10 个快照目录。

## 项目与运行

- 项目主键：`{repo}/{project}`；路由：`/repos/{repo}/projects/{project}/...`。
- 运行请求体必填 `env`（须在清单扫描到的 `envs` 内，否则 422）。
- `cache_scope`：`{repo}:{project}:{env}`（Engine `AuthTable` 禁止 `/`，故未采用设计稿字面量中的斜杠形式）。

## 删除旧库

无 alembic 迁移。若本地 SQLite 仍是 Phase 3 表结构（含 `assets_root` / `config_root` / `env`），启动会报错并提示删除数据库文件后重建。
