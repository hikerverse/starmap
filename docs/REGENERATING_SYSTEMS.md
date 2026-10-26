# Regenerating the planetary systems

This guide explains how StarExplorer's planetary systems are produced and how to rebuild them. Examples
include refreshing the confirmed exoplanets, re-importing the star catalogue and rolling a different
simulated galaxy. For how the simulation works, see the
[Planetary systems](../README.md#planetary-systems) section of the README.

## What is stored and what is generated

The generator can produce full systems (planets, orbits, habitable zone, moons) deterministically from a
seed. The live application now reads **frozen baseline snapshots and published scenarios**; it does not
generate or write planetary data during requests. See [SCENARIOS.md](SCENARIOS.md) for the runtime workflow.

The following files are generator inputs and the legacy statistics summary, not the live scenario store:

| File | Role | How it is produced |
| --- | --- | --- |
| [data/stars.json](../data/stars.json) | The stars that get systems | `tools/import_hyg.py` |
| [data/solar_system.json](../data/solar_system.json) | Sol's real planets and moons | Hand-maintained |
| [data/known_planets.json](../data/known_planets.json) | Confirmed exoplanets matched to map stars | `tools/fetch_exoplanets.py` |
| [data/systems_summary.json](../data/systems_summary.json) | Legacy planet count and flag byte per star, plus the seed | `tools/generate_systems.py` |
| [systems.py](../systems.py) | The generator (occurrence rates, habitable zone, moons) | Code |

Each system is seeded from the string `"<seed>|<star name>"`. Python hashes string seeds with SHA-512, so
the results are the same on every machine and every run. Two things follow:

- Adding or removing stars does not change the other stars' systems.
- Renaming a star gives it a new system.

Confirmed systems (Sol and the stars in `known_planets.json`) always use their real planets. The seed only
affects their simulated moons and the systems of all other stars.

## Prerequisites

Run all commands from the project folder with the project's virtual environment:

```powershell
cd "C:\Users\Simon Clucas\OneDrive - ESA\StarExplorer"
.\.venv\Scripts\python --version
```

`fetch_exoplanets.py` needs internet access unless you use `--offline` (see below).

## Common tasks

### 1. Rebuild the summary with the current seed

Use this to check the generator or to recreate a deleted `systems_summary.json`. The output is identical to
the existing file.

```powershell
.\.venv\Scripts\python tools\generate_systems.py
```

It takes about 4 s for 106,714 stars and prints a statistics table, for example:

```text
Generated 106714 systems (seed 1) in 3.7 s
112938 planets in total; 914 stars have confirmed (real) systems

Star type                  stars  planets   giant    hab.   cons.   moon
G dwarf                     9813    75.6%   15.7%   12.1%    8.8%  0.12%
K dwarf                     3264    81.6%   13.2%   13.2%    9.3%  0.00%
...
```

### 2. Generate a different simulated galaxy (new seed)

```powershell
.\.venv\Scripts\python tools\generate_systems.py --seed 42
```

The new seed is saved in `systems_summary.json`, and later legacy statistics runs without `--seed` keep
using it. This does not alter published scenarios. To show a new population, create a new snapshot with
the desired seed, then select its published scenario.

### 3. Refresh the confirmed exoplanets

```powershell
.\.venv\Scripts\python tools\fetch_exoplanets.py
.\.venv\Scripts\python tools\generate_systems.py
```

`fetch_exoplanets.py`:

1. Queries the NASA Exoplanet Archive `pscomppars` table (systems within 1,000 pc).
2. Matches each host to a map star:
   - first by HIP / HD / Gliese catalogue number, via the HYG database;
   - otherwise by sky position (within 4′) and distance (within 20%).
3. Writes `data/known_planets.json` with today's date in `retrieved`, and prints how many hosts matched.

It caches two downloads in `%TEMP%`: `nasa_pscomppars.csv` (the archive table) and `hygdata_v40.csv.gz`
(the HYG catalogue). Add `--offline` to reuse the cached archive table without querying the archive again.

The second command is optional and prints updated statistics. To use the refreshed observations in the
map, create a new baseline snapshot. Existing snapshots keep their original observations.

### 4. After re-importing or editing the star catalogue

```powershell
.\.venv\Scripts\python tools\import_hyg.py all
.\.venv\Scripts\python tools\fetch_exoplanets.py --offline   # re-match hosts to the new star list
.\.venv\Scripts\python tools\generate_systems.py
```

Summaries are stored in the same order as `stars.json`. Re-run `fetch_exoplanets.py` so confirmed planets
attach to the right stars, then create a new baseline for the changed catalogue. Published scenarios
check catalogue compatibility and reject mismatches instead of attaching planets to the wrong stars.

### 5. After editing Sol's data

Edit `data/solar_system.json`, then create a new baseline to capture the change. Alternatively export Sol
into a scenario override, edit that JSON and publish the scenario. Mark fictional additions as manual;
they are not confirmed observations. The seed does not change the original observed Solar System planets.

### 6. After changing the generator code

If you change occurrence rates, flags or anything else in [systems.py](../systems.py) that affects the
summary, increase `GENERATOR_VERSION` at the top of the file:

```python
GENERATOR_VERSION = 3
```

Then run `generate_systems.py` to inspect the new statistics and create a new baseline snapshot.
Bumping the version makes the legacy `systems_summary.json` stale on its next tooling run, but cannot
change a frozen published population.

## Legacy summary rebuilds

When `tools/generate_systems.py` prepares its legacy summary, it records:

| Key | Changes when |
| --- | --- |
| `version` | `GENERATOR_VERSION` in `systems.py` changes |
| `seed` | A new seed is given to `generate_systems.py` |
| `star_count`, `names_crc` | Stars are added, removed, renamed or reordered |
| `known_crc` | `known_planets.json` or `solar_system.json` changes |

These keys identify the legacy generator result. They do not trigger runtime rebuilding. Snapshot and
scenario publication have their own revision and full-catalogue compatibility checks.

## Checking the result

1. Run `generate_systems.py` and check the table. With seed 1, G dwarfs show about 76% with planets
   and 12% potentially habitable (optimistic).
2. Create a snapshot as described in [SCENARIOS.md](SCENARIOS.md), start the app
   (`.\.venv\Scripts\python app.py`) and set **Colour by → Planets**. Grey, blue, amber and
   green stars should appear, and the legend counts should be non-zero.
3. Select a star with confirmed planets, for example "Tau Ceti", "Epsilon Eridani" or
   "Proxima Centauri", and click **View system**. The planets should be marked as confirmed.
4. Optionally check one system directly: `http://127.0.0.1:5001/api/system/Sol` (or the port set in
   `PORT`).

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| The map still shows the old galaxy after `--seed` | Published snapshots are immutable. Create a new baseline with that seed and select its scenario. |
| `fetch_exoplanets.py` times out | The archive is slow or unreachable. Retry later, or use `--offline` if a cached table exists. |
| A known exoplanet host has no planets | It may be too faint for HYG or have no spectral type (listed as unmatched in the fetch output). Or its planets were attached to a merged binary partner, e.g. GJ 667 C's planets appear on "Gl 667B". |
| Scenarios are unavailable | Create/publish a snapshot, check catalogue compatibility, and use **Refresh scenarios**. Check server logs for invalid data or missing files. |
