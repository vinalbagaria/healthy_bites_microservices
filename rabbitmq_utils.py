"""
Shared utilities for interacting with RabbitMQ via its HTTP management API.

This module provides simple helper functions to declare queues, publish
messages and continuously consume messages from a queue. It uses the
RabbitMQ management API provided by the management plugin, which runs on
port 15672 by default. These functions rely on basic HTTP authentication
using the `guest` user credentials. If your RabbitMQ server uses
different credentials or a different host/port, export the environment
variables listed below before running your microservices:

* `RABBITMQ_API_URL`: Base URL of the management API (default
  ``http://localhost:15672/api``).
* `RABBITMQ_USERNAME`: Username for HTTP authentication (default
  ``guest``).
* `RABBITMQ_PASSWORD`: Password for HTTP authentication (default
  ``guest``).
* `RABBITMQ_VHOST`: Virtual host for publishing/consuming (default ``/``).

Note: The default virtual host ``/`` must be percent‑encoded when used in
URLs; the helper functions handle that for you.
"""

from __future__ import annotations

import json
import threading
import time
import os
import urllib.parse
from typing import Callable, Any, Dict, List

import requests

# Read configuration from environment variables with sensible defaults
BASE_URL = os.getenv("RABBITMQ_API_URL", "http://localhost:15672/api").rstrip("/")
USERNAME = os.getenv("RABBITMQ_USERNAME", "guest")
PASSWORD = os.getenv("RABBITMQ_PASSWORD", "guest")
VHOST = os.getenv("RABBITMQ_VHOST", "/")

_vhost_enc = urllib.parse.quote(VHOST, safe="")  # percent‑encoded virtual host

def _url(path: str) -> str:
    """Return full URL for a given management API path."""
    return f"{BASE_URL}{path}"


def declare_queue(queue_name: str, durable: bool = True, auto_delete: bool = False) -> None:
    """
    Declare a queue in RabbitMQ.

    If the queue already exists the declaration is idempotent. Durable queues
    survive broker restarts. Auto‑delete queues are deleted when the last
    consumer disconnects.

    Args:
        queue_name: The name of the queue to declare.
        durable: Whether the queue should be durable.
        auto_delete: Whether the queue should be auto‑deleted.
    """
    url = _url(f"/queues/{_vhost_enc}/{urllib.parse.quote(queue_name, safe='')}" )
    data = {
        "auto_delete": auto_delete,
        "durable": durable,
        "arguments": {}
    }
    # The management API uses PUT for declarations
    resp = requests.put(url, auth=(USERNAME, PASSWORD), json=data)
    # Raise an exception if the request failed
    try:
        resp.raise_for_status()
    except Exception as exc:
        raise RuntimeError(f"Failed to declare queue '{queue_name}': {resp.text}") from exc


def publish_message(routing_key: str, payload: Dict[str, Any]) -> None:
    """
    Publish a message to the default exchange with a given routing key.

    The default exchange (amq.default) routes messages to the queue whose name
    matches the routing key. The payload is serialised as JSON before being
    delivered.

    Args:
        routing_key: Name of the queue that should receive the message.
        payload: A serialisable object (e.g. dict) representing the message.
    """
    url = _url(f"/exchanges/{_vhost_enc}/amq.default/publish")
    body = {
        "properties": {},
        "routing_key": routing_key,
        "payload": json.dumps(payload),
        "payload_encoding": "string"
    }
    resp = requests.post(url, auth=(USERNAME, PASSWORD), json=body)
    try:
        resp.raise_for_status()
    except Exception as exc:
        raise RuntimeError(f"Failed to publish message to '{routing_key}': {resp.text}") from exc
    # Optionally inspect response to ensure it was routed
    result = resp.json()
    if not result.get("routed", False):
        raise RuntimeError(f"Message to '{routing_key}' was not routed: {result}")


def get_messages(queue_name: str, count: int = 1) -> List[Dict[str, Any]]:
    """
    Retrieve messages from a queue.

    This function uses the management API's `/get` endpoint, which removes
    messages from the queue (unless requeue is requested). It should be used
    sparingly and primarily for development/demo purposes.

    Args:
        queue_name: The name of the queue to retrieve messages from.
        count: Maximum number of messages to fetch.

    Returns:
        A list of messages, each containing 'payload' and metadata.
    """
    url = _url(f"/queues/{_vhost_enc}/{urllib.parse.quote(queue_name, safe='')}/get")
    body = {
        "count": count,
        "ackmode": "ack_requeue_false",
        "encoding": "auto",
        "truncate": 50000
    }
    resp = requests.post(url, auth=(USERNAME, PASSWORD), json=body)
    try:
        resp.raise_for_status()
    except Exception as exc:
        raise RuntimeError(f"Failed to get messages from '{queue_name}': {resp.text}") from exc
    return resp.json() if resp.text else []


def _process_single_message(
    msg: Dict[str, Any],
    handler: Callable[[Dict[str, Any]], None],
    queue_name: str,
) -> None:
    """Decode a single message and invoke the handler, swallowing errors."""
    payload = msg.get("payload")
    if not payload:
        return

    try:
        data = json.loads(payload)
    except Exception:
        # Ignore malformed payloads
        return

    try:
        handler(data)
    except Exception as handler_exc:
        # Log exception (print) and continue
        print(f"Error handling message on {queue_name}: {handler_exc}")


def _poll_queue_once(
    queue_name: str,
    handler: Callable[[Dict[str, Any]], None],
    poll_interval: float,
) -> bool:
    """
    Poll the queue once and process any messages.

    Returns True if polling succeeded, False if there was an error.
    """
    try:
        messages = get_messages(queue_name, count=5)
    except Exception as exc:
        print(f"Error consuming from {queue_name}: {exc}")
        return False

    for msg in messages:
        _process_single_message(msg, handler, queue_name)

    # Sleep after successful poll
    time.sleep(poll_interval)
    return True


def _consumer_loop(
    queue_name: str,
    handler: Callable[[Dict[str, Any]], None],
    poll_interval: float,
) -> None:
    """Background loop that continuously polls the queue."""
    while True:
        ok = _poll_queue_once(queue_name, handler, poll_interval)
        if not ok:
            # On error, back off a bit before retrying
            time.sleep(poll_interval * 2)


def start_consumer(
    queue_name: str,
    handler: Callable[[Dict[str, Any]], None],
    poll_interval: float = 1.0,
) -> threading.Thread:
    """
    Start a background thread that polls a RabbitMQ queue and invokes a handler
    for each message.
    """
    declare_queue(queue_name)

    thread = threading.Thread(
        target=_consumer_loop,
        args=(queue_name, handler, poll_interval),
        daemon=True,
    )
    thread.start()
    return thread
