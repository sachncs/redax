import { readFileSync } from "node:fs";

const settingsSource = readFileSync(new URL("../../app/config.py", import.meta.url), "utf8");
const referenceSource = readFileSync(new URL("../src/pages/docs/config.astro", import.meta.url), "utf8");
const settings = [...settingsSource.matchAll(/^    ([a-z][a-z0-9_]+):/gm)].map(
  ([, name]) => "REDAX_" + name.toUpperCase(),
);
const missing = settings.filter((name) => !referenceSource.includes('"' + name + '"'));

if (missing.length > 0) {
  console.error("Missing configuration reference rows: " + missing.join(", "));
  process.exit(1);
}

console.log("Configuration reference covers " + settings.length + " typed Settings fields.");
