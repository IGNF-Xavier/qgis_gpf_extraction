# Audit des styles du catalogue CSW — `audit_csw_styles.py`

## À quoi ça sert

Le plugin GPF Extraction découvre les styles (SLD) d'un produit en interrogeant le
catalogue de métadonnées CSW général de la Géoplateforme — un contournement documenté
comme limitation connue (voir `gpf_extraction/README_fr.md`, section *Limitations
connues*) : coûteux (tout le catalogue doit être téléchargé pour être filtré côté
client, la recherche plein texte côté serveur ne fonctionnant pas), et heuristique
(correspondance par nom de fichier, pas de lien garanti).

Ce script objective cette limitation sur l'**ensemble du catalogue** (pas seulement la
BD TOPO®), en croisant trois sources publiques et non authentifiées :

- le **catalogue CSW** (les fiches de métadonnées et les fichiers de style qu'elles
  référencent, y compris dézippés d'une archive) ;
- le **WFS** de la Géoplateforme (quelles couches sont réellement servies, et à quelle
  fiche de métadonnées chacune est officiellement rattachée) ;
- le **TMS** de la Géoplateforme, limité aux tuiles vectorielles (`.pbf` uniquement —
  les tuiles raster `png`/`jpeg` ne sont pas pertinentes pour un style) et à ses
  propres styles vectoriels (JSON Mapbox).

## Comment le lancer

```bash
pip install openpyxl   # si pas déjà installé
python tools/audit_csw_styles.py                          # catalogue entier (~4-5 min)
python tools/audit_csw_styles.py --limit 10                # test rapide, 10 fiches
python tools/audit_csw_styles.py --record-id IGNF_BD-TOPO  # une seule fiche
python tools/audit_csw_styles.py --output mon_audit.xlsx   # nom de fichier personnalisé
```

Le script est autonome (bibliothèque standard + `openpyxl`), pas besoin de QGIS ni du
plugin. Il ne modifie rien côté serveur (uniquement des requêtes `GET`).

## Comment lire le fichier généré

### Bloc résumé (lignes 4 à 13)

Compteurs calculés par formule (`COUNTIF`), donc à jour si vous filtrez/modifiez le
tableau en dessous :

| Ligne | Signification |
|---|---|
| Fiches CSW scannées | Nombre total de fiches du catalogue au moment du run |
| Fiches retenues | Fiches ayant au moins une couche WFS, un TMS, ou un style — les autres (documentation pure, etc.) sont ignorées |
| Couches WFS totales liées à une fiche | Nombre de lignes `couche_wfs` |
| … dont sans style trouvé | Couches pour lesquelles aucun fichier de style ne correspond |
| Styles orphelins | Fichiers de style qui ne correspondent à **aucune** couche de leur propre fiche |
| Styles déclarés par un TMS .pbf | Styles vectoriels Mapbox trouvés en interrogeant directement les TMS |
| FeatureType WFS total / … dont SANS métadonnée liée | Sur tout le WFS de la plateforme (pas seulement les fiches retenues) : combien n'ont **aucune** fiche CSW associée |
| TMS .pbf total / … dont SANS métadonnée liée | Idem côté TMS vectoriel |

### Tableau (à partir de la ligne 15)

Chaque ligne a un `type_ligne` (colonne A, couleur associée) qui en détermine la
nature — filtrez/triez dessus dans Excel plutôt que de lire toutes les colonnes d'un
coup :

| `type_ligne` | Couleur | Une ligne = | Colonnes pertinentes |
|---|---|---|---|
| `couche_wfs` | vert | une couche WFS rattachée à une fiche (avec ou sans style trouvé) | `couche_qualifiee`, `couche`, + colonnes style si trouvé |
| `style_geoserver` | orange | un fichier de style (SLD/QML/JSON) qui ne correspond à **aucune** couche de sa fiche | `ressource_titre/url`, `fichier`, `format` |
| `tms_style` | jaune | un style vectoriel Mapbox déclaré par un TMS `.pbf`, avec ou sans présence dans la métadonnée | `tms_nom`, `fichier`, `diagnostic` (« présent » / « absent de la métadonnée ») |
| `wfs_orphelin` | gris | un `FeatureType` WFS qui n'a **aucune** fiche de métadonnées liée | `couche_qualifiee`, `couche` |
| `tms_orphelin` | gris | un TMS `.pbf` qui n'a **aucune** fiche de métadonnées liée | `tms_nom`, `ressource_url` |

La colonne `diagnostic` (dernière colonne) porte aussi un **commentaire** (petit
triangle rouge dans le coin de la cellule) qui explicite le cas, notamment pourquoi
une ligne `style_geoserver` est orpheline.

`lien_metadonnee` pointe vers l'appel `GetRecordById` de la fiche (XML brut) — utile
pour vérifier une ligne à la source.

## Comment c'est calculé (résumé technique)

- **Couches/fiche** : pas de déduction par nom. Le WFS déclare lui-même, dans son
  `GetCapabilities`, un `MetadataURL` par `FeatureType` pointant vers la fiche CSW
  correspondante (ou rien, d'où `wfs_orphelin`). Même principe pour le TMS, via un
  élément `Metadata type="ISO19115:2003"` sur le document `TileMap` individuel de
  chaque tuile `.pbf`.
- **Style ↔ couche** : même heuristique que celle du plugin
  (`gpf_extraction/core/style_bundle.py`) — retrait d'un préfixe de produit versionné
  (`bdtopo_v3_...`) et des articles français (`de`/`du`/`des`/`la`/`le`/`les`), puis
  correspondance **exacte** (pas un simple suffixe, pour éviter les faux positifs).
- **Style TMS présent dans la métadonnée** : comparaison de l'URL (ou du nom de
  fichier) du style déclaré par le TMS avec les ressources de style trouvées dans la
  fiche CSW correspondante.

## Limites connues du script lui-même

- Une poignée de fiches ont un `dc:identifier` non conforme (le titre en clair au lieu
  d'un identifiant court) — gérées (URL-encodées) mais signalées sur `stderr` si
  l'appel échoue quand même.
- Le catalogue évolue : relancer le script donne des chiffres légèrement différents
  d'un jour à l'autre.
- Les archives de style téléchargées sont mises en cache localement
  (`%TEMP%/gpf_csw_audit_cache`) pour accélérer les relances — supprimez ce dossier
  pour forcer un re-téléchargement complet.
