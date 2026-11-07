"""Read-only spatial and stellar query endpoints."""

import math
import sqlite3
from functools import wraps

from flask import Blueprint, current_app, jsonify, request

import datasets

DEFAULT_LIMIT = 100
MAX_LIMIT = 1000
MAX_OFFSET = 1_000_000
MAX_RADIUS_PC = 1_000_000


class QueryParameterError(ValueError):
    pass


def create_query_blueprint(get_store):
    blueprint = Blueprint("dataset_queries", __name__, url_prefix="/api/query")

    def endpoint(handler):
        @wraps(handler)
        def wrapped(*args, **kwargs):
            try:
                response = jsonify(handler(*args, **kwargs))
                response.headers["Cache-Control"] = "no-cache"
                return response
            except QueryParameterError as exc:
                return jsonify(error=str(exc)), 400
            except datasets.DatasetNotFound as exc:
                return jsonify(error=str(exc)), 404
            except datasets.DatasetError as exc:
                current_app.logger.warning("Dataset query rejected: %s", exc)
                return jsonify(error=str(exc)), 503
            except (OSError, sqlite3.Error, ValueError, KeyError):
                current_app.logger.exception("Dataset query failed")
                return jsonify(error="The active dataset is unavailable or invalid."), 503
        return wrapped

    def number(name, required=True, default=None, minimum=None, maximum=None):
        values = request.args.getlist(name)
        if not values:
            if required:
                raise QueryParameterError(f"Missing required query parameter '{name}'.")
            return default
        if len(values) != 1:
            raise QueryParameterError(f"Query parameter '{name}' must be supplied once.")
        try:
            value = float(values[0])
        except ValueError as exc:
            raise QueryParameterError(f"Query parameter '{name}' must be a number.") from exc
        if not math.isfinite(value):
            raise QueryParameterError(f"Query parameter '{name}' must be finite.")
        if minimum is not None and value < minimum:
            raise QueryParameterError(f"Query parameter '{name}' must be at least {minimum}.")
        if maximum is not None and value > maximum:
            raise QueryParameterError(f"Query parameter '{name}' must not exceed {maximum}.")
        return value

    def integer(name, default, minimum, maximum):
        value = number(name, required=False, default=default, minimum=minimum, maximum=maximum)
        value = float(value)
        if not value.is_integer():
            raise QueryParameterError(f"Query parameter '{name}' must be an integer.")
        return int(value)

    def coordinates():
        return tuple(number(axis, minimum=-1_000_000_000, maximum=1_000_000_000)
                     for axis in ("x", "y", "z"))

    @blueprint.get("/stars/within")
    @endpoint
    def stars_within():
        x, y, z = coordinates()
        radius = number("radius_pc", minimum=0, maximum=MAX_RADIUS_PC)
        limit = integer("limit", DEFAULT_LIMIT, 1, MAX_LIMIT)
        offset = integer("offset", 0, 0, MAX_OFFSET)
        return get_store().stars_within(x, y, z, radius, limit, offset)

    @blueprint.get("/stars/nearest")
    @endpoint
    def nearest_stars():
        x, y, z = coordinates()
        limit = integer("limit", 25, 1, MAX_LIMIT)
        max_radius = number("max_radius_pc", required=False, minimum=0, maximum=MAX_RADIUS_PC)
        return get_store().nearest_stars(x, y, z, limit, max_radius)

    @blueprint.get("/stars/<path:name>/within")
    @endpoint
    def stars_within_named(name):
        radius = number("radius_pc", minimum=0, maximum=MAX_RADIUS_PC)
        limit = integer("limit", DEFAULT_LIMIT, 1, MAX_LIMIT)
        offset = integer("offset", 0, 0, MAX_OFFSET)
        store = get_store()
        center = store.star_position(name)
        result = store.stars_within(
            center["x"], center["y"], center["z"], radius, limit, offset
        )
        result["center"] = center
        return result

    @blueprint.get("/distance")
    @endpoint
    def distance_between():
        first_values = request.args.getlist("from")
        second_values = request.args.getlist("to")
        if len(first_values) != 1 or not first_values[0].strip():
            raise QueryParameterError("Supply exactly one nonempty 'from' parameter.")
        if len(second_values) != 1 or not second_values[0].strip():
            raise QueryParameterError("Supply exactly one nonempty 'to' parameter.")
        return get_store().distance_between(first_values[0].strip(), second_values[0].strip())

    return blueprint
