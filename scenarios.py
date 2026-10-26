"""Offline snapshot publication and read-only planetary scenario access."""

import copy
import hashlib
import json
import math
import os
import re
import sqlite3
import tempfile
import uuid
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path

import systems as S

SCHEMA = 1
FLAG_MANUAL = 64
SLUG = re.compile(r"[a-z0-9][a-z0-9-]{0,79}")
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}")
PROVENANCE = {"observed", "simulated", "manual", "derived"}
PLANET_FIELDS = {
    "id", "name", "a_au", "e", "mass_mearth", "radius_rearth", "period_d", "period_source",
    "provenance", "source", "mass_estimated", "radius_estimated", "mass_kind", "disputed",
    "discovery", "year", "moons", "minor_moons", "notes",
}
MOON_FIELDS = {"id", "name", "a_km", "mass_mearth", "radius_km", "period_d", "period_source",
               "provenance", "notes"}
STAR_FIELDS = {"teff", "lum", "mass", "radius", "category", "spectral_class", "abs_mag",
               "source", "metallicity", "provenance"}


class ScenarioError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def read_json(path):
    def invalid(value):
        raise ValueError(f"Non-finite JSON number: {value}")
    return json.loads(Path(path).read_text(encoding="utf-8"), parse_constant=invalid)


def fingerprint(stars):
    return hashlib.sha256(dumps(stars).encode("utf-8")).hexdigest()


def slug(value):
    if not isinstance(value, str) or not SLUG.fullmatch(value):
        raise ScenarioError("IDs must be lowercase letters, digits and hyphens (1-80 characters).")
    return value


def stable_id(kind, parent, label):
    return f"{kind}-{uuid.uuid5(uuid.NAMESPACE_URL, f'StarExplorer:{parent}:{label}').hex}"


def atomic_json(path, value):
    path = Path(path)
    fd, temporary = tempfile.mkstemp(prefix=".publish-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            out.write(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def publication_lock(root):
    root.mkdir(parents=True, exist_ok=True)
    path = root / ".publish.lock"
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise ScenarioError(f"Another publisher is running ({path}). If it crashed, remove this lock after verifying it has stopped.") from exc
    try:
        os.close(fd)
        yield
    finally:
        path.unlink()


def connect(path):
    if not path.is_file():
        raise ScenarioError(f"Published database is missing: {path.name}", 503)
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)


def create_database(path):
    db = sqlite3.connect(path)
    db.executescript("""
        CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE systems (
            id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, ordinal INTEGER NOT NULL UNIQUE,
            document TEXT NOT NULL, editable TEXT NOT NULL, planets INTEGER NOT NULL, flags INTEGER NOT NULL
        );
        CREATE TABLE object_ids (id TEXT PRIMARY KEY, star_id TEXT NOT NULL);
    """)
    return db


def object_ids(editable):
    yield editable["star_id"]
    for planet in editable["planets"]:
        yield planet["id"]
        for moon in planet["moons"]:
            yield moon["id"]


def insert_system(db, ordinal, document, editable):
    db.execute("INSERT INTO systems VALUES (?,?,?,?,?,?,?)",
               (editable["star_id"], editable["name"], ordinal, dumps(document), dumps(editable),
                len(document["planets"]), document["flags"]))
    db.executemany("INSERT INTO object_ids VALUES (?,?)",
                   ((identifier, editable["star_id"]) for identifier in object_ids(editable)))


def metadata(db, value):
    db.executemany("INSERT INTO metadata VALUES (?,?)", ((key, dumps(v)) for key, v in value.items()))


def summary_of(db, meta, baseline=None):
    if baseline:
        counts = list(baseline["planets"])
        flags = list(baseline["flags"])
    else:
        counts = [0] * meta["star_count"]
        flags = [0] * meta["star_count"]
    for ordinal, count, flag in db.execute("SELECT ordinal,planets,flags FROM systems"):
        counts[ordinal], flags[ordinal] = count, flag
    return dict(meta, planets=counts, flags=flags)


def annotate_snapshot(star, document, known):
    document = copy.deepcopy(document)
    sid = stable_id("star", "", star["name"])
    document["id"] = sid
    document["provenance"] = "observed" if document["confirmed"] else "simulated"
    st = document["star"]
    st["provenance"] = "observed" if known and known.get("star") else "derived"
    editable = {
        "schema_version": SCHEMA, "star_id": sid, "name": star["name"],
        "star": {k: v for k, v in st.items() if k in STAR_FIELDS},
        "hosts": document["hosts"], "planets": [],
    }
    observed = {p["name"]: p for p in (known or {}).get("planets", [])}
    for index, p in enumerate(document["planets"]):
        p["id"] = stable_id("planet", sid, str(index))
        p["provenance"] = "observed" if known else "simulated"
        p["period_source"] = "observed" if observed.get(p["name"], {}).get("period_d") else "derived"
        for mi, moon in enumerate(p["moons"]):
            moon["id"] = stable_id("moon", p["id"], str(mi))
            moon["provenance"] = "simulated" if p.get("moons_simulated") else p["provenance"]
            moon["period_source"] = "observed" if moon["provenance"] == "observed" else "derived"
        item = {k: copy.deepcopy(v) for k, v in p.items() if k in PLANET_FIELDS}
        if item["period_source"] == "derived":
            item.pop("period_d", None)
        for moon in item["moons"]:
            for key in list(moon):
                if key not in MOON_FIELDS or (key == "period_d" and moon["period_source"] == "derived"):
                    del moon[key]
        editable["planets"].append(item)
    return document, editable


def baseline_meta(root, baseline_id):
    path = root / slug(baseline_id) / "manifest.json"
    if not path.exists():
        raise ScenarioError(f"Unknown baseline '{baseline_id}'", 404)
    value = read_json(path)
    if not isinstance(value, dict) or value.get("kind") != "baseline" or value.get("id") != baseline_id:
        raise ScenarioError("Pinned baseline manifest is invalid.", 503)
    validate_published(value)
    return value


def published_meta(root, scenario_id):
    folder = root / slug(scenario_id)
    if not (folder / "published.json").exists():
        raise ScenarioError(f"Scenario '{scenario_id}' is not published. Run tools\\manage_scenarios.py publish {scenario_id}.", 503)
    value = read_json(folder / "published.json")
    if not isinstance(value, dict) or value.get("scenario_id") != scenario_id:
        raise ScenarioError("Published scenario manifest is invalid.", 503)
    validate_published(value)
    return value


def validate_published(value):
    for key in ("scenario_id", "baseline_id"):
        slug(value.get(key))
    for key in ("revision", "baseline_revision"):
        identifier = value.get(key)
        if not isinstance(identifier, str) or not ID.fullmatch(identifier):
            raise ScenarioError(f"Published manifest has an invalid {key}.", 503)
    if value.get("schema_version") != SCHEMA:
        raise ScenarioError("Unsupported published snapshot schema.", 503)
    if not isinstance(value.get("name"), str) or not value["name"].strip():
        raise ScenarioError("Published scenario needs a display name.", 503)


def load_summary(root, meta):
    with closing(connect(root / meta["scenario_id"] / f"{meta['revision']}.sqlite")) as db:
        return json.loads(db.execute("SELECT value FROM metadata WHERE key='summary'").fetchone()[0])


def snapshot(data_dir, baseline_id, name=None, seed=None):
    data_dir = Path(data_dir)
    root = data_dir / "scenarios"
    slug(baseline_id)
    with publication_lock(root):
        folder = root / baseline_id
        if folder.exists():
            raise ScenarioError("Baseline ID already exists; use a new ID. Baselines are immutable.")
        source_hashes = {p: hashlib.sha256((data_dir / p).read_bytes()).hexdigest()
                         for p in ("stars.json", "known_planets.json", "solar_system.json")
                         if (data_dir / p).exists()}
        stars = read_json(data_dir / "stars.json")["stars"]
        known, _ = S.load_known_systems(data_dir)
        if seed is None:
            legacy = data_dir / "systems_summary.json"
            seed = read_json(legacy).get("seed", S.DEFAULT_SEED) if legacy.exists() else S.DEFAULT_SEED
        revision = uuid.uuid4().hex
        meta = {
            "schema_version": SCHEMA, "kind": "baseline", "id": baseline_id,
            "scenario_id": baseline_id, "name": name or baseline_id, "revision": revision,
            "baseline_id": baseline_id, "baseline_revision": revision,
            "seed": seed, "generator_version": S.GENERATOR_VERSION,
            "generator_hash": hashlib.sha256(Path(S.__file__).read_bytes()).hexdigest(),
            "sources": source_hashes, "catalogue_fingerprint": fingerprint(stars),
            "names_crc": S.names_crc(stars), "star_count": len(stars),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        folder.mkdir()
        path = folder / f"{revision}.sqlite"
        temporary = folder / f".{revision}.tmp"
        try:
            with closing(create_database(temporary)) as db:
                for i, star in enumerate(stars):
                    document, editable = annotate_snapshot(star, S.build_system(star, known.get(star["name"]), seed),
                                                           known.get(star["name"]))
                    insert_system(db, i, document, editable)
                    if (i + 1) % 10000 == 0:
                        print(f"  Captured {i + 1:,} / {len(stars):,} systems", flush=True)
                summary = summary_of(db, meta)
                for filename, digest in source_hashes.items():
                    if hashlib.sha256((data_dir / filename).read_bytes()).hexdigest() != digest:
                        raise ScenarioError("Source data changed while capturing the snapshot. Retry with stable inputs.")
                metadata(db, dict(meta, summary=summary))
                db.commit()
            os.replace(temporary, path)
            atomic_json(folder / "manifest.json", meta)
            atomic_json(folder / "published.json", meta)
            if not (root / "index.json").exists():
                atomic_json(root / "index.json", {"default_scenario": baseline_id})
        except BaseException:
            if temporary.exists():
                temporary.unlink()
            if not (folder / "published.json").exists():
                if path.exists():
                    path.unlink()
                manifest = folder / "manifest.json"
                if manifest.exists():
                    manifest.unlink()
                folder.rmdir()
            raise
        return meta


def create_scenario(data_dir, scenario_id, baseline_id, name=None):
    root = Path(data_dir) / "scenarios"
    slug(scenario_id)
    with publication_lock(root):
        base = baseline_meta(root, baseline_id)
        folder = root / scenario_id
        if folder.exists():
            raise ScenarioError("Scenario ID already exists.")
        folder.mkdir()
        (folder / "overrides").mkdir()
        atomic_json(folder / "manifest.json", {
            "schema_version": SCHEMA, "kind": "scenario", "id": scenario_id,
            "name": name or scenario_id, "baseline_id": baseline_id, "baseline_revision": base["revision"],
        })
    return publish(data_dir, scenario_id)


def check_keys(value, fields, label):
    if not isinstance(value, dict):
        raise ScenarioError(f"{label} must be an object.")
    extra = value.keys() - fields
    if extra:
        raise ScenarioError(f"{label}: unknown fields {', '.join(sorted(extra))}. Edit physical inputs, not derived display fields.")


def positive(value, label, zero=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ScenarioError(f"{label} must be a finite number.")
    if value < 0 or (value == 0 and not zero):
        raise ScenarioError(f"{label} must be {'non-negative' if zero else 'positive'}.")
    if not zero and value < 1e-20:
        raise ScenarioError(f"{label} is too small for supported physical calculations (minimum 1e-20).")
    return value


def bounded(value, label, maximum, zero=False):
    value = positive(value, label, zero=zero)
    if value > maximum:
        raise ScenarioError(f"{label} must not exceed {maximum:g}.")
    return value


def text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ScenarioError(f"{label} must be a nonempty string.")
    return value


def validate_body(body, fields, label, ids):
    check_keys(body, fields, label)
    text(body.get("name"), f"{label}.name")
    identifier = body.get("id")
    if not isinstance(identifier, str) or not ID.fullmatch(identifier) or identifier in ids:
        raise ScenarioError(f"{label}.id must be a unique stable identifier (letters, digits, . _ : -).")
    ids.add(identifier)
    if body.get("provenance") not in {"observed", "simulated", "manual"}:
        raise ScenarioError(f"{label}.provenance must be observed, simulated or manual.")
    if body.get("period_source") not in {"observed", "derived"}:
        raise ScenarioError(f"{label}.period_source must be observed or derived.")
    if body["period_source"] == "observed":
        bounded(body.get("period_d"), f"{label}.period_d", 1e12)
        if body["provenance"] != "observed":
            raise ScenarioError(f"{label}: only observed objects can have observed periods; set period_source to derived.")
    elif "period_d" in body:
        raise ScenarioError(f"{label}: remove period_d when period_source is derived.")
    positive(body.get("mass_mearth"), f"{label}.mass_mearth")
    if "notes" in body and not isinstance(body["notes"], str):
        raise ScenarioError(f"{label}.notes must be a string.")
    for key in ("mass_estimated", "radius_estimated", "disputed"):
        if key in body and not isinstance(body[key], bool):
            raise ScenarioError(f"{label}.{key} must be a boolean.")
    for key in ("source", "mass_kind", "discovery"):
        if key in body and not isinstance(body[key], str):
            raise ScenarioError(f"{label}.{key} must be a string.")
    if "year" in body and body["year"] is not None and (
            isinstance(body["year"], bool) or not isinstance(body["year"], int)):
        raise ScenarioError(f"{label}.year must be an integer or null.")


def changed_provenance(body, original, exclude):
    """An edited physical record cannot silently keep its observational attribution."""
    current = {k: v for k, v in body.items() if k not in exclude}
    previous = {k: v for k, v in (original or {}).items() if k not in exclude}
    if current != previous:
        body["provenance"] = "manual"
        body["period_source"] = "derived"
        body.pop("period_d", None)
        if "source" in body:
            body["source"] = "manual"
        for key in ("mass_estimated", "radius_estimated", "mass_kind", "discovery", "year", "disputed"):
            body.pop(key, None)
    return body


def prepare_override(editable, original, seed):
    check_keys(editable, {"schema_version", "star_id", "name", "star", "hosts", "planets"}, "system")
    if editable.get("schema_version") != SCHEMA:
        raise ScenarioError("Unsupported editable schema version.")
    if editable.get("star_id") != original["star_id"]:
        raise ScenarioError("System star_id does not match the pinned baseline.")
    text(editable.get("name"), "system.name")
    st = editable.get("star")
    check_keys(st, STAR_FIELDS, "star")
    for key, maximum in (("teff", 1e7), ("lum", 1e12), ("mass", 1e6), ("radius", 1e8)):
        bounded(st.get(key), f"star.{key}", maximum)
    if st.get("category") not in S.CATEGORY_LABELS:
        raise ScenarioError("Invalid stellar category.")
    text(st.get("spectral_class"), "star.spectral_class")
    text(st.get("source"), "star.source")
    if st.get("provenance") not in PROVENANCE:
        raise ScenarioError("Invalid stellar provenance.")
    for key in ("abs_mag", "metallicity"):
        val = st.get(key)
        if val is not None and (isinstance(val, bool) or not isinstance(val, (int, float)) or not math.isfinite(val)):
            raise ScenarioError(f"star.{key} must be a finite number or null.")
    if not isinstance(editable.get("hosts"), list) or not all(isinstance(h, str) for h in editable["hosts"]):
        raise ScenarioError("hosts must be a list of strings.")
    if not isinstance(editable.get("planets"), list) or len(editable["planets"]) > 65535:
        raise ScenarioError("planets must be an explicit list with at most 65535 entries.")
    editable = copy.deepcopy(editable)
    st = editable["star"]
    if st != original["star"]:
        st["provenance"], st["source"] = "manual", "Manual scenario stellar parameters"
    star_changed = st != original["star"]
    ids = {editable["star_id"]}
    originals = {p["id"]: p for p in original["planets"]}
    warnings = []
    for i, planet in enumerate(editable["planets"]):
        label = f"planet[{i}]"
        validate_body(planet, PLANET_FIELDS, label, ids)
        for key in ("a_au", "radius_rearth"):
            bounded(planet.get(key), f"{label}.{key}", 1e7)
        bounded(planet["mass_mearth"], f"{label}.mass_mearth", 1e9)
        if positive(planet.get("e"), f"{label}.e", zero=True) >= 1:
            raise ScenarioError(f"{label}.e must be less than 1.")
        if not isinstance(planet.get("moons"), list):
            raise ScenarioError(f"{label}.moons must be an explicit list (use [] for none).")
        minor = planet.get("minor_moons")
        if isinstance(minor, bool) or not isinstance(minor, int) or minor < 0:
            raise ScenarioError(f"{label}.minor_moons must be a non-negative integer.")
        previous = originals.get(planet["id"])
        before = planet["provenance"]
        changed_provenance(planet, previous, {"moons", "minor_moons", "notes", "name"})
        if before != planet["provenance"]:
            warnings.append(f"{planet['name']}: changed or newly added physical data is marked manual; its period is recalculated.")
        if star_changed:
            planet["period_source"] = "derived"
            planet.pop("period_d", None)
        old_moons = {m["id"]: m for m in (previous or {}).get("moons", [])}
        for j, moon in enumerate(planet["moons"]):
            ml = f"{label}.moon[{j}]"
            validate_body(moon, MOON_FIELDS, ml, ids)
            for key in ("a_km", "radius_km"):
                bounded(moon.get(key), f"{ml}.{key}", 1e13)
            bounded(moon["mass_mearth"], f"{ml}.mass_mearth", 1e9)
            before = moon["provenance"]
            changed_provenance(moon, old_moons.get(moon["id"]), {"name", "notes"})
            if before != moon["provenance"]:
                warnings.append(f"{moon['name']}: changed or newly added physical data is marked manual; its period is recalculated.")
            if previous and planet["mass_mearth"] != previous["mass_mearth"]:
                moon["period_source"] = "derived"
                moon.pop("period_d", None)
            if moon["mass_mearth"] >= planet["mass_mearth"]:
                raise ScenarioError(f"{ml}: moon mass must be less than its planet's mass.")
            if moon["a_km"] <= planet["radius_rearth"] * 6371 + moon["radius_km"]:
                warnings.append(f"{moon['name']}: moon orbit intersects the planet.")
            hill = planet["a_au"] * (1 - planet["e"]) * (planet["mass_mearth"] / (3 * st["mass"] * S.MEARTH_PER_MSUN)) ** (1 / 3)
            if moon["a_km"] > 0.49 * hill * S.AU_KM:
                warnings.append(f"{moon['name']}: orbit exceeds the approximate prograde stable Hill limit.")
        if planet["a_au"] * (1 - planet["e"]) <= st["radius"] * S.AU_PER_RSUN:
            warnings.append(f"{planet['name']}: orbit intersects the star.")
    ordered = sorted(editable["planets"], key=lambda p: p["a_au"])
    for p, q in zip(ordered, ordered[1:]):
        hill = ((p["mass_mearth"] + q["mass_mearth"]) / (3 * st["mass"] * S.MEARTH_PER_MSUN)) ** (1 / 3) * (p["a_au"] + q["a_au"]) / 2
        if q["a_au"] - p["a_au"] < 8 * hill or p["a_au"] * (1 + p["e"]) >= q["a_au"] * (1 - q["e"]):
            warnings.append(f"{p['name']} / {q['name']}: crossing or closely spaced orbits; stability is not established.")
    document = derive_system(editable, seed)
    if editable != original:
        document["flags"] |= FLAG_MANUAL
        document["provenance"] = "manual"
    return document, editable, warnings


def derive_system(editable, seed):
    """Use the existing physics helpers with explicit planets/moons; never simulate missing bodies."""
    st = editable["star"]
    catalogue_star = {"name": editable["name"], "spectral_class": st["spectral_class"], "abs_mag": st.get("abs_mag")}
    raw = copy.deepcopy(editable["planets"])
    for planet in raw:
        if planet["period_source"] == "derived":
            planet["period_d"] = S.orbital_period_days(planet["a_au"], st["mass"], planet["mass_mearth"])
        for moon in planet["moons"]:
            if moon["period_source"] == "derived":
                moon["period_d"] = 2 * math.pi * math.sqrt(moon["a_km"] ** 3 /
                    (S.GM_EARTH_KM3_S2 * (planet["mass_mearth"] + moon["mass_mearth"]))) / 86400
    # The generator already derives planetary descriptions and HZ status. Supply all bodies explicitly.
    document = S.build_system(catalogue_star, {"star": st, "star_source": st["source"],
                                              "hosts": editable["hosts"], "planets": raw}, seed)
    props = dict(st, group=S.teff_group(st["teff"]), category_label=S.CATEGORY_LABELS[st["category"]])
    props["habitable_host"] = S._host_can_be_habitable(props)
    document["star"] = props
    document["id"] = editable["star_id"]
    document["flags"] &= ~(S.FLAG_CONFIRMED | S.FLAG_HABITABLE | S.FLAG_CONSERVATIVE | S.FLAG_HAB_MOON)
    for p in document["planets"]:
        p["source"] = "confirmed" if p["provenance"] == "observed" else p["provenance"]
        p["habitable"] = bool(p["hz"] and props["habitable_host"] and S.is_rocky(p["radius_rearth"], p["mass_mearth"])
                             and p["mass_mearth"] >= S.MIN_HABITABLE_MASS)
        if p["habitable"]:
            document["flags"] |= S.FLAG_HABITABLE
            if p["hz"] == "conservative":
                document["flags"] |= S.FLAG_CONSERVATIVE
        climate = "hot" if p["insolation"] > document["habitable_zone"]["flux"]["recent_venus"] else "temperate" if p["hz"] else "cold"
        p["description"] = S._describe(p["type"], climate, p["teq_k"], p["period_d"], p["habitable"], p["radius_rearth"])
        if p["provenance"] == "observed":
            document["flags"] |= S.FLAG_CONFIRMED
        p["moons_simulated"] = any(m["provenance"] == "simulated" for m in p["moons"])
        for moon in p["moons"]:
            moon["habitable"] = bool(p["hz"] and props["habitable_host"] and moon["mass_mearth"] >= S.MIN_HABITABLE_MASS)
            if moon["habitable"]:
                document["flags"] |= S.FLAG_HAB_MOON
    document["confirmed"] = bool(document["planets"]) and all(p["provenance"] == "observed" for p in document["planets"])
    document["provenance"] = "observed" if document["confirmed"] else "simulated"
    return document


def publish(data_dir, scenario_id):
    data_dir = Path(data_dir)
    root = data_dir / "scenarios"
    with publication_lock(root):
        folder = root / slug(scenario_id)
        if not (folder / "manifest.json").exists():
            raise ScenarioError("Scenario does not exist.", 404)
        manifest = read_json(folder / "manifest.json")
        if not isinstance(manifest, dict) or manifest.get("kind") != "scenario":
            raise ScenarioError("Baselines cannot be republished; create a new baseline.")
        if manifest.get("schema_version") != SCHEMA or manifest.get("id") != scenario_id:
            raise ScenarioError("Scenario manifest schema or ID is invalid.")
        base = baseline_meta(root, manifest["baseline_id"])
        if base["revision"] != manifest["baseline_revision"]:
            raise ScenarioError("Pinned baseline revision does not match.")
        stars = read_json(data_dir / "stars.json")["stars"]
        if fingerprint(stars) != base["catalogue_fingerprint"]:
            raise ScenarioError("Star catalogue does not match the pinned baseline.")
        revision = uuid.uuid4().hex
        meta = {k: v for k, v in base.items() if k not in {"kind", "id", "name", "scenario_id", "revision", "created_at"}}
        meta.update(scenario_id=scenario_id, name=text(manifest["name"], "scenario name"), revision=revision,
                    created_at=datetime.now(timezone.utc).isoformat(),
                    publisher_generator_version=S.GENERATOR_VERSION,
                    publisher_generator_hash=hashlib.sha256(Path(S.__file__).read_bytes()).hexdigest())
        temporary = folder / f".{revision}.tmp"
        warnings = []
        try:
            with closing(connect(root / base["id"] / f"{base['revision']}.sqlite")) as source, closing(create_database(temporary)) as db:
                seen = set()
                for path in sorted((folder / "overrides").glob("*.json")):
                    editable = read_json(path)
                    if not isinstance(editable, dict) or not isinstance(editable.get("star_id"), str):
                        raise ScenarioError(f"{path.name}: missing star_id.")
                    row = source.execute("SELECT ordinal,editable FROM systems WHERE id=?", (editable["star_id"],)).fetchone()
                    if row is None:
                        raise ScenarioError(f"{path.name}: unknown star_id.")
                    if editable["star_id"] in seen:
                        raise ScenarioError("Duplicate system replacements.")
                    seen.add(editable["star_id"])
                    original = json.loads(row[1])
                    document, canonical, notes = prepare_override(editable, original, base["seed"])
                    if canonical == original:
                        continue
                    for identifier in object_ids(canonical):
                        owner = source.execute("SELECT star_id FROM object_ids WHERE id=?", (identifier,)).fetchone()
                        if owner and owner[0] != editable["star_id"]:
                            raise ScenarioError(f"Object ID {identifier} belongs to another system.")
                    if canonical["name"] != json.loads(row[1])["name"]:
                        other = source.execute("SELECT id FROM systems WHERE id=? OR name=?",
                                               (canonical["name"], canonical["name"])).fetchone()
                        if other and other[0] != canonical["star_id"]:
                            raise ScenarioError("System display name collides with another catalogue star.")
                    insert_system(db, row[0], document, canonical)
                    warnings.extend(notes)
                base_summary = json.loads(source.execute("SELECT value FROM metadata WHERE key='summary'").fetchone()[0])
                summary = summary_of(db, meta, base_summary)
                metadata(db, dict(meta, summary=summary))
                db.commit()
            destination = folder / f"{revision}.sqlite"
            os.replace(temporary, destination)
            try:
                atomic_json(folder / "published.json", meta)
            except BaseException:
                destination.unlink()
                raise
        finally:
            if temporary.exists():
                temporary.unlink()
        return dict(meta, warnings=warnings)


class Store:
    """No write-capable database connections and no generator calls in the request path."""

    def __init__(self, data_dir, stars):
        self.root = Path(data_dir) / "scenarios"
        self.catalogue_fingerprint = fingerprint(stars)
        self.names_crc = S.names_crc(stars)

    def resolve(self, scenario_id=None, revision=None):
        if not self.root.exists() or not (self.root / "index.json").exists():
            raise ScenarioError("No snapshot installed. Run: python tools\\manage_scenarios.py snapshot baseline-001", 503)
        if scenario_id is None:
            scenario_id = read_json(self.root / "index.json")["default_scenario"]
        latest = published_meta(self.root, scenario_id)
        if revision is not None and revision != latest["revision"]:
            if not ID.fullmatch(revision):
                raise ScenarioError("Invalid revision.", 400)
            path = self.root / scenario_id / f"{revision}.sqlite"
            if not path.exists():
                raise ScenarioError("Requested revision is unavailable. Refresh scenarios.", 409)
            with closing(connect(path)) as db:
                latest = {key: json.loads(val) for key, val in db.execute("SELECT key,value FROM metadata WHERE key!='summary'")}
            validate_published(latest)
            if latest["scenario_id"] != scenario_id or latest["revision"] != revision:
                raise ScenarioError("Published database does not match the requested revision.", 409)
        if latest.get("catalogue_fingerprint") != self.catalogue_fingerprint:
            raise ScenarioError("Scenario does not match the current star catalogue. Create a compatible snapshot.", 409)
        return latest

    def list(self):
        default = self.resolve()
        entries = []
        for path in sorted(self.root.glob("*/published.json")):
            meta = published_meta(self.root, path.parent.name)
            if meta.get("catalogue_fingerprint") == self.catalogue_fingerprint:
                entries.append({k: meta[k] for k in ("scenario_id", "name", "revision", "baseline_id")} | {"id": meta["scenario_id"]})
        return {"default_scenario": default["scenario_id"], "catalogue_fingerprint": self.catalogue_fingerprint,
                "names_crc": self.names_crc, "scenarios": entries}

    def summary(self, meta):
        return load_summary(self.root, meta)

    def system(self, meta, name, editable=False):
        column = "editable" if editable else "document"
        with closing(connect(self.root / meta["baseline_id"] / f"{meta['baseline_revision']}.sqlite")) as base:
            row = base.execute("SELECT id FROM systems WHERE id=? OR name=?", (name, name)).fetchone()
            sid = row[0] if row else name
            with closing(connect(self.root / meta["scenario_id"] / f"{meta['revision']}.sqlite")) as db:
                row = db.execute(f"SELECT {column} FROM systems WHERE id=? OR name=?", (sid, name)).fetchone()
            if row is None:
                row = base.execute(f"SELECT {column} FROM systems WHERE id=?", (sid,)).fetchone()
        if row is None:
            raise ScenarioError(f"No system named '{name}'.", 404)
        document = json.loads(row[0])
        if not editable:
            document.update(scenario_id=meta["scenario_id"], revision=meta["revision"])
        return document


def export_system(data_dir, scenario_id, name, output=None):
    data_dir = Path(data_dir)
    stars = read_json(data_dir / "stars.json")["stars"]
    store = Store(data_dir, stars)
    meta = store.resolve(scenario_id)
    if scenario_id == meta["baseline_id"]:
        raise ScenarioError("Create an editable scenario first; baseline snapshots are immutable.")
    value = store.system(meta, name, editable=True)
    path = Path(output) if output else store.root / scenario_id / "overrides" / f"{value['star_id']}.json"
    if path.exists():
        raise ScenarioError(f"Refusing to overwrite existing editable file: {path}")
    atomic_json(path, value)
    return path


def set_default(data_dir, scenario_id):
    data_dir = Path(data_dir)
    root = data_dir / "scenarios"
    with publication_lock(root):
        store = Store(data_dir, read_json(data_dir / "stars.json")["stars"])
        store.resolve(scenario_id)
        atomic_json(root / "index.json", {"default_scenario": scenario_id})


def purge(data_dir, dry_run=False):
    """Remove obsolete revision files only after validating every retained dependency."""
    root = Path(data_dir) / "scenarios"
    if not root.is_dir():
        raise ScenarioError("Scenario store does not exist.")
    with publication_lock(root):
        retained = set()
        candidates = []

        def retain(folder_id, revision):
            slug(folder_id)
            if not isinstance(revision, str) or not ID.fullmatch(revision):
                raise ScenarioError("Invalid revision reference; purge aborted.")
            path = root / folder_id / f"{revision}.sqlite"
            if not path.is_file() or path.resolve().parent != root.resolve() / folder_id:
                raise ScenarioError(f"Missing or linked dependency: {path}. Purge aborted.")
            retained.add(path)

        folders = []
        for folder in sorted(root.iterdir()):
            if not folder.is_dir():
                continue
            databases = sorted(folder.glob("*.sqlite"))
            manifest_path = folder / "manifest.json"
            if not databases and not manifest_path.exists():
                continue
            if folder.resolve() != root.resolve() / folder.name:
                raise ScenarioError(f"Linked scenario folder: {folder}. Purge aborted.")
            slug(folder.name)
            manifest = read_json(manifest_path)
            if not isinstance(manifest, dict) or manifest.get("id") != folder.name or manifest.get("schema_version") != SCHEMA:
                raise ScenarioError(f"Invalid manifest: {manifest_path}. Purge aborted.")
            if manifest.get("kind") == "baseline":
                baseline_meta(root, folder.name)
                retain(folder.name, manifest["revision"])
            elif manifest.get("kind") == "scenario":
                baseline_meta(root, manifest["baseline_id"])
                retain(manifest["baseline_id"], manifest["baseline_revision"])
            else:
                raise ScenarioError(f"Unknown manifest kind: {manifest_path}. Purge aborted.")
            if (folder / "published.json").exists():
                published = published_meta(root, folder.name)
                retain(folder.name, published["revision"])
                baseline_meta(root, published["baseline_id"])
                retain(published["baseline_id"], published["baseline_revision"])
            for path in databases:
                if not ID.fullmatch(path.stem) or path.resolve().parent != folder.resolve():
                    raise ScenarioError(f"Invalid or linked revision: {path}. Purge aborted.")
            candidates.extend(databases)
            folders.append(folder.name)
        if (root / "index.json").exists():
            default = read_json(root / "index.json")["default_scenario"]
            if default not in folders or not (root / slug(default) / "published.json").exists():
                raise ScenarioError("Default scenario is not published; purge aborted.")
        obsolete = [path for path in candidates if path not in retained]
        size = sum(path.stat().st_size for path in obsolete)
        removed = []
        for path in obsolete:
            if not dry_run:
                try:
                    path.unlink()
                except OSError as exc:
                    raise ScenarioError(f"Could not delete {path}: {exc}. Already deleted {len(removed)} revision(s).") from exc
            removed.append(str(path))
        return {"dry_run": dry_run, "files": removed, "file_count": len(removed), "bytes": size,
                "retained_count": len(retained)}
