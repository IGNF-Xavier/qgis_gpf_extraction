// Construit le site statique dans dist/ :
//  - js/app.js + OpenLayers + geopf-extensions-openlayers → dist/app.js et dist/app.css (esbuild) ;
//  - thème DSFR des extensions (css/Dsfr.css) → dist/geopf-dsfr.css ;
//  - DSFR (CSS, JS, fontes, icônes) copié depuis node_modules, donc servi par le site lui-même
//    (aucun CDN) ;
//  - index.html et style.css tels quels.
import { build } from "esbuild";
import { cpSync, mkdirSync, rmSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(fileURLToPath(import.meta.url));
const dist = join(root, "dist");
const nm = join(root, "node_modules");

rmSync(dist, { recursive: true, force: true });
mkdirSync(dist, { recursive: true });

const assetLoaders = {
  ".png": "file", ".gif": "file", ".jpg": "file", ".svg": "file",
  ".woff": "file", ".woff2": "file", ".ttf": "file", ".eot": "file",
};

await build({
  entryPoints: [join(root, "js/app.js")],
  outfile: join(dist, "app.js"),
  bundle: true,
  format: "esm",
  target: "es2020",
  minify: true,
  loader: assetLoaders,
  assetNames: "assets/[name]-[hash]",
  legalComments: "none",
  logLevel: "warning",
});

await build({
  entryPoints: [join(nm, "geopf-extensions-openlayers/css/Dsfr.css")],
  outfile: join(dist, "geopf-dsfr.css"),
  bundle: true,
  minify: true,
  loader: assetLoaders,
  assetNames: "assets/[name]-[hash]",
  logLevel: "warning",
});

const dsfr = join(nm, "@gouvfr/dsfr/dist");
const copy = (from, to) => cpSync(join(dsfr, from), join(dist, "dsfr", to), { recursive: true });
copy("dsfr.min.css", "dsfr.min.css");
copy("dsfr.module.min.js", "dsfr.module.min.js");
copy("fonts", "fonts");
copy("icons", "icons");
copy("utility/icons", "utility/icons");

cpSync(join(root, "index.html"), join(dist, "index.html"));
cpSync(join(root, "style.css"), join(dist, "style.css"));
console.log("Site construit dans", dist);
