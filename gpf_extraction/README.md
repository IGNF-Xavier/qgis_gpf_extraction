# GPF Extraction

> ⚠️ **Experimental plugin — not for production use.**
> Fork of the original *BD TOPO® Extractor* plugin by Jules Grillot,
> rewritten around the Géoplateforme's new authenticated extraction
> service and renamed **GPF Extraction**. Behaviour against the real API
> is still being calibrated.

[Documentation en français](README_fr.md)

## Description

### What's the point

This tool lets you extract the BD TOPO® and other Géoplateforme products
your cartes.gouv.fr account has access to, using the Géoplateforme's
[extraction service](https://cartes.gouv.fr/actualites/services-validation-et-extraction)
(an OGC API - Processes service, asynchronous job-based extraction) rather
than the historical anonymous WFS.

### How to use it

1. **Connect** to the Géoplateforme: either reuse an existing QGIS
   authentication configuration (e.g. one already created by the official
   [QGIS Géoplateforme plugin](https://github.com/Geoplateforme/plugin-qgis-geoplateforme)),
   or use the built-in "Se connecter" flow (currently disabled — see
   *Known limitations* below).
2. **Choose an extent**: a BBox drawn on the map, or an administrative
   area (commune, département, région) searched by name.
3. **Choose a product** from the list of processes your account has
   access to (BD TOPO® is listed first when available).
4. **Fill in the parameters**. For "ARCHIVE from VECTOR-DB" extraction
   processes (BD TOPO, GPU_EXTRACTION, ...), a dedicated table picker
   lets you check the tables you want, and automatically builds the
   spatial filter (`ST_Intersects`) for each from your chosen extent. An
   advanced raw-JSON editor is always available as a fallback for
   whatever the generic form doesn't cover.
5. **Launch the extraction**, follow its progress, and let the plugin
   download the result and add it to your project.

## Known limitations (experimental status)

- The exact request body accepted by each process is inferred at runtime
  from what the API returns (`GET /processes/{id}`), since it isn't fully
  typed in the service's OpenAPI description. It has been validated live
  against the "BD TOPO" and "GPU_EXTRACTION" processes; other processes
  may need adjustments via the advanced JSON editor.
- The autonomous "Se connecter" button is disabled: the public OAuth2
  client used by the official Swagger UI (`gpf-swagger`) does not accept
  a local callback redirect. A dedicated OAuth2 client registered with
  the Géoplateforme would be required to re-enable it. Until then, reuse
  an existing authentication configuration (e.g. from the official QGIS
  Géoplateforme plugin).

## Reference

- Extraction service documentation: <https://cartes.gouv.fr/aide/fr/guides-utilisateur/utiliser-les-services-de-la-geoplateforme/extraction/>
- Extraction service Swagger: <https://data.geopf.fr/extraction/swagger-ui/index.html>
