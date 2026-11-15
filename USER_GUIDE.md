# StarExplorer: user guide, data and methods

A Flask web app with a three.js front end that renders an interactive 3D map of stars,
nebulae, compact objects and galaxies, from a selected star's sky to extragalactic scales.
It ships with ~107,000 stars from the HYG catalogue (everything within ~1 kpc that has a distance and
spectral class).

Three.js 0.160.0 and its OrbitControls add-on are served locally from `static/vendor/three`;
the included license is in that directory. The browser does not need to fetch Three.js from a CDN.

For installation, deployment and data-maintenance commands, see the [README](README.md).

## Contents

- [Getting started](#getting-started)
- [Data sources and how they are used](#data-sources-and-how-they-are-used)
- [Controls and navigation](#controls)
- [Star data and Gaia techniques](#star-database)
- [Neutron stars](#neutron-star-database), [black holes](#black-hole-database) and [nebulae](#nebulae)
- [Galaxies and cross-matching](#extragalactic-objects)
- [Why the galaxy distribution looks like an hourglass](#why-the-galaxy-distribution-looks-like-an-hourglass)
- [Sovereignties](#sovereignty-database)
- [Planetary observations and simulation](#planetary-systems)

## Getting started

Open the app in your browser at the address supplied by its operator
(normally `http://127.0.0.1:5001` when running locally).

Use the top menu's **Catalogue** item to choose HYG, GAIA, or Both and the load radius from Sol
(1, 2, or 5 kpc), then select **Reload catalogue**. These selections are saved.
On first load, phone-sized screens default to **HYG within 1 kpc** to reduce loading time
and memory use; other screens default to **Both within 1 kpc**. Valid saved choices take
precedence, and phone users can still choose GAIA, Both or a larger radius. Phone-sized means
a viewport up to 600 px wide, or up to 600 px high with a coarse pointer (landscape touchscreens).
Resizing does not reload the catalogue. Galaxy and other object overlays still load separately.

The map and planetary systems come from the active standalone SQLite dataset selected by
the operator. The Catalogue menu selects the star sample within that dataset, not a different
backend database.

The startup spinner shows loading stages and a progress bar. Download progress reports decoded
MiB received, with a percentage only when the uncompressed total is known. Star processing reports
objects completed out of the catalogue total; other stages remain indeterminate. The overlay closes
after the prepared view has rendered, including any planetary data required by saved settings.

## Data sources and how they are used

Observed catalogue objects and illustrative rendering are kept distinct. The active SQLite
database supplies stars and planetary systems; the separate JSON overlays supply neutron stars,
black holes, nebulae and galaxies. Catalogue/load-radius choices change the star sample, not
the galaxy catalogue. All map positions use parsecs in equatorial J2000 with Sol at the origin;
the browser can rotate them into galactic coordinates without changing the underlying positions.

| Dataset / reference | Where it is used | Processing and limitations |
| --- | --- | --- |
| [HYG v4.0](https://github.com/astronexus/HYG-Database) | [Star catalogue](#star-database), labels, stellar colours and observer views | Imported into the active SQLite dataset; names and original positions are preserved during Gaia enrichment. Magnitude-limited and incomplete, especially for distant faint stars. CC BY-SA 4.0. |
| [Gaia DR3](https://www.cosmos.esa.int/web/gaia/dr3) | [HYG enrichment](#enriching-the-star-database-with-gaia-dr3), [additional stars](#adding-gaia-dr3-stars), [estimated spectral classes](#estimating-gaia-spectral-classes) | Identifier/position cross-matching, quality and brightness cuts, inverse-parallax distances, epoch propagation to J2000 and temperature-based classification. This is a selected sample, not all Gaia stars. |
| SIMBAD / ATNF and published compact-object measurements | [Neutron stars](#neutron-star-database) and [black holes](#black-hole-database) | Curated positions, distances and available masses; uncertainties and disputed cases are documented below. |
| Curated nebulae; González-Santamaría et al. (2021); Zucker et al. (2020) | [Nebula overlays](#nebulae) | Literature/Gaia distances, angular sizes, planetary morphology and molecular-cloud sightlines; glows are procedural, not observed images or reconstructed gas volumes. |
| [Reid et al. (2019)](https://arxiv.org/html/1910.03357v1#A2.T2) | Milky Way spiral-arm backdrop | Parallax-based arm fits anchor illustrative broadened/extended arms. Decorative stars, gas, dust and the home-galaxy symbol do not add observed catalogue objects. |
| Curated NED/SIMBAD/literature galaxies | [Extragalactic objects](#extragalactic-objects): 52 galaxies, groups and clusters | Per-object published distances take precedence when matching additional survey detections. |
| [OpenNGC](https://github.com/mattiaverga/OpenNGC) | [Extragalactic expansion](#extragalactic-objects): 9,087 additions | NGC/IC objects with known redshifts in the selected range, deduplicated against curated entries; approximate heliocentric Hubble-flow distances. Adapted records retain CC BY-SA 4.0. |
| [HIZOA-S / VizieR J/AJ/151/52](https://doi.org/10.26093/cds/vizier.51510052) | [Galaxies behind the Milky Way](#galaxies-behind-the-milky-way): 883 radio detections | Published HI measurements and counterpart associations; 4 existing objects matched and 879 new markers. Gas-selected southern coverage reduces, but does not remove, the Zone of Avoidance. |
| Stored stellar parameters and the existing stellar model | Star mass/luminosity details and planetary-system calculations | Reuse stored values, derive missing supported values from spectral class/absolute magnitude, label estimates and show their source. These are not new measured stellar masses. |
| [NASA Exoplanet Archive](https://exoplanetarchive.ipac.caltech.edu/) and Solar System data | [Planetary systems](#planetary-systems) | Confirmed planets cross-matched to map stars, with observed host parameters where available; statistical planets and exoplanet moons remain explicitly simulated. |

The source-specific sections below describe bundled files, selection cuts,
cross-matching, distance conventions and attribution. 2MASS/2MASX identifiers can appear as
published galaxy counterparts, but **a standalone 2MASS/2MRS galaxy catalogue is not imported**.
No artificial galaxies are added to fill survey gaps.

## Controls

**Help → About StarExplorer & methods** opens a draggable, resizable in-app window like the user
guide. Close it with **Close** or Escape without disturbing the map. It describes the tool,
astronomical data sources, statistical planet generation,
SQLite datasets, provenance and scientific limitations. The existing **User guide**
remains the step-by-step reference for controls. A standalone `/about` page is also available.

### Subspace disturbance

Open **View → Subspace disturbance...** for a separate, draggable settings window, then enable
**Show subspace disturbance** for an illustrative, static volumetric field
within 1,200 pc of Sol. Domain-warped filaments run through a weak background, with cores typically
a few parsecs across. This is fictional spatial data, independent of the astronomical catalogue and
planetary data; it does not change object visibility, picking or filters.
The window is non-blocking so you can navigate the map while adjusting it. **Close** or Escape
closes the window without disabling the layer or discarding settings.

**Glow** adjusts the presentation only. The **Seed** (an unsigned 32-bit integer) determines the field;
**Regenerate** picks a new seed. The seed, generation version (currently 1), glow and visibility are
saved with browser settings. Share the seed and generation version to reproduce the same field.
Galactic/Equatorial frame changes preserve its alignment with the stars.

The map displays accumulated disturbance along each line of sight, not a local percentage.
Separate **Local disturbance** readings show the actual field strength at the camera and selected
object, or indicate positions outside the mapped field. Glow does not affect these readings.

The volume uses a cached, reduced-resolution ray-marched image (lower resolution on phones), with
distance-filtered strands to limit aliasing. Fine strands blend together at survey-wide zoom levels;
zoom in to inspect them. The layer does not render when disabled or when Glow is zero.

### Primitive shapes

Open **View → Primitive shapes...** for a draggable, resizable, non-blocking annotation window.
Add spheres/ellipsoids, boxes, cylinders, cones, rings/toruses or XY planes. Set full X/Y/Z dimensions
in parsecs (diameters for spheres), colour, transparency from 0% opaque to 100% invisible,
wireframe, rotation and an optional label. Planes ignore Z height.

Centres and rotations use **Galactic coordinates**, in parsecs from Sol, even in Equatorial view.
Enter coordinates directly, choose an exact catalogue object name, or select an object on the map
or star list and press **Use selected object**. These buttons copy a fixed centre; later object
selections do not move the annotation. Press **Add shape** or **Save changes** to apply.

Choose a saved shape to edit it or use **Delete shape**. Close or Escape dismisses the window
without removing shapes. Annotations stay aligned across frame changes, are independent of catalogue
filters and do not intercept object picking. The **Labels** toggle also hides annotation labels.
Shapes are saved automatically in this browser; **Clear saved data...** removes them too.

### Navigation

On tablets and phones (up to 1024 px wide), **Controls** opens a collapsible display-controls panel.
Tap **Close** or the map to dismiss it. Object details, search, filters, planetary systems and the user
guide fit the smaller viewport; long panels scroll, and planetary tables scroll horizontally.
With a touchscreen, drag with one finger to rotate, pinch to zoom, and move two fingers to pan.
Tap an object for details, then use **Centre on object** to fly to it without needing a double-click.

| Action | Effect |
| --- | --- |
| Left-drag | Rotate around the current centre |
| Right-drag / Shift+drag / arrow keys | Pan |
| Scroll wheel | Zoom |
| Click a star (or list entry) | Show star details |
| Double-click a star (or list entry) | Centre on it and move the camera to 3 pc away, keeping the viewing direction |
| Double-click a galaxy (or list entry) | Make it the rotation centre and move to a size-appropriate galaxy viewing distance |
| View from (star details) | Put the camera at that star's catalogue position; drag to look and use the magnitude controls to limit visible stars |
| Reset view | Centre on Sol, 12 pc away |
| Show all | Fit stars locally, or galaxies at extragalactic scales |
| Esc | Close details |
| ? | Open the user guide (also **Help → User guide**); drag its header to move it, its corner to resize it |

Star size and brightness follow each star's apparent magnitude as seen from the camera, so the
neighbourhood around the camera looks right at any zoom level. Labels are decluttered automatically:
the selected/centre star first, then stars near the rotation centre, then the brightest (named stars
ahead of catalogue ids). Zoom in to reveal more. The grid rescales with zoom (spacing shown bottom-centre).

The star details panel shows mass (M☉) and bolometric luminosity (L☉), fetched on selection.
Stored stellar parameters are reused; derived values are marked **(est.)** with their source.
Gaia-only stars use the existing spectral-type/absolute-magnitude model, not measured masses.
Missing parameters are shown as unavailable.
The on-demand `/api/star-properties/<star name>` response includes mass, luminosity, source,
estimate status and the active dataset ID; these values do not enlarge the initial compact
star-catalogue download. Estimates use the existing stellar model only when the necessary
absolute-magnitude data is present. Derived values are not equivalent to direct measurements.

Select a star to open its details panel, then use **View from** there to place the camera at that
star and explore the surrounding sky. The details panel also lets you search for a different visible
observer star. While viewing from a star, search for another visible star under **Point camera at**
to aim toward it. Drag to look around, scroll to zoom, and adjust the limiting apparent magnitude or
choose an illustrative dark-sky, binocular or small-telescope preset. The observer star is omitted
from the view. This is only an approximation: the catalogue is incomplete, some magnitudes and
distances are estimated, and equipment presets do not simulate optics, sky brightness or dark
adaptation. Choose **Exit viewpoint** to restore the previous map view.

Open **View → Star list** to show a floating, draggable panel listing the 25 stars nearest the rotation
centre; type in its search box to find stars by name. Click an entry to select it, double-click to fly to
it. Drag the panel by its title; close it with **×**, the menu item again, or Escape (the first Escape
clears a search). The list is only recomputed while the panel is open.

### Saved settings

StarExplorer remembers your session in this browser (`localStorage`, key `starexplorer:prefs:v1`):
the applied advanced filter, frame, colour mode, sidebar toggles and class / type chips,
sovereignty and planet legend toggles, the quick distance filter, the camera and rotation-centre star,
and whether the star list is open and where. Changes are saved automatically (debounced) and restored
on the next visit. Filters and the Planets colour mode wait for the active dataset before they are
reapplied. Stars and sovereignties are stored by name, and anything invalid or no longer present is
ignored rather than blocking start-up. **View → Clear saved data...** forgets everything and reloads
with the defaults. Nothing is sent to the server, and if browser storage is disabled the app simply
starts with defaults each time.

### Advanced filters

Open **View → Filters...** in the top menu to build a set of conditions. The builder is hidden until
opened; **Reset view** and **Show all** are also in the View menu.

- **ALL (AND)** requires every condition to match. For example, within 10 pc of Star X AND within 15 pc
  of Star Y shows the overlap of the two spheres.
- **ANY (OR)** accepts either condition. Use it for separate neighbourhoods, for example within 10 pc
  of Sol OR within 10 pc of Vega, even when the spheres do not overlap. Add nested groups to combine AND and OR.
- **NOT** excludes matches to a condition or a whole group.
- Conditions support distance from a reference star, object type, spectral class, sovereignty,
  planetary category and confirmed planets. Planetary conditions use the active dataset even when
  the map is not coloured by planets; spectral, sovereignty and planet conditions match stars only
  before NOT is applied.

Reference-star search uses the whole star catalogue, including hidden stars. Choose a result from
the reference-star selector; typing a search alone does not change the centre. Each distance rule
shows its chosen centre, which stays fixed when selecting or centring other stars.
Distances are in parsecs and include the boundary (zero matches coincident positions). They are
evaluated in the original catalogue coordinates, so switching display frames cannot change the result.
Galaxies remain an unfiltered backdrop unless **Apply advanced filters to galaxies too** is checked.

The filter builder is a non-blocking floating panel: drag its title to move it while continuing to
navigate and select stars on the map. **Apply** activates the rules and leaves the panel open for
further adjustments. **Close** or Escape closes it and discards only unapplied edits; applied filters
stay active. Opening **View → Filters...** again restores the last applied rules and panel position.
**Clear rules**, then **Apply**,
disables advanced filters. Rules last for the current page session. Sidebar visibility controls and
the existing quick distance filter are additional restrictions, not overridden by the builder.
The top menu shows the combined visible-object count while advanced filters are active.

To keep a filter across refreshes, open **Save / load filter text** in the panel. **Copy filter text**
exports the *applied* rules (and the galaxy option) as a compact JSON string and copies it to the
clipboard; paste it back later and click **Load & apply**. Stars and sovereignties are stored by name,
so the text stays valid if the catalogue is rebuilt, for example:

```json
{"starexplorer":1,"galaxies":false,"match":"any","rules":[
  {"distance":10,"from":"Sol"},{"distance":10,"from":"Deneb"}]}
```

Rules are `{"match":"all"|"any","rules":[...]}` groups or single conditions:
`{"distance":pc,"from":"star name"}`, `{"kind":"Star"}`, `{"spectral":"G"}`,
`{"sovereignty":"name"}` (`null` = unclaimed), `{"planet":"Potentially habitable"}` and
`{"confirmed":true}`. Add `"not":true` to any rule or group to negate it. The optional `index` saved
with distance rules is only a hint; the star name is authoritative, matched case-insensitively.

Filter results are cached per object and uploaded as a GPU visibility attribute. Complex expressions
are evaluated only when applied or when the active dataset changes, not during camera movement.
Picking, labels, search, the nearest list and nebula clouds all use the same cached result.

The **Frame** selector chooses the display coordinate system. A fixed-size orientation widget below the
sidebar in the lower-left corner shows the red X, green Y and blue Z axes and a direction legend.
It rotates with the camera, but stays fixed when panning or zooming. The axes are not drawn over the star
field. The widget remains visible when **Grid & drop lines** is switched off.
The grid lies on the frame's z = 0 plane:

The **XY**, **XZ** and **YZ** buttons beside the orientation axes snap the camera to face that plane
in the selected frame, preserving the current rotation centre and camera distance. XY looks from +Z,
XZ from -Y and YZ from +X. These are axis-aligned camera views; the perspective projection is unchanged.

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

Single-clicking a star also shows **selected star to rotation-centre star** in the bottom-centre
panel, separately from the camera distance. The details panel shows the same separation under
**Distance from centre**. This uses the centre star's position even during a camera move.
After panning away from a star, the separation is measured to the free view centre instead.
Clearing the selection hides this readout.

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
fits the selected star catalogue locally, or galaxies at extragalactic scale.

Nebulae are drawn as soft, noise-textured glows sized to their physical radius, plus a dashed-ring marker
(❋) for picking. Emission nebulae glow, supernova remnants are faint broken shells of thin wispy filaments,
planetary nebulae show uneven nested shells, filament detail and faint outer halos, with blue-green
inner gas and reddish rims. Catalogue morphology selects round, elliptical, bipolar or irregular
shapes; unclassified objects get a stable procedural mix. Dark clouds dim the stars behind them.
Use the **Nebulae** checkbox to hide or show them all. The
type chips (**Emission, Reflection, Planetary, SNR, Dark**) work like the spectral-class chips: click to
toggle, double-click to show only that type. Nebulae are searchable, show up in the nearest list and respect
the distance filter. The details panel shows catalogue IDs, size and the distance source.

**Milky Way** (above Extragalactic, enabled by default) adds a translucent, procedural spiral disk,
central bar/bulge and faint halo. Mottled blue-white arms include dark dust lanes,
stellar flecks and pink star-forming clouds; these details are baked once into a procedural texture
and viewed through a thin 3D disk. Its centre follows the catalogue position of **Sagittarius A***,
about 8,178 pc from Sol; if that overlay is unavailable it uses the approximate Galactic Centre
on the +X axis. The disk lies in the galactic plane, extends to about 15,000 pc in radius, and
stays aligned when changing coordinate frames. It fades in as the camera-to-view-centre distance
increases from 500 to 6,000 pc, so local views are unchanged. Zoom out with the wheel to see the
local catalogue in context. Beyond 40,000 pc from the Galactic Centre, the disk switches to a
selectable Milky Way symbol. Zooming can continue out to the extragalactic catalogue;
the outer zoom limit is derived from the galaxy catalogue bounds rather than the former
fixed 40,000 pc cap. The home symbol requires both **Milky Way** and **Extragalactic** to be enabled.
At extragalactic scale, an on-screen **Return to Milky Way** button flies back to the Galactic
Centre, 35,000 pc away in an angled full-disk view. It enables the Milky Way and Stars checkboxes
and restores local-object rendering; other filters remain in effect.
The field of view widens on narrow screens when needed to fit the whole disk.
The button disappears after returning below the galaxy-scale threshold. This is distinct from **Reset view**, which
returns to Sol's immediate neighbourhood.
At galaxy scale, **Star list** becomes **Galaxy list** and search finds visible galaxies
by name or catalogue ID. **View from**, observer selection and its viewing-condition controls
are hidden: distant galaxies have no internal star catalogue for a meaningful observer sky.
Returning to local scale restores the star search labels and viewpoint controls.
At this scale, individual stars, neutron stars, black holes and nebulae are hidden from rendering,
labels, picking and search. Zooming back in restores them according to their existing display toggles.
**Show all**
fits the galaxies at this scale, or the star catalogue at local scales. Double-click a galaxy
to make it the rotation centre at a distance appropriate to its size.
Arm centre-lines follow the parallax-based, kinked logarithmic fits from
[Reid et al. (2019), Table 2 and Section III](https://arxiv.org/html/1910.03357v1#A2.T2):
Norma, Scutum-Centaurus, Sagittarius-Carina, Local (Orion), Perseus and Outer.
Azimuth is zero from the centre towards Sol, increasing in the direction of Galactic rotation.
The fits' 8.15 kpc solar radius is scaled to the catalogue's centre-to-Sol distance; star positions
are not moved. At Sol's azimuth, Sagittarius lies inward, Perseus outward, and Sol is within
the broad Local Arm region, not forced onto its centre-line.
Arm bands are broadened for a softer, more legible zoomed-out view.
Beyond the measured ranges, the main arms continue as illustrative trailing spirals around the
far side, fading into the inner disk and outer edge. The Local Arm remains a short segment near Sol.
This is an observationally anchored model, not a definitive arm-membership map: the fits have
uncertainties, track young star-forming regions rather than all stellar populations, and do not
include a disk warp. Extended arm paths, cloud knots, dust, stellar flecks, disk thickness, bar and halo
remain illustrative; decorative stellar flecks are not catalogue objects.
This backdrop does not affect picking, filters or colour modes, and its checkbox is saved with
the other browser settings. It renders at reduced resolution and is cached while the camera is still.

**Extragalactic ⬭** toggles the expanded galaxy catalogue.
Galaxies are off by default (saved display settings still apply). Entering extragalactic zoom
automatically turns them on once per entry; you can turn them off again and they stay off until
you leave and re-enter that scale. Returning to star-scale zoom automatically unchecks
**Extragalactic**, removing the external galaxies from the local view.
Zooming out into galaxy scale sets the Milky Way as the rotation centre while keeping the
camera's position. Explicit galaxy-centering animations still finish at the selected galaxy.
Returning to star scale restores the last star used as the rotation centre, without a
close-up camera jump. This also applies to **Return to Milky Way**: the disk-view camera
position is retained, but rotation resumes around your previous star. Explicitly centering
on another star or using **Reset view** still takes precedence.
The catalogue extends from the Magellanic Clouds out to
3C 273 (~650 Mpc). They are drawn as tilted elliptical glows at their real distances, so zoom far out to
see them. Click one (or search by name or catalogue ID, e.g. `M31`, `Whirlpool`,
`HIZOA J0640-02`) for details.
Double-clicking one makes it the centre of rotation at a galaxy-sized viewing distance.
The info box shows morphology, available size/photometry, catalogue IDs and linked references,
distance provenance and notes. For HIZOA detections it also shows published counterparts,
cross-match status, measured heliocentric radial velocity and uncertainty, the survey's distance,
and neutral-hydrogen mass. Matched objects can have different optical and radio distance estimates;
both are displayed, but the existing catalogue distance remains the map position.
The distance filter does not hide galaxies.

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
observed in the active dataset. The backend selects the dataset; restart it and reload the page to
switch populations. The details panel summarises the system. **View system** opens a panel with stellar data,
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

This JSON is an import source. The app serves the star catalogue from the active SQLite dataset.
The running map uses the operator's active database rather than reading this import source directly.

The first 10 stars were entered by hand; the rest come from the
[HYG Database v4.0](https://github.com/astronexus/HYG-Database) by David Nash, licensed
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).

The importer keeps existing entries, skips rows without a valid distance or spectral class, and skips close
binary companions within 0.05 pc of an included star (e.g. Sirius B), since they would sit on the same point.
Colours are derived from each star's B-V colour index. Names fall back to Bayer/Flamsteed, Gliese, HD, HIP or
HR designations.

Caveats: HYG distances come from Hipparcos parallaxes, so they become uncertain beyond a few hundred parsecs
and a few stars with bad parallaxes appear in odd places. The catalogue is also magnitude-limited, so
faint stars (most red dwarfs) are missing beyond ~20 pc.

### Enriching the star database with Gaia DR3

The existing catalogue can be enriched without changing its names, positions, or planetary-system links.
The offline importer recovers HYG identifiers, uses the Gaia Archive's Hipparcos cross-match where
unambiguous, and tries a position match for remaining HYG stars after propagating their coordinates
from J2000 to Gaia's reference epoch. Position matches are accepted only when exactly one Gaia source
is found within 2 arcseconds; ambiguous and unmatched stars are listed in a CSV report. This radius
captures 99.8% of the uniquely cross-matched HYG/Hipparcos sources tested against Gaia DR3.

Enrichment obtains observations from the
[Gaia Archive TAP service](https://gea.esac.esa.int/tap-server/tap).
Gaia values are stored under each star's `gaia_dr3` object in the SQLite `extra` field.
It includes the source ID, Gaia position, parallax and uncertainty, proper motion and uncertainties,
G/BP/RP mean magnitudes, RUWE, astrometric solution type, and match provenance. Gaia DR3 source IDs
are strings so their 64-bit values remain exact in JSON. A successful cross-match does not replace the
catalogue's original coordinates or distances. See the [Gaia DR3 data model](https://gea.esac.esa.int/archive/documentation/GDR3/Gaia_archive/chap_datamodel/)
and [Gaia data credits](https://www.cosmos.esa.int/web/gaia-users/credits) when using the measurements.

### Adding Gaia DR3 stars

The importer adds a separate `gaia_stars` table and does not invent planetary-system rows.
It downloads sources with nominal parallax distances within 5 kpc, parallax signal-to-noise
of at least 5, RUWE below 1.4, a five- or six-parameter astrometric solution, and Gaia G magnitude
10.8 or brighter. These cuts select only a fraction of Gaia. Gaia distances are inverse-parallax
estimates, and display colours are approximate from BP-RP.

The saved **Catalogue** menu selects HYG, GAIA, or Both; **Load stars from Sol out to**
applies a 1, 2, or 5 kpc radius. Reload to apply changes. GAIA includes HYG entries with Gaia
crossmatches (using their original HYG positions and planetary systems) plus the deduplicated Gaia
additions; Both also includes HYG entries without a crossmatch. Gaia additions have no planetary
systems. Other object overlays are controlled separately. Larger selections require more memory.

For map alignment, Gaia positions are propagated from DR3's 2016 reference epoch back to J2000;
the original Gaia coordinates and proper motions remain in the row's `gaia_dr3` data. The importer
excludes source IDs already matched to existing stars and probable positional matches within 5
arcseconds for the remaining unmatched stars. The Gaia Archive may temporarily reject or delay TAP
queries when its anonymous job queue is busy.
Only complete, validated imports are published as datasets.

### Estimating Gaia spectral classes

The temperature-enriched dataset uses Gaia DR3 GSP-Phot effective temperatures and their
16th–84th percentile bounds for the imported sample. For Gaia-only additions, an approximate
O/B/A/F/G/K/M class is assigned using broad main-sequence temperature ranges only when both
confidence bounds fall in the same range; otherwise it remains Other. Details mark estimates
**(est.)**. Temperature alone does not determine luminosity class or identify unusual stars, and
Gaia temperatures can have systematic errors even when the reported bounds are narrow.
The original temperature and bounds remain in the full catalogue and spatial-query API data.
HYG classifications are unchanged.

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
constellation, notes).

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
RA/Dec J2000, notes).

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

Curated planetary nebulae take the Gaia distance when a catalogue match within 1′ has a good parallax.
Curated radii are `distance × tan(angular size / 2)`.

Caveats: curated coordinates, distances and sizes are rounded literature values, good to roughly 5–20%.
Nebulae use camera-facing procedural billboards, not reconstructed 3D gas volumes. Planetary shapes
follow catalogue morphology where available, but their orientation and small-scale detail are
illustrative, not measured images. A molecular cloud's
size reflects the spread of its sightline distances, so large complexes (Cygnus X, Cepheus) can look
elongated along the line of sight.

## Extragalactic objects

A curated list of 52 galaxies and clusters lives in [data/galaxies.csv](data/galaxies.csv), supplemented
by 9,087 OpenNGC additions in [data/galaxies-opengnc.csv](data/galaxies-opengnc.csv) and 883 HIZOA-S
radio detections (4 cross-matched, 879 new markers): 10,018 objects in total. They are converted
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
| `catalogues` | array | Catalogue names and reference URLs, displayed as links in the info box |
| `hi_observations` | array | HIZOA detection IDs, measured heliocentric velocities/errors, published distances, log neutral-hydrogen masses and cross-match provenance |

The OpenNGC expansion uses J2000 positions and heliocentric redshifts from
[OpenNGC by Mattia Verga](https://github.com/mattiaverga/OpenNGC), licensed under
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). The adapted expansion and its
corresponding generated JSON records retain that license. Changes include filtering to galaxies/pairs/groups
with 0.0033 <= z <= 0.05, removing curated NGC/IC/Messier duplicates, assigning marker types,
and estimating distance as cz/H0 (H0 = 70 km/s/Mpc). V-band absolute magnitudes are derived only
where OpenNGC supplies V-band photometry; B-band values are not substituted. These distances ignore
peculiar velocities and cosmological corrections, and are less reliable than the curated distances.
Unknown morphology uses an irregular marker, not a confirmed classification. Groups are single markers.
The source data combines NED, HyperLEDA and SIMBAD; see the upstream project for full credits.

### Galaxies behind the Milky Way

The [HIZOA-S survey, Staveley-Smith et al. (2016), AJ 151, 52](https://doi.org/10.26093/cds/vizier.51510052)
supplies 883 real Parkes 21-cm neutral-hydrogen detections in the southern Zone of Avoidance.
The bundled [measurement table](data/galaxies-hizoa-hi.tsv) and
[counterpart table](data/galaxies-hizoa-counterparts.tsv) are factual VizieR table 2/3 snapshots,
retrieved 2026-11-15. This work uses the VizieR catalogue access tool, CDS, Strasbourg, France
([service DOI](https://doi.org/10.26093/cds/vizier)); cite the original survey when reusing these observations.
The snapshots retain their source metadata; they are not OpenNGC-derived records.

The importer cross-references **definite** published counterpart identifiers (NGC/IC/Messier,
ESO, PGC, UGC, CGMW, WKK/RKK and 2MASX/2MASS). When identifiers do not match, a definite
counterpart can match within 1 arcmin if its radial velocity agrees with the existing distance
to within max(300 km/s, 10% of velocity), using H0=70 only for this compatibility check.
Group/cluster markers are excluded from matching individual detections.
Multiple possible matches remain separate; probable, ambiguous and confused counterparts are
shown with the paper's classification but are not asserted as aliases.
Codes: `d` definite, `p` probable, `a` ambiguous, `c` confused, `-` no candidate.

Matched galaxies retain their existing position, distance, morphology and photometry.
Their info boxes show both catalogue references and the separate radio measurements.
New galaxies use the published radio centroid and distance, primarily Local Group velocity
with H0=75 km/s/Mpc; nearby distance choices require consulting the survey reference.
Neutral-hydrogen mass is displayed separately, **not** as total galaxy or stellar mass.
No V magnitude or morphology is invented; the irregular marker for new radio detections
is illustrative. Flow distances are uncertain, especially nearby, due to peculiar velocities.
This southern, gas-selected survey reduces the gap but cannot fill the entire sky or detect
every gas-poor galaxy behind the Milky Way.

### Why the galaxy distribution looks like an hourglass

When zoomed right out, the optical galaxy sample can resemble an egg timer or two opposing
lobes, with a sparse band aligned with the Milky Way's plane. This is primarily the
**Zone of Avoidance**: Galactic dust absorbs background visible light, while crowded foreground
stars make background galaxies harder to identify and obtain redshifts for.
The missing band extends outward along obscured sightlines from Sol; in 3D its two better-observed
sides can look like an hourglass. It is **not evidence of a galaxy-free plane**, nor a gap cut
out by the procedural Milky Way renderer.

Before the HIZOA additions, only **33 of the 9,087 OpenNGC expansion objects (0.4%)**
lay within 10 degrees of the galactic plane, although that band covers **17.4% of the sky**
(the area fraction is sin(10 degrees)). This statistic refers to the selected OpenNGC expansion,
not the curated objects or the complete current catalogue. NGC/IC's historical optical coverage
and our requirement for a known redshift also make the sample uneven. Real galaxy clustering,
magnitude limits and distance-selection limits contribute additional structure; the displayed
points are not a complete or uniformly sampled map of the Universe.

The added HIZOA-S detections use the 21-cm radio line, which can penetrate dust that blocks
visible light. The 879 new markers are within roughly 6 degrees of the galactic plane, so they
add real objects to the previously sparse region. Their southern survey footprint and sensitivity
to neutral-hydrogen-rich galaxies mean the gap remains uneven: gas-poor galaxies and unobserved
directions are still missing. The different radial coverage of optical and radio samples can
also remain apparent when zoomed far out.

Infrared and further radio/redshift surveys could reduce the gap further, but adding them
would require their own completeness cuts, distance provenance and duplicate matching.
The current map does not invent objects, relocate observed galaxies or interpolate a uniform
background to conceal missing observations.

Caveats for the curated objects: positions and distances are rounded literature values (Cepheid, TRGB and eclipsing-binary
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

HYG stars have system records (possibly with no planets); Gaia-only additions do not acquire
invented planetary systems. The application reads a complete SQLite
dataset rather than regenerating planets during requests. Its normalized tables make star coordinates
and planetary properties directly queryable.

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

**Limitations**

- Some HYG entries merge close binaries, so a companion's planets can appear on the merged star. For
  example, GJ 667 C's planets appear on "Gl 667B".
- Archive hosts too faint for HYG are not on the map.
