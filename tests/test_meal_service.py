import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from meal_service.main import app, _meal_store

client = TestClient(app)


def setup_function() -> None:
    """
    Pytest hook: runs before *each* test in this module.

    We clear the in-memory store to avoid cross-test interference.
    Works whether _meal_store is a dict or a custom class that
    exposes a .clear() method.
    """
    if hasattr(_meal_store, "clear"):
        _meal_store.clear()
    else:
        # Fallback if _meal_store is a plain dict-like
        try:
            _meal_store.clear()
        except Exception:
            # Last resort: try resetting common attribute names; adjust if needed
            if hasattr(_meal_store, "store"):
                _meal_store.store.clear()


# -----------------------------
# Black-box tests (Equivalence Class Partitioning)
# -----------------------------


def test_log_meal_bb_valid_meal() -> None:
    """
    BB1 – Happy path: valid meal (EC1).
    Expect 201 Created and a generated id, and GET returns 1 meal.
    """
    body = {
        "mealType": "breakfast",
        "items": [
            {"name": "Oatmeal", "calories": 150},
        ],
    }

    resp = client.post("/users/u1/meals", json=body)
    assert resp.status_code == 201
    data = resp.json()
    assert "id" in data

    # Check that one meal exists for this user via GET
    get_resp = client.get("/users/u1/meals")
    assert get_resp.status_code == 200
    meals = get_resp.json()
    assert isinstance(meals, list)
    assert len(meals) == 1


def test_log_meal_bb_invalid_meal_type() -> None:
    """
    BB2 – Invalid mealType (EC2: value not in enum).
    Expect 422 validation error.
    """
    body = {
        "mealType": "brunch",  # invalid
        "items": [
            {"name": "Oatmeal", "calories": 150},
        ],
    }

    resp = client.post("/users/u1/meals", json=body)
    assert resp.status_code == 422  # FastAPI/Pydantic validation error


def test_log_meal_bb_empty_items_list() -> None:
    """
    BB3 – Empty items list (EC3).
    If items is constrained with min_length=1, Pydantic should raise 422.
    """
    body = {
        "mealType": "dinner",
        "items": [],  # invalid: empty
    }

    resp = client.post("/users/u1/meals", json=body)
    assert resp.status_code == 422


def test_log_meal_bb_invalid_calories_value() -> None:
    """
    BB4 – Invalid calories (EC4: 0 or negative).
    We assume calories has a constraint > 0, so 422 is expected.
    """
    body = {
        "mealType": "lunch",
        "items": [
            {"name": "Burger", "calories": -5},  # invalid
        ],
    }

    resp = client.post("/users/u1/meals", json=body)
    assert resp.status_code == 422


def test_log_meal_bb_missing_meal_type() -> None:
    """
    BB5 – Missing required field mealType (EC5).
    Expect 422 because request body is incomplete.
    """
    body = {
        # "mealType" missing
        "items": [
            {"name": "Oatmeal", "calories": 150},
        ],
    }

    resp = client.post("/users/u1/meals", json=body)
    assert resp.status_code == 422


# -----------------------------
# White-box tests (Control Flow)
# -----------------------------


def test_log_meal_wb_first_meal_creates_new_user_list() -> None:
    """
    WB1 – First meal for a user: branch where the store creates a new list
    for user 'u1'. We validate through GET that exactly 1 meal is stored.
    """
    body = {
        "mealType": "breakfast",
        "items": [
            {"name": "Oats", "calories": 100},
        ],
    }

    resp = client.post("/users/u1/meals", json=body)
    assert resp.status_code == 201

    get_resp = client.get("/users/u1/meals")
    assert get_resp.status_code == 200
    meals = get_resp.json()
    assert len(meals) == 1


def test_log_meal_wb_second_meal_appends_for_same_user() -> None:
    """
    WB2 – Second meal for same user: branch where the store appends to an
    existing list rather than creating a new one.
    """
    body1 = {
        "mealType": "breakfast",
        "items": [
            {"name": "Oats", "calories": 100},
        ],
    }
    body2 = {
        "mealType": "lunch",
        "items": [
            {"name": "Rice", "calories": 200},
        ],
    }

    resp1 = client.post("/users/u2/meals", json=body1)
    resp2 = client.post("/users/u2/meals", json=body2)
    assert resp1.status_code == 201
    assert resp2.status_code == 201

    get_resp = client.get("/users/u2/meals")
    assert get_resp.status_code == 200
    meals = get_resp.json()
    assert len(meals) == 2


def test_log_meal_wb_multiple_items_all_macros() -> None:
    """
    WB3 – Path where we iterate over multiple items and all optional macro
    fields are present (carbs, protein, fats).
    """
    body = {
        "mealType": "dinner",
        "items": [
            {
                "name": "Rice",
                "calories": 200,
                "carbs": 40,
                "protein": 4,
                "fats": 2,
            },
            {
                "name": "Dal",
                "calories": 150,
                "carbs": 20,
                "protein": 8,
                "fats": 3,
            },
        ],
    }

    resp = client.post("/users/u3/meals", json=body)
    assert resp.status_code == 201

    get_resp = client.get("/users/u3/meals")
    assert get_resp.status_code == 200
    meals = get_resp.json()
    assert len(meals) == 1
    # At least check that two items are present in stored meal representation
    assert len(meals[0].get("items", [])) == 2


def test_log_meal_wb_items_with_missing_optional_macros() -> None:
    """
    WB4 – Path where some items omit optional macro fields.
    The control flow should still treat the meal as valid and store it.
    """
    body = {
        "mealType": "lunch",
        "items": [
            {
                "name": "Salad",
                "calories": 80,
                # no macros
            },
            {
                "name": "Yogurt",
                "calories": 90,
                "protein": 5,  # some macros present
            },
        ],
    }

    resp = client.post("/users/u4/meals", json=body)
    assert resp.status_code == 201

    get_resp = client.get("/users/u4/meals")
    assert get_resp.status_code == 200
    meals = get_resp.json()
    assert len(meals) == 1
    assert len(meals[0].get("items", [])) == 2


def test_log_meal_wb_publisher_failure_does_not_break_endpoint() -> None:
    """
    WB5 – Path where the RabbitMQ publisher raises an exception.
    The endpoint should still return 201 and store the meal
    (we're testing resilience of the control flow).
    """
    body = {
        "mealType": "snack",
        "items": [
            {"name": "Nuts", "calories": 120},
        ],
    }

    # Adjust patch target depending on how you import publish_message.
    # If in meal_service.main you do:
    #   from healthy_bites_microservices import rabbitmq_utils
    #   rabbitmq_utils.publish_message(...)
    # then patch as below:
    patch_target = "meal_service.main.rabbitmq_utils.publish_message"

    with patch(patch_target, side_effect=Exception("Broker down")):
        resp = client.post("/users/u5/meals", json=body)

    # Even if publisher fails, we want the request to succeed
    assert resp.status_code == 201

    get_resp = client.get("/users/u5/meals")
    assert get_resp.status_code == 200
    meals = get_resp.json()
    assert len(meals) == 1