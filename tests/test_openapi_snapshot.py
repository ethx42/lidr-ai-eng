import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from app.config import Settings
from app.main import create_app
from app.routers.estimations import example_response
from app.schemas.context import ContextResponse, ReferenceView
from app.schemas.estimation import CallMetrics, EstimateResponse, Usage
from app.schemas.session import SessionView, TurnResponse
from app.schemas.stream import ErrorEvent, PartialEvent, StatusEvent
from app.sessions import ProjectMetadata

ESTIMATE_PATHS = ["/api/v1/estimate", "/api/v1/estimate/stream"]
SESSION_TURN_PATHS = ["/sessions/{session_id}/estimate", "/sessions/{session_id}/estimate/stream"]


def test_contract_snapshot_is_current() -> None:
    current = create_app().openapi()
    committed = json.loads(Path("contracts/openapi.json").read_text())
    assert current == committed, "Run `make openapi` and commit contracts/openapi.json"


def test_stream_event_models_are_in_the_contract() -> None:
    schemas = create_app().openapi()["components"]["schemas"]
    assert {"StatusEvent", "PartialEvent", "ErrorEvent", "EstimateResponse"} <= set(schemas)


@pytest.mark.parametrize(
    "model",
    [
        EstimateResponse,
        CallMetrics,
        Usage,
        StatusEvent,
        PartialEvent,
        ErrorEvent,
        ContextResponse,
        ReferenceView,
        TurnResponse,
        SessionView,
        ProjectMetadata,
    ],
)
def test_always_serialized_fields_are_required(model: type[BaseModel]) -> None:
    schema = create_app().openapi()["components"]["schemas"][model.__name__]
    assert set(schema["required"]) == set(model.model_fields)


def test_contract_follows_one_null_default_convention() -> None:
    # FastAPI dumps its schemas without None values; the merged event schemas must match.
    assert '"default": null' not in Path("contracts/openapi.json").read_text()


def test_documented_example_keeps_every_field() -> None:
    # FastAPI drops None values from examples, which would leave required keys out.
    operation = create_app().openapi()["paths"]["/api/v1/estimate"]["post"]
    assert operation["responses"]["200"]["content"]["application/json"]["example"] == (
        example_response()
    )


def test_documented_example_names_the_default_prompt_version() -> None:
    # The code default, never the environment the snapshot was exported from.
    committed = json.loads(Path("contracts/openapi.json").read_text())
    operation = committed["paths"]["/api/v1/estimate"]["post"]
    example = operation["responses"]["200"]["content"]["application/json"]["example"]
    assert example["prompt_version"] == Settings.model_fields["prompt_version"].default


def test_stream_operation_documents_every_event_payload() -> None:
    operation = create_app().openapi()["paths"]["/api/v1/estimate/stream"]["post"]
    content = operation["responses"]["200"]["content"]["text/event-stream"]
    refs = {item["$ref"].rsplit("/", 1)[1] for item in content["schema"]["oneOf"]}
    assert refs == {"StatusEvent", "PartialEvent", "EstimateResponse", "ErrorEvent"}
    assert operation["responses"]["422"]


def test_session_stream_operation_documents_every_event_payload() -> None:
    operation = create_app().openapi()["paths"][SESSION_TURN_PATHS[1]]["post"]
    content = operation["responses"]["200"]["content"]["text/event-stream"]
    refs = {item["$ref"].rsplit("/", 1)[1] for item in content["schema"]["oneOf"]}
    assert refs == {"StatusEvent", "PartialEvent", "TurnResponse", "ErrorEvent"}


@pytest.mark.parametrize("path", SESSION_TURN_PATHS)
def test_session_turns_take_a_multipart_body(path: str) -> None:
    operation = create_app().openapi()["paths"][path]["post"]
    assert list(operation["requestBody"]["content"]) == ["multipart/form-data"]
    assert {"404", "409", "413", "422", "503"} <= set(operation["responses"])


def query_params(path: str) -> dict[str, dict[str, Any]]:  # Any: OpenAPI parameter objects are JSON
    params = create_app().openapi()["paths"][path]["post"]["parameters"]
    assert {p["name"] for p in params} == {"refresh", "prompt_version"}
    assert len(params) == 2
    return {p["name"]: p for p in params}


@pytest.mark.parametrize("path", ESTIMATE_PATHS)
def test_estimate_operations_accept_refresh(path: str) -> None:
    param = query_params(path)["refresh"]
    schema = param["schema"]
    assert (param["name"], param["in"], param["required"]) == ("refresh", "query", False)
    assert (schema["type"], schema["default"]) == ("boolean", False)


@pytest.mark.parametrize("path", ESTIMATE_PATHS)
def test_estimate_operations_accept_prompt_version(path: str) -> None:
    param = query_params(path)["prompt_version"]
    assert (param["in"], param["required"]) == ("query", False)
    assert "default" not in param["schema"]  # omitted: the PROMPT_VERSION setting
