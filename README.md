# StarExplorer

A Flask web app with a three.js front end that renders an interactive 3D map of stars.
It ships with ~107,000 stars from the HYG catalogue (everything within ~1 kpc that has a distance and
spectral class).

## Run

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python app.py            # http://127.0.0.1:5001
$env:PORT=5057; .\.venv\Scripts\python app.py   # use another port if 5001 is busy
```

The ~12 MB star file is served gzip-compressed (~2.8 MB) and cached in memory until the file changes.

## Controls

| Action | Effect |
| --- | --- |
| Left-drag | Rotate around the current centre |
| Right-drag / Shift+drag / arrow keys | Pan |
| Scroll wheel | Zoom |
| Click a star (or list entry) | Show star details |
| Double-click a star (or list entry) | Make it the centre of rotation |
| Reset view | Centre on Sol, 12 pc away |
| Show all | Zoom out to fit every star |
| Esc | Close details |

Star size and brightness follow each star's apparent magnitude as seen from the camera, so the
neighbourhood around the camera looks right at any zoom level. Labels are decluttered automatically:
the selected/centre star first, then stars near the rotation centre, then the brightest (named stars
ahead of catalogue ids). Zoom in to reveal more. The grid rescales with zoom (spacing shown bottom-centre).

The sidebar lists the 25 stars nearest the rotation centre; type in the search box to find stars by name.

### Advanced filters

Open **View → Filters...** in the top menu to build a set of conditions. The builder is hidden until
opened; **Reset view** and **Show all** are also in the View menu.

- **ALL (AND)** requires every condition to match. For example, within 10 pc of Star X AND within 15 pc
  of Star Y shows the overlap of the two spheres.
- **ANY (OR)** accepts either condition. Use it for separate neighbourhoods, for example within 10 pc
  of Sol OR within 10 pc of Vega, even when the spheres do not overlap. Add nested groups to combine AND and OR.
- **NOT** excludes matches to a condition or a whole group.
- Conditions support distance from a reference star, object type, spectral class, sovereignty,
  planetary category and confirmed planets. Planetary conditions use the active scenario even when
  the map is not coloured by planets; spectral, sovereignty and planet conditions match stars only
  before NOT is applied.

Reference-star search uses the whole star catalogue, including hidden stars. Choose a result from
the reference-star selector; typing a search alone does not change the centre. Each distance rule
shows its chosen centre, which stays fixed when selecting or centring other stars.
Distances are in parsecs and include the boundary (zero matches coincident positions). They are
evaluated in the original catalogue coordinates, so switching display frames cannot change the result.
Galaxies remain an unfiltered backdrop unless **Apply advanced filters to galaxies too** is checked.

**Apply** activates the rules; **Cancel** or Escape discards edits. **Clear rules**, then **Apply**,
disables advanced filters. Rules last for the current page session. Sidebar visibility controls and
the existing quick distance filter are additional restrictions, not overridden by the builder.
The top menu shows the combined visible-object count while advanced filters are active.

Filter results are cached per object and uploaded as a GPU visibility attribute. Complex expressions
are evaluated only when applied or when planetary scenario data changes, not during camera movement.
Picking, labels, search, the nearest list and nebula clouds all use the same cached result.

The dependency-free filter-engine tests can be run with Node.js 22+:

```powershell
node --experimental-default-type=module tests\test_filters.mjs
```

The **Frame** selector chooses the display coordinate system. A fixed-size orientation widget below the
sidebar in the lower-left corner shows the red X, green Y and blue Z axes and a direction legend.
It rotates with the camera, but stays fixed when panning or zooming. The axes are not drawn over the star
field. The widget remains visible when **Grid & drop lines** is switched off.
The grid lies on the frame's z = 0 plane:

- **Galactic** (default): right-handed. +X points to the Galactic Centre (l = 0°, b = 0°), +Y to l = 90°
  (the direction of Galactic rotation) and +Z to the North Galactic Pole. The grid is the Galactic plane.
- **Equatorial (J2000)**: the frame the JSON files are stored in. +X points to RA 0h, +Y to RA 6h and +Z to
  the North Celestial Pole.

Positions are converted in the browser with the Hipparcos equatorial-to-galactic rotation matrix. The details
panel shows X/Y/Z in the current frame plus galactic longitude and latitude (l, b).

The bottom-centre panel shows the camera's live position in galactic coordinates (X, Y, Z in parsecs and
l, b, with Sol at the origin) in either frame. It also shows how far the camera is from the selected object,
or from the rotation centre when nothing is selected. That distance is shown in AU, pc (with light years)
or kpc, depending on scale.

Type a distance in parsecs into **Show within … pc** to only show objects (stars, neutron stars and black
holes) within that distance of the selected star. With nothing selected, the sphere is centred on the
rotation centre (Sol by default). Clicking another star moves the sphere to it. Clear the box to show
everything again. Picking, labels, the nearest list and search all respect the filter.

Neutron stars are drawn as violet "pulsar" glyphs (a core, a ring and a cross) at a fixed minimum size,
always labelled, and listed with a diamond swatch. The **Stars**, **Neutron stars** and **Black holes** checkboxes
hide or show each kind of object.

Under the **Stars** checkbox, the spectral-class chips (**O B A F G K M Other**) filter stars by their main
spectral class. Click a chip to show or hide that class, double-click it to show only that class, or click
**All** to reset. Hover over a chip to see how many stars it holds. The class is the first letter of the HYG
spectral type. Luminosity prefixes (`dM4`, `sdF8`, `gK0`) and lower-case types (`m`, `k-m`) are mapped to
their main class. White dwarfs (D), carbon stars (C/R/N/S), Wolf-Rayet stars (W) and unclassified stars count
as **Other**. The chips do not affect neutron stars or black holes, and they combine with the distance and
sovereignty filters.

Black holes are drawn as orange glyphs (a dark centre, a photon ring and a tilted accretion disc), always
labelled, and listed with a ring swatch. Use the **Black holes** checkbox to hide or show them. Most lie well
beyond the HYG stars (up to ~8.6 kpc), so zoom out or double-click one in the list to fly to it. **Show all**
still fits the HYG stars only.

Nebulae are drawn as soft, noise-textured glows sized to their physical radius, plus a dashed-ring marker
(❋) for picking. Emission nebulae glow, supernova remnants are faint broken shells of thin wispy filaments,
planetary nebulae show a shell with a red
rim, and dark clouds dim the stars behind them. Use the **Nebulae** checkbox to hide or show them all. The
type chips (**Emission, Reflection, Planetary, SNR, Dark**) work like the spectral-class chips: click to
toggle, double-click to show only that type. Nebulae are searchable, show up in the nearest list and respect
the distance filter. The details panel shows catalogue IDs, size and the distance source.

**Extragalactic ⬭** toggles 52 well-known galaxies and galaxy clusters, from the Magellanic Clouds out to
3C 273 (~650 Mpc). They are drawn as tilted elliptical glows at their real distances, so zoom far out to
see them. Click one (or search by name or catalogue ID, e.g. `M31`, `Whirlpool`) for details. They are a
distant backdrop: double-clicking one selects it but never makes it the centre of rotation, and the
distance filter does not hide them.

**Colour by** switches between the stars' own colours and **Sovereignty**. In sovereignty mode each member
star takes its sovereignty's colour, is drawn at least 10 px wide and is preferred for labelling. Unclaimed
stars turn grey. A legend lists each sovereignty with its member count: click a name to fit the view to its
members, use its checkbox to hide or show it, and untick **Unclaimed stars** to show members only. The
details panel shows a star's sovereignty in either colour mode.

**Colour by → Planets** colours every star by its planetary system:

| Colour | Category |
| --- | --- |
| Grey | No planets |
| Blue | Planets, none in the habitable zone |
| Amber | A planet in the habitable zone (e.g. a gas giant or a mini-Neptune) |
| Green | Potentially habitable: a rocky planet in the habitable zone of a suitable star |

Each legend entry has a checkbox. **Confirmed planets only** restricts the map to systems marked as
observed in the selected scenario. **Scenario** switches between published planetary populations without
reloading the star field; **Refresh scenarios** picks up newly published revisions. The details panel summarises the system. **View system** opens a panel with stellar data,
the habitable zone (conservative band in green, optimistic margins in amber), the snow line, a log-scale
orbit diagram and a planet table. Click a planet row or dot to expand its description and moons. The
Drag the panel's title to move it around the screen. The panel follows the selection, and Esc closes it.

## Star database

Stars live in [data/stars.json](data/stars.json) (one star per line). Each entry has:

| Field | Type | Notes |
| --- | --- | --- |
| `name` | string | |
| `x`, `y`, `z` | number | Position in parsecs (equatorial J2000, Z towards the north celestial pole, Sol at the origin) |
| `colour` | string | Hex colour, e.g. `#ffd2a1` |
| `spectral_class` | string | e.g. `G2V` |
| `abs_mag` | number | Optional absolute visual magnitude (used for size/brightness; defaults to 5) |

The file is validated when the app serves `/api/stars`. Refresh the browser after editing it.

The first 10 stars were entered by hand; the rest come from the
[HYG Database v4.0](https://github.com/astronexus/HYG-Database) by David Nash, licensed
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). They were imported with:

```powershell
.\.venv\Scripts\python tools\import_hyg.py all   # every usable star
.\.venv\Scripts\python tools\import_hyg.py 100   # or just the next 100 nearest
```

The importer keeps existing entries, skips rows without a valid distance or spectral class, and skips close
binary companions within 0.05 pc of an included star (e.g. Sirius B), since they would sit on the same point.
Colours are derived from each star's B-V colour index. Names fall back to Bayer/Flamsteed, Gliese, HD, HIP or
HR designations.

Caveats: HYG distances come from Hipparcos parallaxes, so they become uncertain beyond a few hundred parsecs
and a few stars with bad parallaxes appear in odd places. The catalogue is also magnitude-limited, so
faint stars (most red dwarfs) are missing beyond ~20 pc.

## Neutron star database

Neutron stars live in [data/neutron_stars.json](data/neutron_stars.json). They use the same fields as the
star database (`abs_mag` omitted, `spectral_class` is `"Neutron star"`), plus:

| Field | Type | Notes |
| --- | --- | --- |
| `type` | string | e.g. `Millisecond Pulsar`, `XDINS (Magnificent Seven)` |
| `constellation` | string | |
| `notes` | string | |
| `distance_pc` | number | Distance from Sol used for the position |
| `ra_deg`, `dec_deg` | number | J2000 sky position used for the position |

Type, constellation and notes appear in the details panel. The file is served at `/api/neutron-stars`.

It is generated from [data/neutron_stars_1000pc.csv](data/neutron_stars_1000pc.csv) (name, type, distance,
constellation, notes) with:

```powershell
.\.venv\Scripts\python tools\import_neutron_stars.py
```

The CSV has no sky coordinates, so [tools/import_neutron_stars.py](tools/import_neutron_stars.py) holds the J2000
RA/Dec of each object (SIMBAD / ATNF Pulsar Catalogue) and checks each one against the object's J2000
designation (e.g. `J1856.5-3754`). For new rows with no entry in that table, it falls back to the position
encoded in a `J` designation in the name (accurate to ~1 arcminute).

Caveats: the CSV distances are used as given. PSR J1748-2021B sits in the globular cluster NGC 6440, usually
placed at ~8 kpc rather than 727 pc. Distance estimates for PSR J0952-0607 range from ~1 to ~6 kpc.

## Black hole database

Black holes live in [data/black_holes.json](data/black_holes.json). They use the same fields as the neutron
star database (`spectral_class` is `"Black hole"`), plus `mass_msun` (mass in solar masses). Mass, type,
constellation and notes appear in the details panel. The file is served at `/api/black-holes`.

It is generated from [data/black_holes.csv](data/black_holes.csv) (name, type, distance, constellation, mass,
RA/Dec J2000, notes) with:

```powershell
.\.venv\Scripts\python tools\import_black_holes.py
```

The list holds 15 well-established objects: the dormant Gaia black holes (BH1, BH2, BH3), dynamically confirmed
X-ray binaries (e.g. Cygnus X-1, V404 Cygni, A0620-00, GRS 1915+105) and Sagittarius A*. Values are rounded
literature values (SIMBAD positions, published distances and masses) and should be treated as approximate.

Caveats: X-ray binary distances are often uncertain. GRO J1655-40 is quoted anywhere from 1.7 to 3.2 kpc, and
GRS 1124-683 and V4641 Sgr have large uncertainties. Disputed or retracted candidates (LB-1, HR 6819, "The
Unicorn") are deliberately left out.

## Nebulae

Nebulae live in [data/nebulae.json](data/nebulae.json) (under a `nebulae` key) and are served at
`/api/nebulae`. The file holds 454 objects from three sources:

| Source | Count | Contents |
| --- | --- | --- |
| [data/nebulae_curated.csv](data/nebulae_curated.csv) | 88 | Famous emission, reflection, planetary, supernova-remnant and dark nebulae (M42, Helix, Veil, Gum, Coalsack…) with literature distances and angular sizes |
| González-Santamaría et al. 2021, [A&A 656, A51](https://doi.org/10.1051/0004-6361/202141916) | 272 | Planetary nebulae with Gaia EDR3 parallaxes (S/N ≥ 3, within 3 kpc), with physical radius and morphology |
| Zucker et al. 2020, [A&A 633, A51](https://doi.org/10.1051/0004-6361/201936145) | 94 | Local molecular clouds with Gaia DR2 distances, drawn as dark clouds with one puff per measured sightline |

Each entry uses the star fields (`name`, `x`, `y`, `z`, `colour`, `spectral_class` holding the type label), plus:

| Field | Type | Notes |
| --- | --- | --- |
| `nebula_type` | string | `emission`, `reflection`, `planetary`, `snr` or `dark` |
| `type` | string | Detailed type, e.g. `H II region`, `Planetary nebula (elliptical)` |
| `radius_pc` | number | Physical radius used for the glow |
| `ra_deg`, `dec_deg`, `distance_pc` | number | J2000 position and distance |
| `ids`, `constellation`, `notes` | string | Optional |
| `distance_ref`, `distance_range_pc` | string, array | Where the distance came from and its range, if known |
| `source` | string | Which source the entry came from |
| `puffs` | array | Molecular clouds only: `[x, y, z, radius]` per sightline (pc, equatorial) |

Regenerate it with (downloads the two VizieR tables, cached in `%TEMP%`; add `--offline` to use the cache):

```powershell
.\.venv\Scripts\python tools\import_nebulae.py
```

Curated planetary nebulae take the Gaia distance when a catalogue match within 1′ has a good parallax.
Curated radii are `distance × tan(angular size / 2)`.

Caveats: curated coordinates, distances and sizes are rounded literature values, good to roughly 5–20%.
Nebulae are drawn as spheres, so filaments and bipolar shapes are only suggested. A molecular cloud's
size reflects the spread of its sightline distances, so large complexes (Cygnus X, Cepheus) can look
elongated along the line of sight.

## Extragalactic objects

A curated list of 52 galaxies and clusters lives in [data/galaxies.csv](data/galaxies.csv). It is converted
to [data/galaxies.json](data/galaxies.json) (under a `galaxies` key) and served at `/api/galaxies`. It
covers Milky Way satellites (LMC, SMC, Sagittarius, the classical dwarf spheroidals), Local Group members
(M31, M33, M32, M110, NGC 6822, IC 1613…), nearby landmark galaxies (M81/M82, Centaurus A, M83, M101,
M51, Sombrero, M87…), four clusters (Fornax, Norma, Perseus, Coma), and a few famous objects (Stephan's
Quintet, the Cartwheel, Hoag's Object, Cygnus A, 3C 273).

Each entry uses the star fields (`name`, `x`, `y`, `z`, `colour`, `spectral_class` holding the
morphology), plus:

| Field | Type | Notes |
| --- | --- | --- |
| `galaxy_type` | string | `spiral`, `elliptical`, `irregular`, `dwarf`, `interacting`, `peculiar`, `active` or `cluster` (sets the marker colour) |
| `type` | string | Readable type label |
| `abs_mag` | number | Approximate absolute V magnitude; omitted for clusters |
| `size_arcmin` | number | Optional major-axis angular size, shown as a physical size in kpc |
| `ra_deg`, `dec_deg`, `distance_pc` | number | J2000 position and distance |
| `ids`, `constellation`, `notes`, `distance_ref` | string | Catalogue IDs, location and distance source |

To add or change an object, edit the CSV (RA/Dec are sexagesimal J2000, distance in Mpc) and run:

```powershell
.\.venv\Scripts\python tools\import_galaxies.py
```

Caveats: positions and distances are rounded literature values (Cepheid, TRGB and eclipsing-binary
distances for nearby galaxies; Hubble-flow distances with H0 = 70 km/s/Mpc beyond ~20 Mpc), good to roughly
5–15%. Galaxies are drawn as fixed-size markers, not to scale.

## Sovereignty database

Sovereignties live in [data/sovereignties.json](data/sovereignties.json), separate from the star files, so
the 12 MB HYG catalogue can be re-imported without losing them and editing a group never touches it.
The file is small, is fetched in parallel with the stars, and membership is resolved in a single pass
when the page loads.

```json
{
  "sovereignties": [
    {
      "name": "Terran Federation",
      "colour": "#3d8bff",
      "notes": "Optional description",
      "stars": ["Sol", "Alpha Centauri A", "Proxima Centauri"]
    }
  ]
}
```

- `stars` lists members by their exact `name` in `stars.json`, `neutron_stars.json` or `black_holes.json`.
  Star names are unique across the catalogue. Names that are not found are skipped and reported in the
  browser console.
- `colour` must be a `#rrggbb` hex string, and sovereignty names must be unique.
- A star can belong to at most one sovereignty. The server rejects the file (`/api/sovereignties` returns
  500) if this or any other rule is broken.
- The entries shipped in the file are illustrative examples; replace them with your own.

## Planetary systems

Every star has a system record (possibly with no planets). Baseline snapshots use real data wherever it
exists and simulate the other systems from measured occurrence rates. The application reads frozen,
published snapshots rather than regenerating planets during requests. Named scenarios can replace
individual systems with manually edited planets and moons.

See [Scenarios and snapshots](docs/SCENARIOS.md) for snapshot creation, JSON editing, publication,
backups and production deployment.

**Real data**

- `data/solar_system.json`: Sol's 8 planets, their major moons and minor-moon counts.
- `data/known_planets.json`: confirmed exoplanets from the
  [NASA Exoplanet Archive](https://exoplanetarchive.ipac.caltech.edu/) `pscomppars` table, cross-matched to map
  stars by HD/HIP/Gliese/HR ids, then by position (≤ 1,000 pc). The current match covers 913 map stars and
  1,317 planets. For these systems, archive stellar parameters override the HYG-derived ones. Only confirmed
  planets are shown, and their moons are simulated, since no exomoon is confirmed.

**Simulation** (`systems.py`, pure Python, deterministic per star from `seed|name`)

- Stellar parameters (Teff, L, M, R) come from the spectral type, luminosity class and absolute magnitude.
- Planet counts are Poisson draws. Occurrence rates depend on spectral type, metallicity and evolutionary state:
  - small planets: SAG13 (Kopparapu et al. 2018), Dressing & Charbonneau (2015);
  - giant planets: Johnson et al. (2010) mass and metallicity scaling, Fulton et al. (2021)
    semi-major-axis distribution, Cumming et al. (2008) mass function;
  - cold Neptunes: Suzuki et al. (2016);
  - lower rates for giants, white dwarfs and hot or massive stars.
- Periods and radii are drawn from broken power laws. Radii follow the Fulton et al. (2017) radius valley,
  and sizes within a system are similar, as in Weiss et al. (2018). Masses come from Chen & Kipping (2017).
  Eccentricities follow Kipping (2013) and Van Eylen et al. (2019). Systems are spaced for Hill stability.
- Planet types are terrestrial, super-Earth, sub-Neptune, Neptune-like/ice giant and gas giant (Jupiter, warm, hot).
- The habitable zone follows Kopparapu et al. (2014). It is conservative (runaway–maximum greenhouse) or
  optimistic (recent Venus–early Mars).
- **Potentially habitable** means a rocky planet (0.25–10 M⊕, R ≤ 1.6 R⊕) in the habitable zone of a
  main-sequence star with Teff 2,600–7,200 K.
- Tidal locking follows Gladman et al. (1996).
- Moons are simulated for every planet, sized by host mass (Canup & Ward 2006) and Hill radius (Domingos et
  al. 2006). Planets too close to their star have no moons (Barnes & O'Brien 2002). Large moons of
  habitable-zone giants can be flagged habitable.

Main-sequence results (seed 1):

| Host | Any planet | Gas giant | Potentially habitable (optimistic) | Potentially habitable (conservative) |
| --- | --- | --- | --- | --- |
| F | 71% | 19% | 6.8% | 4.4% |
| G | 76% | 16% | 12% | 8.8% |
| K | 82% | 13% | 13% | 9.3% |
| M | 89% | 6.6% | 17% | 12.6% |

**Files and regeneration**

```powershell
python tools\fetch_exoplanets.py [--offline]   # refresh data\known_planets.json from the archive
python tools\generate_systems.py [--seed N]    # rebuild data\systems_summary.json and print statistics
```

See [docs/REGENERATING_SYSTEMS.md](docs/REGENERATING_SYSTEMS.md) for a step-by-step guide.

`data/systems_summary.json` holds one planet count and one flag byte per star:

| Bit | Flag |
| --- | --- |
| 1 | Gas giant |
| 2 | Planet in HZ |
| 4 | Potentially habitable |
| 8 | Conservative HZ |
| 16 | Habitable moon |
| 32 | Confirmed planets |
| 64 | Manually edited scenario system (published scenario summaries only) |

The legacy generator commands above are useful for simulation statistics and preparing input data.
They do not change published scenarios. Create a new baseline snapshot to capture a different seed,
updated observations or a changed generator. Existing baselines remain frozen.

**Endpoints**

- `/api/scenarios`: published scenarios, revisions and catalogue metadata.
- `/api/systems-summary?scenario=<id>&revision=<revision>`: the compact, gzipped scenario summary.
- `/api/system/<star name>?scenario=<id>&revision=<revision>`: one frozen system with planets and moons.

Omitting the query selects the configured default scenario. Browser requests always pin an explicit
scenario and revision. Missing published data is an actionable error, not a request-time regeneration.

**Limitations**

- Some HYG entries merge close binaries, so a companion's planets can appear on the merged star. For
  example, GJ 667 C's planets appear on "Gl 667B".
- Archive hosts too faint for HYG are not on the map.
