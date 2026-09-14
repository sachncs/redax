# Redax marketing site

The premium product page for [Redax](https://github.com/sachncs/redax).
Lives at **<https://sachncs.github.io/redax/>** after deployment.

## Stack

- **[Astro 5](https://astro.build/)** — static-first, ships zero JS by default,
  with islands for the interactive demo and tabs.
- **[Tailwind CSS 4](https://tailwindcss.com/)** via `@tailwindcss/vite` —
  design tokens live in `src/styles/global.css`.
- **TypeScript** with `astro/tsconfigs/strict`.
- **Shadcn-style design system** — colour tokens, typography, motion
  primitives, and a hand-rolled syntax highlighter (no Shiki bundle bloat).

## Develop

```bash
cd site
npm install
npm run dev          # http://localhost:4321
npm run build        # static output to ./dist
npm run check        # astro check (TS / .astro)
```

## Deploy

Pushing to `master` runs `.github/workflows/pages.yml`, which builds the
site and deploys `site/dist` to GitHub Pages via the official
`actions/deploy-pages` action.

To deploy from a different branch or a fork, set the repo's
**Settings → Pages → Source** to **GitHub Actions**.

## Layout

```
site/
├── astro.config.mjs        # build, sitemap, vite plugins
├── package.json
├── public/                 # static assets (favicon, og, robots)
└── src/
    ├── components/         # one Astro component per section
    ├── content/site.ts     # single source of truth for copy
    ├── layouts/Base.astro
    ├── pages/index.astro
    ├── scripts/redact.ts   # client-side redaction engine for the demo
    └── styles/global.css   # design tokens, primitives, motion
```

Everything rendered to the page is plain data in `src/content/site.ts`.
We do not source content from Markdown / README files.
