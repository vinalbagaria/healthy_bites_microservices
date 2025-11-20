"""
Community Service
-----------------

This microservice manages community content such as recipes and comments.
Users can create recipes, list all recipes, add comments to recipes and
retrieve comments. When a new recipe is posted the service publishes an
event to the notification service queue so that notifications can be
delivered to interested parties (e.g. followers of the recipe author).

Endpoints:

* **POST** `/recipes` – create a new recipe. The request body should
  include a title, a list of ingredients and instructions. Returns the
  created recipe with an assigned identifier.
* **GET** `/recipes` – list all existing recipes.
* **POST** `/recipes/{recipe_id}/comments` – add a comment to a recipe.
* **GET** `/recipes/{recipe_id}/comments` – retrieve comments for a recipe.
"""

from __future__ import annotations

import uuid
from typing import List, Dict, Optional

from fastapi import FastAPI, HTTPException, Path
from pydantic import BaseModel, Field

import logging

# Configure a module‑level logger
logger = logging.getLogger(__name__)

from healthy_bites_microservices import rabbitmq_utils


class RecipeCreateRequest(BaseModel):
    title: str = Field(..., description="Recipe title")
    ingredients: List[str] = Field(..., description="List of ingredients")
    instructions: str = Field(..., description="Preparation instructions")
    author: Optional[str] = Field(None, description="Author of the recipe")


class Recipe(BaseModel):
    id: str = Field(..., description="Unique recipe identifier")
    title: str
    ingredients: List[str]
    instructions: str
    author: Optional[str] = None


class CommentCreateRequest(BaseModel):
    author: str = Field(..., description="Name of the commenter")
    comment: str = Field(..., description="Comment text")


class Comment(BaseModel):
    author: str
    comment: str


app = FastAPI(title="Community Service", description="Manage community recipes and comments")

# Encapsulate in‑memory storage in simple classes.  This avoids using
# module‑level dictionaries directly and makes it easier to swap in
# persistent storage later.
class RecipeStore:
    def __init__(self) -> None:
        self._data: Dict[str, Recipe] = {}

    def add(self, recipe: Recipe) -> None:
        self._data[recipe.id] = recipe

    def get_all(self) -> List[Recipe]:
        return list(self._data.values())

    def exists(self, recipe_id: str) -> bool:
        return recipe_id in self._data


class CommentStore:
    def __init__(self) -> None:
        self._data: Dict[str, List[Comment]] = {}

    def add(self, recipe_id: str, comment: Comment) -> None:
        self._data.setdefault(recipe_id, []).append(comment)

    def get_for_recipe(self, recipe_id: str) -> List[Comment]:
        return list(self._data.get(recipe_id, []))


# Instantiate global stores
_recipe_store = RecipeStore()
_comment_store = CommentStore()


def _publish_new_recipe_event(recipe: Recipe) -> None:
    """Publish a new_recipe_posted event to the notification queue."""
    event = {
        "event_type": "new_recipe_posted",
        "recipe": recipe.model_dump(),
    }
    try:
        rabbitmq_utils.publish_message("notification_service_queue", event)
    except Exception as exc:
        logger.error("Failed to publish new recipe event: %s", exc)

@app.post("/recipes", response_model=Recipe, status_code=201)
def create_recipe(request: RecipeCreateRequest) -> Recipe:
    """Create a new recipe and publish an event to the notification service."""
    recipe_id = str(uuid.uuid4())
    recipe = Recipe(
        id=recipe_id,
        title=request.title,
        ingredients=request.ingredients,
        instructions=request.instructions,
        author=request.author,
    )
    # Persist the recipe
    _recipe_store.add(recipe)
    # Publish event to notification service
    _publish_new_recipe_event(recipe)
    return recipe


@app.get("/recipes", response_model=List[Recipe])
def list_recipes() -> List[Recipe]:
    """Return all recipes."""
    return _recipe_store.get_all()


@app.post("/recipes/{recipe_id}/comments", response_model=Comment, status_code=201)
def add_comment(
    recipe_id: str = Path(..., description="Recipe identifier"),
    request: CommentCreateRequest = ...,
) -> Comment:
    """Add a comment to the specified recipe."""
    if not _recipe_store.exists(recipe_id):
        raise HTTPException(status_code=404, detail="Recipe not found")
    comment = Comment(author=request.author, comment=request.comment)
    _comment_store.add(recipe_id, comment)
    return comment


@app.get("/recipes/{recipe_id}/comments", response_model=List[Comment])
def get_comments(
    recipe_id: str = Path(..., description="Recipe identifier")
) -> List[Comment]:
    """Retrieve comments for a given recipe."""
    if not _recipe_store.exists(recipe_id):
        raise HTTPException(status_code=404, detail="Recipe not found")
    return _comment_store.get_for_recipe(recipe_id)