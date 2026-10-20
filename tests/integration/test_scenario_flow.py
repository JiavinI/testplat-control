"""新版流程经过真实 Engine、HTTP 契约与历史存储；目标仅本机假服务。"""

import json

import pytest
import testplat_engine
import yaml

from testplat_control.api.case_schemas import CaseResult
from tests.case_support import create_project, project_api_base
from tests.integration.test_real_engine_case_flow import (  # noqa: F401
    SERVER_SECRET,
    _records,
    _run,
    _stored,
    local_server,
)
from tests.integration.test_real_engine_case_flow import real as real_fixture  # noqa: F401

pytestmark = [
    pytest.mark.legacy_git_config,
    pytest.mark.skipif(not hasattr(testplat_engine, "describe_case"), reason="需要场景描述能力"),
]


@pytest.fixture
def scenario(real_fixture):  # noqa: F811 -- 导入并使用既有 pytest fixture
    real = real_fixture
    flow = {
        "schema_version": "0.3",
        "id": "flow.demo.create",
        "inputs": {"name": {"type": "string"}},
        "outputs": {"id": "${created.body.id}"},
        "steps": [
            {
                "step_id": "create",
                "type": "api",
                "api_id": "api.demo.create",
                "params": {"name": "${inputs.name}"},
                "output": "created",
            }
        ],
    }
    case = {
        "schema_version": "0.3",
        "id": "case.demo.scenario",
        "name": "统一参数示例",
        "params": {"common": {"name": "common"}, "private": {"second": "second"}},
        "steps": [
            {
                "step_id": "first",
                "type": "flow",
                "flow_id": flow["id"],
                "params": {"name": "${params.common.name}"},
                "output": "first",
            },
            {
                "step_id": "second",
                "type": "flow",
                "flow_id": flow["id"],
                "params": {"name": "${params.private.second}"},
                "output": "second",
            },
            {
                "step_id": "get",
                "type": "api",
                "api_id": "api.demo.get",
                "params": {"resource_id": "${second.id}"},
            },
        ],
    }

    def save():
        for doc, kind in ((flow, "flow"), (case, "case")):
            path = real["assets"] / "scenarios/demo" / f"{doc['id'].split('.')[-1]}.{kind}.yaml"
            path.write_text(yaml.safe_dump(doc))
        real["project_id"] = create_project(real["client"], real["assets"], real["config"])

    save()
    return real, case, flow, save


def test_description_run_and_history_preserve_nested_trace(scenario):
    real, _, _, _ = scenario
    base = project_api_base(real["project_id"])
    detail = real["client"].get(f"{base}/cases/case.demo.scenario")
    assert detail.status_code == 200, detail.text
    definition = detail.json()["definition"]
    assert definition["params"]["private"]["second"] == "second"
    assert definition["steps"][0]["definition"]["outputs"] == {"id": "${created.body.id}"}
    response = _run(real, "case.demo.scenario")
    assert response.status_code == 200, response.text
    body = response.json()
    result = body["result"]
    assert result["status"] == "success"
    assert result["result_version"] == "0.3"
    assert [json.loads(r["body"])["name"] for r in real["requests"][:2]] == ["common", "second"]
    assert real["requests"][2]["headers"]["X-Resource-Id"] == "res-42"
    nested = result["steps"][0]["trace"]["children"][0]
    assert nested["response"]["body"]["access_token"] == "***"
    assert "access_token" not in nested["trace"]["outputs"]["body"]
    saved = _stored(body["record_id"])
    assert SERVER_SECRET not in saved.result_json
    assert SERVER_SECRET not in response.text
    history = real["client"].get(f"{base}/case-execution-records/{body['record_id']}")
    assert history.json()["result"] == result
    assert json.loads(saved.result_json) == result


def test_nested_timeout_history_preserves_failure(scenario):
    real, _, flow, save = scenario
    flow["steps"][0]["api_id"] = "api.demo.slow"
    save()
    response = real["client"].post(
        f"{project_api_base(real['project_id'])}/cases/case.demo.scenario/run",
        json={"env": "test", "timeout_seconds": 0.05},
    )
    assert response.status_code == 504, response.text
    (record,) = _records(real)
    result = json.loads(_stored(record["id"]).result_json)
    assert result["steps"][0]["trace"]["children"][0]["error"]["kind"] == "timeout"
    assert result["steps"][1]["status"] == "skipped"
    history = real["client"].get(
        f"{project_api_base(real['project_id'])}/case-execution-records/{record['id']}"
    )
    assert history.json()["result"]["result_version"] == "0.3"


def test_missing_input_and_flow_entry_make_no_record(scenario):
    real, case, _, save = scenario
    del case["params"]["private"]
    save()
    assert _run(real, "case.demo.scenario").status_code == 422
    assert _run(real, "flow.demo.create").status_code == 422
    assert real["requests"] == []
    assert _records(real) == []


@pytest.mark.parametrize("expected", ["0.30", "0.31"])
def test_new_nodes_preserve_definition_scalar_outputs_evidence_and_history(scenario, expected):
    real, case, flow, save = scenario
    case["params"] = {"rows": [{"name": "first"}, {"name": "second"}]}
    case["steps"] = [
        {
            "step_id": "each",
            "type": "map",
            "source": "${params.rows}",
            "flow_id": flow["id"],
            "params": {"name": "${item.name}"},
            "output": "each",
        },
        {
            "step_id": "ids",
            "type": "transform",
            "operation": "project",
            "source": "${each}",
            "path": ["id"],
            "output": "ids",
        },
        {
            "step_id": "chosen",
            "type": "extract",
            "source": "${ids}",
            "selector": {"path": [0]},
            "cardinality": "one",
            "value_type": "string",
            "output": "chosen",
        },
        {
            "step_id": "amount",
            "type": "decimal",
            "operation": "add",
            "operands": ["0.1", "0.2"],
            "scale": 2,
            "rounding": "HALF_UP",
            "output": "amount",
        },
        {
            "step_id": "check",
            "type": "assert",
            "operation": "decimal_equal",
            "actual": "${amount}",
            "expected": expected,
        },
    ]
    save()
    base = project_api_base(real["project_id"])
    detail = real["client"].get(f"{base}/cases/case.demo.scenario")
    assert detail.status_code == 200, detail.text
    definition = detail.json()["definition"]
    assert definition["steps"][0]["source"] == "${params.rows}"
    assert definition["steps"][1]["path"] == ["id"]
    assert definition["steps"][2]["selector"] == {"path": [0]}
    assert definition["steps"][3]["scale"] == 2
    response = _run(real, case["id"])
    assert response.status_code == 200, response.text
    body = response.json()
    result = body["result"]
    assert result["status"] == ("success" if expected == "0.30" else "failed")
    assert len(real["requests"]) == 2
    mapped, projected, extracted, calculated, checked = result["steps"]
    assert mapped["trace"]["children"][1]["trace"]["iteration_index"] == 1
    assert mapped["trace"]["outputs"] == [{"id": "res-42"}, {"id": "res-42"}]
    assert projected["trace"]["outputs"] == ["res-42", "res-42"]
    assert projected["trace"]["transforms"][0]["status"] == "success"
    assert extracted["trace"]["outputs"] == "res-42"
    assert extracted["trace"]["extracts"][0]["match_count"] == 1
    assert calculated["trace"]["outputs"] == "0.30"
    assert calculated["trace"]["calculations"][0]["rounding"] == "HALF_UP"
    assert checked["trace"]["assertions"][0]["actual"] == "0.30"
    assert checked["trace"]["assertions"][0]["expected"] == expected
    assert checked["trace"]["bindings"][0]["source_node_id"] == calculated["trace"]["node_id"]
    history = real["client"].get(f"{base}/case-execution-records/{body['record_id']}")
    assert history.status_code == 200
    assert history.json()["result"] == result
    stored = json.loads(_stored(body["record_id"]).result_json)
    # Existing HTTP error fields add nullable defaults; stored Engine payload stays intact.
    assert CaseResult.model_validate(stored).model_dump() == result
    assert stored["steps"][-1]["trace"] == checked["trace"]
    assert SERVER_SECRET not in response.text
