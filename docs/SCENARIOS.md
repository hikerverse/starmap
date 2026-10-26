# Planetary snapshots and scenarios

StarExplorer serves frozen planetary populations. Changing a generator seed or an archive input does
not change a published world. A baseline captures every star's full system, including empty systems,
full moon lists and the stellar properties used in calculations.

## Storage and loading

- An immutable baseline SQLite database stores the full-precision population and its metadata.
- Each named scenario pins a baseline and contains editable JSON replacements for selected systems.
- An absent replacement inherits the baseline. An explicit empty planet list removes all planets from
  that system; it does not trigger random generation.
- Publishing validates the replacements, recalculates derived properties and writes a new immutable
  revision. Runtime databases store only replacements, not another copy of the whole population.
- A compact summary contains planet counts and flags in star-catalogue order. The browser loads this
  summary, not the full planetary population. A system's details are fetched only when needed.

The SQLite stores are indexed, read-only at runtime and use Python's standard library. No database
server or additional Python dependency is required.

## First snapshot

Run commands from the project root, using the project's virtual environment:

```powershell
.\.venv\Scripts\python tools\manage_scenarios.py snapshot baseline-001
```

The initial installation already includes **Original population** (`baseline-001`), **Exploration**
(`exploration`) and **Alternate history** (`alternate-history`). Both editable scenarios initially
inherit the original population unchanged. A Solar System override has been exported in Exploration,
ready to edit. Do not rerun the example snapshot command with an existing ID.

This is an offline preparation step over the entire catalogue, not a web request. It can take
considerably longer and more disk space than generating the legacy summary because it saves all moons
and full system details. Do not interrupt publication or edit the generated SQLite databases.

The snapshot records its seed, generator version, source hashes and catalogue fingerprint. Snapshot
values are not rounded to the precision used in the dialog. Stable star, planet and moon identifiers
are separate from display names.

## Create and select scenarios

```powershell
.\.venv\Scripts\python tools\manage_scenarios.py create exploration --baseline baseline-001 --name Exploration
.\.venv\Scripts\python tools\manage_scenarios.py create alternate-history --baseline baseline-001 --name "Alternate history"
```

Use **Scenario** in the sidebar to select a published population. Use **Refresh scenarios** after
publishing changes. Switching updates map colours, planet counts, filters and any open system dialog
without rebuilding the star geometry or moving the camera. Different browser sessions can select
different scenarios; there is no server-global active scenario.

## Edit and publish a system

```powershell
.\.venv\Scripts\python tools\manage_scenarios.py export exploration "Tau Ceti"
```

The command prints the JSON file path. Edit that file, then publish:

```powershell
.\.venv\Scripts\python tools\manage_scenarios.py publish exploration
```

Exports are complete system replacements, not patches to array positions. Keep the exported stable
IDs when renaming or moving existing objects. Give newly added objects new IDs. Keep moon arrays
explicit, including `[]` for no moons, so publication cannot silently invent additional moons.

The editable schema has `schema_version`, `star_id`, `name`, `star`, `hosts` and `planets` at the top level.
The star object contains effective temperature `teff` (K), luminosity `lum` (solar), mass `mass` (solar),
radius `radius` (solar), `category`, `spectral_class`, `abs_mag`, `metallicity`, `source` and `provenance`.
Start from an export rather than constructing the whole system from scratch.

For example, append this object to an exported system's `planets` array to add a fictional planet:

```json
{
  "id": "planet-exploration-new-world",
  "name": "New World",
  "a_au": 1.2,
  "e": 0.02,
  "mass_mearth": 1.1,
  "radius_rearth": 1.05,
  "period_source": "derived",
  "provenance": "manual",
  "source": "manual",
  "minor_moons": 0,
  "moons": [],
  "notes": "A fictional addition for this scenario."
}
```

A moon entry goes inside its planet's `moons` array:

```json
{
  "id": "moon-exploration-new-world-one",
  "name": "New Moon",
  "a_km": 384400,
  "radius_km": 1737.4,
  "mass_mearth": 0.0123,
  "period_source": "derived",
  "provenance": "manual"
}
```

Names can contain spaces and Unicode. IDs use letters, digits, hyphens, underscores, dots or colons;
they must be unique across the population. Do not reuse another object's ID when copying a template.
System display names can change without changing the star ID; the shared star map still uses catalogue
names. Planet and moon names are independent of their IDs.

Manual or fictional additions must be marked as manual, not confirmed observations. Existing exported
objects keep observed or simulated provenance while unchanged. If an object's physical inputs change,
publication automatically marks that object manual and reports the change; copied new objects cannot
inherit observational confirmation just by copying their provenance field. Renaming an existing body or
adding notes does not turn its unchanged physical measurements into fictional values. Editing stellar
parameters marks the stellar inputs manual.

Planet type, period estimates, temperature, habitable-zone membership and summary flags are derived at
publication, rather than copied from stale dialog values. `period_source: "derived"` requires omitting
`period_d`; it is calculated from the orbit and masses. Unchanged observed objects may retain an
explicit `period_d` with `period_source: "observed"`. Changing their physical inputs switches the period
to derived. Changing stellar mass also recalculates planetary periods, and changing a planet's mass
recalculates its moons' periods.

To remove all planets, set `planets` to `[]`. To remove one, delete its entire object. To remove a
replacement and inherit the original system again, remove its JSON file from `overrides` and republish.
Exports refuse to overwrite existing files. To inspect the currently published canonical inputs without
overwriting your work, export with `--output` pointing at a new filename outside `overrides`.

Publication errors identify invalid inputs. Correct them and publish again; the last successfully
published revision remains available. Check publication warnings too: a mathematically valid orbit is
not necessarily dynamically stable.

## Updated observations or a different generated world

Refresh the source inputs using [REGENERATING_SYSTEMS.md](REGENERATING_SYSTEMS.md), then make a **new**
baseline ID rather than overwriting the old snapshot. Existing scenarios stay pinned to their original
baseline. A catalogue mismatch requires a compatible snapshot; equal star counts alone are not proof of
compatibility.

```powershell
.\.venv\Scripts\python tools\manage_scenarios.py snapshot baseline-002 --name "Population seed 42" --seed 42
.\.venv\Scripts\python tools\manage_scenarios.py set-default baseline-002
.\.venv\Scripts\python tools\manage_scenarios.py list
```

`set-default` sets the scenario used by new pages and API requests without a scenario parameter. After
changing the star catalogue, set the default to a compatible new snapshot too. The selector lists
compatible scenarios only. Refreshing observation inputs alone does not change the star catalogue and
does not invalidate old worlds.

The legacy statistics summary is not a backup of full systems. Do not use it as the scenario store.

## Production and backups

### Purging obsolete SQLite revisions

With the application stopped and no browsers needing old revisions, run:

```powershell
.\.venv\Scripts\python tools\manage_scenarios.py purge --dry-run
.\.venv\Scripts\python tools\manage_scenarios.py purge
```

The command scans all scenarios, reports the affected paths and total bytes, and removes only obsolete
top-level `.sqlite` revision files. It preserves each published revision, baseline snapshots and baseline
revisions pinned by scenario manifests. Editable JSON, manifests and other files are not deleted.
It shares the publication lock and validates all retained dependencies before deleting anything;
missing or invalid manifests/dependencies abort cleanup. It does not check whether the web app is stopped.
Keep backups if you want to restore older revisions: purging removes that rollback history permanently.

Prepare snapshots and publish scenarios before starting the WSGI application. Runtime requests only
read published data; they never regenerate populations or write scenario files. Missing data produces
an explicit error while the star map remains usable.

Publication writes new revision files before atomically switching the published pointer. Do not delete
old revisions while browsers or workers might still refer to them. The API accepts explicit scenario
and revision identifiers, and caches must include both. A revision mismatch is an error, not permission
to serve a different world.

Back up the complete scenario store: immutable baseline databases, manifests, editable overrides and
published revision files. Use version control for editable JSON and documentation; large SQLite
snapshots are generally better kept in a backed-up data directory or suitable large-file storage.
Do not move only an overlay database without its pinned baseline.

SQLite files are excluded from Git. A fresh checkout does not automatically recreate them: restore
the matching databases from a separate backup before starting the app. Republishing editable scenarios
can recreate their overlay databases once their pinned baselines are restored. Creating a new baseline
snapshot produces a new revision; it is not a drop-in replacement for the revision pinned by existing
scenario manifests. Regeneration also depends on the generator and input data versions. To preserve
the exact existing worlds, back up the databases rather than relying only on regeneration.

Ignore rules do not remove files already tracked or committed. If a push was rejected for an oversized
database, that database must also be removed from the commits being pushed; deleting it in a later
commit alone does not remove the oversized blob from history.

Publishing from one process at a time is the simplest operational policy. For multiple web workers,
deploy the same complete published store to all workers. No restart is needed for the browser's
**Refresh scenarios** action to request the latest published revision.
