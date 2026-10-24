"""StarExplorer - a Flask web app serving a three.js 3D star map."""

import gzip
import json
import os
import re
from pathlib import Path

from flask import Flask, Response, abort, render_template, request

BASE_DIR = Path(__file__).resolve().parent
STARS_FILE = BASE_DIR / "data" / "stars.json"
NEUTRON_STARS_FILE = BASE_DIR / "data" / "neutron_stars.json"
BLACK_HOLES_FILE = BASE_DIR / "data" / "black_holes.json"
SOVEREIGNTIES_FILE = BASE_DIR / "data" / "sovereignties.json"

REQUIRED_FIELDS = {"name": str, "x": (int, float), "y": (int, float), "z": (int, float),
                   "colour": str, "spectral_class": str}
OPTIONAL_FIELDS = {"abs_mag": (int, float), "type": str, "constellation": str, "notes": str,
                   "distance_pc": (int, float), "ra_deg": (int, float), "dec_deg": (int, float),
                   "mass_msun": (int, float)}
HEX_COLOUR = re.compile(r"^#[0-9a-fA-F]{6}$")

app = Flask(__name__)

# The full HYG import is ~12 MB, so the validated, serialised payload is cached
# and only rebuilt when the JSON file changes on disk.
_payload_cache: dict = {}


def load_stars(path: Path = STARS_FILE) -> dict:
    """Load and validate the star database."""
    with path.open(encoding="utf-8") as f:
        data = json.load(f)

    stars = data.get("stars")
    if not isinstance(stars, list):
        raise ValueError(f"{path.name} must contain a 'stars' list")

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
    mtime = path.stat().st_mtime_ns
    cached = _payload_cache.get(path)
    if cached is None or cached["mtime"] != mtime:
        raw = json.dumps(loader(path), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        cached = {"mtime": mtime, "raw": raw, "gzip": gzip.compress(raw, compresslevel=6)}
        _payload_cache[path] = cached
    return cached["raw"], cached["gzip"]


@app.route("/")
def index():
    return render_template("index.html")


def json_file_response(path: Path, loader=load_stars) -> Response:
    try:
        raw, compressed = stars_payload(path, loader)
    except (OSError, ValueError) as exc:
        abort(500, description=str(exc))

    if "gzip" in request.accept_encodings:
        resp = Response(compressed, mimetype="application/json")
        resp.headers["Content-Encoding"] = "gzip"
    else:
        resp = Response(raw, mimetype="application/json")
    resp.headers["Vary"] = "Accept-Encoding"
    return resp


@app.route("/api/stars")
def api_stars():
    return json_file_response(STARS_FILE)


@app.route("/api/neutron-stars")
def api_neutron_stars():
    return json_file_response(NEUTRON_STARS_FILE)


@app.route("/api/black-holes")
def api_black_holes():
    return json_file_response(BLACK_HOLES_FILE)


@app.route("/api/sovereignties")
def api_sovereignties():
    return json_file_response(SOVEREIGNTIES_FILE, load_sovereignties)


if __name__ == "__main__":
    app.run(debug=True, port=int(os.environ.get("PORT", 5001)))
