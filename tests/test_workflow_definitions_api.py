from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

URL = "/api/workflow-definitions"
WORKFLOW_DEFINITION = {
    "name": "Laptop Request",
    "description": "Order a new laptop for the User",
    "confidence_threshold": "0.80",
    "steps": [
        {"name": "Get approval", "instructions": "Ask the User's manager to approve the order"},
        {"name": "Place order", "instructions": "Order the laptop from the approved vendor"},
    ],
    "required_inputs": [
        {"key": "budget", "description": "Maximum spend in USD", "type": "number"},
        {"key": "needed_by", "description": "Date the laptop is needed", "type": "date"},
    ],
    "sample_requests": ["My laptop died, I need a new one", "Can I get a MacBook?"],
}
CONTENT_FIELDS = [
    "description",
    "confidence_threshold",
    "steps",
    "required_inputs",
    "sample_requests",
]
CONTENT = {field: WORKFLOW_DEFINITION[field] for field in CONTENT_FIELDS}
LIST_LENGTH = 3


def create_workflow_definition(client: TestClient, name: str = "Laptop Request") -> dict:
    response = client.post(URL, json={**WORKFLOW_DEFINITION, "name": name})
    assert response.status_code == 201
    return response.json()


def get_workflow_definition(client: TestClient, definition_id: str) -> dict:
    response = client.get(f"{URL}/{definition_id}")
    assert response.status_code == 200
    return response.json()


def publish_version(
    client: TestClient, definition_id: str, base_version: int, **content: object
) -> dict:
    response = client.post(
        f"{URL}/{definition_id}/versions",
        json={**CONTENT, **content, "base_version": base_version},
    )
    assert response.status_code == 201
    return response.json()


def set_enabled(client: TestClient, definition_id: str, action: str) -> dict:
    response = client.post(f"{URL}/{definition_id}/{action}")
    assert response.status_code == 200
    return response.json()


def test_create_workflow_definition(client: TestClient) -> None:
    definition = create_workflow_definition(client)

    assert definition["name"] == WORKFLOW_DEFINITION["name"]
    assert definition["is_enabled"] is True
    assert definition["created_at"] is not None
    version = definition["current_version"]
    assert version["version_number"] == 1
    assert {field: version[field] for field in CONTENT_FIELDS} == {
        field: WORKFLOW_DEFINITION[field] for field in CONTENT_FIELDS
    }


def test_create_without_required_inputs(client: TestClient) -> None:
    response = client.post(URL, json={**WORKFLOW_DEFINITION, "required_inputs": []})

    assert response.status_code == 201
    assert response.json()["current_version"]["required_inputs"] == []


@pytest.mark.parametrize("threshold", ["0.01", "1.00"])
def test_create_accepts_threshold_boundaries(client: TestClient, threshold: str) -> None:
    response = client.post(URL, json={**WORKFLOW_DEFINITION, "confidence_threshold": threshold})

    assert response.status_code == 201
    assert response.json()["current_version"]["confidence_threshold"] == threshold


@pytest.mark.parametrize(
    "overrides",
    [
        {"name": ""},
        {"name": "x" * 101},
        {"description": "x" * 2001},
        {"confidence_threshold": "0"},
        {"confidence_threshold": "1.01"},
        {"confidence_threshold": "0.805"},
        {"steps": []},
        {"steps": [{"name": "Step", "instructions": "Do it"}] * 21},
        {"steps": [{"name": "Step", "instructions": ""}]},
        {"required_inputs": [WORKFLOW_DEFINITION["required_inputs"][0]] * 2},
        {"required_inputs": [{"key": "Budget", "description": "Spend", "type": "number"}]},
        {"required_inputs": [{"key": "budget", "description": "Spend", "type": "list"}]},
        {"sample_requests": []},
        {"sample_requests": ["Sample"] * 6},
        {"sample_requests": [""]},
    ],
    ids=[
        "empty name",
        "name too long",
        "description too long",
        "threshold zero",
        "threshold above one",
        "threshold three decimals",
        "no steps",
        "too many steps",
        "empty instructions",
        "duplicate input keys",
        "input key not snake_case",
        "unknown input type",
        "no sample requests",
        "too many sample requests",
        "empty sample request",
    ],
)
def test_create_rejects_invalid_body(client: TestClient, overrides: dict) -> None:
    response = client.post(URL, json={**WORKFLOW_DEFINITION, **overrides})
    assert response.status_code == 422


def test_create_rejects_missing_threshold(client: TestClient) -> None:
    body = {
        key: value for key, value in WORKFLOW_DEFINITION.items() if key != "confidence_threshold"
    }

    response = client.post(URL, json=body)
    assert response.status_code == 422


def test_create_duplicate_name_returns_409(client: TestClient) -> None:
    definition = create_workflow_definition(client)

    response = client.post(URL, json=WORKFLOW_DEFINITION)

    assert response.status_code == 409
    assert get_workflow_definition(client, definition["definition_id"]) == definition


def test_get_workflow_definition(client: TestClient) -> None:
    definition = create_workflow_definition(client)

    assert get_workflow_definition(client, definition["definition_id"]) == definition


def test_list_workflow_definitions(client: TestClient) -> None:
    definitions = [create_workflow_definition(client, f"Workflow {i}") for i in range(LIST_LENGTH)]

    response = client.get(URL)
    assert response.status_code == 200

    ids = {definition["definition_id"] for definition in response.json()["data"]}
    assert ids == {definition["definition_id"] for definition in definitions}


def test_list_pages_do_not_overlap(client: TestClient) -> None:
    definitions = [create_workflow_definition(client, f"Workflow {i}") for i in range(LIST_LENGTH)]

    first = client.get(URL, params={"limit": 2, "offset": 0}).json()["data"]
    second = client.get(URL, params={"limit": 2, "offset": 2}).json()["data"]

    assert len(first) == 2
    assert len(second) == 1
    ids = [definition["definition_id"] for definition in first + second]
    assert sorted(ids) == sorted(definition["definition_id"] for definition in definitions)


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"offset": -1}])
def test_list_rejects_invalid_pagination(client: TestClient, params: dict) -> None:
    response = client.get(URL, params=params)
    assert response.status_code == 422


def test_get_workflow_definition_version(client: TestClient) -> None:
    definition = create_workflow_definition(client)

    response = client.get(f"{URL}/{definition['definition_id']}/versions/1")

    assert response.status_code == 200
    assert response.json() == definition["current_version"]


def test_unknown_version_returns_404(client: TestClient) -> None:
    definition = create_workflow_definition(client)

    response = client.get(f"{URL}/{definition['definition_id']}/versions/2")
    assert response.status_code == 404


def test_version_number_below_one_returns_422(client: TestClient) -> None:
    definition = create_workflow_definition(client)

    response = client.get(f"{URL}/{definition['definition_id']}/versions/0")
    assert response.status_code == 422


def test_publish_version(client: TestClient) -> None:
    definition = create_workflow_definition(client)

    version = publish_version(
        client, definition["definition_id"], 1, description="Order a laptop or a tablet"
    )

    assert version["version_number"] == 2
    assert {field: version[field] for field in CONTENT_FIELDS} == {
        **CONTENT,
        "description": "Order a laptop or a tablet",
    }
    assert get_workflow_definition(client, definition["definition_id"]) == {
        **definition,
        "current_version": version,
    }


def test_publish_keeps_previous_version(client: TestClient) -> None:
    definition = create_workflow_definition(client)
    publish_version(client, definition["definition_id"], 1, confidence_threshold="0.90")

    response = client.get(f"{URL}/{definition['definition_id']}/versions/1")

    assert response.status_code == 200
    assert response.json() == definition["current_version"]


def test_current_version_is_highest(client: TestClient) -> None:
    definition = create_workflow_definition(client)
    publish_version(client, definition["definition_id"], 1)
    latest = publish_version(client, definition["definition_id"], 2)

    response = client.get(URL)
    assert response.status_code == 200

    [listed] = response.json()["data"]
    assert latest["version_number"] == 3
    assert listed["current_version"] == latest
    assert get_workflow_definition(client, definition["definition_id"])["current_version"] == latest


def test_publish_accepts_identical_content(client: TestClient) -> None:
    definition = create_workflow_definition(client)

    version = publish_version(client, definition["definition_id"], 1)

    assert version["version_number"] == 2
    assert {field: version[field] for field in CONTENT_FIELDS} == CONTENT


@pytest.mark.parametrize("base_version", [1, 3], ids=["stale", "ahead of current"])
def test_publish_rejects_base_version_not_current(client: TestClient, base_version: int) -> None:
    definition = create_workflow_definition(client)
    current = publish_version(client, definition["definition_id"], 1)

    response = client.post(
        f"{URL}/{definition['definition_id']}/versions",
        json={**CONTENT, "description": "Lost edit", "base_version": base_version},
    )

    assert response.status_code == 409
    assert (
        get_workflow_definition(client, definition["definition_id"])["current_version"] == current
    )


@pytest.mark.parametrize(
    "body",
    [
        CONTENT,
        {**CONTENT, "base_version": 0},
        {**CONTENT, "base_version": "latest"},
        {**CONTENT, "steps": [], "base_version": 1},
    ],
    ids=["missing base_version", "base_version zero", "base_version not a number", "no steps"],
)
def test_publish_rejects_invalid_body(client: TestClient, body: dict) -> None:
    definition = create_workflow_definition(client)

    response = client.post(f"{URL}/{definition['definition_id']}/versions", json=body)

    assert response.status_code == 422
    assert get_workflow_definition(client, definition["definition_id"]) == definition


def test_rename_workflow_definition(client: TestClient) -> None:
    definition = create_workflow_definition(client)

    response = client.patch(f"{URL}/{definition['definition_id']}", json={"name": "Laptop Order"})

    assert response.status_code == 200
    renamed = get_workflow_definition(client, definition["definition_id"])
    assert renamed == {**definition, "name": "Laptop Order"}


def test_patch_cannot_change_content_or_state(client: TestClient) -> None:
    definition = create_workflow_definition(client)

    response = client.patch(
        f"{URL}/{definition['definition_id']}",
        json={"description": "Changed", "confidence_threshold": "0.10", "is_enabled": False},
    )

    assert response.status_code == 200
    assert get_workflow_definition(client, definition["definition_id"]) == definition


def test_rename_to_taken_name_returns_409(client: TestClient) -> None:
    definition = create_workflow_definition(client)
    create_workflow_definition(client, "Monitor Request")

    response = client.patch(
        f"{URL}/{definition['definition_id']}", json={"name": "Monitor Request"}
    )

    assert response.status_code == 409
    assert get_workflow_definition(client, definition["definition_id"]) == definition


def test_patch_rejects_null_name(client: TestClient) -> None:
    definition = create_workflow_definition(client)

    response = client.patch(f"{URL}/{definition['definition_id']}", json={"name": None})
    assert response.status_code == 422


def test_disable_workflow_definition(client: TestClient) -> None:
    definition = create_workflow_definition(client)

    disabled = set_enabled(client, definition["definition_id"], "disable")

    assert disabled == {**definition, "is_enabled": False}
    assert get_workflow_definition(client, definition["definition_id"]) == disabled


def test_enable_workflow_definition(client: TestClient) -> None:
    definition = create_workflow_definition(client)
    set_enabled(client, definition["definition_id"], "disable")

    enabled = set_enabled(client, definition["definition_id"], "enable")

    assert enabled == definition
    assert get_workflow_definition(client, definition["definition_id"]) == definition


@pytest.mark.parametrize(
    ("actions", "is_enabled"),
    [(["disable", "disable"], False), (["enable"], True)],
    ids=["disable twice", "enable when enabled"],
)
def test_repeated_action_succeeds(client: TestClient, actions: list[str], is_enabled: bool) -> None:
    definition = create_workflow_definition(client)

    for action in actions:
        result = set_enabled(client, definition["definition_id"], action)

    assert result == {**definition, "is_enabled": is_enabled}


def test_disabled_workflow_definition_is_still_readable(client: TestClient) -> None:
    definition = create_workflow_definition(client)
    disabled = set_enabled(client, definition["definition_id"], "disable")

    response_list = client.get(URL)
    assert response_list.status_code == 200
    assert response_list.json()["data"] == [disabled]

    response_version = client.get(f"{URL}/{definition['definition_id']}/versions/1")
    assert response_version.status_code == 200
    assert response_version.json() == definition["current_version"]


def test_publish_version_while_disabled(client: TestClient) -> None:
    definition = create_workflow_definition(client)
    set_enabled(client, definition["definition_id"], "disable")

    version = publish_version(client, definition["definition_id"], 1)

    assert get_workflow_definition(client, definition["definition_id"]) == {
        **definition,
        "is_enabled": False,
        "current_version": version,
    }


def test_disabled_name_stays_reserved(client: TestClient) -> None:
    definition = create_workflow_definition(client)
    set_enabled(client, definition["definition_id"], "disable")

    response = client.post(URL, json=WORKFLOW_DEFINITION)
    assert response.status_code == 409


def test_unknown_workflow_definition_returns_404(client: TestClient) -> None:
    definition_id = uuid4()

    response_get = client.get(f"{URL}/{definition_id}")
    assert response_get.status_code == 404

    response_patch = client.patch(f"{URL}/{definition_id}", json={"name": "Laptop Order"})
    assert response_patch.status_code == 404

    response_version = client.get(f"{URL}/{definition_id}/versions/1")
    assert response_version.status_code == 404

    response_publish = client.post(
        f"{URL}/{definition_id}/versions", json={**CONTENT, "base_version": 1}
    )
    assert response_publish.status_code == 404

    for action in ["disable", "enable"]:
        response_action = client.post(f"{URL}/{definition_id}/{action}")
        assert response_action.status_code == 404


def test_malformed_workflow_definition_id_returns_422(client: TestClient) -> None:
    malformed_id = "123abc"

    response_get = client.get(f"{URL}/{malformed_id}")
    assert response_get.status_code == 422

    response_version = client.get(f"{URL}/{malformed_id}/versions/1")
    assert response_version.status_code == 422

    response_publish = client.post(
        f"{URL}/{malformed_id}/versions", json={**CONTENT, "base_version": 1}
    )
    assert response_publish.status_code == 422

    for action in ["disable", "enable"]:
        response_action = client.post(f"{URL}/{malformed_id}/{action}")
        assert response_action.status_code == 422
