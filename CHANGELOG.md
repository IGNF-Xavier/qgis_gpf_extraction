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
