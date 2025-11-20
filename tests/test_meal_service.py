"""Unit tests for the meal service.

These tests use FastAPI's TestClient to exercise the meal logging and
retrieval endpoints.  They apply both black‑box and white‑box test
strategies by validating normal operation as well as edge cases and
internal side effects (such as event publishing and in‑memory state).

Because the services rely on RabbitMQ for event delivery, the
``publish_message`` function is patched in relevant tests to prevent
network calls.  The in‑memory storage of meals is also cleared before
each test to ensure isolation.
"""

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from meal_service.main import app, _meal_store

class TestMealService(unittest.TestCase):
    """Test cases for the meal logging service.

    The tests cover both valid and invalid inputs (equivalence class
    partitioning) as well as internal behaviours such as state update and
    event publishing (control‑flow based testing).
    """

    def setUp(self) -> None:
        """Reset state and create a fresh client for each test."""
        # Ensure in‑memory store is empty before each test
        _meal_store.clear()
        self.client = TestClient(app)

    def test_valid_meal_logging(self) -> None:
        """Valid input should log a meal and publish an event."""
        with patch(
            "healthy_bites_microservices.meal_service.main.rabbitmq_utils.publish_message"
        ) as mock_pub:
            response = self.client.post(
                "/users/alice/meals",
                json={
                    "mealType": "breakfast",
                    "items": [
                        {
                            "name": "Oatmeal",
                            "calories": 150,
                            "carbs": 27,
                            "protein": 5,
                            "fats": 3,
                        }
                    ],
                },
            )
            self.assertEqual(response.status_code, 201)
            data = response.json()
            # The meal type should be echoed back verbatim
            self.assertEqual(data["mealType"], "breakfast")
            # Exactly one item should be recorded
            self.assertEqual(len(data["items"]), 1)
            # The event publisher should have been called once
            mock_pub.assert_called_once()

    def test_invalid_negative_calories(self) -> None:
        """Negative calories should trigger a validation error (HTTP 422)."""
        response = self.client.post(
            "/users/alice/meals",
            json={
                "mealType": "breakfast",
                "items": [{"name": "Oatmeal", "calories": -10}],
            },
        )
        self.assertEqual(response.status_code, 422)

    def test_empty_items(self) -> None:
        """An empty items list should be rejected as invalid."""
        response = self.client.post(
            "/users/alice/meals",
            json={"mealType": "lunch", "items": []},
        )
        self.assertEqual(response.status_code, 422)

    def test_get_meals_after_logging(self) -> None:
        """After logging a meal, retrieving meals should return the logged entry."""
        # Patch the publisher to avoid RabbitMQ interaction
        with patch(
            "healthy_bites_microservices.meal_service.main.rabbitmq_utils.publish_message"
        ):
            self.client.post(
                "/users/bob/meals",
                json={
                    "mealType": "dinner",
                    "items": [{"name": "Salad", "calories": 100}],
                },
            )
        response = self.client.get("/users/bob/meals")
        self.assertEqual(response.status_code, 200)
        meals = response.json()
        self.assertEqual(len(meals), 1)
        self.assertEqual(meals[0]["mealType"], "dinner")


if __name__ == "__main__":
    unittest.main()