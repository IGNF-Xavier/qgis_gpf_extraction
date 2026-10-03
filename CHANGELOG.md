# CHANGELOG

The format is based on [Keep a Changelog](https://keepachangelog.com/), and this project adheres to [Semantic Versioning](https://semver.org/).

<!--

Unreleased

## version_tag - YYYY-DD-mm

### Added

### Changed

### Removed

-->

## 0.1.0 - 2023-07-30
- First release
- Generated with the [QGIS Plugins templater](https://oslandia.gitlab.io/qgis/template-qgis-plugin/)

## 0.2.0 - 2023-09-22
- Bug correction
- Github Documentation
- Code commenting

## 1.0.0 - 2023-12-10
- Sphinx documentation
- Geoplateform's URL
- Search bar to look for specific data
- CRS bug correction

## 1.1.1 - 2025-04-18
- Correct Internet Checker
- Add French Translation
- Transfer Git repo to FramaGit

## 1.2.1 - 2025-05-25
- Add style to saved layer
- Correct group insertion bug
- Correct minimize window when drawing an extent on linux
- Minor translation correction

## 2.0.1 - 2026-01-02
- PyQT 6 compatibility
- Allow the user to extract WFS data

## 2.0.2 - 2026-02-03
- Add log after extraction to have more detail on what's missing

## 3.0.0 - 2026-08-15 [EXPERIMENTAL]
- Replace the anonymous WFS flow with the Géoplateforme's new authenticated extraction service (OGC API - Processes)
- Add OAuth2 authentication (reuse of an existing QGIS authentication configuration, e.g. from the official QGIS Géoplateforme plugin)
- Add administrative extent search (commune, département, région), in addition to the drawn BBox
- Support any product the authenticated user has access to, not just BD TOPO®
- **Not yet validated against the live API at release time — experimental**

## 3.1.0 - 2026-08-15 [EXPERIMENTAL]
- **Plugin renamed from "BD TOPO® Extractor" to "GPF Extraction"**
- Fix input parsing against the real API (the service uses each input's `title` as its identifier, with a couple of exceptions documented by the official guide, e.g. `lifetime` for the retention duration)
- Add a table picker (with automatic `ST_Intersects` spatial filtering) for "ARCHIVE from VECTOR-DB" extraction processes (BD TOPO, GPU_EXTRACTION, ...)
- Align default values with the official documentation: prefer GPKG output format, enable `append` only for multi-layer formats (GPKG/PGDUMP), don't send an unset retention duration
- Validated live against the real API (BD TOPO and GPU_EXTRACTION processes) — still experimental for other processes

## 3.2.0 - 2026-08-16 [EXPERIMENTAL]
- Extraction jobs are tracked in the background (non-blocking) and persist across QGIS restarts: new "Jobs en cours" menu to list, refresh, download, open the folder of, forget, or import from the server any job launched from this installation
- Fix result download: the `extractData` link is an Atom feed listing the actual downloadable files, not a direct file link — was previously downloading the wrong content because of server-side content negotiation combined with a QGIS HTTP cache quirk
- Automatic styling: styles referenced for a product in the Géoplateforme's metadata catalog (CSW) are downloaded and applied to matching layers, with a picker when several styles match the same layer; fixed a mislabelled character encoding in IGN's SLD files that corrupted accented legend labels
- Don't send optional enum inputs unless the user picked a value (was forcing 7z compression by default on every extraction)
- Prevent launching an extraction without any table selected in the table picker
- Disambiguate homonym communes in the administrative extent search with their département/région code
- Fix the extraction window not resizing to fit dynamically-added content (table picker, etc.)
- Remove the drawn-extent rectangle left on the map canvas after closing the dialog
- Replace a sublayer-loading API removed in recent QGIS versions (`QgsVectorLayer.sublayerSeparator`) with the current recommended one
- A couple of PyQt6/QGIS 4 compatibility fixes (`exec_()` removed in Qt6)

## 3.2.1 - 2026-08-18 [EXPERIMENTAL]
- Fix a QGIS freeze with no recovery path: network calls had no timeout at all, so a stalled request (including a synchronous OAuth2 token refresh triggered internally by QGIS) could hang the whole UI thread indefinitely; requests now abort after 30s (10 minutes for downloads) with a clear error message instead
- Fix the "Aide"/"Help" menu entry duplicating on every hot-reload of the plugin
- Fix the BBox draw tool staying active after drawing a rectangle, causing further map clicks to keep redrawing it instead of behaving normally
- `download_all_results` no longer loses the files it already downloaded successfully if one of several downloads fails partway through the batch
- Add a small generation report after a job completes: number of tables requested vs. layers actually delivered, and any per-file download failures
- Clarify the `append` input's label in the parameter form ("Fusionner toutes les tables en un seul fichier") instead of showing the raw API field name — the id sent to the server is unchanged
- Fix a typo in one of IGN's published SLD style file names (`hydrograpgique` instead of `hydrographique`) that prevented automatic styling of the `surface_hydrographique` table
- Fix a false-positive style match: `piste_aerodrome.sld` (a runway style) was wrongly attributed to the `aerodrome` table instead of `piste_d_aerodrome`, because the previous matching heuristic tolerated any suffix match rather than an exact one after stripping a recognized product prefix and French articles (`de`/`du`/`des`/`la`/`le`/`les`)

## 3.3.0 - 2026-08-19 [EXPERIMENTAL]
- Tables with no features at all in the requested extent are now automatically removed from the downloaded GeoPackage, instead of being added to the project as empty layers
- The generation report (requested tables vs. layers delivered, empty layers removed, per-file download failures) is now also logged to the QGIS message panel — not just shown in the transient job-tracking window or end-of-download dialog, which could be missed or lost (e.g. if QGIS becomes unresponsive around that time)
- Fix a false "mismatch" warning in that same report: the count of delivered layers was taken *after* removing empty ones, so it always looked lower than the number of tables requested, even though removing them on purpose is the whole point
- Major performance fix: looking up a product's style went through the Géoplateforme's CSW metadata catalog (~300 records), re-downloaded in full on *every single* extraction because its cache lived on a short-lived, per-call client instance and was therefore never actually reused. Measured in real conditions: ~35 seconds spent just on this lookup, blocking the QGIS UI thread the whole time — the most likely explanation for a QGIS freeze/crash report after downloading a large multi-table result. The cache is now shared for the whole QGIS session: the first lookup still costs ~35s (server-side catalog size, largely out of the plugin's control), every subsequent one in the same session is near-instant
- Document, as a known limitation, that style (SLD) availability isn't exposed by the extraction service itself — it's inferred through this indirect, heuristic CSW catalog lookup — and note the need for a dedicated SLD-discovery service tied to the extraction service

## Interface web 0.4.0 - 2026-10-03 [EXPERIMENTAL]
- The steps (connection, extent, product, parameters, request, jobs) are now collapsible DSFR accordions, each with a status badge. « Continuer » closes a step and opens the next one, the connection step moves on by itself once a token is accepted, and the parameters and request steps are disabled until a product is chosen
- « Jobs suivis dans ce navigateur » is now paginated (5 per page, newest first, same DSFR pagination as the server list) and gets an « Oublier les jobs terminés ou en échec » button; it used to be one long list
- The product list is a plain DSFR radio group instead of a scrolling box (the filter field only appears with more than 12 products). One job covers a single product, and the service refuses a second concurrent job (HTTP 429, no server-side queue), so choosing several products is not offered
- Buttons with an icon inside a DSFR button group now show their label (`fr-btns-group--icon-left`)
- The QGIS plugin itself is unchanged by this entry (no new plugin version)

## Interface web 0.3.0 - 2026-10-03 [EXPERIMENTAL]
- New « Jobs du serveur » list: every job of the account, newest first, with a status filter and DSFR pagination (5 per page). The whole list is loaded once (following the service's `next` links, the service returns oldest first and gives no total) and paged in the browser, so changing page makes no request and does not refresh the page. « Suivre » adds a job to the tracked list, « Résultats » shows its files in place. It replaces the old « Importer les jobs du serveur » button, which dumped every job into the tracked list
- Fix: the extent (selection) layer no longer shows up in the layer switcher, where it could be removed; it is now an unmanaged layer drawn above the map layers
- The QGIS plugin itself is unchanged by this entry (no new plugin version)

## Interface web 0.2.0 - 2026-10-03 [EXPERIMENTAL]
- The web interface now uses the French State design system ([DSFR](https://www.systeme-de-design.gouv.fr/) 1.14.4: header, tabs, forms, alerts, badges, modals, light/dark theme chooser), self-hosted rather than loaded from a CDN
- The map now uses OpenLayers and the Géoplateforme extensions for OpenLayers ([geopf-extensions-openlayers](https://github.com/IGNF/geopf-extensions-openlayers) 1.0.0-beta.15, DSFR theme): Plan IGN, aerial photographs and administrative limits layers, layer switcher, address search, zoom, mouse position and attribution controls. The rectangle is drawn with OpenLayers' `Draw` interaction. Leaflet is gone
- The site is now built (esbuild, `npm run build` in `web/`) and CI publishes `web/dist`; dependencies are pinned by `web/package-lock.json`. The map loads the Géoplateforme `essentiels` configuration from `raw.githubusercontent.com` at runtime; if it is unavailable the map shows a message and the rest of the page keeps working
- The QGIS plugin itself is unchanged by this entry (no new plugin version)

## Interface web 0.1.0 - 2026-10-03 [EXPERIMENTAL]
- New experimental web interface in `web/`, published on GitHub Pages (<https://ignf-xavier.github.io/qgis_gpf_extraction/>): static site, no build step, native ES modules (Leaflet and proj4 from jsDelivr with SRI hashes). The QGIS plugin itself is unchanged by this entry (no new plugin version)
- Same functional scope as the plugin's extraction dialog, minus the QGIS-side post-processing (clip, GeoPackage renaming, styling): administrative search (commune/département/région through the Géoplateforme geocoding API, precise boundary) and presets (mainland France, the 5 overseas départements with their real boundary), hand-drawn or typed rectangle, all shown on the Plan IGN; product and table picker; multiple geometric predicates combined with OR; output projection; format, merge and retention fields; copyable JSON/curl request; job tracking with cancel/forget/import, direct download links
- Carries over the lessons learned on the plugin: the spatial filter uses the precise boundary (`ST_GeomFromText`) in the stored data's *native* SRID, independent of the chosen output projection; `jobName` is not requested; service errors are shown with the request sent and the response received, copyable (never the token); an overseas département gets a warning when the product title says "hors DOM"; results get heuristic warnings (very fast completion, very small file) for the empty-GeoPackage case seen once on a 10-table nationwide extraction
- Authentication: a Bearer token pasted by hand (kept in memory, or in `sessionStorage` on request, never `localStorage`; sent only to `data.geopf.fr`). Verified against the real services: CORS is open on the extraction API, geocoding, WFS, WMTS and downloads, but the public `gpf-swagger` OAuth2 client refuses a redirect to another origin (HTTP 400) and has the device flow disabled — so automatic login needs a dedicated client registered on the Géoplateforme side. The Authorization Code + PKCE code is already in place, inactive until `OIDC.clientId` is set in `web/js/config.js` (the PKCE challenge is checked against the RFC 7636 test vector)
- 27 unit tests (`node --test web/tests/`) run in CI before each deployment (`.github/workflows/web-pages.yml`), which publishes only the site files

## 3.4.7 - 2026-09-30 [EXPERIMENTAL]
- Selecting a commune, département, région or preset in the administrative search now zooms the map to it in the background (the dialog keeps focus) — an immediate visual check, handy for homonyms or to confirm a DOM/mainland preset before launching a long extraction
- Fixed a real bug found while testing this live: zooming straight to the target's bounding box, reprojected into whatever CRS the canvas happens to use, produced nonsensical coordinates for an overseas département when the canvas CRS is only defined for mainland France (e.g. Lambert-93 — its own declared area of use doesn't cover the DOM). Now skipped silently in that case (checked against the CRS's own area of use) rather than sending the canvas somewhere meaningless; verified fixed for that exact combination, and unaffected for a canvas CRS valid everywhere (EPSG:4326) or an in-bounds mainland target

## 3.4.6 - 2026-09-30 [EXPERIMENTAL]
- Clarified the extent summary label ("Emprise (EPSG:4326): xmin, ymin → xmax, ymax"): it always shows the bounding box, even when the actual extent has a precise boundary (administrative search or a project layer). Verified live that the actual spatial filter sent to the server already used the full boundary in that case (`ST_GeomFromText`, not `ST_MakeEnvelope`) — only the label made it look like just the rectangle was used. The label now says so explicitly when a precise boundary is in play, and is left unchanged for a hand-drawn BBox, where the rectangle genuinely is the extent used

## 3.4.5 - 2026-09-30 [EXPERIMENTAL]
- Administrative search now uses the Géoplateforme's own geocoding API (`index=poi&category=administratif&returntruegeometry=true`) instead of the raw ADMIN EXPRESS WFS added in 3.4.4 (three separate queries, one per administrative level, sorted by hand): this API searches commune/département/région in a single call with its own relevance ranking, and can return the actual boundary on request instead of just a representative point — a better fit for this kind of interactive search, raised right after 3.4.4 shipped
- Verified live before switching: département and région search (Rhône, Bretagne, ...), homonym communes correctly disambiguated by département code, apostrophes in names ("Saint-Jean-d'Angély", "L'Île-Rousse"), and a no-match query handled cleanly. Presets (mainland France, each overseas département) are unchanged, still fetched directly from the WFS by INSEE code — no relevance ranking needed there, no ambiguity to resolve

## 3.4.4 - 2026-09-30 [EXPERIMENTAL]
- Replaced `geo.api.gouv.fr` (used for administrative search) with the Géoplateforme's own WFS (ADMIN EXPRESS, `LIMITES_ADMINISTRATIVES_EXPRESS.LATEST`): `geo.api.gouv.fr` had stopped returning a boundary for départements and régions at all (only communes still worked, since 3.4.3's presets worked around it). This WFS fixes département/région search entirely, and also gives the overseas département presets their real boundary instead of a fallback rectangle — mainland France stays a fixed bounding box, since no single "country" entity exists at this level
- Checked live before switching: response time is unaffected by a leading wildcard in the name filter at this table size (administrative boundaries — tens of thousands of rows for communes, far fewer for départements/régions), CQL special characters (apostrophes in names like "Saint-Jean-d'Angély") are escaped correctly, and a dedicated autocomplete/geocoding endpoint on the Géoplateforme was evaluated and ruled out for this specific need — it only ever returns a point, never the polygon this feature requires to build a spatial filter

## 3.4.3 - 2026-09-30 [EXPERIMENTAL]
- Diagnosed a real-world report of an unreadable downloaded GeoPackage (10-table hydrography extraction, mainland France, merged into one file): the file turned out well-formed but entirely empty (not a single layer registered), despite the server reporting every relation as `SUCCESS` in about 3 seconds — far too fast for genuine nationwide processing across 10 tables. Replaying the exact same request live through the actual dialog right after succeeded normally (~40 minutes, 6.9 GB of real data), so this is treated as an intermittent service-side issue, not reproducible on demand, rather than a plugin bug
- Fixed a real, definite bug found in the same investigation: forgetting a job ("Oublier"), or cancelling one from its monitor window, didn't actually stick — the next "Importer les jobs du serveur" silently brought it right back, because only the currently-tracked job list was checked against, not what had been explicitly dismissed before. A separate, persistent list of dismissed job ids is now checked too
- Added a hard-to-miss warning (not just a report line easy to miss) when a job completes with the server reporting success but the downloaded GeoPackage ends up with zero usable layers after removing empty ones — the exact situation above, now surfaced clearly instead of silently leaving the user with a hollow file
- New extent presets: mainland France and each of the five overseas départements (Guadeloupe, Martinique, Guyane, La Réunion, Mayotte), shown as soon as the administrative search field is left empty. Motivated directly by the investigation above: `geo.api.gouv.fr` (used for administrative extents) turns out to no longer return a boundary (`contour`) for départements or régions at all — only communes still work, regardless of the query parameters tried — and manually drawing a country-scale BBox is exactly the kind of imprecise, easy-to-get-wrong input this aims to avoid. These presets are bounding boxes (with a deliberate margin), not precise coastlines. Picking an overseas département now also warns if the selected product's title explicitly excludes DOM (e.g. "France entière (hors DOM)", as declared for BDFORET®) — a naming-convention heuristic, not an actual availability check, since none is exposed by the API

## 3.4.2 - 2026-09-25 [EXPERIMENTAL]
- Fix: closing QGIS always warned that "all jobs are still running", because the check counted every tracked job without a downloaded result (including jobs already finished, failed or cancelled on the server). Jobs live on the server and are found again on next start, so nothing is lost by closing QGIS: the confirmation is now only asked when a result download is actually in progress (it would be interrupted), with "No" as the default answer

## 3.4.1 - 2026-09-25 [EXPERIMENTAL]
- Fix: every extraction was rejected with `HTTP 400` ("Erreur indéterminée dans le JSON") since the service started declaring a new output, `jobName` ("Nom du job d'extraction"): the plugin requested every declared output with an empty value, and the service refuses it for this one. `jobName` is no longer requested (the job is created normally without it; verified live)
- Errors returned by the service are now shown in a dialog with the request sent and the response received, as selectable text with a "Copier" button, so a rejected request can be replayed or reported as is (the authentication token is never shown)
- History of a server-side behaviour seen on 2026-09-01: with `append` (merge into one file) enabled, the service answered `HTTP 500` from 59 tables (BD TOPO® all themes) while 58 went through, whichever table was excluded. It was no longer reproducible on 2026-09-25 (59 merged tables accepted). The plugin blocks nothing upfront; on a 500 with merging enabled, the error dialog adds a hint pointing at this earlier observation

## 3.4.0 - 2026-09-01 [EXPERIMENTAL]
- Choose the output projection (`srs`) from a dropdown, pre-filled with the stored data's native projection (pre-selected) plus a few common ones (EPSG:4326, EPSG:2154, EPSG:3857, EPSG:4171), editable for any other `EPSG:xxxx` code
- New extent mode: a polygon layer from the project (all its features, or only the selected ones — several are merged into a single extent geometry), alongside the existing BBox and administrative-area modes
- Replace the hardcoded `ST_Intersects` spatial filter with a choice of any combination of predicates — Intersects, Contains, Within, Disjoint, Touches, Crosses, Overlaps, Equals — checked via checkboxes and combined with OR (at least one always stays checked)
- Name the downloaded GeoPackage instead of always keeping the server's name (`data.gpkg`); when the server produces one file per table, each gets the table name appended
- New option to clip downloaded features to the exact extent geometry client-side after download (`native:clip`, off by default), instead of getting the full geometry of every feature that merely crosses the extent — the downloaded file on disk keeps the untrimmed geometries, only the layer added to the project is clipped. Checked live against the real API first: server-side clipping via an `ST_Intersection` expression in the `attributes` input is rejected (`HTTP 400`, not a documented column name), confirming this has to be a client-side, post-download step
- Fix a real bug found through live end-to-end testing: the spatial filter's geometry was being reprojected to the *chosen output projection* instead of the stored data's *native* projection — since the filter (`filters`, a raw PostGIS WHERE clause evaluated against the source table) and the output reprojection (`srs`) are two independent, unrelated parameters of the API, sending the filter in a different projection than the source data's own silently returned zero features whenever they differed, with no error from the server
- Fix a related bug in the same testing pass: the output-projection dropdown's selected value wasn't actually reaching the request body when chosen from the list after a prior free-text entry (or vice versa) — an editable `QComboBox`'s cached selection doesn't always follow `setCurrentText`/manual list selection, so the wrong (stale) projection could be sent to the server without any visible sign in the UI. Both fixes were confirmed by rerunning the exact same live job that first exposed them

## 3.3.1 - 2026-08-19 [EXPERIMENTAL]
- Preload the CSW metadata catalog in the background (`QgsTask`, non-blocking) as soon as the extraction dialog opens, instead of only on demand. The extraction job itself typically takes several minutes server-side, so by the time a style lookup is actually needed (after the result downloads), the catalog is normally already warm — hiding the ~30 second one-time cost entirely instead of just making it a one-time-per-session cost (3.3.0). Best-effort: a failed background prefetch (e.g. no network at that moment) has no consequence, the lookup simply falls back to loading on demand as before. Verified live: the task runs without blocking QGIS (confirmed responsive throughout), and lookups are instant once it completes.
- Substantially expand the "known limitations" documentation (both READMEs) on CSW-based style discovery, now presented as a clearly flagged workaround rather than a minor caveat, with concrete figures from real-world testing on BD TOPO®: 34 of its 59 tables have no published style at all, 11 of the 36 SLD files in the IGN package match none of those tables, at least 4 distinct naming inconsistencies had to be fixed one by one (a typo, two missing French articles, and a genuine false positive), and the CSW catalog's server-side full-text search consistently fails, forcing a full-catalog client-side filter. Restates the need for a dedicated SLD-discovery service tied to the extraction service itself.
