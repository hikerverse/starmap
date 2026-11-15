# StarExplorer: installation and operation

StarExplorer is a Flask web app with a Three.js front end for exploring stars, nebulae,
compact objects and galaxies.

**For what the app does, how to use it, data sources, rendering techniques and scientific
limitations, see the [user guide, data and methods](USER_GUIDE.md).**

## Install and run locally

Run commands from the project directory. The ignored SQLite dataset is not included in Git.
Restore `data\stars.sqlite` from a backup, create one from the source data, or convert a matching
legacy full snapshot using [SQLite datasets](docs/DATASETS.md) before starting the app.

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python app.py            # http://127.0.0.1:5001
$env:PORT=5057; .\.venv\Scripts\python app.py   # use another port if 5001 is busy
```

Three.js 0.160.0 and OrbitControls are served locally from `static/vendor/three`;
the included license is in that directory. The browser does not fetch Three.js from a CDN.

## Select the active database

The map and planetary systems are loaded from the active standalone SQLite dataset.
The app prefers, in order:

1. `data/stars-gaia-temperatures.sqlite`
2. `data/stars-gaia-nearby.sqlite`
3. `data/stars-gaia-expanded.sqlite`
4. `data/stars-gaia-enriched.sqlite`
5. `data/stars.sqlite`

`STAREXPLORER_DATABASE` overrides this order:

```powershell
$env:STAREXPLORER_DATABASE = "data\stars-gaia-enriched.sqlite"
.\.venv\Scripts\python app.py
```

This backend setting chooses the database for all clients. The browser's **Catalogue** menu
selects HYG, GAIA or Both and a 1, 2 or 5 kpc star sample within it; it does not choose a
different database. Larger selections require more memory.
Missing or invalid databases produce an explicit error, not request-time regeneration.
See [SQLite datasets](docs/DATASETS.md) for conversion, cloning, SQL queries and editing.

## Run with Gunicorn on Linux

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/gunicorn --no-control-socket --bind 127.0.0.1:8000 app:app
```

Gunicorn serves the app at `http://127.0.0.1:8000` without Flask's development server.
It stays in the foreground; use a service manager for automatic startup.
Apache needs a reverse proxy configuration to serve the app through port 80.
Gunicorn is not installed on Windows. The optional control socket is disabled to avoid
runtime-directory permission errors.

### Run Gunicorn as a systemd service

`deploy/starmap.service` runs Gunicorn as `simon` from `/home/simon/starmap`, starts at boot,
and restarts on failure. Update its user, group and paths if installing elsewhere.
Stop any manually started Gunicorn instance first (Ctrl+C in its terminal) so port 8000 is free.

Run these commands from the project directory in a regular terminal where `sudo` can prompt
for your password:

```bash
sudo install -m 644 deploy/starmap.service /etc/systemd/system/starmap.service
sudo systemctl daemon-reload
sudo systemctl enable --now starmap.service
sudo systemctl status starmap.service --no-pager
curl -I http://127.0.0.1:8000/
```

View logs with `sudo journalctl -u starmap.service -f`. After updating the app, run
`sudo systemctl restart starmap.service`. Apache can continue proxying to `127.0.0.1:8000`
without configuration changes.

### Apache HTTPS reverse proxy

`deploy/hikerverse.org.conf` serves `https://hikerverse.org` through Gunicorn at
`127.0.0.1:8000` and redirects HTTP to HTTPS. It expects a valid certificate and key at
`/etc/letsencrypt/live/hikerverse.org/fullchain.pem` and
`/etc/letsencrypt/live/hikerverse.org/privkey.pem`. Obtain the certificate before enabling
this site, or edit those paths to use your existing certificate.

On Ubuntu, with Gunicorn running:

```bash
sudo a2enmod ssl proxy proxy_http headers
sudo install -m 644 deploy/hikerverse.org.conf /etc/apache2/sites-available/hikerverse.org.conf
sudo a2ensite hikerverse.org.conf
sudo apache2ctl configtest && sudo systemctl reload apache2
curl -I https://hikerverse.org/
```

Point the domain's DNS records at this server and allow inbound ports 80 and 443.
The configuration covers `hikerverse.org`, not `www.hikerverse.org`.

## Data preparation and maintenance

The following commands are for operators, not required for ordinary browsing.
Selection criteria, provenance, attribution and scientific caveats are in the
[user guide's data sections](USER_GUIDE.md#data-sources-and-how-they-are-used).
Do not overwrite or experiment on the active database; clone it first.
Editing an import-source JSON file alone does not update the SQLite-backed running map.

### HYG star import

```powershell
.\.venv\Scripts\python tools\import_hyg.py all   # every usable star
.\.venv\Scripts\python tools\import_hyg.py 100   # or the next 100 nearest
```

This updates `data/stars.json`, an import source. Convert or update a database and activate
it using [SQLite datasets](docs/DATASETS.md).
See [HYG processing and limitations](USER_GUIDE.md#star-database).

### Gaia enrichment and additional stars

Enrich HYG entries in a separate database:

```powershell
.\.venv\Scripts\python tools\enrich_gaia.py `
  data\stars.sqlite data\stars-gaia-enriched.sqlite
```

This requires the [Gaia Archive TAP service](https://gea.esac.esa.int/tap-server/tap),
creates `data\stars-gaia-enriched.gaia-report.csv` and refuses to overwrite either output.
Gaia measurements and match provenance are retained without replacing HYG positions.

```powershell
.\.venv\Scripts\python tools\import_gaia_stars.py
.\.venv\Scripts\python tools\import_gaia_stars.py --nearby
.\.venv\Scripts\python tools\estimate_gaia_spectral.py
```

The first command copies the enriched database to `data\stars-gaia-expanded.sqlite` and imports
the 1-5 kpc sample. The second copies that database to `data\stars-gaia-nearby.sqlite` and adds
the sample within 1 kpc. The third creates `data\stars-gaia-temperatures.sqlite` with GSP-Phot
temperature estimates and inferred spectral classes. Existing databases are not overwritten.

The star importer refuses more than 1,000,000 candidates and existing additions in total;
use `--max-g-mag` for a brighter limit if needed. It retries HTTP 429 responses and does not
publish a database unless the complete result passes validation. The archive can temporarily
reject or delay requests when its anonymous job queue is busy.
See [Gaia matching](USER_GUIDE.md#enriching-the-star-database-with-gaia-dr3),
[sample selection](USER_GUIDE.md#adding-gaia-dr3-stars) and
[spectral estimates](USER_GUIDE.md#estimating-gaia-spectral-classes).

### Compact-object and nebula overlays

```powershell
.\.venv\Scripts\python tools\import_neutron_stars.py
.\.venv\Scripts\python tools\import_black_holes.py
.\.venv\Scripts\python tools\import_nebulae.py
```

Neutron stars are generated from `data/neutron_stars_1000pc.csv`; their J2000 coordinates
are maintained in `tools/import_neutron_stars.py`, with a designation-based fallback.
Black holes are generated from `data/black_holes.csv`.
Nebulae combine `data/nebulae_curated.csv` with two VizieR tables downloaded and cached in
`%TEMP%`; add `--offline` to reuse the cache.
These create the corresponding overlay JSON files, independently of the star database.
See [compact-object sources](USER_GUIDE.md#neutron-star-database) and
[nebula data and techniques](USER_GUIDE.md#nebulae).

### Galaxy catalogue

```powershell
.\.venv\Scripts\python tools\import_galaxies.py
```

This combines `data/galaxies.csv`, `data/galaxies-opengnc.csv`,
`data/galaxies-hizoa-hi.tsv` and `data/galaxies-hizoa-counterparts.tsv` into
`data/galaxies.json`. Normal rebuilds require no internet access.
Edit the curated CSV to add or change an object (sexagesimal J2000 RA/Dec, distance in Mpc).

To refresh OpenNGC, download its `database_files/NGC.csv`, then run:

```powershell
.\.venv\Scripts\python tools\import_galaxies.py --opengnc C:\path\to\NGC.csv
```

To refresh HIZOA-S, replace the bundled files with full VizieR TSV exports
(`-out.all`, `-out.max=unlimited`) of
[table 2](https://vizier.cfa.harvard.edu/viz-bin/asu-tsv?-source=J/AJ/151/52/table2&-out.all&-out.max=unlimited)
and [table 3](https://vizier.cfa.harvard.edu/viz-bin/asu-tsv?-source=J/AJ/151/52/table3&-out.all&-out.max=unlimited),
then rerun the importer. Preserve source metadata and attribution.
See [galaxy sources](USER_GUIDE.md#extragalactic-objects),
[HIZOA cross-matching](USER_GUIDE.md#galaxies-behind-the-milky-way) and
[the hourglass distribution](USER_GUIDE.md#why-the-galaxy-distribution-looks-like-an-hourglass).

### Sovereignty data

Edit `data/sovereignties.json` separately from the star imports. Each group has a unique name,
a `#rrggbb` colour and exact member names from the object catalogues.
A star can belong to at most one group; missing members are reported in the browser console.
See the [format and user-facing behaviour](USER_GUIDE.md#sovereignty-database).

### Planetary systems

```powershell
python tools\fetch_exoplanets.py [--offline]   # refresh data\known_planets.json
python tools\generate_systems.py [--seed N]    # rebuild summary and print statistics
```

The brackets indicate optional arguments. See
[regenerating systems](docs/REGENERATING_SYSTEMS.md) for the full workflow.
These commands prepare inputs/statistics; they do not mutate the active database.
Clone the active dataset before experimenting, then activate the chosen file in the backend.
The application reads complete normalized system records without regenerating during requests.
See [observations, simulation and limitations](USER_GUIDE.md#planetary-systems).

`data/systems_summary.json` holds one planet count and one flag byte per star:

| Bit | Flag |
| --- | --- |
| 1 | Gas giant |
| 2 | Planet in HZ |
| 4 | Potentially habitable |
| 8 | Conservative HZ |
| 16 | Habitable moon |
| 32 | Confirmed planets |
| 64 | Manually edited system |

## API endpoints

- `/api/stars`: selected star catalogue and coordinate frame.
- `/api/systems-summary`: compact planet counts and system flags.
- `/api/system/<star name>`: a system with planets and moons from normalized rows.
- `/api/star-properties/<star name>`: stellar mass/luminosity, source and estimate status.
- `/api/neutron-stars`, `/api/black-holes`, `/api/nebulae`: separate object overlays.
- `/api/galaxies`: combined curated/OpenNGC/HIZOA catalogue, sources and import counts.
- `/api/query/stars/within`: stars within a radius of an arbitrary coordinate.
- `/api/query/stars/nearest`: nearest stars to an arbitrary coordinate.
- `/api/query/stars/<name>/within`: stars within a radius of a named star.
- `/api/query/distance`: exact distance between named stars or stable IDs.

## Focused frontend tests

These dependency-free tests require Node.js 22+:

```powershell
node --experimental-default-type=module tests\test_subspace.mjs
node --experimental-default-type=module tests\test_primitive_shapes.mjs
node --experimental-default-type=module tests\test_filters.mjs
```
