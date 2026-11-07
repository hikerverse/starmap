"""StarExplorer - a Flask web app serving a three.js 3D star map."""

import gzip
import json
import os
import re
import sqlite3
import threading
from functools import lru_cache
from pathlib import Path

from flask import Flask, Response, abort, render_template, request

import datasets
from query_api import create_query_blueprint

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
_dataset_setting = os.environ.get("STAREXPLORER_DATABASE")
DATASET_FILE = Path(_dataset_setting) if _dataset_setting else DATA_DIR / "stars.sqlite"
if not DATASET_FILE.is_absolute():
    DATASET_FILE = BASE_DIR / DATASET_FILE
STARS_FILE = DATA_DIR / "stars.json"
KNOWN_PLANETS_FILE = DATA_DIR / "known_planets.json"
SOLAR_SYSTEM_FILE = DATA_DIR / "solar_system.json"
NEUTRON_STARS_FILE = BASE_DIR / "data" / "neutron_stars.json"
BLACK_HOLES_FILE = BASE_DIR / "data" / "black_holes.json"
SOVEREIGNTIES_FILE = BASE_DIR / "data" / "sovereignties.json"
NEBULAE_FILE = DATA_DIR / "nebulae.json"
NEBULA_TYPES = {"emission", "reflection", "planetary", "snr", "dark"}
GALAXIES_FILE = DATA_DIR / "galaxies.json"
GALAXY_TYPES = {"spiral", "elliptical", "irregular", "dwarf", "interacting", "peculiar", "active", "cluster"}

REQUIRED_FIELDS = {"name": str, "x": (int, float), "y": (int, float), "z": (int, float),
                   "colour": str, "spectral_class": str}
OPTIONAL_FIELDS = {"abs_mag": (int, float), "type": str, "constellation": str, "notes": str,
                   "distance_pc": (int, float), "ra_deg": (int, float), "dec_deg": (int, float),
                   "mass_msun": (int, float)}
HEX_COLOUR = re.compile(r"^#[0-9a-fA-F]{6}$")

app = Flask(__name__)

# The complete stellar catalogue is serialized and cached until the active database changes.
_payload_cache: dict = {}


def load_stars(path: Path = STARS_FILE) -> dict:
    """Load and validate the star database."""
    with path.open(encoding="utf-8") as f:
        data = json.load(f)

    stars = data.get("stars")
    if not isinstance(stars, list):
        raise ValueError(f"{path.name} must contain a 'stars' list")
    load_stars_list(stars)
    return data


def load_stars_list(stars: list) -> None:
    """Validate the per-object marker fields shared by stars and other map objects."""
    for i, star in enumerate(stars):
        for field, ftype in REQUIRED_FIELDS.items():
            value = star.get(field)
            # bool is a subclass of int, so exclude it explicitly
            if not isinstance(value, ftype) or isinstance(value, bool):
                raise ValueError(f"Star #{i} has missing/invalid field '{field}'")
        for field, ftype in OPTIONAL_FIELDS.items():
            value = star.get(field)
            if value is not None and (not isinstance(value, ftype) or isinstance(value, bool)):
                raise ValueError(f"Star #{i} has invalid field '{field}'")
        if not HEX_COLOUR.match(star["colour"]):
            raise ValueError(f"Star '{star['name']}' colour must be a hex string like #ffaa00")


def load_nebulae(path: Path = NEBULAE_FILE) -> dict:
    """Load and validate the nebula database (marker fields as for stars, plus size and optional puffs)."""
    with path.open(encoding="utf-8") as f:
        data = json.load(f)

    nebulae = data.get("nebulae")
    if not isinstance(nebulae, list):
        raise ValueError(f"{path.name} must contain a 'nebulae' list")
    load_stars_list(nebulae)
    for neb in nebulae:
        radius = neb.get("radius_pc")
        if not isinstance(radius, (int, float)) or isinstance(radius, bool) or radius <= 0:
            raise ValueError(f"Nebula '{neb['name']}' needs a positive 'radius_pc'")
        if neb.get("nebula_type") not in NEBULA_TYPES:
            raise ValueError(f"Nebula '{neb['name']}' has invalid 'nebula_type'")
        puffs = neb.get("puffs", [])
        if not isinstance(puffs, list) or not all(
                isinstance(p, list) and len(p) == 4 and all(isinstance(v, (int, float)) for v in p) for p in puffs):
            raise ValueError(f"Nebula '{neb['name']}' 'puffs' must be a list of [x, y, z, radius]")
    return data


def load_galaxies(path: Path = GALAXIES_FILE) -> dict:
    """Load and validate the curated extragalactic objects (marker fields as for stars, plus galaxy_type)."""
    with path.open(encoding="utf-8") as f:
        data = json.load(f)

    galaxies = data.get("galaxies")
    if not isinstance(galaxies, list):
        raise ValueError(f"{path.name} must contain a 'galaxies' list")
    load_stars_list(galaxies)
    for gal in galaxies:
        if gal.get("galaxy_type") not in GALAXY_TYPES:
            raise ValueError(f"Galaxy '{gal['name']}' has invalid 'galaxy_type'")
        size = gal.get("size_arcmin")
        if size is not None and (not isinstance(size, (int, float)) or isinstance(size, bool) or size <= 0):
            raise ValueError(f"Galaxy '{gal['name']}' 'size_arcmin' must be a positive number")
    return data


def load_sovereignties(path: Path = SOVEREIGNTIES_FILE) -> dict:
    """Load and validate the sovereignty groups (star membership is by star name)."""
    with path.open(encoding="utf-8") as f:
        data = json.load(f)

    groups = data.get("sovereignties")
    if not isinstance(groups, list):
        raise ValueError(f"{path.name} must contain a 'sovereignties' list")

    seen_names: set[str] = set()
    owner: dict[str, str] = {}
    for i, group in enumerate(groups):
        name = group.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError(f"Sovereignty #{i} has a missing/invalid 'name'")
        if name in seen_names:
            raise ValueError(f"Duplicate sovereignty name '{name}'")
        seen_names.add(name)
        if not isinstance(group.get("colour"), str) or not HEX_COLOUR.match(group["colour"]):
            raise ValueError(f"Sovereignty '{name}' colour must be a hex string like #ffaa00")
        if group.get("notes") is not None and not isinstance(group["notes"], str):
            raise ValueError(f"Sovereignty '{name}' has invalid 'notes'")
        members = group.get("stars")
        if not isinstance(members, list) or not all(isinstance(s, str) for s in members):
            raise ValueError(f"Sovereignty '{name}' must have a 'stars' list of star names")
        for star in members:
            if star in owner and owner[star] != name:
                raise ValueError(f"Star '{star}' is in both '{owner[star]}' and '{name}'")
            owner[star] = name

    return data


def stars_payload(path: Path = STARS_FILE, loader=load_stars) -> tuple[bytes, bytes]:
    stat = path.stat()
    cached = _payload_cache.get(path)
    if cached is None or cached["mtime"] != stat.st_mtime_ns or cached["size"] != stat.st_size:
        raw = json.dumps(loader(path), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        cached = {"mtime": stat.st_mtime_ns, "size": stat.st_size,
                  "raw": raw, "gzip": gzip.compress(raw, compresslevel=6)}
        _payload_cache[path] = cached
    return cached["raw"], cached["gzip"]


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/about")
def about():
    return render_template("about.html")


def json_file_response(path: Path, loader=load_stars) -> Response:
    try:
        raw, compressed = stars_payload(path, loader)
    except (OSError, ValueError) as exc:
        abort(503 if path == DATASET_FILE else 500, description=str(exc))
    return gzip_response(raw, compressed)


@app.route("/api/stars")
def api_stars():
    return json_file_response(DATASET_FILE, load_catalogue)


def load_catalogue(path: Path) -> dict:
    data = datasets.DatasetStore(path).catalogue()
    load_stars_list(data["stars"])
    return data


@app.route("/api/neutron-stars")
def api_neutron_stars():
    return json_file_response(NEUTRON_STARS_FILE)


@app.route("/api/black-holes")
def api_black_holes():
    return json_file_response(BLACK_HOLES_FILE)


@app.route("/api/nebulae")
def api_nebulae():
    return json_file_response(NEBULAE_FILE, load_nebulae)


@app.route("/api/galaxies")
def api_galaxies():
    return json_file_response(GALAXIES_FILE, load_galaxies)


@app.route("/api/sovereignties")
def api_sovereignties():
    return json_file_response(SOVEREIGNTIES_FILE, load_sovereignties)


# ---------------------------------------------------------------------------
# Planetary systems (see systems.py)
# ---------------------------------------------------------------------------
_systems_lock = threading.Lock()
_systems_state: dict = {}


def systems_state() -> dict:
    """Cache the active read-only dataset until its file changes."""
    stat = DATASET_FILE.stat()
    key = (str(DATASET_FILE.resolve()), stat.st_mtime_ns, stat.st_size)
    with _systems_lock:
        if _systems_state.get("key") != key:
            _systems_state.clear()
            _systems_state.update(key=key, store=datasets.DatasetStore(DATASET_FILE), stat=stat)
        return dict(_systems_state)


app.register_blueprint(create_query_blueprint(lambda: systems_state()["store"]))


def gzip_response(raw: bytes, compressed: bytes) -> Response:
    if "gzip" in request.accept_encodings:
        resp = Response(compressed, mimetype="application/json")
        resp.headers["Content-Encoding"] = "gzip"
    else:
        resp = Response(raw, mimetype="application/json")
    resp.headers["Vary"] = "Accept-Encoding"
    return resp


@app.route("/api/systems-summary")
def api_systems_summary():
    return dataset_response("summary")


@app.route("/api/system/<path:name>")
def api_system(name: str):
    return dataset_response("system", name)


@lru_cache(maxsize=16)
def dataset_summary_payload(path: str, mtime_ns: int, size: int) -> tuple[bytes, bytes]:
    raw = json.dumps(datasets.DatasetStore(path).summary(), ensure_ascii=False,
                     separators=(",", ":"), allow_nan=False).encode("utf-8")
    return raw, gzip.compress(raw, compresslevel=6)


def dataset_response(operation: str, name: str | None = None) -> Response:
    try:
        state = systems_state()
        store = state["store"]
        stat = state["stat"]
        if operation == "summary":
            raw, compressed = dataset_summary_payload(str(DATASET_FILE), stat.st_mtime_ns, stat.st_size)
            response = gzip_response(raw, compressed)
        else:
            response = Response(json.dumps(store.system(name), ensure_ascii=False,
                                           separators=(",", ":"), allow_nan=False), mimetype="application/json")
        response.headers["Cache-Control"] = "no-cache"
        response.set_etag(
            f"{store.meta['dataset_id']}-{stat.st_mtime_ns}-{operation}-{name or ''}".encode().hex()
        )
        return response.make_conditional(request)
    except datasets.DatasetNotFound as exc:
        app.logger.warning("Dataset request rejected: %s", exc)
        return Response(json.dumps({"error": str(exc)}), status=404, mimetype="application/json")
    except datasets.DatasetError as exc:
        app.logger.warning("Dataset request rejected: %s", exc)
        return Response(json.dumps({"error": str(exc)}), status=503, mimetype="application/json")
    except (OSError, ValueError, KeyError, sqlite3.Error):
        app.logger.exception("Could not read the active dataset")
        return Response(json.dumps({"error": "The active dataset is unavailable or invalid. Check the server logs and select a valid database."}),
                        status=503, mimetype="application/json")


if __name__ == "__main__":
    app.run(debug=True, port=int(os.environ.get("PORT", 5001)))
