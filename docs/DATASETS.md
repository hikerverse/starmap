# Standalone SQLite datasets

The app loads one complete dataset selected by the backend. The browser has no dataset selector:
set `STAREXPLORER_DATABASE` for the server process, restart the server, and reload the page to switch.
The default is `data/stars.sqlite`.

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

## Editing a clone

Use any SQLite editor or script to change rows in a cloned database. Enable foreign-key checks in your
editing connection with `PRAGMA foreign_keys=ON`, and preserve unique object IDs and relationships.
Changes to star coordinates appear in the map on page reload. For changes
to planets or moons, preserve valid physical values and provenance, then refresh stored summary flags:

```powershell
.\.venv\Scripts\python tools\manage_datasets.py refresh data\alternate.sqlite
```

`refresh` recalculates flags from normalized planetary inputs. It is an offline operation over the
complete dataset; stop the web app while editing or refreshing. A dataset should contain one `stars`
and one `systems` row per mapped star. Adding a new star therefore also requires its system row and,
optionally, planet, moon and host rows. Keep `stars.ordinal` contiguous and update `metadata.star_count`
when adding or removing catalogue entries.

The JSON files under `data/` remain inputs for importing or regenerating catalogue data; changing them
does not mutate an already-built SQLite dataset. Re-import or update the database explicitly, then
activate that file on the backend.
