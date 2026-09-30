# Dawei floods and landslides, 26–29 September 2026

Interactive situation dashboard built from the 49 posts **Dawei Watch**
(<https://web.facebook.com/DaweiWatch>) published on 26–29 Sep 2026, with every
place they name geocoded onto **MIMU** (Myanmar Information Management Unit) geography.

**Live dashboard:** <https://geonet-myanmar.github.io/dawei-flood-dashboard-v3/>

Or open `index.html` locally. It is self-contained (data inline; Leaflet from cdnjs) and the
MIMU vectors are the basemap; optional satellite/topographic tiles work when the
page is served normally. The 26–28 Sep edition is at
<https://geonet-myanmar.github.io/dawei-flood-dashboard-v2/>.

## What is on the page

- Headline figures as of 29 Sep: 23 dead (Dawei Watch count), the missing the round-up
  names, red-level villages, houses buried or wrecked, people in shelters, and the second
  rainfall record in two days (346 mm at Dawei on the 28 Sep reading).
- Map with a **26 / 27 / 28 / 29 Sep switch**: each of 101 places shows what had been
  reported by the end of that day (colour = what happened to people, shape = hazard,
  ring = red level, blue arrow = water reported falling). Also: cut or flooded roads and
  bridges, junta troop movements the posts report, the rescue convoy's route, the area
  beyond its furthest point, flooded wards, and MIMU villages, hospitals, schools, roads,
  bridges, rivers, land below 5 m, mine sites and the Dawei SEZ.
- Posts tab: the Dawei Watch feed newest first; opening a post shows only the places it named.
- Charts and tables: places by township and day first named; the death count as reported
  (Launglon and the whole area); where the 23 dead and the named missing were (29 Sep
  round-up); the Tanintharyi River against its alert and danger marks; rescue progress and
  what lay beyond it (MIMU analysis); lifelines board; September and storm rainfall
  (Open-Meteo model plus the two DMH records); the explainer's storm sequence; toll ledger;
  seven-township comparison; facilities within 1 km; red-level villages; timeline; quotes
  (Myanmar + English).

## Rebuild

```
pip install -r requirements.txt
python scripts/01_download_mimu.py    # MIMU GeoServer WFS -> data/raw/ (gitignored)
python scripts/02_fetch_rainfall.py   # Open-Meteo -> data/source/rainfall_openmeteo.json
python scripts/03_build_reports.py    # posts -> data/processed/flood.json (geocoded, by day)
python scripts/04_process_gis.py      # clip/simplify + analysis -> data/processed/
python scripts/05_build_html.py       # src/template.html + data -> index.html, dist/
```

Script 01 skips layers already in `data/raw/`; delete a file to fetch it again. Script 02
caches its result (last fetched 29 Sep, 12:29 UTC); model hours are replaced by analysis
values over time, so re-running it later changes the rainfall numbers. Skip it to keep the
published figures. Never hand-edit `index.html`; edit `src/template.html` and re-run script 05.

## Sources and limits

- Posts: `data/source/dawei_watch_2026-09-26_29.docx`, flattened to
  `dawei_watch_2026-09-26_29.txt` (one paragraph per line, newest post first). Every place,
  figure, quote, event and lifeline cell in `flood.json` cites a line of that file; script 03
  checks the post boundaries, every cited line and every quote against it. Lines 384–750
  are the 26–28 Sep edition's file unchanged; lines 1–383 are the 25 posts added since.
- Figures are as reported while many villages were still cut off; unverified, and they
  disagree between posts (Kyauk Ni Maw most of all). The dashboard shows the latest and notes
  the conflicts.
- The 17 ft mark on the Tanintharyi River is its alert level and 24 ft its danger level
  (29 Sep post); the 26–28 Sep edition called 17 ft the danger mark.
- Geocoding grades (in `flood.json`): 82 exact, 6 variant, 3 probable, 4 approximate,
  6 not found in MIMU.
- MIMU: boundaries v9.4, village points, wards v9.4, health facilities 2020 (hospitals
  only), formal schools 2019, roads 1:250k, bridges, mining areas, land below 5 m,
  industrial zones 2024. Area of interest: Dawei District, Palaw, Tanintharyi and Bokpyin.
- Ka Det Nge (ကဒက်ငယ်) in the posts is Ka Det Nge Htein (ကဒက်ငယ်ထိန်), as local residents confirmed; its
  reports are merged into that village at its MIMU point.
- Rainfall curves are Open-Meteo model output, not gauges.

## Deployment

GitHub Pages serves `index.html` from the root of the `main` branch of
`geonet-myanmar/dawei-flood-dashboard-v3` (`.nojekyll` skips the Jekyll build). To publish a
change: re-run `scripts/05_build_html.py` (its `SITE` constant sets the canonical URL), commit
`index.html` together with the source change, and push. `data/processed/` and
`data/source/` are committed so step 5 runs without re-downloading MIMU data.
