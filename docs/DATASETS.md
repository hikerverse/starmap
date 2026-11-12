# Standalone SQLite datasets

The app loads one complete dataset selected by the backend. The browser has no dataset selector:
set `STAREXPLORER_DATABASE` for the server process, restart the server, and reload the page to switch.
The default is `data/stars.sqlite`. If present, `data/stars-gaia-temperatures.sqlite`, `data/stars-gaia-nearby.sqlite`,
`data/stars-gaia-expanded.sqlite` or `data/stars-gaia-enriched.sqlite` takes priority, in that order. `STAREXPLORER_DATABASE` overrides
the default selection.

Each dataset is a self-contained SQLite file with:

- `stars`: catalogue positions (`x`, `y`, `z`, in parsecs), names, colour, spectral class and
  additional catalogue attributes.
- `systems`: stellar parameters, system name, seed, provenance and summary flags.
- `hosts`: one row per archive host.
- `planets` and `moons`: one row per body, linked by stable IDs and with commonly queried physical,
  period and provenance fields in columns.
- `metadata`: dataset identity, display name, coordinate frame, units and schema version.
- `star_positions`: an R-Tree spatial index maintained when rows in `stars` are inserted, updated or
  deleted.
- Optional `gaia_stars`: Gaia DR3-only catalogue sources, with a matching `gaia_star_positions`
  spatial index. These records are separate from `stars` and intentionally have no `systems`,
  planets, or moons.

The map endpoints `/api/stars` and `/api/systems-summary` accept the same `source` (`both`,
`hyg`, or `gaia`) and `max_distance_pc` (1000, 2000, or 5000) parameters. Defaults are `both`
and 1000. Gaia includes crossmatched HYG stars and Gaia-only additions. The radius is measured
from Sol and applies to both tables; summary arrays correspond only to the selected `stars` rows,
in catalogue order. Gaia additions are an imported, deduplicated subset, not the complete Gaia
catalogue. A database without the optional table reports `gaia_available: false` and contributes
no Gaia additions; `gaia_nearby_available` indicates whether the nearby import was performed.
The map uses `/api/stars?compact=1` to omit the detailed Gaia-only measurements from its startup
payload, but retains the estimated-class flag. The default response and the spatial-query endpoints
still include the Gaia GSP-Phot temperatures, uncertainty bounds and estimation provenance.

The app opens the selected database read-only. System details and derived fields are assembled from
the normalized rows when requested. Planet counts are computed from the planet table; summary flags
are stored on each system. After directly editing planetary rows with SQL, run the offline `refresh`
command before using the dataset so its summary flags are recalculated.

## Convert the installed snapshot

The existing scenario-era database can be converted once. Read the source revision from
`data/scenarios/baseline-001/manifest.json` and use its matching `.sqlite` file:

```powershell
$manifest = Get-Content data\scenarios\baseline-001\manifest.json -Raw | ConvertFrom-Json
$snapshot = "data\scenarios\baseline-001\$($manifest.revision).sqlite"
.\.venv\Scripts\python tools\manage_datasets.py import-snapshot `
  $snapshot data\stars.sqlite `
  --stars data\stars.json --name "Original population"
```

The source snapshot and star catalogue must describe the same population and order. The command
refuses to overwrite an existing destination.

## Build from current source data

For a new generated population, build the database directly without creating a legacy snapshot first:

```powershell
.\.venv\Scripts\python tools\manage_datasets.py create `
  data\population-42.sqlite --name "Population seed 42" --seed 42
```

This is an offline operation over the full star catalogue. It uses `stars.json`,
`known_planets.json`, `solar_system.json` and the existing planet generator, then writes normalized
rows into one standalone database. The source inputs are recorded in the database metadata.

## Clone and activate a dataset

```powershell
.\.venv\Scripts\python tools\manage_datasets.py clone `
  data\stars.sqlite data\alternate.sqlite --name "Alternate population"

$env:STAREXPLORER_DATABASE = "data\alternate.sqlite"
.\.venv\Scripts\python app.py
```

Set the environment variable in the web service configuration for production. A relative path is
resolved from the project directory. Restart the backend and reload the browser after switching.
Clones are full copies, so keep enough disk space and make your own backups. SQLite files are excluded
from Git.

## Querying star distances

The R-Tree can first narrow candidates to a cube around a point; exact distances use the coordinates
stored in `stars`. SQLite builds with math functions support `sqrt`:

```sql
WITH candidates AS (
  SELECT s.name,
         sqrt((s.x - :x) * (s.x - :x)
            + (s.y - :y) * (s.y - :y)
            + (s.z - :z) * (s.z - :z)) AS distance_pc
  FROM star_positions r
  JOIN stars s ON s.rowid = r.star_rowid
  WHERE r.x_min <= :x + :radius AND r.x_max >= :x - :radius
    AND r.y_min <= :y + :radius AND r.y_max >= :y - :radius
    AND r.z_min <= :z + :radius AND r.z_max >= :z - :radius
)
SELECT name, distance_pc FROM candidates
WHERE distance_pc <= :radius
ORDER BY distance_pc
LIMIT 100;
```

For a direct star-to-star comparison, join `stars` twice and apply the same three-dimensional
Euclidean distance formula. Coordinates are Cartesian parsecs in the frame recorded in `metadata`.

Planet data is similarly queryable without parsing nested JSON:

```sql
SELECT s.name AS host, p.name, p.mass_mearth, p.a_au, p.provenance
FROM planets p JOIN stars s ON s.id = p.star_id
WHERE p.mass_mearth >= 1
ORDER BY p.mass_mearth DESC;
```

## HTTP query API

The read-only query controller is mounted below `/api/query`. Coordinate arguments use the active
dataset's Cartesian coordinate frame and parsecs. Responses include `dataset_id`, `units`, and `frame`.
Result lists include each star's exact Euclidean `distance_pc` from the requested centre.

Find stars in a spherical radius. Results are ordered by distance then name; `limit` defaults to 100
and is capped at 1,000, while `offset` supports pagination:

```text
GET /api/query/stars/within?x=0&y=0&z=0&radius_pc=10&limit=100&offset=0
```

Find the nearest stars to an arbitrary point. `limit` defaults to 25; `max_radius_pc` is optional and,
when supplied, limits the search to that radius:

```text
GET /api/query/stars/nearest?x=0&y=0&z=0&limit=25&max_radius_pc=10
```

Use a named star or stable star ID as the centre:

```text
GET /api/query/stars/Alpha%20Centauri%20A/within?radius_pc=5
```

Get the separation between two named stars or stable IDs:

```text
GET /api/query/distance?from=Sol&to=Alpha%20Centauri%20A
```

Invalid, non-finite or out-of-range query values return `400`; unknown stars return `404`.
Unbounded `nearest` scans the star catalogue, so prefer a `max_radius_pc` when an approximate search
boundary is known. Radius searches use the R-Tree to narrow the candidate set before calculating exact
distances.

## Editing a clone

Use any SQLite editor or script to change rows in a cloned database. Enable foreign-key checks in your
editing connection with `PRAGMA foreign_keys=ON`, and preserve unique object IDs and relationships.
Changes to star coordinates appear in the map on page reload. For changes
to planets or moons, preserve valid physical values and provenance, then refresh stored summary flags:

```powershell
.\.venv\Scripts\python tools\manage_datasets.py refresh data\alternate.sqlite
```

`refresh` recalculates flags from normalized planetary inputs. It is an offline operation over the
complete dataset; stop the web app while editing or refreshing. A system-backed dataset should contain
one `stars` and one `systems` row per system. Gaia-only catalogue sources are kept in the optional
`gaia_stars` table and do not receive fabricated system rows. Keep `stars.ordinal` contiguous and
update `metadata.star_count` when adding or removing system-backed catalogue entries.

The JSON files under `data/` remain inputs for importing or regenerating catalogue data; changing them
does not mutate an already-built SQLite dataset. Re-import or update the database explicitly, then
activate that file on the backend.
