// @ts-check
import { defineConfig } from "astro/config";
import sitemap from "@astrojs/sitemap";
import tailwindcss from "@tailwindcss/vite";

const SITE_URL = process.env.SITE_URL ?? "https://sachncs.github.io/redax";

export default defineConfig({
  site: SITE_URL,
  base: "/redax",
  trailingSlash: "ignore",
  build: {
    format: "directory",
    inlineStylesheets: "auto",
    assets: "_assets",
  },
  prefetch: {
    prefetchAll: true,
    defaultStrategy: "viewport",
  },
  integrations: [sitemap()],
  vite: {
    plugins: [/** @type {any} */ (tailwindcss())],
    build: {
      cssMinify: "lightningcss",
    },
  },
  compressHTML: true,
});
