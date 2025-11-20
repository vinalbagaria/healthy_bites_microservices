"""
Notification Service
--------------------

This microservice listens for events from other services and stores
notifications that can be retrieved via an API. It demonstrates how
microservices can subscribe to events produced elsewhere and perform
side‑effects, such as delivering notifications to users. In this simple
implementation notifications are just stored in memory.

Endpoints:

* **GET** `/notifications` – return a list of all notifications received.
"""

from __future__ import annotations

import threading
from typing import List, Dict, Any

from fastapi import FastAPI
from pydantic import BaseModel, Field

from healthy_bites_microservices import rabbitmq_utils

import logging


class Notification(BaseModel):
    event_type: str
    data: Dict[str, Any] = Field(..., description="Payload associated with the event")


app = FastAPI(
    title="Notification Service",
    description="Receive and expose notifications from other services",
)

# Configure a logger for the service
logger = logging.getLogger(__name__)

# Encapsulate notification storage in a simple class to avoid global lists
class NotificationStore:
    def __init__(self) -> None:
        self._data: List[Notification] = []

    def add(self, notification: Notification) -> None:
        self._data.append(notification)

    def all(self) -> List[Notification]:
        return list(self._data)

    def clear(self) -> None:
        self._data.clear()


_notif_store = NotificationStore()


def _handle_event(event: Dict[str, Any]) -> None:
    """Callback invoked for each message in the notification queue."""
    try:
        notif = Notification(
            event_type=event.get("event_type", "unknown"), data=event
        )
        _notif_store.add(notif)
        logger.info("Notification received: %s", notif)
    except Exception as exc:
        logger.error("Failed to process notification event: %s", exc)


@app.on_event("startup")
def startup() -> None:
    """Start a background consumer for the notification queue."""
    rabbitmq_utils.start_consumer("notification_service_queue", _handle_event, poll_interval=1.0)


@app.get("/notifications", response_model=List[Notification])
def get_notifications() -> List[Notification]:
    """Return all received notifications."""
    return _notif_store.all()