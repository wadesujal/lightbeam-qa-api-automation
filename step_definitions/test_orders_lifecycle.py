"""Order state machine, read-model integrity, and cancellation.

Kept as direct pytest functions rather than YAML cases (like the reference
framework's reliability/concurrency tests) because each scenario's logic --
when to poll, how long to wait, what to do with the result -- isn't
naturally data, it's control flow.
"""

import time

import pytest

from utilities.payload_builders import compute_expected_total, create_order_payload
from utilities.polling import PollTimeoutError, wait_for_condition
from utilities.soft_assert import SoftAssert

pytestmark = pytest.mark.orders

# Server-side transition threshold, read from mock-server/server.js: an order
# stays PENDING until 5s after creation. Named here (rather than inlined) so
# the read-only test below can prove it stayed inside that window.
PENDING_WINDOW_SECONDS = 5.0


@pytest.mark.smoke
@pytest.mark.title("Validate that the orders API returns 404 for an order that does not exist")
def test_get_nonexistent_order_returns_404(order_client):
    response = order_client.get_order("ORD-99999999")
    assert response.status_code == 404, response.text


@pytest.mark.title("Validate that the orders API returns 401 for an unauthenticated read request")
def test_get_order_without_auth_returns_401(anonymous_order_client):
    response = anonymous_order_client.get_order("ORD-00000")
    assert response.status_code == 401, response.text


@pytest.mark.title("Validate that the orders API returns 401 for an unauthenticated cancel request")
def test_cancel_order_without_auth_returns_401(anonymous_order_client):
    """DELETE is a destructive operation, so its 401 path matters more than
    the read paths' -- an unauthenticated caller must never be able to
    cancel someone else's order."""
    response = anonymous_order_client.delete_order("ORD-00000")
    assert response.status_code == 401, response.text
    assert "error" in response.json()


@pytest.mark.smoke
@pytest.mark.title("Validate that the orders API returns every persisted field for a created order")
def test_get_order_returns_the_persisted_order(order_client, step_log):
    """POST returns a summary; GET must return the full persisted resource.
    Nothing else in the suite proves the server actually stored what it was
    sent -- the state-machine tests only ever look at `status`."""
    sa = SoftAssert(step_log)
    payload = create_order_payload()

    with step_log.step("POST /orders"):
        created = order_client.create_order(payload)
    assert created.status_code == 202, created.text
    created_body = created.json()

    with step_log.step("GET /orders/:orderId"):
        response = order_client.get_order(created_body["orderId"])

    sa.equals(response.status_code, 200, "status code")
    body = response.json()

    sa.equals(body.get("orderId"), created_body["orderId"], "orderId")
    sa.equals(body.get("customerId"), payload["customerId"], "customerId round-trips")
    sa.equals(body.get("items"), payload["items"], "items round-trip unchanged")
    sa.equals(
        body.get("shippingAddress"), payload["shippingAddress"], "shippingAddress round-trips"
    )
    sa.equals(
        body.get("createdAt"), created_body["createdAt"], "createdAt matches the creation response"
    )
    sa.equals(
        body.get("totalAmount"),
        pytest.approx(compute_expected_total(payload["items"])),
        "totalAmount matches independently computed total",
    )
    sa.check(
        body.get("status") in {"PENDING", "PROCESSING", "COMPLETED"}, "status is a known state"
    )
    sa.assert_all()


@pytest.mark.title("Validate that repeated reads do not advance the order state")
def test_get_order_does_not_itself_mutate_state(order_client):
    """Reading must not drive the state machine -- transitions are a function
    of elapsed wall-clock time, not of how many times the order was fetched.

    Deterministic by construction: several reads are issued back-to-back
    immediately after creation and all must still report PENDING. If the
    machine was slow enough that the reads spilled past the server's 5s
    PENDING window, the premise no longer holds and the test skips rather
    than reporting a false failure.
    """
    order_id = order_client.create_order(create_order_payload()).json()["orderId"]
    started = time.monotonic()

    statuses = [order_client.get_order(order_id).json()["status"] for _ in range(6)]
    elapsed = time.monotonic() - started

    if elapsed >= PENDING_WINDOW_SECONDS:
        pytest.skip(
            f"6 reads took {elapsed:.1f}s, past the server's {PENDING_WINDOW_SECONDS}s PENDING "
            f"window -- environment too slow to isolate read-driven mutation"
        )

    assert statuses == ["PENDING"] * len(statuses), (
        f"Repeated reads inside the PENDING window returned {statuses} -- status must be "
        f"driven by elapsed time since creation, not by the act of reading it"
    )


@pytest.mark.slow
@pytest.mark.title(
    "Validate that an order advances PENDING to PROCESSING to COMPLETED on elapsed time"
)
def test_order_transitions_pending_to_processing_to_completed(order_client, settings, step_log):
    sa = SoftAssert(step_log)
    order_id = order_client.create_order(create_order_payload()).json()["orderId"]

    def poll():
        return order_client.get_order(order_id).json()

    with step_log.step("wait for PROCESSING"):
        processing = wait_for_condition(
            poll_fn=poll,
            predicate=lambda o: o["status"] == "PROCESSING",
            timeout=settings.order_poll_timeout_seconds,
            interval=settings.order_poll_interval_seconds,
            description=f"order {order_id} to reach PROCESSING",
        )
    sa.equals(processing.value["status"], "PROCESSING", "status after first transition")
    sa.equals(processing.value["orderId"], order_id, "orderId unchanged")

    with step_log.step("wait for COMPLETED"):
        completed = wait_for_condition(
            poll_fn=poll,
            predicate=lambda o: o["status"] == "COMPLETED",
            timeout=settings.order_poll_timeout_seconds,
            interval=settings.order_poll_interval_seconds,
            description=f"order {order_id} to reach COMPLETED",
        )
    sa.equals(completed.value["status"], "COMPLETED", "final status")
    sa.assert_all()


@pytest.mark.smoke
@pytest.mark.title("Validate that the orders API cancels an order while it is PENDING")
def test_cancel_order_while_pending_succeeds(order_client):
    order_id = order_client.create_order(create_order_payload()).json()["orderId"]
    response = order_client.delete_order(order_id)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "CANCELLED"


@pytest.mark.slow
@pytest.mark.title("Validate that the orders API cancels an order while it is PROCESSING")
def test_cancel_order_while_processing_succeeds(order_client, settings):
    order_id = order_client.create_order(create_order_payload()).json()["orderId"]
    wait_for_condition(
        poll_fn=lambda: order_client.get_order(order_id).json(),
        predicate=lambda o: o["status"] == "PROCESSING",
        timeout=settings.order_poll_timeout_seconds,
        interval=settings.order_poll_interval_seconds,
        description=f"order {order_id} to reach PROCESSING before cancelling",
    )
    response = order_client.delete_order(order_id)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "CANCELLED"


@pytest.mark.slow
@pytest.mark.title("Validate that the orders API returns 409 when cancelling a COMPLETED order")
def test_cancel_order_after_completed_returns_409(order_client, settings):
    order_id = order_client.create_order(create_order_payload()).json()["orderId"]
    wait_for_condition(
        poll_fn=lambda: order_client.get_order(order_id).json(),
        predicate=lambda o: o["status"] == "COMPLETED",
        timeout=settings.order_poll_timeout_seconds,
        interval=settings.order_poll_interval_seconds,
        description=f"order {order_id} to reach COMPLETED before cancelling",
    )
    response = order_client.delete_order(order_id)
    assert response.status_code == 409, response.text
    assert "error" in response.json()


@pytest.mark.title(
    "Validate that cancelling an already-cancelled order still returns 200 CANCELLED"
)
def test_cancelling_twice_is_idempotent(order_client):
    """Confirmed server behavior: CANCELLED is sticky, and DELETE only
    rejects with 409 once status is COMPLETED -- so a second cancel succeeds again."""
    order_id = order_client.create_order(create_order_payload()).json()["orderId"]
    first = order_client.delete_order(order_id)
    second = order_client.delete_order(order_id)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json()["status"] == "CANCELLED"


@pytest.mark.title(
    "Validate that the orders API returns 404 when cancelling an order that does not exist"
)
def test_cancel_nonexistent_order_returns_404(order_client):
    response = order_client.delete_order("ORD-99999999")
    assert response.status_code == 404, response.text


@pytest.mark.slow
@pytest.mark.title("Validate that a CANCELLED order never advances to PROCESSING or COMPLETED")
def test_cancelled_order_never_advances_state(order_client, settings):
    """Confirmed server behavior: getUpdatedOrder skips the time-based
    transition once status is CANCELLED, so it must never flip forward again.

    The observation window comes from settings (`cancelled_observation_seconds`,
    default 18s) rather than an inline literal: it only proves anything if it
    outlasts the server's 15s PROCESSING->COMPLETED threshold, so it has to be
    tunable alongside the other timing config."""
    order_id = order_client.create_order(create_order_payload()).json()["orderId"]
    order_client.delete_order(order_id)

    observation_seconds = settings.cancelled_observation_seconds
    assert observation_seconds > 15, (
        f"cancelled_observation_seconds={observation_seconds} does not outlast the server's "
        f"15s COMPLETED threshold, so this test would pass without proving anything"
    )

    with pytest.raises(PollTimeoutError):
        wait_for_condition(
            poll_fn=lambda: order_client.get_order(order_id).json(),
            predicate=lambda o: o["status"] != "CANCELLED",
            timeout=observation_seconds,
            interval=settings.order_poll_interval_seconds,
            description="order to leave CANCELLED (it must not)",
        )

    final = order_client.get_order(order_id).json()
    assert final["status"] == "CANCELLED"
