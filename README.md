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

The **Frame** selector chooses the display coordinate system. Axis labels at the centre show which way each
axis points, and the grid lies on the frame's z = 0 plane:

- **Galactic** (default): right-handed. +X points to the Galactic Centre (l = 0°, b = 0°), +Y to l = 90°
  (the direction of Galactic rotation) and +Z to the North Galactic Pole. The grid is the Galactic plane.
- **Equatorial (J2000)**: the frame the JSON files are stored in. +X points to RA 0h, +Y to RA 6h and +Z to
  the North Celestial Pole.

Positions are converted in the browser with the Hipparcos equatorial-to-galactic rotation matrix. The details
panel shows X/Y/Z in the current frame plus galactic longitude and latitude (l, b).

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

**Colour by** switches between the stars' own colours and **Sovereignty**. In sovereignty mode each member
star takes its sovereignty's colour, is drawn at least 10 px wide and is preferred for labelling. Unclaimed
stars turn grey. A legend lists each sovereignty with its member count: click a name to fit the view to its
members, use its checkbox to hide or show it, and untick **Unclaimed stars** to show members only. The
details panel shows a star's sovereignty in either colour mode.

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
