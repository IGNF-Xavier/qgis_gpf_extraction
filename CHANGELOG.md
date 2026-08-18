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
- The extraction service can produce one GeoPackage per table instead of a single multi-layer file, even with the `append` input set to `true`: results are now merged client-side into a single GeoPackage, which the user can name
- `download_all_results` no longer loses the files it already downloaded successfully if one of several downloads fails partway through the batch
- Add a small generation report after a job completes: number of tables requested vs. layers actually delivered, and any per-file download failures
