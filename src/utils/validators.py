def assert_has_fields(body: dict, required_fields, context: str = "response") -> None:
    missing = [f for f in required_fields if f not in body]
    assert not missing, f"{context} missing required fields {missing}. Full body: {body}"


def assert_status(response, expected_status: int, context: str = "") -> None:
    assert response.status_code == expected_status, (
        f"{context} Expected HTTP {expected_status} but got {response.status_code}. "
        f"Response body: {response.text}"
    )
