"""报告仅用隔离 SQLite 和虚构 Assets；另验证 CLI 不启动应用或建表。"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from testplat_control.services.shared_parameter_audit import build_audit, to_markdown

SHA = 'a' * 40


def _fixture(tmp_path: Path, *, with_parameter_sets: bool = True):
    database = tmp_path / "audit.db"
    with sqlite3.connect(database) as db:
        db.executescript("""
            CREATE TABLE projects(id TEXT PRIMARY KEY, repo TEXT, project_key TEXT,
                archived INTEGER, commit_sha TEXT);
            CREATE TABLE workspace_bindings(project_id TEXT PRIMARY KEY, platform TEXT,
                business_project TEXT, configuration_project_id TEXT);
            CREATE TABLE project_environments(project_id TEXT, env TEXT, enabled INTEGER,
                case_params TEXT, revision INTEGER);
            CREATE TABLE test_accounts(encrypted_credentials TEXT);
            INSERT INTO test_accounts VALUES ('opaque-account-not-to-be-read');
        """)
        db.executemany("INSERT INTO projects VALUES (?, 'demo', ?, 0, ?)", [
            ("demo/owner", "owner", SHA), ("demo/consumer", "consumer", SHA),
        ])
        db.executemany("INSERT INTO workspace_bindings VALUES (?, 'gsb', ?, 'demo/owner')", [
            ("demo/owner", "go2"), ("demo/consumer", "e3e3"),
        ])
        db.execute("INSERT INTO project_environments VALUES ('demo/owner', 'test', 1, ?, 4)", (
            json.dumps({"keyword": "do-not-report", "count": 0, "password": "fake-secret",
                        "filter": {"a": 0}, "optional": None, "active": False,
                        "nested": {"Cookie": "fake-hidden-cookie"}}),
        ))
        db.execute("INSERT INTO project_environments VALUES ('demo/owner','pre',0,'{}',5)")
        if with_parameter_sets:
            db.execute('''CREATE TABLE parameter_sets(project_id TEXT, asset_type TEXT,
                asset_id TEXT, scope TEXT, env_key TEXT, "values" TEXT, revision INTEGER)''')
            db.executemany('INSERT INTO parameter_sets VALUES (?,?,?,?,?,?,?)', [
                ('demo/consumer', 'api', 'api.demo.search', 'environment_override', 'test',
                 json.dumps({'keyword': 'different-hidden'}), 3),
                ('demo/consumer', 'api', 'api.demo.search', 'asset_default', '',
                 json.dumps({'keyword': 'do-not-report'}), 2),
                ('demo/consumer', 'case', 'case.demo.search', 'environment_override', 'test',
                 json.dumps({'active': 0, 'optional': None}), 1),
            ])
    root = tmp_path / "repos" / "demo" / "snap" / SHA
    for key in ('owner', 'consumer'):
        (root / f"projects/{key}/api/demo").mkdir(parents=True)
        (root / f"projects/{key}/scenarios/demo").mkdir(parents=True)
    (root / "testplat.yaml").write_text("""schema_version: '1'
projects:
  owner: {name: Owner, assets: projects/owner, config: projects/owner}
  consumer: {name: Consumer, assets: projects/consumer, config: projects/consumer}
""", encoding="utf-8")
    for key in ('owner', 'consumer'):
        (root / f"projects/{key}/api/demo/search.yaml").write_text("""id: api.demo.search
request:
  inputs:
    keyword: {type: string, default: git}
    count: {type: number, default: 3}
    active: {type: boolean, default: true}
""", encoding="utf-8")
    (root / "projects/consumer/scenarios/demo/search.case.yaml").write_text("""schema_version: '0.2'
id: case.demo.search
params: {keyword: asset, filter: {a: 1, b: 2}, optional: null}
steps:
  - step_id: search
    type: api
    api_id: api.demo.search
    params: {q: '${params.keyword}', count: '${params.filter.a}', optional: '${params.optional}'}
""", encoding="utf-8")
    return database, tmp_path / "repos", root


def _key(report, key):
    section = next(s for s in report['shared_environments'] if s['environment'] == 'test')
    return next(k for k in section['keys'] if k['name'] == key)


def test_consumers_conflicts_removal_and_redaction(tmp_path: Path):
    database, data_dir, _ = _fixture(tmp_path)
    before = database.read_bytes()
    report = build_audit(database, data_dir)
    assert report['analysis_gaps'] == []
    assert report['summary']['environment_count'] == 2
    pre = next(s for s in report['shared_environments'] if s['environment'] == 'pre')
    assert not pre['enabled']
    keyword = _key(report, 'keyword')
    assert {c['project_id'] for c in keyword['consumers']} == {'demo/owner', 'demo/consumer'}
    consumer = next(c for c in keyword['consumers'] if c['project_id'] == 'demo/consumer'
                    and c['asset_type'] == 'api')
    assert consumer['current_source'] == 'environment_override'
    assert consumer['remove_shared_key'] == 'unchanged'
    assert consumer['copy_to_asset_environment'] == 'would_overwrite_existing_override'
    assert consumer['existing_values'] == [
        {'scope': 'asset_default', 'relation': 'same_value'},
        {'scope': 'environment_override', 'relation': 'different_value'},
    ]
    assert (consumer['default_revision'], consumer['override_revision']) == (2, 3)
    case = next(c for c in _key(report, 'filter')['consumers'] if c['asset_type'] == 'case')
    assert case['nested_reference_count'] == 1
    assert case['remove_shared_key'] == 'changed'
    assert case['unresolved_references_after_removal'] == 0  # Git fallback remains resolvable
    active = next(c for c in _key(report, 'active')['consumers'] if c['asset_type'] == 'case')
    assert active['consumer'] == 'case_injected_without_reference'
    assert active['existing_values'][0]['relation'] == 'different_value'  # False != 0
    optional = next(c for c in _key(report, 'optional')['consumers'] if c['asset_type'] == 'case')
    assert optional['existing_values'][0]['relation'] == 'same_value'  # explicit null
    assert not _key(report, 'nested')['consumers'][0]['can_save_as_business_parameter']
    serialized = json.dumps(report) + to_markdown(report)
    for hidden in ('do-not-report', 'fake-secret', 'different-hidden', 'fake-hidden-cookie',
                   'opaque-account-not-to-be-read'):
        assert hidden not in serialized
    assert database.read_bytes() == before


def test_case_injection_includes_undeclared_unused_keys_and_old_schema(tmp_path: Path):
    database, data_dir, _ = _fixture(tmp_path, with_parameter_sets=False)
    before = database.read_bytes()
    report = build_audit(database, data_dir)
    sensitive = _key(report, '[sensitive key omitted]')
    assert sensitive['consumers'][0]['consumer'] == 'case_injected_without_reference'
    assert not sensitive['consumers'][0]['can_save_as_business_parameter']
    assert not report['parameter_sets_table_available']
    assert database.read_bytes() == before


def test_missing_invalid_and_symlink_assets_are_gaps(tmp_path: Path):
    database, data_dir, root = _fixture(tmp_path)
    (root / 'projects/owner/api/demo/bad.yaml').write_text('request: [bad', encoding='utf-8')
    outside = tmp_path / 'outside.yaml'
    outside.write_text('password: hidden', encoding='utf-8')
    (root / 'projects/owner/api/escape.yaml').symlink_to(outside)
    report = build_audit(database, data_dir)
    assert {g['kind'] for g in report['analysis_gaps']} == {
        'asset_analysis_failed', 'symlink_not_scanned',
    }
    (root / 'testplat.yaml').unlink()
    report = build_audit(database, data_dir)
    assert {g['kind'] for g in report['analysis_gaps']} == {'snapshot_unavailable_or_invalid'}


def test_invalid_types_and_nested_reference_loss(tmp_path: Path):
    database, data_dir, root = _fixture(tmp_path)
    with sqlite3.connect(database) as db:
        db.execute("UPDATE project_environments SET case_params=? WHERE env='test'", (
            json.dumps({'count': False, 'filter': {'a': 0}}),
        ))
    path = root / 'projects/consumer/scenarios/demo/search.case.yaml'
    path.write_text(path.read_text().replace('filter: {a: 1, b: 2}', 'filter: {b: 2}'))
    report = build_audit(database, data_dir)
    assert all(c['shared_type_compatible'] is False for c in _key(report, 'count')['consumers']
               if c['asset_type'] == 'api')
    assert all(not c['can_save_as_business_parameter']
               for c in _key(report, 'count')['consumers'] if c['asset_type'] == 'api')
    case = _key(report, 'filter')['consumers'][0]
    assert case['unresolved_references_after_removal'] == 1


def test_cli_never_initializes_database_and_handles_paths_with_spaces(tmp_path: Path):
    database, data_dir, _ = _fixture(tmp_path, with_parameter_sets=False)
    renamed = database.with_name('audit with spaces.db')
    database.rename(renamed)
    output = tmp_path / 'report.md'
    before = renamed.read_bytes()
    result = subprocess.run([
        sys.executable, 'scripts/audit_shared_case_params.py', '--database', str(renamed),
        '--data-dir', str(data_dir), '--output', str(output),
    ], env={**os.environ, 'DATABASE_URL': f'sqlite:///{renamed}'},
        capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert 'read_only=true' in result.stdout
    assert output.exists() and renamed.read_bytes() == before
    assert 'do-not-report' not in output.read_text()


def test_cli_rejects_report_overwriting_input_database(tmp_path: Path):
    database, data_dir, _ = _fixture(tmp_path)
    before = database.read_bytes()
    result = subprocess.run([
        sys.executable, 'scripts/audit_shared_case_params.py', '--database', str(database),
        '--data-dir', str(data_dir), '--output', str(database),
    ], capture_output=True, text=True, timeout=30)
    assert result.returncode == 2
    assert database.read_bytes() == before
