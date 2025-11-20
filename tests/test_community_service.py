"""Unit tests for the community service.

These tests exercise the recipe and comment endpoints of the community
service.  The tests patch the RabbitMQ publisher to prevent external
dependencies and validate that the in‑memory stores behave correctly.
"""

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from community_service.main import _recipe_store, _comment_store


class TestCommunityService(unittest.TestCase):
    """Test cases for recipe and comment endpoints."""

    def setUp(self) -> None:
        # Clear stores before each test
        _recipe_store._data.clear()  # type: ignore[attr-defined]
        _comment_store._data.clear()  # type: ignore[attr-defined]
        self.client = TestClient(app)

    def test_create_recipe_and_publish_event(self) -> None:
        """Creating a recipe should persist it and publish an event."""
        with patch(
            "healthy_bites_microservices.community_service.main.rabbitmq_utils.publish_message"
        ) as mock_pub:
            response = self.client.post(
                "/recipes",
                json={
                    "title": "Avocado Toast",
                    "ingredients": ["Avocado", "Bread"],
                    "instructions": "Toast bread and spread avocado.",
                    "author": "alice",
                },
            )
            self.assertEqual(response.status_code, 201)
            data = response.json()
            self.assertEqual(data["title"], "Avocado Toast")
            mock_pub.assert_called_once()

    def test_list_recipes_returns_created(self) -> None:
        """After a recipe is created it should appear in the list."""
        with patch(
            "healthy_bites_microservices.community_service.main.rabbitmq_utils.publish_message"
        ):
            self.client.post(
                "/recipes",
                json={
                    "title": "Smoothie",
                    "ingredients": ["Banana", "Yogurt"],
                    "instructions": "Blend ingredients.",
                    "author": "bob",
                },
            )
        response = self.client.get("/recipes")
        self.assertEqual(response.status_code, 200)
        recipes = response.json()
        self.assertEqual(len(recipes), 1)
        self.assertEqual(recipes[0]["title"], "Smoothie")

    def test_add_comment_and_get_comments(self) -> None:
        """Comments can be added and retrieved for a recipe."""
        with patch(
            "healthy_bites_microservices.community_service.main.rabbitmq_utils.publish_message"
        ):
            create_resp = self.client.post(
                "/recipes",
                json={
                    "title": "Salad",
                    "ingredients": ["Lettuce"],
                    "instructions": "Mix.",
                    "author": None,
                },
            )
        recipe_id = create_resp.json()["id"]
        comment_resp = self.client.post(
            f"/recipes/{recipe_id}/comments",
            json={"author": "eve", "comment": "Looks great!"},
        )
        self.assertEqual(comment_resp.status_code, 201)
        data = comment_resp.json()
        self.assertEqual(data["author"], "eve")
        # Retrieve comments
        get_resp = self.client.get(f"/recipes/{recipe_id}/comments")
        self.assertEqual(get_resp.status_code, 200)
        comments = get_resp.json()
        self.assertEqual(len(comments), 1)
        self.assertEqual(comments[0]["comment"], "Looks great!")

    def test_add_comment_to_nonexistent_recipe(self) -> None:
        """Adding a comment to an unknown recipe should yield 404."""
        response = self.client.post(
            "/recipes/nonexistent/comments",
            json={"author": "anonymous", "comment": "Hello"},
        )
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()