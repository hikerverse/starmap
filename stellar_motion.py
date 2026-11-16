"""Measured, heliocentric stellar motion in equatorial Cartesian coordinates."""

import json
import math
import sqlite3
import zlib
from contextlib import closing

KM_S_TO_PC_YR = 31557600 / 3.085677581491367e13
MAS_TO_RAD = math.pi / (180 * 3600000)


def number(value):
    if value in (None, "") or isinstance(value, bool):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def velocity(ra, dec, distance, pmra, pmdec, rv):
    """Convert mu_alpha*cos(delta), mu_delta (mas/yr), RV (km/s) to pc/yr."""
    a, d = math.radians(ra), math.radians(dec)
    radial = (math.cos(d) * math.cos(a), math.cos(d) * math.sin(a), math.sin(d))
    east = (-math.sin(a), math.cos(a), 0)
    north = (-math.sin(d) * math.cos(a), -math.sin(d) * math.sin(a), math.cos(d))
    return tuple(distance * MAS_TO_RAD * (pmra * east[i] + pmdec * north[i])
                 + rv * KM_S_TO_PC_YR * radial[i] for i in range(3))


def gaia_measurement(row):
    values = {k: number(row.get(k)) for k in (
        "ra", "dec", "parallax", "parallax_error", "pmra", "pmdec",
        "pmra_error", "pmdec_error", "radial_velocity", "radial_velocity_error",
    )}
    required = ("ra", "dec", "parallax", "pmra", "pmdec")
    if any(values[k] is None for k in required) or values["parallax"] <= 0:
        return None
    distance = 1000 / values["parallax"]
    rv = values["radial_velocity"]
    v = velocity(values["ra"], values["dec"], distance, values["pmra"], values["pmdec"], rv or 0)
    errors = [values[k] for k in ("pmra_error", "pmdec_error", "parallax_error", "radial_velocity_error")]
    sigma = None
    if rv is not None and all(e is not None and e >= 0 for e in errors):
        # A scalar error budget, not an ellipsoid or a full covariance propagation.
        tangent = distance * MAS_TO_RAD
        sigma = math.sqrt(
            tangent**2 * (errors[0]**2 + errors[1]**2)
            + (tangent * math.hypot(values["pmra"], values["pmdec"])
               * errors[2] / values["parallax"])**2
            + (errors[3] * KM_S_TO_PC_YR)**2
        )
    return {"v": v, "full": rv is not None, "rv": rv,
            "rv_error": values["radial_velocity_error"], "sigma": sigma,
            "source": "Gaia DR3", "source_id": str(row["source_id"]), "epoch": 2016.0,
            "values": values}


def motion_payload(dataset, motion_file, radius, source):
    """Return rows in exactly the same order as DatasetStore.catalogue."""
    with closing(sqlite3.connect(f"{motion_file.as_uri()}?mode=ro", uri=True)) as db:
        meta = {k: json.loads(v) for k, v in db.execute("SELECT key,value FROM metadata")}
        if meta["dataset_id"] != dataset.meta["dataset_id"]:
            raise ValueError("Stellar motion data belongs to a different dataset; run tools/import_stellar_motion.py.")
        conditions = ["distance <= ?"]
        if source == "hyg":
            conditions.append("origin = 0")
        elif source == "gaia":
            conditions.append("has_gaia = 1")
        elif source != "both":
            raise ValueError("Unknown stellar motion catalogue source.")
        rows = db.execute(
            """SELECT name,measurement FROM motion WHERE """ + " AND ".join(conditions)
            + " ORDER BY origin,ordinal,distance,source_id", (radius,),
        )
        measurements, sources = [], ["Gaia DR3", "HYG v4.0", "Heliocentric reference"]
        crc, complete, partial = 0, 0, 0
        for name, text in rows:
            crc = zlib.crc32((("\n" if measurements else "") + name).encode("utf-8"), crc)
            m = json.loads(text) if text else None
            measurements.append([*m["v"], int(m["full"]), m["sigma"], m["rv"], m["rv_error"],
                                 sources.index(m["source"]), m["source_id"]] if m else None)
            complete += bool(m and m["full"])
            partial += bool(m and not m["full"])
    return {"dataset_id": meta["dataset_id"], "names_crc": crc,
            "count": len(measurements), "reference_epoch": 2000, "measurements": measurements,
            "sources": sources,
            "provenance": meta["provenance"],
            "complete": complete, "partial": partial}
