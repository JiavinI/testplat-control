"""Phase 3.3a 真实 Engine 鉴权矩阵（Phase 4.0：两段式路由 + 必填 env）。

HTTP 层，设计稿 §6 全部 10 条 + B2 + Q2。
由 ``scripts/run_real_engine_matrix.sh`` 调用：本地 target、真实 Engine 的 Control 已启动，
各 config root 已写在临时目录。本脚本：
- 经 Control HTTP API 执行单 API 与 Case（两身份交替混跑），
- 经 target 的 ``/__inspect`` 核对**实际发出**的凭证头（只比对 sha256 与次数，H2、M3），
- 对每个响应全文搜索假秘密，
- 把逐条结果写入 ``auth-matrix-report.json``，把真实 Engine 的 422 文案写入
  ``auth-422-real-engine.json``（供重新生成 ``docs/phase3_3/examples``，B5）。

约束：假秘密只用于计算摘要和做搜索，绝不打印、绝不写入报告（报告写出前再自检一次）。
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

# 手册 §0.3-3 的假秘密：同时是泄密搜索目标。AWS 假值用于验证白名单外变量不被读取（§6-6）。
FAKE_SECRET = "tp-fake-secret-9f31c2a7"
FAKE_PARTNER = "tp-fake-partner-4c8e11d0"
FAKE_AWS = "tp-fake-aws-7d2e9b10"
SEARCH_TARGETS = (FAKE_SECRET, FAKE_PARTNER, FAKE_AWS)

BACKEND = os.environ.get("MATRIX_BACKEND_URL", "http://127.0.0.1:8000")
TARGET = os.environ["MATRIX_TARGET_URL"]
ASSETS_ROOT = os.environ.get("MATRIX_ASSETS_ROOT", "")  # 兼容旧 shell；运行改读同步快照
REPO = os.environ.get("MATRIX_REPO", "matrix")
ENV = os.environ.get("MATRIX_ENV", "test")
OUT_DIR = Path(os.environ["MATRIX_OUT_DIR"])
ROOTS = {
    name: os.environ[f"MATRIX_ROOT_{name.upper().replace('-', '_')}"]
    for name in (
        "auth",
        "noauth",
        "bad-yaml",
        "literal-cr",
        "literal-lf",
        "literal-nul",
        "default-missing",
        "header-case-dup",
    )
}


def sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


ADMIN_SHA = sha(f"Bearer {FAKE_SECRET}")
PARTNER_SHA = sha(FAKE_PARTNER)
COMBO_SHA = sha(f"{FAKE_SECRET}.{FAKE_PARTNER}")


def leaks(text: str) -> int:
    """返回文本中假秘密（含白名单外变量 AWS_SECRET_ACCESS_KEY 的假值）出现的总次数。

    HOME 的值是路径前缀，日志与资产路径里本来就有，不能作全文搜索目标；
    它只在 422 detail 上单独断言（见 ``expect_422``）。
    """
    return sum(text.count(t) for t in SEARCH_TARGETS)


def _establish():
    """延迟导入，避免在修改 sys.path 之前触发 E402。"""
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from tests.platform_gate import establish

    return establish


class Matrix:
    def __init__(self) -> None:
        self.client = httpx.Client(timeout=60)
        # 配置与执行接口需要平台会话；cookie 留在这个客户端上。
        _establish()(self.client, auth_base=BACKEND)
        self.rows: list[dict[str, Any]] = []
        self.projects: dict[str, str] = {}
        self.real_422: dict[str, Any] = {}

    # ---- 基础（Phase 4.0：两段式路由 + 必填 env；项目由服务端同步建立）----
    def project(self, root: str) -> str:
        if root not in self.projects:
            resp = self.client.get(f"{BACKEND}/repos/{REPO}/projects/{root}")
            resp.raise_for_status()
            self.projects[root] = root
        return self.projects[root]

    def _base(self, root: str) -> str:
        return f"{BACKEND}/repos/{REPO}/projects/{self.project(root)}"

    def run_api(self, root: str, asset: str, params: dict | None = None) -> httpx.Response:
        return self.client.post(
            f"{self._base(root)}/assets/{asset}/run",
            json={"params": params or {}, "env": ENV},
        )

    def run_case(self, root: str, case: str) -> httpx.Response:
        return self.client.post(
            f"{self._base(root)}/cases/{case}/run",
            json={"env": ENV},
        )

    def record_count(self, root: str) -> int:
        resp = self.client.get(f"{self._base(root)}/execution-records?limit=200")
        resp.raise_for_status()
        return len(resp.json())

    def reset_target(self) -> None:
        self.client.post(f"{TARGET}/__inspect/reset").raise_for_status()

    def received(self) -> list[dict[str, Any]]:
        return self.client.get(f"{TARGET}/__inspect").json()["requests"]

    def check(self, row_id: str, item: str, desc: str, fn: Callable[[], dict[str, Any]]) -> None:
        """执行一条矩阵用例；异常只记类型名，不记消息（避免把任何值带进报告）。"""
        try:
            detail = fn()
            ok = bool(detail.pop("ok"))
        except AssertionError as exc:
            ok, detail = False, {"assertion": str(exc)}
        except Exception as exc:  # noqa: BLE001
            ok, detail = False, {"exc_type": type(exc).__name__}
        self.rows.append({"id": row_id, "item": item, "desc": desc, "pass": ok, **detail})
        print(f"{'PASS' if ok else 'FAIL'} {row_id} {desc}", flush=True)

    # ---- 断言辅助 ----
    @staticmethod
    def _no_leak(resp: httpx.Response) -> int:
        return leaks(resp.text)

    def single_ok(self, root: str, asset: str, expect: dict[str, Any]) -> dict[str, Any]:
        """单 API：期望 200 + auth 字段 + target 收到的凭证摘要。"""
        self.reset_target()
        resp = self.run_api(root, asset)
        body = resp.json()
        got = self.received()
        assert resp.status_code == 200, f"status={resp.status_code}"
        auth = body.get("auth")
        exp_auth = expect["auth"]
        if exp_auth is None:
            assert auth is None, f"auth 应为 null，实际 {auth}"
        else:
            assert auth and auth["identity"] == exp_auth["identity"], f"auth={auth}"
            assert auth["header_names"] == exp_auth["header_names"], f"auth={auth}"
            assert auth["overridden_headers"] == exp_auth.get("overridden_headers", []), (
                f"auth={auth}"
            )
        assert len(got) == 1, f"target 收到 {len(got)} 个请求"
        req = got[0]
        for header, digest in expect["sent"].items():
            assert req[f"{header}_count"] == (1 if digest else 0), f"{header} 次数不对"
            if digest:
                assert req[f"{header}_sha256"] == [digest], f"{header} 摘要不符（串号或未注入）"
        leak = self._no_leak(resp)
        assert leak == 0, f"响应中秘密命中 {leak}"
        echo = (((body.get("result") or {}).get("response") or {}).get("body") or {}).get(
            "echo", {}
        )
        masked = [k for k, v in echo.items() if isinstance(v, str) and "***" in v]
        if expect["auth"] is not None:
            assert masked, "回显的凭证（非敏感键下）应被按值替换为 ***"
        return {
            "ok": True,
            "http": resp.status_code,
            "status": body.get("status"),
            "auth": auth,
            "echo_masked_keys": masked,
            "secret_hits_in_response": leak,
        }

    def expect_422(self, root: str, kind: str, target: str, key: str | None = None) -> dict:
        """预检 422：不保存记录、target 未收到任何请求、detail 不含秘密。"""
        before = self.record_count(root)
        self.reset_target()
        resp = self.run_case(root, target) if kind == "case" else self.run_api(root, target)
        got = self.received()
        after = self.record_count(root)
        assert resp.status_code == 422, f"status={resp.status_code}"
        body = resp.json()
        assert set(body) == {"detail"}, f"keys={sorted(body)}"
        leak = self._no_leak(resp)
        assert leak == 0, f"422 detail 中秘密命中 {leak}"
        home = os.environ.get("HOME")
        assert not home or home not in body["detail"], "422 detail 含 HOME 的值（§6-6）"
        assert after == before, f"422 不应保存记录（{before}->{after}）"
        assert not got, f"预检失败但 target 收到 {len(got)} 个请求"
        if key:
            self.real_422[key] = {"status": 422, "body": body}
        return {"ok": True, "http": 422, "detail": body["detail"], "records_delta": 0}


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    m = Matrix()
    admin = {"identity": "admin", "header_names": ["Authorization"]}
    partner = {"identity": "partner", "header_names": ["X-Api-Key"]}
    combo = {"identity": "combo", "header_names": ["X-Tenant-Token"]}

    # §6-1/2：admin 回显到非敏感键 → ***；target 确认收到正确凭证
    m.check(
        "S1",
        "§6-1,§6-2",
        "单 API admin：凭证确实发出，回显被按值替换",
        lambda: m.single_ok(
            "auth", "api.authm.echo_admin", {"auth": admin, "sent": {"authorization": ADMIN_SHA}}
        ),
    )
    m.check(
        "S2",
        "§6-2",
        "单 API partner（X-Api-Key 裸值）",
        lambda: m.single_ok(
            "auth",
            "api.authm.echo_partner",
            {"auth": partner, "sent": {"x-api-key": PARTNER_SHA, "authorization": None}},
        ),
    )
    m.check(
        "S3",
        "§6-2,H1,Q5",
        "自定义头 X-Tenant-Token + 一个 header 两个秘密",
        lambda: m.single_ok(
            "auth",
            "api.authm.echo_combo",
            {"auth": combo, "sent": {"x-tenant-token": COMBO_SHA, "authorization": None}},
        ),
    )
    m.check(
        "S4",
        "§5.3",
        "未声明 auth → default_identity(admin)",
        lambda: m.single_ok(
            "auth", "api.authm.echo_default", {"auth": admin, "sent": {"authorization": ADMIN_SHA}}
        ),
    )
    m.check(
        "S5",
        "§6-8",
        "auth: none 且配置了 default_identity → 不带凭证",
        lambda: m.single_ok(
            "auth",
            "api.authm.echo_none",
            {
                "auth": None,
                "sent": {"authorization": None, "x-api-key": None, "x-tenant-token": None},
            },
        ),
    )
    m.check(
        "S6",
        "§6-9,Q3,M3",
        "资产小写 authorization 与凭证同名 → 凭证优先、只发一份、记录原始写法",
        lambda: m.single_ok(
            "auth",
            "api.authm.echo_override",
            {
                "auth": {**admin, "overridden_headers": ["authorization"]},
                "sent": {"authorization": ADMIN_SHA},
            },
        ),
    )

    def error_body() -> dict[str, Any]:
        m.reset_target()
        before = m.record_count("auth")
        resp = m.run_api("auth", "api.authm.error_admin")
        body = resp.json()
        got = m.received()
        assert resp.status_code == 200 and body["status"] == "failed", f"{resp.status_code}"
        assert got and got[0]["authorization_sha256"] == [ADMIN_SHA], "凭证未发出"
        assert m.record_count("auth") == before + 1, "业务失败应保存记录"
        leak = leaks(resp.text)
        assert leak == 0, f"失败结果中秘密命中 {leak}"
        rec = m.client.get(
            f"{BACKEND}/repos/{REPO}/projects/{m.project('auth')}/execution-records/{body['record_id']}"
        )
        assert leaks(rec.text) == 0, "历史详情泄密"
        assert "***" in resp.text
        return {"ok": True, "http": 200, "status": "failed", "secret_hits_in_response": 0}

    m.check("S7", "§6-3", "目标把凭证写进 401 错误正文 → 失败结果为 ***，记录已保存", error_body)

    def alternate() -> dict[str, Any]:
        """§6-5：单 API 与 Case 混跑，两个身份交替，逐请求核对摘要。"""
        m.reset_target()
        seq = []
        for asset in ("echo_admin", "echo_partner", "echo_admin", "echo_partner"):
            r = m.run_api("auth", f"api.authm.{asset}")
            assert r.status_code == 200 and leaks(r.text) == 0
            seq.append(asset)
        rc = m.run_case("auth", "case.authm.mixed")
        assert rc.status_code == 200, f"case status={rc.status_code}"
        case_body = rc.json()
        assert leaks(rc.text) == 0, "Case 响应泄密"
        r = m.run_api("auth", "api.authm.echo_partner")
        assert r.status_code == 200
        got = m.received()
        expected = [
            ("authorization", ADMIN_SHA),
            ("x-api-key", PARTNER_SHA),
            ("authorization", ADMIN_SHA),
            ("x-api-key", PARTNER_SHA),
            # Case mixed：admin / partner / 匿名 / 默认(admin) / combo / admin / alias(匿名)
            ("authorization", ADMIN_SHA),
            ("x-api-key", PARTNER_SHA),
            (None, None),
            ("authorization", ADMIN_SHA),
            ("x-tenant-token", COMBO_SHA),
            ("authorization", ADMIN_SHA),
            (None, None),
            ("x-api-key", PARTNER_SHA),
        ]
        assert len(got) == len(expected), f"收到 {len(got)} 个请求"
        for idx, (req, (name, digest)) in enumerate(zip(got, expected, strict=True)):
            present = {
                h for h in ("authorization", "x-api-key", "x-tenant-token") if req[f"{h}_count"]
            }
            if name is None:
                assert not present, f"#{idx} 匿名请求带了凭证 {present}"
            else:
                assert present == {name}, f"#{idx} 凭证头 {present} != {name}（串号）"
                assert req[f"{name}_sha256"] == [digest], f"#{idx} 摘要不符（串号）"
        steps = case_body["result"]["steps"]
        ids = [None if s["auth"] is None else s["auth"]["identity"] for s in steps]
        assert ids == ["admin", "partner", None, "admin", "combo", "admin", None], f"{ids}"
        # §6-4：alias 引用回显的凭证 → 下一步实际发出的值是 ***，不是原值
        alias_sent = got[10]["x-resource-id"] or ""
        assert "***" in alias_sent and leaks(alias_sent) == 0, "alias 拿到了原值"
        return {
            "ok": True,
            "requests_checked": len(got),
            "case_step_identities": ids,
            "alias_sent_masked": True,
        }

    m.check("S8", "§6-5,§6-4,H2", "单 API 与 Case 混跑两身份交替不串号；alias 拿到 ***", alternate)

    # §6-6/7 + B2：不可用身份 → 422，无记录，target 未收到请求
    for row_id, item, asset, key in (
        ("U1", "§6-7", "echo_missing", "identity_unavailable"),
        ("U2", "§6-7", "echo_empty", None),
        ("U3", "§6-7", "echo_short", None),
        ("U4", "§6-6", "echo_home", None),
        ("U5", "§6-6", "echo_aws", None),
        ("U6", "B2", "echo_crlf", None),
        ("U7", "B2", "echo_lf", None),
        ("U8", "§6-7", "echo_ghost", "identity_not_found"),
    ):
        m.check(
            row_id,
            item,
            f"单 API {asset} → 422",
            lambda a=asset, k=key: m.expect_422("auth", "api", f"api.authm.{a}", k),
        )
    for row_id, case in (("C1", "unavailable"), ("C2", "ghost"), ("C3", "crlf")):
        m.check(
            row_id,
            "§5.3,B2",
            f"Case {case}：预检一次性检查，首步也不发出",
            lambda c=case: m.expect_422("auth", "case", f"case.authm.{c}"),
        )
    for row_id, root, key in (
        ("Y1", "bad-yaml", "config_invalid_yaml"),
        ("Y2", "literal-cr", "config_template_control_char"),
        ("Y3", "literal-lf", None),
        ("Y4", "literal-nul", None),
        ("Y5", "default-missing", "config_default_identity_missing"),
        ("Y6", "header-case-dup", "config_header_case_duplicate"),
    ):
        m.check(
            row_id,
            "§6-7,B2,Q3,Q7",
            f"配置 {root} → 加载即 422（匿名资产也不执行）",
            lambda r=root, k=key: m.expect_422(r, "api", "api.authm.echo_none", k),
        )

    # §6-10 / Q2：无 auth 配置
    m.check(
        "R1",
        "§6-10,Q2",
        "无 auth 配置 + 资产声明身份 → 422",
        lambda: m.expect_422("noauth", "api", "api.authm.echo_admin"),
    )
    m.check(
        "R2",
        "§6-10",
        "无 auth 配置 + auth: none → 匿名，与 v0.2.0 一致",
        lambda: m.single_ok(
            "noauth", "api.authm.echo_none", {"auth": None, "sent": {"authorization": None}}
        ),
    )

    def phase3_api() -> dict[str, Any]:
        # 无参数的 Phase 3 资产：断言失败属于既有业务结果（200 + failed），auth 恒为 null
        r = m.run_api("noauth", "api.demo.always_fail_assert")
        c = m.run_case("noauth", "case.demo.create_then_get")
        assert r.status_code == 200, f"api http={r.status_code}"
        assert r.json()["status"] == "failed", f"api status={r.json()['status']}"
        assert r.json()["auth"] is None, "api auth 应为 null"
        assert c.status_code == 200, f"case http={c.status_code}"
        assert c.json()["status"] == "success", f"case status={c.json()['status']}"
        assert all(s["auth"] is None for s in c.json()["result"]["steps"]), "步骤 auth 应为 null"
        return {"ok": True, "api": "failed(既有断言失败)", "case": "success"}

    m.check("R3", "§6-10", "无 auth 配置的 Phase 3 资产：结果不变、auth 恒为 null", phase3_api)

    report = {
        "rows": m.rows,
        "projects": m.projects,
        "passed": sum(r["pass"] for r in m.rows),
        "total": len(m.rows),
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    real = json.dumps(m.real_422, ensure_ascii=False, indent=2)
    # 写出前自检：报告本身绝不含秘密
    assert leaks(text) == 0 and leaks(real) == 0, "报告含秘密，拒绝写出"
    (OUT_DIR / "auth-matrix-report.json").write_text(text + "\n", encoding="utf-8")
    (OUT_DIR / "auth-422-real-engine.json").write_text(real + "\n", encoding="utf-8")
    (OUT_DIR / "auth-matrix-projects.json").write_text(
        json.dumps(m.projects) + "\n", encoding="utf-8"
    )
    print(f"AUTH MATRIX {report['passed']}/{report['total']}")
    return 0 if report["passed"] == report["total"] else 1


if __name__ == "__main__":
    sys.exit(main())
