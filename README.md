# GPF Extraction - QGIS Plugin

> ⚠️ **Plugin expérimental — ne pas utiliser en production.**
> Ce dépôt est un fork expérimental de l'ancien plugin *BD TOPO® Extractor*
> (renommé **GPF Extraction**), réécrit pour utiliser le nouveau service
> d'extraction authentifié de la Géoplateforme
> (<https://cartes.gouv.fr/actualites/services-validation-et-extraction>,
> API OGC API - Processes) au lieu de l'ancien flux WFS anonyme. Il permet
> d'extraire la BD TOPO® ainsi que tout autre produit auquel le compte
> cartes.gouv.fr connecté a accès. Le comportement face à l'API réelle est
> encore en cours de calibration : testez avant tout usage.

[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Imports: isort](https://img.shields.io/badge/%20imports-isort-%231674b1?style=flat&labelColor=ef8336)](https://pycqa.github.io/isort/)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit&logoColor=white)](https://github.com/pre-commit/pre-commit)

## Generated options

### Plugin

| Cookiecutter option | Picked value |
| :-- | :--: |
| Plugin name | GPF Extraction |
| Plugin name slugified | gpf_extraction |
| Plugin name class (used in code) | GpfExtraction |
| Plugin category | Vector |
| Plugin description short | [Expérimental] Extract IGN's BD TOPO® and other Géoplateforme products via the authenticated extraction service, within a BBox or an administrative extent. |
| Plugin description long | [Expérimental, fork de "BD TOPO® Extractor" par Jules Grillot] Extract the BD TOPO® and other Géoplateforme products via the extraction service (OGC API - Processes), authenticated with your cartes.gouv.fr account. Extent is a BBox drawn on the map or an administrative area searched by name. |
| Plugin tags | vector |
| Plugin icon | default_icon.png |
| Plugin with processing provider | yes |
| Author name | Jules GRILLOT |
| Author email | <jules.grillot@fdn.fr> |
| Minimum QGIS version | 3.10 |
| Maximum QGIS version | 3.99 |
| Git repository URL | <https://framagit.org/JulesGrillot/plugin_bd_topo_extractor> |
| Git default branch | main |
| License | GPLv2+ |
| Python linter | None |
| CI/CD platform | GitLab |
| IDE | VSCode |

### Tooling

This project is configured with the following tools:

- [Black](https://black.readthedocs.io/en/stable/) to format the code without any existential question
- [iSort](https://pycqa.github.io/isort/) to sort the Python imports

Code rules are enforced with [pre-commit](https://pre-commit.com/) hooks.

See also: [contribution guidelines](CONTRIBUTING.md).

## CI/CD

Plugin is linted, tested, packaged and published with GitHub.

If you mean to deploy it to the [official QGIS plugins repository](https://plugins.qgis.org/), remember to set your OSGeo credentials (`OSGEO_USER_NAME` and `OSGEO_USER_PASSWORD`) as environment variables in your CI/CD tool.

### Documentation

The documentation is generated using Sphinx and is automatically generated through the CI and published on Pages.

- homepage: <https://julesgrillot.frama.io/plugin_bd_topo_extractor/>
- repository: <https://framagit.org/JulesGrillot/plugin_bd_topo_extractor>
- tracker: <https://framagit.org/JulesGrillot/plugin_bd_topo_extractor/issues>

----

## Next steps

### Set up development environment

> Typical commands on Linux (Ubuntu).

1. If you don't pick the `git init` option, initialize your local repository:

    ```sh
    git init
    ```

1. Follow the [embedded documentation to set up your development environment](./docs/development/environment.md)
1. Add all files to git index to prepare initial commit:

    ```sh
    git add -A
    ```

1. Run the git hooks to ensure that everything runs OK and to start developing on quality standards:

    ```sh
    pre-commit run
    ```

### Try to build documentation locally

1. Have a look to the [plugin's metadata.txt file](gpf_extraction/metadata.txt): review it, complete it or fix it if needed (URLs, etc.).
1. Follow the [embedded documentation to build plugin documentation locally](./docs/development/environment.md)

----

## License

Distributed under the terms of the [`GNU General Public License v2.0` license](LICENSE).
