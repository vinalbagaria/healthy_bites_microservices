"""
Nutrition Service
-----------------

This microservice maintains nutrition insights for users. It listens for
``meal_logged`` events on the ``nutrition_service_queue`` and updates
aggregate calorie and macronutrient totals for each user. Clients can
retrieve the current nutrition insights for a user via a REST endpoint.

Endpoints:

* **GET** `/users/{user_id}/nutrition/insights` – return the aggregated
  calories and macronutrients consumed by the given user. If the user has
  not logged any meals yet, zeros are returned.

On startup the service declares its queue and spawns a background thread
that polls RabbitMQ for new messages. When a meal_logged event is
received, the service updates the stored totals accordingly.
"""

from __future__ import annotations

import threading
from typing import Dict, Any

from fastapi import FastAPI, Path
from pydantic import BaseModel, Field

from healthy_bites_microservices import rabbitmq_utils

import logging


class NutritionInsights(BaseModel):
    calories_consumed: float = Field(..., description="Total calories consumed")
    carbs: float = Field(..., description="Total carbohydrates (g)")
    protein: float = Field(..., description="Total protein (g)")
    fats: float = Field(..., description="Total fats (g)")


app = FastAPI(
    title="Nutrition Service",
    description="Aggregate nutrition data and respond to events",
)

# Configure logger
logger = logging.getLogger(__name__)

class NutritionAggregator:
    """Aggregate and store nutrition metrics per user."""

    def __init__(self) -> None:
        self._totals: Dict[str, Dict[str, float]] = {}

    def update_from_meal(self, user_id: str, items: list[dict[str, Any]]) -> None:
        """Add nutrition values from a meal to the user's totals."""
        calories = 0.0
        carbs = 0.0
        protein = 0.0
        fats = 0.0
        for item in items:
            try:
                calories += float(item.get("calories", 0))
                carbs += float(item.get("carbs", 0))
                protein += float(item.get("protein", 0))
                fats += float(item.get("fats", 0))
            except Exception as exc:
                logger.error("Failed to parse item in meal: %s", exc)
                continue
        stats = self._totals.setdefault(
            user_id, {"calories": 0.0, "carbs": 0.0, "protein": 0.0, "fats": 0.0}
        )
        stats["calories"] += calories
        stats["carbs"] += carbs
        stats["protein"] += protein
        stats["fats"] += fats

    def get_totals(self, user_id: str) -> Dict[str, float]:
        return self._totals.get(
            user_id, {"calories": 0.0, "carbs": 0.0, "protein": 0.0, "fats": 0.0}
        )


_aggregator = NutritionAggregator()


def _handle_event(event: Dict[str, Any]) -> None:
    """Process a meal_logged event and update nutrition totals."""
    if event.get("event_type") != "meal_logged":
        return
    user_id: str = event.get("user_id")
    meal = event.get("meal") or {}
    items = meal.get("items", [])
    _aggregator.update_from_meal(user_id, items)
    # Optionally you could publish another event here (e.g., goal achieved)


@app.on_event("startup")
def startup() -> None:
    """Declare the service queue and start the consumer thread."""
    # Start background consumer to process incoming events
    rabbitmq_utils.start_consumer("nutrition_service_queue", _handle_event, poll_interval=1.0)


@app.get("/users/{user_id}/nutrition/insights", response_model=NutritionInsights)
def get_insights(user_id: str = Path(..., description="Identifier for the user")) -> NutritionInsights:
    """Return aggregated nutrition insights for a given user."""
    stats = _aggregator.get_totals(user_id)
    return NutritionInsights(
        calories_consumed=stats.get("calories", 0.0),
        carbs=stats.get("carbs", 0.0),
        protein=stats.get("protein", 0.0),
        fats=stats.get("fats", 0.0),
    )