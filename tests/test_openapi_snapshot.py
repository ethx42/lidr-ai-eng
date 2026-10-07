import json
from pathlib import Path

import pytest
from pydantic import BaseModel

from app.main import create_app
from app.routers.estimations import example_response
from app.schemas.context import ContextResponse, ReferenceView
from app.schemas.estimation import CallMetrics, EstimateResponse, Usage
from app.schemas.stream import ErrorEvent, PartialEvent, StatusEvent


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


def test_stream_operation_documents_every_event_payload() -> None:
    operation = create_app().openapi()["paths"]["/api/v1/estimate/stream"]["post"]
    content = operation["responses"]["200"]["content"]["text/event-stream"]
    refs = {item["$ref"].rsplit("/", 1)[1] for item in content["schema"]["oneOf"]}
    assert refs == {"StatusEvent", "PartialEvent", "EstimateResponse", "ErrorEvent"}
    assert operation["responses"]["422"]


@pytest.mark.parametrize("path", ["/api/v1/estimate", "/api/v1/estimate/stream"])
def test_estimate_operations_accept_refresh(path: str) -> None:
    [param] = create_app().openapi()["paths"][path]["post"]["parameters"]
    schema = param["schema"]
    assert (param["name"], param["in"], param["required"]) == ("refresh", "query", False)
    assert (schema["type"], schema["default"]) == ("boolean", False)
