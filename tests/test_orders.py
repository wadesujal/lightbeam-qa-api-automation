import pytest

from config.config import config
from src.builders.payload_builders import compute_expected_total, create_order_payload
from src.clients.order_client import OrderClient
from src.utils.polling import PollTimeoutError, wait_for_condition


pytestmark = pytest.mark.orders


class TestCreateOrder:
    @pytest.mark.smoke
    def test_create_order_returns_202_with_pending_status(self, order_client):
        payload = create_order_payload()
        response = order_client.create_order(payload)

        assert response.status_code == 202, response.text
        body = response.json()
        for field in ("orderId", "status", "totalAmount", "createdAt"):
            assert field in body, f"Missing '{field}' in create-order response: {body}"
        assert body["status"] == "PENDING"

    @pytest.mark.smoke
    def test_total_amount_is_calculated_correctly(self, order_client):
        payload = create_order_payload()
        response = order_client.create_order(payload)
        body = response.json()

        expected_total = compute_expected_total(payload["items"])
        assert body["totalAmount"] == pytest.approx(expected_total), (
            f"Server totalAmount {body['totalAmount']} != independently computed "
            f"{expected_total} for items {payload['items']}"
        )

    def test_total_amount_with_decimal_pricing_is_correct(self, order_client):
        items = [{"sku": "SKU-X", "quantity": 3, "unitPrice": 9.995}]
        payload = create_order_payload(items=items)
        body = order_client.create_order(payload).json()
        assert body["totalAmount"] == pytest.approx(compute_expected_total(items))

    def test_create_order_without_correlation_id_returns_400(self, order_client):
        response = order_client.create_order(create_order_payload(), include_correlation_id=False)
        assert response.status_code == 400, response.text
        assert "error" in response.json()

    def test_create_order_without_auth_returns_401(self):
        client = OrderClient(token=None)
        response = client.create_order(create_order_payload())
        assert response.status_code == 401, response.text

    @pytest.mark.parametrize("missing_field", ["customerId", "items", "shippingAddress"])
    def test_create_order_missing_required_field_returns_400(self, order_client, missing_field):
        payload = create_order_payload()
        del payload[missing_field]
        response = order_client.create_order(payload)
        assert response.status_code == 400, response.text

    def test_create_order_with_empty_items_returns_400(self, order_client):
        response = order_client.create_order(create_order_payload(items=[]))
        assert response.status_code == 400, response.text


@pytest.mark.slow
class TestOrderStateTransition:
    def test_order_transitions_pending_to_processing_to_completed(self, order_client):
        order_id = order_client.create_order(create_order_payload()).json()["orderId"]

        def poll():
            return order_client.get_order(order_id).json()

        processing = wait_for_condition(
            poll_fn=poll,
            predicate=lambda o: o["status"] == "PROCESSING",
            timeout=config.ORDER_POLL_TIMEOUT,
            interval=config.ORDER_POLL_INTERVAL,
            description=f"order {order_id} to reach PROCESSING",
        )
        assert processing.value["status"] == "PROCESSING"
        assert processing.value["orderId"] == order_id

        completed = wait_for_condition(
            poll_fn=poll,
            predicate=lambda o: o["status"] == "COMPLETED",
            timeout=config.ORDER_POLL_TIMEOUT,
            interval=config.ORDER_POLL_INTERVAL,
            description=f"order {order_id} to reach COMPLETED",
        )
        assert completed.value["status"] == "COMPLETED"


class TestOrderRetrieval:
    @pytest.mark.smoke
    def test_get_nonexistent_order_returns_404(self, order_client):
        response = order_client.get_order("ORD-99999999")
        assert response.status_code == 404, response.text

    def test_get_order_without_auth_returns_401(self):
        client = OrderClient(token=None)
        response = client.get_order("ORD-00000")
        assert response.status_code == 401, response.text

    def test_get_order_does_not_itself_mutate_state(self, order_client):
        order_id = order_client.create_order(create_order_payload()).json()["orderId"]
        first = order_client.get_order(order_id).json()
        second = order_client.get_order(order_id).json()
        assert first["status"] == second["status"], (
            "Two GETs milliseconds apart returned different statuses -- status must be "
            "driven by elapsed wall-clock time, not by the act of reading it"
        )


class TestCancelOrder:
    @pytest.mark.smoke
    def test_cancel_order_while_pending_succeeds(self, order_client):
        order_id = order_client.create_order(create_order_payload()).json()["orderId"]
        response = order_client.delete_order(order_id)
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "CANCELLED"

    @pytest.mark.slow
    def test_cancel_order_while_processing_succeeds(self, order_client):
        order_id = order_client.create_order(create_order_payload()).json()["orderId"]
        wait_for_condition(
            poll_fn=lambda: order_client.get_order(order_id).json(),
            predicate=lambda o: o["status"] == "PROCESSING",
            timeout=config.ORDER_POLL_TIMEOUT,
            interval=config.ORDER_POLL_INTERVAL,
            description=f"order {order_id} to reach PROCESSING before cancelling",
        )
        response = order_client.delete_order(order_id)
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "CANCELLED"

    @pytest.mark.slow
    def test_cancel_order_after_completed_returns_409(self, order_client):
        order_id = order_client.create_order(create_order_payload()).json()["orderId"]
        wait_for_condition(
            poll_fn=lambda: order_client.get_order(order_id).json(),
            predicate=lambda o: o["status"] == "COMPLETED",
            timeout=config.ORDER_POLL_TIMEOUT,
            interval=config.ORDER_POLL_INTERVAL,
            description=f"order {order_id} to reach COMPLETED before cancelling",
        )
        response = order_client.delete_order(order_id)
        assert response.status_code == 409, response.text
        assert "error" in response.json()

    def test_cancelling_twice_is_idempotent(self, order_client):
        """Confirmed server behavior: CANCELLED is sticky, and DELETE only rejects
        with 409 when status is already COMPLETED -- so a second cancel succeeds again."""
        order_id = order_client.create_order(create_order_payload()).json()["orderId"]
        first = order_client.delete_order(order_id)
        second = order_client.delete_order(order_id)

        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text
        assert second.json()["status"] == "CANCELLED"

    def test_cancel_nonexistent_order_returns_404(self, order_client):
        response = order_client.delete_order("ORD-99999999")
        assert response.status_code == 404, response.text

    @pytest.mark.slow
    def test_cancelled_order_never_advances_state(self, order_client):
        """Confirmed server behavior: getUpdatedOrder skips the time-based transition
        once status is CANCELLED, so it must never flip to PROCESSING/COMPLETED afterward."""
        order_id = order_client.create_order(create_order_payload()).json()["orderId"]
        order_client.delete_order(order_id)

        with pytest.raises(PollTimeoutError):
            wait_for_condition(
                poll_fn=lambda: order_client.get_order(order_id).json(),
                predicate=lambda o: o["status"] != "CANCELLED",
                timeout=18,
                interval=2,
                description="order to leave CANCELLED (it must not)",
            )

        final = order_client.get_order(order_id).json()
        assert final["status"] == "CANCELLED"
