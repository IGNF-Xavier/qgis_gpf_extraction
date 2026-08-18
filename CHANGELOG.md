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
