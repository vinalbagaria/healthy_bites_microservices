"""
Meal Service
------------

This microservice provides endpoints for users to log their meals and query
previously logged meals. When a meal is logged, the service publishes an
event to the nutrition service via RabbitMQ so that nutrition insights can
be updated asynchronously.

Endpoints:

* **POST** `/users/{user_id}/meals` – log a meal for a user. The request body
  should include the meal type (e.g. breakfast) and a list of items with
  nutritional information. Returns the recorded meal with a generated
  identifier.
* **GET** `/users/{user_id}/meals` – retrieve all meals logged for a user.

Configuration:

This service relies on a running RabbitMQ server with the management plugin
enabled on port 15672. It reads RabbitMQ settings from environment
variables (see ``rabbitmq_utils.py`` for details). Before running this
service you must start a RabbitMQ server. For example using Docker:

```
docker run -it --rm --name rabbitmq -p 5672:5672 -p 15672:15672 rabbitmq:3-management
```

To start the service:

```
uvicorn main:app --host 0.0.0.0 --port 8001
```

Once running, you can log a meal via curl:

```
curl -X POST http://localhost:8001/users/alice/meals \
     -H "Content-Type: application/json" \
     -d '{"mealType": "breakfast", "items": [{"name": "Oatmeal", "calories": 150, "carbs": 27, "protein": 5, "fats": 3}]}'
```

And query logged meals:

```
curl http://localhost:8001/users/alice/meals
```
"""

from __future__ import annotations

import uuid
from typing import List, Dict, Optional
from enum import Enum

from fastapi import FastAPI, HTTPException, Path
from pydantic import BaseModel, Field

import logging

# Configure a module‑level logger.  Individual services can adjust logging
# levels via the standard logging configuration API.  Avoid using print
# statements for operational messages as they cannot be redirected or
# filtered easily in production.
logger = logging.getLogger(__name__)

# Import rabbitmq_utils via absolute package path. Using absolute import
# avoids issues when running the service directly (e.g. ``uvicorn main:app``) where
# Python would otherwise treat the service directory as the top level package.
from healthy_bites_microservices import rabbitmq_utils

# Create FastAPI application
app = FastAPI(title="Meal Service", description="Manage user meals and publish events to other services")


class MealItem(BaseModel):
    name: str = Field(..., description="Name of the food item")
    calories: float = Field(..., ge=0, description="Calories in the item")
    carbs: Optional[float] = Field(0, ge=0, description="Carbohydrates (grams)")
    protein: Optional[float] = Field(0, ge=0, description="Protein (grams)")
    fats: Optional[float] = Field(0, ge=0, description="Fat (grams)")


class MealTypeEnum(str, Enum):
    """Enumeration of valid meal types.

    Restricting the meal type to a well‑defined set prevents typos and
    encourages clients to use the canonical values.  Additional types can be
    added here as needed without changing the public API contract.
    """

    breakfast = "breakfast"
    lunch = "lunch"
    dinner = "dinner"
    snack = "snack"


class Meal(BaseModel):
    id: str = Field(..., description="Unique identifier for the meal")
    mealType: MealTypeEnum = Field(
        ..., description="Type of meal, e.g. breakfast, lunch, dinner, snack"
    )
    items: List[MealItem] = Field(
        ..., description="List of food items in the meal", min_items=1
    )


class MealCreateRequest(BaseModel):
    mealType: MealTypeEnum = Field(
        ..., description="Type of meal, e.g. breakfast, lunch, dinner, snack"
    )
    items: List[MealItem] = Field(
        ..., description="Food items making up the meal", min_items=1
    )


# In‑memory storage encapsulated in a simple store class.  Encapsulating
# state makes it easier to swap out the backing store (e.g. use a real
# database) and avoids accidental mutation of global dictionaries.
class MealStore:
    """In‑memory storage for meals keyed by user ID."""

    def __init__(self) -> None:
        self._data: Dict[str, List[Meal]] = {}

    def add_meal(self, user_id: str, meal: Meal) -> None:
        """Append a meal to the list for a user."""
        self._data.setdefault(user_id, []).append(meal)

    def get_meals(self, user_id: str) -> List[Meal]:
        """Return all meals logged by a user.

        A new list is returned to prevent callers from modifying the
        underlying storage.
        """
        return list(self._data.get(user_id, []))

    def clear(self) -> None:
        """Clear all stored meals (used for testing)."""
        self._data.clear()


_meal_store = MealStore()


def _publish_meal_event(user_id: str, meal: Meal) -> None:
    """Publish a meal_logged event to the nutrition service.

    The event payload contains the serialised meal and the associated user.
    Any exceptions during publishing are logged but do not prevent the
    operation of the service.
    """
    event = {
        "event_type": "meal_logged",
        "user_id": user_id,
        # Use model_dump() instead of .dict() for Pydantic v2 compatibility
        "meal": meal.model_dump(),
    }
    try:
        rabbitmq_utils.publish_message("nutrition_service_queue", event)
    except Exception as exc:
        logger.error("Failed to publish meal event: %s", exc)

@app.post("/users/{user_id}/meals", response_model=Meal, status_code=201)
def log_meal(
    user_id: str = Path(..., description="Identifier for the user"),
    request: MealCreateRequest = ...,
) -> Meal:
    """Log a new meal for a user and publish an event to the nutrition service.

    When a meal is logged, the service records it in memory via the
    ``MealStore`` and publishes an event to the ``nutrition_service_queue``.
    Publishing exceptions are logged but do not impact the response.
    """
    meal_id = str(uuid.uuid4())
    meal = Meal(id=meal_id, mealType=request.mealType, items=request.items)
    # Save meal in the store
    _meal_store.add_meal(user_id, meal)
    # Publish event to nutrition service
    _publish_meal_event(user_id, meal)
    return meal


@app.get("/users/{user_id}/meals", response_model=List[Meal])
def get_meals(user_id: str = Path(..., description="Identifier for the user")) -> List[Meal]:
    """Retrieve all meals logged by a user."""
    return _meal_store.get_meals(user_id)