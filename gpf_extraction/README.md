# GPF Extraction

> ⚠️ **Experimental plugin — not for production use.**
> Fork of the original *BD TOPO® Extractor* plugin by Jules Grillot,
> rewritten around the Géoplateforme's new authenticated extraction
> service and renamed **GPF Extraction**. It has been tested against the
> real service (BD TOPO and GPU_EXTRACTION processes) but has not gone
> through a full release process — expect rough edges, and please report
> anything unexpected.

[Documentation en français](README_fr.md)

## Description

### What's the point

This tool lets you extract the BD TOPO® and other Géoplateforme products
your cartes.gouv.fr account has access to, using the Géoplateforme's
[extraction service](https://cartes.gouv.fr/actualites/services-validation-et-extraction)
(an OGC API - Processes service, asynchronous job-based extraction) rather
than the historical anonymous WFS.

### How to use it

1. **Connect** to the Géoplateforme: reuse an existing QGIS authentication
   configuration — for example one already created by the official
   [QGIS Géoplateforme plugin](https://github.com/Geoplateforme/plugin-qgis-geoplateforme).
   (The built-in autonomous "Se connecter" flow is currently disabled —
   see *Known limitations*.)
2. **Choose an extent**: a BBox drawn on the map, or an administrative
   area (commune, département, région — homonyms are disambiguated with
   the département/région code) searched by name.
3. **Choose a product** from the list of processes your account has
   access to (BD TOPO® is listed first when available).
4. **Fill in the parameters**. For "ARCHIVE from VECTOR-DB" extraction
   processes (BD TOPO, GPU_EXTRACTION, ...), a dedicated table picker
   lets you check the tables you want, and automatically builds the
   spatial filter (`ST_Intersects`) for each from your chosen extent. An
   advanced raw-JSON editor is always available as a fallback for
   whatever the generic form doesn't cover.
5. **Launch the extraction**. This does **not** block QGIS: the job runs
   on the server (typically several minutes) and is tracked in the
   background. You can keep working, close the progress window, or even
   close QGIS entirely — see below.
6. Once downloaded, the result is added to your project, and any style
   published for the product on the Géoplateforme's metadata catalog
   (CSW) is looked up and applied automatically per table — if several
   styles could match a table, you're asked which one to use.

### Tracking jobs — "Jobs en cours"

A job keeps running on the Géoplateforme's server independently of QGIS.
The **"Jobs en cours"** entry in the plugin's menu lists every job you've
launched from this installation — its status (running / ready to
download / downloaded, with its destination folder), an optional comment
you can set when launching to tell jobs apart, and actions to refresh its
status, download its result, open its folder, or forget it.

If you close QGIS while a job is still running, you'll be asked to
confirm — it keeps running on the server regardless, and stays listed
next time you open QGIS. If a job isn't listed (e.g. it was launched
before an update of the plugin, or from a different installation), use
**"Importer les jobs du serveur"** in that same dialog to fetch it back
from the Géoplateforme.

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
- Automatic styling only works for products actually referenced in the
  Géoplateforme's metadata catalog with a style resource attached (BD
  TOPO has one; not every product does — GPU_EXTRACTION currently
  doesn't). When none is found, the result is loaded with QGIS's default
  rendering.
- If the server returns the result as a compressed archive (`compression`
  parameter explicitly set to `7zip`), the plugin does not extract it —
  7-Zip (or equivalent) is needed. Leaving `compression` unset avoids this
  entirely.

## Reference

- Extraction service documentation: <https://cartes.gouv.fr/aide/fr/guides-utilisateur/utiliser-les-services-de-la-geoplateforme/extraction/>
- Extraction service Swagger: <https://data.geopf.fr/extraction/swagger-ui/index.html>
