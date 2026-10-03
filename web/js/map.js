// Carte OpenLayers + extensions Géoplateforme (geopf-extensions-openlayers, thème DSFR).
// Isolée du reste de l'application : si la configuration Géoplateforme ou les tuiles sont
// indisponibles, la carte affiche un message mais la requête d'extraction reste utilisable.

import Map from "ol/Map.js";
import View from "ol/View.js";
import GeoJSON from "ol/format/GeoJSON.js";
import Draw, { createBox } from "ol/interaction/Draw.js";
import VectorLayer from "ol/layer/Vector.js";
import { fromLonLat, transformExtent } from "ol/proj.js";
import VectorSource from "ol/source/Vector.js";
import { Fill, Stroke, Style } from "ol/style.js";
import "ol/ol.css";
import Gp from "geoportal-access-lib";
// Enregistre les définitions de projections (EPSG:2154…) dont MousePosition a besoin.
import "geopf-extensions-openlayers/src/packages/CRS/AutoLoadCRS.js";
import {
  GeoportalAttribution, GeoportalZoom, LayerSwitcher, LayerWMS, LayerWMTS, MousePosition, SearchEngine,
} from "geopf-extensions-openlayers";

import { CONFIG_KEY } from "./config.js";

const MAP_CRS = "EPSG:3857";
const DATA_CRS = "EPSG:4326";
const BLUE = "#000091"; // bleu France (DSFR)
const RED = "#ce0500"; // rouge Marianne (DSFR)

const extentStyle = new Style({ stroke: new Stroke({ color: BLUE, width: 2 }), fill: new Fill({ color: "rgba(0, 0, 145, 0.12)" }) });
const drawStyle = new Style({ stroke: new Stroke({ color: RED, width: 2 }), fill: new Fill({ color: "rgba(206, 5, 0, 0.1)" }) });

// Les couches et contrôles de l'extension lisent la configuration dans `window.Gp.Config`.
function loadGeoportalConfig() {
  window.Gp = Gp;
  return new Promise((resolve, reject) => {
    Gp.Services.getConfig({
      apiKey: CONFIG_KEY,
      onSuccess: (data) => { window.Gp.Config = data; resolve(data); },
      onFailure: (error) => reject(new Error((error && error.message) || "configuration indisponible")),
    });
  });
}

/**
 * @param {{ target: string, onBox: (bbox: number[]) => void, onDrawChange?: (active: boolean) => void }} options
 * @returns {{ ready: Promise<boolean>, showExtent: (geometry: object, bbox: number[]) => void, startDraw: () => boolean, cancelDraw: () => void }}
 */
export function createMap({ target, onBox, onDrawChange = () => {} }) {
  const container = document.getElementById(target);
  let map = null;
  let draw = null;
  let pending = null; // dernière emprise demandée avant que la carte soit prête
  const extentSource = new VectorSource();
  const geojson = new GeoJSON();

  function applyExtent({ geometry, bbox }) {
    extentSource.clear();
    extentSource.addFeature(geojson.readFeature({ type: "Feature", geometry, properties: {} }, { dataProjection: DATA_CRS, featureProjection: MAP_CRS }));
    map.getView().fit(transformExtent(bbox, DATA_CRS, MAP_CRS), { padding: [24, 24, 24, 24], maxZoom: 17, duration: 250 });
  }

  function stopDraw() {
    if (!draw) return;
    map.removeInteraction(draw);
    draw = null;
    container.style.cursor = "";
    onDrawChange(false);
  }

  function build() {
    const plan = new LayerWMTS({ layer: "GEOGRAPHICALGRIDSYSTEMS.PLANIGNV2" });
    const ortho = new LayerWMTS({ layer: "ORTHOIMAGERY.ORTHOPHOTOS" });
    const limits = new LayerWMS({ layer: "LIMITES_ADMINISTRATIVES_EXPRESS.LATEST" });
    ortho.setVisible(false);
    limits.setVisible(false);
    map = new Map({
      target,
      layers: [plan, ortho, limits],
      controls: [],
      view: new View({ center: fromLonLat([2.5, 46.6]), zoom: 5, maxZoom: 19 }),
    });
    // Couche de l'emprise « non gérée » : affichée au-dessus de tout mais absente de la liste des
    // couches de la carte, donc invisible pour le sélecteur de couches (on ne peut pas la supprimer).
    new VectorLayer({ source: extentSource, style: extentStyle }).setMap(map);
    map.addControl(new GeoportalZoom());
    map.addControl(new SearchEngine({ collapsed: true }));
    map.addControl(new LayerSwitcher({ options: { collapsed: true } }));
    map.addControl(new MousePosition({ collapsed: true }));
    map.addControl(new GeoportalAttribution());
    if (pending) applyExtent(pending);
  }

  const ready = loadGeoportalConfig().then(() => { build(); return true; }).catch((error) => {
    console.warn("Carte indisponible :", error);
    container.textContent = `Fond de carte indisponible (${error.message}). La recherche d'emprise et la requête restent utilisables : l'emprise s'affichera dès que la carte pourra se charger.`;
    container.classList.add("map-error");
    return false;
  });

  return {
    ready,
    showExtent(geometry, bbox) {
      pending = { geometry, bbox };
      if (map) applyExtent(pending);
    },
    // Rectangle dessiné par cliquer-glisser : le rectangle EST l'emprise utilisée.
    startDraw() {
      if (!map) return false;
      stopDraw();
      draw = new Draw({ type: "Circle", geometryFunction: createBox(), freehand: true, style: drawStyle });
      draw.on("drawend", (event) => {
        const [x0, y0, x1, y1] = transformExtent(event.feature.getGeometry().getExtent(), MAP_CRS, DATA_CRS);
        stopDraw();
        const clamp = (value, limit) => Math.max(-limit, Math.min(limit, value));
        if (x0 === x1 || y0 === y1) return;
        onBox([clamp(x0, 180), clamp(y0, 90), clamp(x1, 180), clamp(y1, 90)]);
      });
      map.addInteraction(draw);
      container.style.cursor = "crosshair";
      onDrawChange(true);
      return true;
    },
    cancelDraw: stopDraw,
  };
}
