"""Order state machine and cancellation. Kept as direct pytest functions
rather than YAML cases (like the reference framework's reliability/
concurrency tests) because each scenario's logic -- when to poll, how
long to wait, what to do with the result -- isn't naturally data, it's
control flow."""

import pytest

from utilities.api_client import OrderClient
from utilities.payload_builders import create_order_payload
from utilities.polling import PollTimeoutError, wait_for_condition
from utilities.soft_assert import SoftAssert

pytestmark = pytest.mark.orders


@pytest.mark.smoke
def test_get_nonexistent_order_returns_404(order_client):
    response = order_client.get_order("ORD-99999999")
    assert response.status_code == 404, response.text


def test_get_order_without_auth_returns_401(settings):
    client = OrderClient(settings=settings, token=None)
    response = client.get_order("ORD-00000")
    assert response.status_code == 401, response.text


def test_get_order_does_not_itself_mutate_state(order_client):
    order_id = order_client.create_order(create_order_payload()).json()["orderId"]
    first = order_client.get_order(order_id).json()
    second = order_client.get_order(order_id).json()
    assert first["status"] == second["status"], (
        "Two GETs milliseconds apart returned different statuses -- status must be "
        "driven by elapsed wall-clock time, not by the act of reading it"
    )


@pytest.mark.slow
def test_order_transitions_pending_to_processing_to_completed(order_client, settings, step_log):
    sa = SoftAssert(step_log)
    order_id = order_client.create_order(create_order_payload()).json()["orderId"]

    def poll():
        return order_client.get_order(order_id).json()

    with step_log.step("wait for PROCESSING"):
        processing = wait_for_condition(
            poll_fn=poll, predicate=lambda o: o["status"] == "PROCESSING",
            timeout=settings.order_poll_timeout_seconds, interval=settings.order_poll_interval_seconds,
            description=f"order {order_id} to reach PROCESSING",
        )
    sa.equals(processing.value["status"], "PROCESSING", "status after first transition")
    sa.equals(processing.value["orderId"], order_id, "orderId unchanged")

    with step_log.step("wait for COMPLETED"):
        completed = wait_for_condition(
            poll_fn=poll, predicate=lambda o: o["status"] == "COMPLETED",
            timeout=settings.order_poll_timeout_seconds, interval=settings.order_poll_interval_seconds,
            description=f"order {order_id} to reach COMPLETED",
        )
    sa.equals(completed.value["status"], "COMPLETED", "final status")
    sa.assert_all()


@pytest.mark.smoke
def test_cancel_order_while_pending_succeeds(order_client):
    order_id = order_client.create_order(create_order_payload()).json()["orderId"]
    response = order_client.delete_order(order_id)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "CANCELLED"


@pytest.mark.slow
def test_cancel_order_while_processing_succeeds(order_client, settings):
    order_id = order_client.create_order(create_order_payload()).json()["orderId"]
    wait_for_condition(
        poll_fn=lambda: order_client.get_order(order_id).json(),
        predicate=lambda o: o["status"] == "PROCESSING",
        timeout=settings.order_poll_timeout_seconds, interval=settings.order_poll_interval_seconds,
        description=f"order {order_id} to reach PROCESSING before cancelling",
    )
    response = order_client.delete_order(order_id)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "CANCELLED"


@pytest.mark.slow
def test_cancel_order_after_completed_returns_409(order_client, settings):
    order_id = order_client.create_order(create_order_payload()).json()["orderId"]
    wait_for_condition(
        poll_fn=lambda: order_client.get_order(order_id).json(),
        predicate=lambda o: o["status"] == "COMPLETED",
        timeout=settings.order_poll_timeout_seconds, interval=settings.order_poll_interval_seconds,
        description=f"order {order_id} to reach COMPLETED before cancelling",
    )
    response = order_client.delete_order(order_id)
    assert response.status_code == 409, response.text
    assert "error" in response.json()


def test_cancelling_twice_is_idempotent(order_client):
    """Confirmed server behavior: CANCELLED is sticky, and DELETE only
    rejects with 409 once status is COMPLETED -- so a second cancel succeeds again."""
    order_id = order_client.create_order(create_order_payload()).json()["orderId"]
    first = order_client.delete_order(order_id)
    second = order_client.delete_order(order_id)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json()["status"] == "CANCELLED"


def test_cancel_nonexistent_order_returns_404(order_client):
    response = order_client.delete_order("ORD-99999999")
    assert response.status_code == 404, response.text


@pytest.mark.slow
def test_cancelled_order_never_advances_state(order_client):
    """Confirmed server behavior: getUpdatedOrder skips the time-based
    transition once status is CANCELLED, so it must never flip forward again."""
    order_id = order_client.create_order(create_order_payload()).json()["orderId"]
    order_client.delete_order(order_id)

    with pytest.raises(PollTimeoutError):
        wait_for_condition(
            poll_fn=lambda: order_client.get_order(order_id).json(),
            predicate=lambda o: o["status"] != "CANCELLED",
            timeout=18, interval=2,
            description="order to leave CANCELLED (it must not)",
        )

    final = order_client.get_order(order_id).json()
    assert final["status"] == "CANCELLED"
