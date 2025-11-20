# HealthyBites Microservices

This repository contains implementation of a microservice‑
based application for the **HealthyBites** meal‑tracking app. The services
correspond to the user stories and bounded contexts defined in assignment 1
and satisfy the requirements of assignment 2. The implementation uses
multiple independent services that communicate via **RabbitMQ**.

## Overview

The system is decomposed into four services:

| Service | Description | Default Port |
| ------- | ----------- | ------------ |
| **Meal Service** | Handles logging meals for users. When a meal is logged it publishes a `meal_logged` event to RabbitMQ so that the nutrition service can update aggregated statistics. | 8001 |
| **Nutrition Service** | Listens for `meal_logged` events, accumulates calorie and macronutrient totals per user and exposes an endpoint to retrieve nutrition insights. | 8002 |
| **Community Service** | Manages community recipes and comments. When a new recipe is created it publishes a `new_recipe_posted` event so that notifications can be generated. | 8003 |
| **Notification Service** | Subscribes to `new_recipe_posted` events and stores them as notifications. It exposes an endpoint to retrieve all notifications. | 8004 |

All inter‑service communication happens asynchronously via RabbitMQ: services
publish events to queues and other services consume them in the background.

## Prerequisites

1. **RabbitMQ**: A RabbitMQ broker with the management plugin enabled must be
   running. The easiest way is to use Docker. Make sure the management port
   (15672) and the AMQP port (5672) are exposed:

   ```bash
   docker run -it --rm --name rabbitmq \
     -p 5672:5672 -p 15672:15672 \
     rabbitmq:3-management
   ```

   By default the username and password are both `guest` and the default
   virtual host is `/`. If you use different credentials, export the
   appropriate environment variables before starting the services (see
   below).

2. **Python packages**: Install the dependencies listed in
   `requirements.txt`. It is recommended to create a virtual environment:

   ```bash
   cd healthy_bites_microservices
   python3 -m venv venv
   source venv/bin/activate
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

   The core dependencies are [`fastapi`](https://fastapi.tiangolo.com/),
   [`uvicorn`](https://www.uvicorn.org/) and [`requests`](https://requests.readthedocs.io/).

## Configuration

Each service reads RabbitMQ configuration from environment variables. The
defaults are suitable for a RabbitMQ instance running locally with the
management plugin enabled:

| Variable | Description | Default |
| -------- | ----------- | ------- |
| `RABBITMQ_API_URL` | Base URL for the HTTP management API | `http://localhost:15672/api` |
| `RABBITMQ_USERNAME` | Username for HTTP authentication | `guest` |
| `RABBITMQ_PASSWORD` | Password for HTTP authentication | `guest` |
| `RABBITMQ_VHOST` | Virtual host for publishing/consuming | `/` |

If your setup differs, export these variables before starting each service.

## Running the services

In separate terminal windows (or using a process manager) start each service
with `uvicorn`. Make sure your current working directory is the root of the
repository (`healthy_bites_microservices` should be importable as a package):

```bash
# Terminal 1: Meal Service (port 8001)
uvicorn healthy_bites_microservices.meal_service.main:app --host 0.0.0.0 --port 8001

# Terminal 2: Nutrition Service (port 8002)
uvicorn healthy_bites_microservices.nutrition_service.main:app --host 0.0.0.0 --port 8002

# Terminal 3: Community Service (port 8003)
uvicorn healthy_bites_microservices.community_service.main:app --host 0.0.0.0 --port 8003

# Terminal 4: Notification Service (port 8004)
uvicorn healthy_bites_microservices.notification_service.main:app --host 0.0.0.0 --port 8004
```

Alternatively you can change the port numbers as needed. Each service
independently declares its queue and will begin polling for messages once it
starts.

## Trying it out

1. **Log a meal** using the Meal Service. This will store the meal locally
   and publish an event for the Nutrition Service to consume:

   ```bash
   curl -X POST http://localhost:8001/users/alice/meals \
        -H "Content-Type: application/json" \
        -d '{"mealType": "breakfast", "items": [{"name": "Oatmeal", "calories": 150, "carbs": 27, "protein": 5, "fats": 3}]}'
   ```

   Response:

   ```json
   {
     "id": "...",
     "mealType": "breakfast",
     "items": [ { "name": "Oatmeal", "calories": 150.0, "carbs": 27.0, "protein": 5.0, "fats": 3.0 } ]
   }
   ```

2. **Get nutrition insights** from the Nutrition Service. After a short delay
   (the consumer polls every second) the Nutrition Service will have updated
   its aggregates:

   ```bash
   curl http://localhost:8002/users/alice/nutrition/insights
   ```

   Response:

   ```json
   {
     "calories_consumed": 150.0,
     "carbs": 27.0,
     "protein": 5.0,
     "fats": 3.0
   }
   ```

3. **Create a recipe** using the Community Service. This will publish a
   notification event:

   ```bash
   curl -X POST http://localhost:8003/recipes \
        -H "Content-Type: application/json" \
        -d '{"title": "Avocado Toast", "ingredients": ["Avocado", "Bread"], "instructions": "Toast bread and spread avocado.", "author": "alice"}'
   ```

4. **Retrieve notifications** from the Notification Service. After the
   community service publishes an event the notification service will store
   it. You can view all notifications via:

   ```bash
   curl http://localhost:8004/notifications
   ```

   Response:

   ```json
   [
     {
       "event_type": "new_recipe_posted",
       "data": {
         "event_type": "new_recipe_posted",
         "recipe": {
           "id": "...",
           "title": "Avocado Toast",
           "ingredients": ["Avocado", "Bread"],
           "instructions": "Toast bread and spread avocado.",
           "author": "alice"
         }
       }
     }
   ]
   ```

## Extending the system

This implementation is intentionally minimal. It stores data in memory and
uses the RabbitMQ management HTTP API for simplicity. For a production‑
ready system you would typically:

* Use a proper database (e.g. PostgreSQL) for persistent storage.
* Use an AMQP client library (e.g. `pika` or `aio_pika`) instead of the
  management API for efficient message streaming.
* Implement authentication and authorization for the REST endpoints.
* Expand the domain models and validation according to the full set of
  requirements.

Nevertheless, this code should provide a solid starting point for experimenting
with microservices, FastAPI and RabbitMQ in a local development environment.