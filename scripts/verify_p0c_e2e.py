"""Disposable, deterministic P0-C live BI workflow.

The script uses the real local services, ETL/Kafka pipeline, Query SQL guard and
executor, Visualization/Metabase integration, report read boundary, and tenant
authorization. It never calls a paid provider or sends email. Every durable
fixture is uniquely tagged and removed in ``finally``.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

import requests


REPO_ROOT = Path(__file__).resolve().parents[1]
HTTP_TIMEOUT = 45


def read_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key.strip()] = value
    return values


def docker(*args: str, env: dict[str, str] | None = None) -> str:
    command = ["docker", *args]
    if args and args[0] == "exec" and env:
        command = ["docker", "exec"]
        for key, value in env.items():
            command.extend(["-e", f"{key}={value}"])
        command.extend(args[1:])
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=240,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"Docker command failed ({' '.join(command[:3])}); output withheld.")
    return completed.stdout + completed.stderr


def django_shell(container: str, code: str, env: dict[str, str] | None = None) -> str:
    return docker("exec", container, "python", "manage.py", "shell", "-c", code, env=env)


def tagged(output: str, marker: str) -> str:
    match = re.search(re.escape(marker) + r"([^\r\n]+)", output)
    if not match:
        raise RuntimeError(f"Expected verification marker was not returned: {marker}")
    return match.group(1).strip()


def http(
    method: str,
    url: str,
    *,
    expected: int | set[int],
    token: str = "",
    headers: dict[str, str] | None = None,
    payload: dict[str, Any] | None = None,
    files: dict[str, Any] | None = None,
) -> requests.Response:
    request_headers = dict(headers or {})
    if token:
        request_headers["Authorization"] = f"Bearer {token}"
    response = requests.request(
        method,
        url,
        headers=request_headers,
        json=payload,
        files=files,
        timeout=HTTP_TIMEOUT,
    )
    allowed = {expected} if isinstance(expected, int) else set(expected)
    if response.status_code not in allowed:
        safe_body = response.text[:500]
        raise RuntimeError(f"{method} {url} returned {response.status_code}; body={safe_body}")
    return response


def json_body(response: requests.Response) -> dict[str, Any]:
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("Expected a JSON object response.")
    return payload


def print_pass(message: str) -> None:
    print(f"PASS {message}", flush=True)


def main() -> int:
    config = read_dotenv(REPO_ROOT / ".env")
    required = ("SURREAL_USER", "SURREAL_PASS", "ETL_INTERNAL_API_KEY")
    if any(not config.get(key) for key in required):
        raise RuntimeError("Required local E2E configuration is incomplete.")

    suffix = uuid.uuid4().hex[:12]
    tag = f"p0c-{suffix}"
    email_a = f"{tag}-a@example.invalid"
    email_b = f"{tag}-b@example.invalid"
    password = f"P0c!{uuid.uuid4().hex}"
    workspace_name_a = f"P0C E2E A {suffix}"
    workspace_name_b = f"P0C E2E B {suffix}"
    filename = f"p0c_sales_{suffix}.csv"
    expected_table_name = filename.replace(".", "_").replace("-", "_")

    user_a = user_b = workspace_a = workspace_b = None
    dataset_id = job_id = uploaded_path = table_name = clickhouse_database = None
    report_id = dashboard_id = None
    query_definition_ids: list[str] = []
    question_ids: list[int] = []
    cleanup_verified = False

    csv_text = """date,product,category,quantity,unit_price,revenue
2025-01-05,Atlas,Business,2,40,80
2025-01-12,Beacon,Consumer,3,25,75
2025-01-20,Cedar,Business,4,20,80
2025-02-03,Atlas,Business,1,40,40
2025-02-11,Beacon,Consumer,5,25,125
2025-02-19,Cedar,Business,2,20,40
2025-03-02,Atlas,Business,3,40,120
2025-03-10,Beacon,Consumer,2,25,50
2025-03-18,Cedar,Business,6,20,120
2025-04-04,Atlas,Business,2,40,80
2025-04-12,Beacon,Consumer,4,25,100
2025-04-21,Cedar,Business,3,20,60
"""

    try:
        auth_code = """
import os
from users.models import User
a = User.objects.create_user(email=os.environ['P0C_EMAIL_A'], password=os.environ['P0C_PASSWORD'], name='P0C Tenant A', role='manager', is_verified=True)
b = User.objects.create_user(email=os.environ['P0C_EMAIL_B'], password=os.environ['P0C_PASSWORD'], name='P0C Tenant B', role='manager', is_verified=True)
print(f'P0C_USERS:{a.id},{b.id}')
"""
        auth_output = django_shell(
            "auth-service",
            auth_code,
            {"P0C_EMAIL_A": email_a, "P0C_EMAIL_B": email_b, "P0C_PASSWORD": password},
        )
        user_a, user_b = (int(item) for item in tagged(auth_output, "P0C_USERS:").split(","))
        print_pass("created two disposable users without email delivery")

        workspace_code = """
import os
from workspace.models import Workspace
a = Workspace.objects.create(name=os.environ['P0C_WS_A_NAME'], owner=int(os.environ['P0C_USER_A']), owner_email=os.environ['P0C_EMAIL_A'], owner_name='P0C Tenant A')
b = Workspace.objects.create(name=os.environ['P0C_WS_B_NAME'], owner=int(os.environ['P0C_USER_B']), owner_email=os.environ['P0C_EMAIL_B'], owner_name='P0C Tenant B')
print(f'P0C_WORKSPACES:{a.id},{b.id}')
"""
        workspace_output = django_shell(
            "workspace-service",
            workspace_code,
            {
                "P0C_WS_A_NAME": workspace_name_a,
                "P0C_WS_B_NAME": workspace_name_b,
                "P0C_USER_A": str(user_a),
                "P0C_USER_B": str(user_b),
                "P0C_EMAIL_A": email_a,
                "P0C_EMAIL_B": email_b,
            },
        )
        workspace_a, workspace_b = (
            int(item) for item in tagged(workspace_output, "P0C_WORKSPACES:").split(",")
        )
        print_pass("created two disposable workspaces")

        login_a = json_body(
            http(
                "POST",
                "http://127.0.0.1:8000/auth/login/",
                expected=200,
                payload={"email": email_a, "password": password},
            )
        )
        login_b = json_body(
            http(
                "POST",
                "http://127.0.0.1:8000/auth/login/",
                expected=200,
                payload={"email": email_b, "password": password},
            )
        )
        token_a = str(login_a.get("access") or "")
        token_b = str(login_b.get("access") or "")
        if not token_a or not token_b:
            raise RuntimeError("Login did not return both disposable access tokens.")
        print_pass("authenticated both tenants through the real Gateway/Auth path")

        with tempfile.TemporaryDirectory(prefix="biavora-p0c-") as temp_dir:
            csv_path = Path(temp_dir) / filename
            csv_path.write_text(csv_text, encoding="utf-8", newline="")
            with csv_path.open("rb") as csv_file:
                upload_payload = json_body(
                    http(
                        "POST",
                        "http://127.0.0.1:8000/database/upload/",
                        expected=201,
                        token=token_a,
                        files={"file": (filename, csv_file, "text/csv")},
                    )
                )

        upload_data = upload_payload.get("data") if isinstance(upload_payload.get("data"), dict) else {}
        dataset_id = int(upload_data["id"])
        job_id = str(upload_data["ingestion_job_id"])
        print_pass("uploaded a tagged synthetic sales CSV through Query -> ETL Connector")

        deadline = time.monotonic() + 240
        dataset_payload: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            response = http(
                "GET",
                f"http://127.0.0.1:8000/database/?dataset_id={dataset_id}",
                expected={200, 409, 422},
                token=token_a,
            )
            body = json_body(response)
            candidate = body.get("data") if isinstance(body.get("data"), dict) else {}
            if response.status_code == 200 and candidate.get("etl_status") == "completed":
                dataset_payload = candidate
                break
            time.sleep(2)
        if dataset_payload is None:
            raise RuntimeError("ETL did not produce a completed dataset within 240 seconds.")

        table_name = str(dataset_payload.get("clickhouse_table_name") or "")
        clickhouse_database = str(dataset_payload.get("clickhouse_database") or "")
        uploaded_path = str(dataset_payload.get("file_path") or "")
        if not table_name or not clickhouse_database or int(dataset_payload.get("row_count") or 0) < 12:
            raise RuntimeError(
                "Completed dataset metadata was incomplete: "
                f"table={bool(table_name)} database={bool(clickhouse_database)} "
                f"rows={int(dataset_payload.get('row_count') or 0)} "
                f"file_path={bool(uploaded_path)} status={dataset_payload.get('etl_status')!r}."
            )
        print_pass(
            f"real Kafka ETL completed ({dataset_payload.get('row_count')} rows, "
            f"{dataset_payload.get('column_count')} columns)"
        )

        preview = json_body(
            http(
                "GET",
                "http://127.0.0.1:8000/database/preview/",
                expected=200,
                token=token_a,
            )
        )
        preview_data = preview.get("data") if isinstance(preview.get("data"), dict) else {}
        preview_columns = {str(value).lower() for value in preview_data.get("columns", [])}
        required_columns = {"date", "product", "category", "quantity", "unit_price", "revenue"}
        if not required_columns.issubset(preview_columns):
            raise RuntimeError(f"ETL preview omitted expected columns: {sorted(required_columns - preview_columns)}")
        print_pass("retrieved the real ClickHouse-backed dataset preview")

        metadata_headers = {
            "X-Internal-Service": "query-service",
            "X-Internal-API-Key": config["ETL_INTERNAL_API_KEY"],
            "X-Workspace-ID": str(workspace_a),
            "X-Dataset-ID": job_id,
            "X-Ingestion-Job-ID": job_id,
        }
        metadata: dict[str, Any] = {}
        metadata_deadline = time.monotonic() + 60
        while time.monotonic() < metadata_deadline:
            metadata = json_body(
                http(
                    "GET",
                    "http://127.0.0.1:8106/api/logs/connections/",
                    expected=200,
                    headers=metadata_headers,
                )
            )
            if metadata.get("success") and list(metadata.get("data") or []):
                break
            time.sleep(1)
        if not metadata.get("success") or not list(metadata.get("data") or []):
            raise RuntimeError("Scoped ETL connection metadata was not found.")
        foreign_headers = dict(metadata_headers)
        foreign_headers["X-Workspace-ID"] = str(workspace_b)
        foreign_metadata = json_body(
            http(
                "GET",
                "http://127.0.0.1:8106/api/logs/connections/",
                expected=200,
                headers=foreign_headers,
            )
        )
        if list(foreign_metadata.get("data") or []):
            raise RuntimeError("Tenant B received Tenant A ETL metadata.")
        print_pass("verified scoped Surreal metadata and cross-tenant filtering")

        tick = "`"
        qualified_table = f"{clickhouse_database}.{tick}{table_name}{tick}"
        analytics = [
            {
                "name": "Revenue by month",
                "sql": (
                    f"SELECT toStartOfMonth(toDate(date)) AS month, "
                    f"sum(toFloat64(revenue)) AS revenue FROM {qualified_table} "
                    "GROUP BY month ORDER BY month"
                ),
                "chart": "line",
                "columns": ["month", "revenue"],
                "compatible": {"line", "bar", "area"},
            },
            {
                "name": "Revenue by category",
                "sql": (
                    f"SELECT category, sum(toFloat64(revenue)) AS revenue FROM {qualified_table} "
                    "GROUP BY category ORDER BY revenue DESC"
                ),
                "chart": "bar",
                "columns": ["category", "revenue"],
                "compatible": {"bar", "pie"},
            },
            {
                "name": "Top products by revenue",
                "sql": (
                    f"SELECT product, sum(toFloat64(revenue)) AS revenue FROM {qualified_table} "
                    "GROUP BY product ORDER BY revenue DESC LIMIT 3"
                ),
                "chart": "bar",
                "columns": ["product", "revenue"],
                "compatible": {"bar", "pie"},
            },
        ]

        analytical_results: list[dict[str, Any]] = []
        for analytic in analytics:
            execution = json_body(
                http(
                    "POST",
                    "http://127.0.0.1:8000/query/execute/",
                    expected=200,
                    token=token_a,
                    payload={"workspace_id": workspace_a, "sql": analytic["sql"]},
                )
            )
            if not execution.get("success") or int(execution.get("row_count") or 0) < 1:
                raise RuntimeError(f"Analytical execution failed for {analytic['name']}.")
            analytical_results.append(execution)

            definition = json_body(
                http(
                    "POST",
                    "http://127.0.0.1:8000/query/definitions/",
                    expected=201,
                    token=token_a,
                    payload={
                        "workspace_id": workspace_a,
                        "dataset_id": dataset_id,
                        "sql": analytic["sql"],
                    },
                )
            )
            definition_id = str(definition["query_definition_id"])
            query_definition_ids.append(definition_id)
            visualization = json_body(
                http(
                    "POST",
                    "http://127.0.0.1:8000/visualization/question/create/",
                    expected=200,
                    token=token_a,
                    payload={
                        "name": f"{tag} {analytic['name']}",
                        "query_definition_id": definition_id,
                        "chart_type": analytic["chart"],
                        "visualization_settings": {
                            "selection_mode": "deterministic",
                            "dataset_columns": analytic["columns"],
                            "columns": analytic["columns"],
                            "result_rows": execution.get("rows") or [],
                            "result_shape": execution.get("result_shape") or {},
                        },
                        "ai_trace": {"p0c_fixture": True, "question": analytic["name"]},
                    },
                )
            )
            selected_chart = str(visualization.get("chart_type") or "")
            if selected_chart not in analytic["compatible"]:
                raise RuntimeError(
                    f"{analytic['name']} selected incompatible chart type {selected_chart!r}."
                )
            question_ids.append(int(visualization["question_id"]))
            print_pass(
                f"{analytic['name']}: SQL guard/execution + Query definition + {selected_chart} visualization"
            )

        foreign_definition = http(
            "POST",
            "http://127.0.0.1:8000/query/definitions/",
            expected=403,
            token=token_b,
            payload={"workspace_id": workspace_b, "dataset_id": dataset_id, "sql": analytics[0]["sql"]},
        )
        if foreign_definition.status_code != 403:
            raise RuntimeError("Tenant B unexpectedly authorized Tenant A's dataset.")

        dashboard = json_body(
            http(
                "POST",
                "http://127.0.0.1:8000/visualization/dashboard/create/",
                expected=200,
                token=token_a,
                payload={"name": f"{tag} Sales dashboard", "description": "Disposable P0-C E2E"},
            )
        )
        dashboard_id = int(dashboard["dashboard_id"])
        http(
            "POST",
            "http://127.0.0.1:8000/visualization/dashboard/add-question/",
            expected=200,
            token=token_a,
            payload={"question_id": question_ids[0], "dashboard_id": dashboard_id},
        )
        http(
            "GET",
            f"http://127.0.0.1:8000/visualization/dashboard/{dashboard_id}/embed-url/",
            expected=200,
            token=token_a,
        )
        http(
            "GET",
            f"http://127.0.0.1:8000/visualization/dashboard/{dashboard_id}/embed-url/",
            expected=403,
            token=token_b,
        )
        print_pass("created a Metabase dashboard and enforced tenant-owned embedding")

        forecast_code = """
from forecasting.pipeline import detect_forecast_request
r = detect_forecast_request(intent={'intent_type': 'predictive', 'requires_forecast': False}, question_type='predictive', final_route='metabase')
assert r.requires_forecast and r.reason == 'predictive_invariant'
print('P0C_FORECAST:eligible')
"""
        forecast_output = docker("exec", "ai-service", "python", "-c", forecast_code)
        if tagged(forecast_output, "P0C_FORECAST:") != "eligible":
            raise RuntimeError("Forecast eligibility contract did not accept the predictive intent.")
        print_pass("validated forecast eligibility without model inference")

        report_code = """
import os
from voice_reports.models import VoiceReport
r = VoiceReport.objects.create(
    workspace_id=os.environ['P0C_WORKSPACE'], created_by_id=os.environ['P0C_USER'],
    created_by_email=os.environ['P0C_EMAIL'], audio_file='',
    transcription='Revenue by month', intent_json={'metric': 'revenue', 'time_grain': 'month'},
    generated_sql=os.environ['P0C_SQL'], final_sql=os.environ['P0C_SQL'], sql_validated=True,
    query_result={'p0c_tag': os.environ['P0C_TAG'], 'validated_analytics': 3},
    row_count=4, chart_type='line', chart_config={'p0c_tag': os.environ['P0C_TAG']},
    metabase_question_id=int(os.environ['P0C_QUESTION']),
    metabase_dashboard_id=int(os.environ['P0C_DASHBOARD']),
    status=VoiceReport.STATUS_VISUALIZATION_CREATED,
    title=os.environ['P0C_TITLE'], description='Disposable deterministic P0-C report fixture')
print(f'P0C_REPORT:{r.id}')
"""
        report_output = django_shell(
            "voice-service",
            report_code,
            {
                "P0C_WORKSPACE": str(workspace_a),
                "P0C_USER": str(user_a),
                "P0C_EMAIL": email_a,
                "P0C_SQL": analytics[0]["sql"],
                "P0C_TAG": tag,
                "P0C_QUESTION": str(question_ids[0]),
                "P0C_DASHBOARD": str(dashboard_id),
                "P0C_TITLE": f"{tag} Revenue report",
            },
        )
        report_id = int(tagged(report_output, "P0C_REPORT:"))
        report = json_body(
            http(
                "GET",
                f"http://127.0.0.1:8003/voice-reports/{report_id}/",
                expected=200,
                token=token_a,
            )
        )
        if int(report.get("report", {}).get("id") or 0) != report_id:
            raise RuntimeError("Owner report retrieval returned the wrong record.")
        http(
            "GET",
            f"http://127.0.0.1:8003/voice-reports/{report_id}/",
            expected=404,
            token=token_b,
        )
        print_pass("saved/retrieved a report and denied the second tenant")
        print("P0C_E2E:PASS", flush=True)

    finally:
        cleanup_errors: list[str] = []

        def cleanup_step(name: str, action) -> None:
            try:
                action()
            except Exception as exc:  # noqa: BLE001 - cleanup must continue
                cleanup_errors.append(f"{name}:{type(exc).__name__}")

        if report_id is not None:
            cleanup_step(
                "voice report",
                lambda: django_shell(
                    "voice-service",
                    "from voice_reports.models import VoiceReport; import os; VoiceReport.objects.filter(pk=int(os.environ['P0C_REPORT'])).delete()",
                    {"P0C_REPORT": str(report_id)},
                ),
            )

        if dashboard_id is not None or question_ids:
            visualization_cleanup = """
import os
from visualization_api.models import VisualizationObjectOwnership
from visualization_api.services import get_metabase_service
cards = [int(v) for v in os.environ.get('P0C_CARDS', '').split(',') if v]
dashboards = [int(v) for v in os.environ.get('P0C_DASHBOARDS', '').split(',') if v]
service = get_metabase_service()
service.authenticate()
for object_id in dashboards: service.delete_dashboard(object_id)
for object_id in cards: service.delete_question(object_id)
VisualizationObjectOwnership.objects.filter(object_type='card', metabase_object_id__in=cards).delete()
VisualizationObjectOwnership.objects.filter(object_type='dashboard', metabase_object_id__in=dashboards).delete()
"""
            cleanup_step(
                "visualization/Metabase objects",
                lambda: django_shell(
                    "visualization-service",
                    visualization_cleanup,
                    {
                        "P0C_CARDS": ",".join(str(value) for value in question_ids),
                        "P0C_DASHBOARDS": "" if dashboard_id is None else str(dashboard_id),
                    },
                ),
            )

        if user_a is not None:
            query_cleanup = """
import os
from database.models import Database, AuthorizedQueryDefinition
from database.utils import ClickHouseClient, cleanup_database
for item in Database.objects.filter(manager=int(os.environ['P0C_USER'])):
    cleanup_database(item)
    item.delete()
expected_table = os.environ.get('P0C_EXPECTED_TABLE', '')
if expected_table: ClickHouseClient().drop_table('etl', expected_table)
if os.environ.get('P0C_WORKSPACE'): AuthorizedQueryDefinition.objects.filter(workspace_id=int(os.environ['P0C_WORKSPACE'])).delete()
"""
            cleanup_step(
                "Query metadata/ClickHouse",
                lambda: django_shell(
                    "query-service",
                    query_cleanup,
                    {
                        "P0C_USER": str(user_a),
                        "P0C_WORKSPACE": "" if workspace_a is None else str(workspace_a),
                        "P0C_EXPECTED_TABLE": expected_table_name,
                    },
                ),
            )

        if uploaded_path:
            file_cleanup = """
import os
from pathlib import Path
base = Path('/app/uploaded_files').resolve()
target = Path(os.environ['P0C_UPLOAD_PATH']).resolve()
target.relative_to(base)
assert os.environ['P0C_SUFFIX'] in target.name
target.unlink(missing_ok=True)
"""
            cleanup_step(
                "uploaded file",
                lambda: docker(
                    "exec",
                    "etl-connector",
                    "python",
                    "-c",
                    file_cleanup,
                    env={"P0C_UPLOAD_PATH": uploaded_path, "P0C_SUFFIX": suffix},
                ),
            )

        if workspace_a is not None and job_id:
            def cleanup_surreal() -> None:
                tables = (
                    "upload_logs",
                    "connection_logs",
                    "schema_logs",
                    "extract_logs",
                    "transform_logs",
                    "load_logs",
                    "connection_metadata",
                    "schema_metadata",
                    "extraction_metadata",
                    "cleaning_metadata",
                    "loading_metadata",
                )
                statements = " ".join(
                    f"DELETE {table} WHERE workspace_id = {workspace_a} AND ingestion_job_id = '{job_id}';"
                    for table in tables
                )
                response = requests.post(
                    "http://127.0.0.1:8008/sql",
                    headers={"surreal-ns": "bi_etl", "surreal-db": "etl_logs", "Accept": "application/json"},
                    auth=(config["SURREAL_USER"], config["SURREAL_PASS"]),
                    data=statements,
                    timeout=HTTP_TIMEOUT,
                )
                response.raise_for_status()

            cleanup_step("Surreal metadata", cleanup_surreal)

        if workspace_a is not None or workspace_b is not None:
            cleanup_step(
                "workspaces",
                lambda: django_shell(
                    "workspace-service",
                    "from workspace.models import Workspace; import os; Workspace.objects.filter(pk__in=[int(v) for v in os.environ['P0C_IDS'].split(',') if v]).delete()",
                    {"P0C_IDS": ",".join(str(value) for value in (workspace_a, workspace_b) if value is not None)},
                ),
            )

        if user_a is not None or user_b is not None:
            cleanup_step(
                "users",
                lambda: django_shell(
                    "auth-service",
                    "from users.models import User; import os; User.objects.filter(pk__in=[int(v) for v in os.environ['P0C_IDS'].split(',') if v]).delete()",
                    {"P0C_IDS": ",".join(str(value) for value in (user_a, user_b) if value is not None)},
                ),
            )

        if not cleanup_errors and user_a is not None:
            try:
                counts: list[int] = []
                counts.append(
                    int(
                        tagged(
                            django_shell(
                                "auth-service",
                                "from users.models import User; import os; print('P0C_COUNT:'+str(User.objects.filter(email__in=os.environ['P0C_EMAILS'].split(',')).count()))",
                                {"P0C_EMAILS": f"{email_a},{email_b}"},
                            ),
                            "P0C_COUNT:",
                        )
                    )
                )
                counts.append(
                    int(
                        tagged(
                            django_shell(
                                "workspace-service",
                                "from workspace.models import Workspace; import os; print('P0C_COUNT:'+str(Workspace.objects.filter(name__in=os.environ['P0C_NAMES'].split('|')).count()))",
                                {"P0C_NAMES": f"{workspace_name_a}|{workspace_name_b}"},
                            ),
                            "P0C_COUNT:",
                        )
                    )
                )
                query_count_code = "from database.models import Database, AuthorizedQueryDefinition; import os; print('P0C_COUNT:'+str(Database.objects.filter(manager=int(os.environ['P0C_USER'])).count()+AuthorizedQueryDefinition.objects.filter(workspace_id=int(os.environ['P0C_WORKSPACE'])).count()))"
                counts.append(
                    int(
                        tagged(
                            django_shell(
                                "query-service",
                                query_count_code,
                                {"P0C_USER": str(user_a), "P0C_WORKSPACE": str(workspace_a)},
                            ),
                            "P0C_COUNT:",
                        )
                    )
                )
                if report_id is not None:
                    counts.append(
                        int(
                            tagged(
                                django_shell(
                                    "voice-service",
                                    "from voice_reports.models import VoiceReport; import os; print('P0C_COUNT:'+str(VoiceReport.objects.filter(pk=int(os.environ['P0C_ID'])).count()))",
                                    {"P0C_ID": str(report_id)},
                                ),
                                "P0C_COUNT:",
                            )
                        )
                    )
                if any(counts):
                    raise RuntimeError(f"Durable cleanup counts were not zero: {counts}")
                cleanup_verified = True
                print("P0C_E2E_CLEANUP:PASS", flush=True)
            except Exception as exc:  # noqa: BLE001
                cleanup_errors.append(f"cleanup proof:{type(exc).__name__}")

        password = ""
        if cleanup_errors:
            raise RuntimeError("P0-C cleanup failed: " + ", ".join(cleanup_errors))
        if not cleanup_verified:
            raise RuntimeError("P0-C cleanup could not be proven.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
