// Single source of truth for site copy. Plain data, no markdown.
// Anything rendered to the page comes from here.

export const SITE = {
  name: "Redax",
  title: "Redax — Self-hosted PII redaction for the LLM era",
  description:
    "A tiny, self-hosted redaction engine that sits between your text and your LLM. Deterministic. Auditable. Runs on your hardware.",
  repo: "https://github.com/sachncs/redax",
  registry: "https://ghcr.io/sachncs/redax",
} as const;

export const DOCS = {
  api: "/redax/docs/api",
  architecture: "/redax/docs/architecture",
  integration: "/redax/docs/integration",
  policies: "/redax/docs/policies",
  bench: "/redax/docs/bench",
} as const;

export const HERO = {
  eyebrow: "Self-hosted · Apache-2.0",
  title: ["Redact before", "you prompt."],
  subtitle:
    "Redax is a small, deterministic PII engine that strips emails, phones, names, and identifiers from any text — before it reaches an LLM. Built for teams that refuse to send customer data to someone else's GPU.",
  ctas: [
    { label: "Get started", href: "#start", variant: "primary" as const },
    { label: "Read the docs", href: DOCS.api, variant: "ghost" as const },
  ],
  proof: ["Apache-2.0", "No telemetry", "Runs on a laptop", "CPU-friendly"],
} as const;

export const NAV = [
  { label: "Product", href: "/redax/#product" },
  { label: "How it works", href: "/redax/#how-it-works" },
  { label: "Pipeline", href: "/redax/#pipeline" },
  { label: "Benchmarks", href: "/redax/#benchmarks" },
  { label: "Deploy", href: "/redax/#deploy" },
  { label: "Docs", href: DOCS.api },
  { label: "GitHub", href: SITE.repo, external: true },
] as const;

export const VALUE_PROPS = [
  {
    eyebrow: "01",
    title: "Deterministic by design",
    body:
      "Same input, same output, every time. Two replicas behind a load balancer return byte-for-byte identical results — no drift, no surprises.",
  },
  {
    eyebrow: "02",
    title: "Privacy is the architecture",
    body:
      "No cloud calls. No model phones home. Your text and your telemetry never leave the box you deploy Redax on.",
  },
  {
    eyebrow: "03",
    title: "Drop-in, not rip-and-replace",
    body:
      "A single POST endpoint, an OpenAI-compatible shape, and a Python SDK. Wrap any LLM call in five lines.",
  },
  {
    eyebrow: "04",
    title: "Built for production",
    body:
      "Idempotency, rate limiting, response cache, Prometheus metrics, OpenTelemetry traces, and an append-only audit log.",
  },
] as const;

export const PIPELINE = [
  {
    n: "01",
    name: "Regex safety net",
    detail:
      "Deterministic patterns catch emails, E.164 phones, IBANs, SSNs, IPs, and Luhn-checked credit cards in microseconds.",
    tone: "fast",
  },
  {
    n: "02",
    name: "GLiNER2 zero-shot NER",
    detail:
      "A 205M encoder identifies people, organisations, and contextual entities the regex misses. Runs on CPU.",
    tone: "model",
  },
  {
    n: "03",
    name: "OpenMed-PII (optional)",
    detail:
      "A 434M clinical-grade encoder with 54 entity types for healthcare and multilingual workloads. Swap in with one env var.",
    tone: "model",
  },
  {
    n: "04",
    name: "Consensus fusion",
    detail:
      "Spans are merged across detectors, deduped by overlap, and typed with the highest-confidence label.",
    tone: "merge",
  },
  {
    n: "05",
    name: "Replacement + relex",
    detail:
      "Deterministic typed placeholders ([EMAIL_0001]) plus optional hiding-in-plain-sight relexicalization.",
    tone: "shape",
  },
  {
    n: "06",
    name: "Audit log",
    detail:
      "What was redacted and where — never the value itself. fsync'd, rotated, and signed by default.",
    tone: "log",
  },
] as const;

export const FEATURES = [
  {
    icon: "regex",
    title: "Seven structured PII types",
    body: "Email, phone (E.164), IBAN, SSN, IPv4, credit card with Luhn check, URL — covered with deterministic regex out of the box.",
  },
  {
    icon: "gliner",
    title: "Zero-shot NER on CPU",
    body: "Default detector is a 0.3B GLiNER2 model that catches PERSON, ORG, and contextual entities without retraining.",
  },
  {
    icon: "swap",
    title: "One env var to swap detectors",
    body: "Switch to OpenMed-PII for healthcare workloads with `REDAX_DETECTOR=openmed`. No code change.",
  },
  {
    icon: "lock",
    title: "Reversible typed placeholders",
    body: "`[EMAIL_0001]` instead of `[REDACTED]`. The same entity always maps to the same placeholder across requests.",
  },
  {
    icon: "spark",
    title: "Hiding-in-Plain-Sight relex",
    body: "Optionally replace names with plausible lookalikes so the output still reads like English.",
  },
  {
    icon: "policy",
    title: "Versioned YAML policies",
    body: "Field-by-field redaction rules checked into git. Reviewed in PRs, not runtime configs.",
  },
  {
    icon: "audit",
    title: "Append-only audit log",
    body: "Records what was redacted and where — never the values. Configurable rotation, retention, and fsync.",
  },
  {
    icon: "obs",
    title: "Prometheus + OpenTelemetry",
    body: "`/metrics` for scraping, OTLP gRPC for traces. SRE-friendly without bolting on a sidecar.",
  },
  {
    icon: "rate",
    title: "Rate limit + idempotency",
    body: "Per-API-key token bucket in Redis. `Idempotency-Key` short-circuits retries safely.",
  },
  {
    icon: "wasm",
    title: "WASM bundle",
    body: "Same model, INT8-quantised, runs in the browser via Transformers.js. No server round-trip needed.",
  },
  {
    icon: "rfc",
    title: "RFC 7807 errors",
    body: "Every error path returns a problem-details JSON body. Easier debugging, predictable SDKs.",
  },
  {
    icon: "bench",
    title: "Quantified against a benchmark",
    body: "RedactionBench R-Score measured against `ai4privacy/pii-masking-200k`. Numbers you can defend in review.",
  },
] as const;

export type BenchRow = {
  detector: string;
  role: string;
  params: string;
  redactionbench: number;
  pii200k: number;
  latency: string;
  winner?: boolean;
};

export const BENCH: {
  intro: string;
  rows: BenchRow[];
  winner: string;
} = {
  intro:
    "Redax is scored against the RedactionBench harness on a 5,060-document stratified sample of `ai4privacy/pii-masking-200k`. The metric rewards both recall and format precision, with a strict penalty for redaction gaps.",
  rows: [
    {
      detector: "regex",
      role: "Safety net",
      params: "n/a",
      redactionbench: 0.167,
      pii200k: 0.142,
      latency: "< 1 ms",
    },
    {
      detector: "openmed",
      role: "Clinical-grade",
      params: "434M",
      redactionbench: 0.272,
      pii200k: 0.385,
      latency: "168 ms",
    },
    {
      detector: "gliner2",
      role: "Default",
      params: "205M",
      redactionbench: 0.454,
      pii200k: 0.552,
      latency: "123 ms",
      winner: true,
    },
  ],
  winner: "gliner2",
};

export const DEPLOY = [
  {
    title: "Docker Compose",
    badge: "Fastest",
    body: "Clones the repo, brings up Redax + Redis, and ships a working stack with one command.",
    code: ["git clone https://github.com/sachncs/redax.git", "cd redax", "docker compose up"],
  },
  {
    title: "Pre-built image",
    badge: "No clone",
    body: "Pull from GHCR and run on any host with a Docker daemon. Useful for CI and air-gapped nodes.",
    code: ["docker run --rm -p 8000:8000 \\", "  ghcr.io/sachncs/redax:latest"],
  },
  {
    title: "From source",
    badge: "Dev-friendly",
    body: "Install pinned deps from the lockfile and run Redax in a virtualenv. Best for hacking on the engine.",
    code: ["python3 -m venv .venv", "source .venv/bin/activate", "pip install -r requirements.lock", "pip install -e '.[dev]'", "make dev"],
  },
  {
    title: "WASM bundle",
    badge: "Browser",
    body: "Same GLiNER2 model, INT8-quantised. Runs locally via Transformers.js with no server round-trip.",
    code: ["import { redact } from '@sachncs/redax/wasm'", "await redact(text)"],
  },
] as const;

export const FOOTER = {
  tagline: "Self-hosted PII redaction. Your text never leaves your hardware.",
  columns: [
    {
      title: "Product",
      links: [
        { label: "Features", href: "/redax/#product" },
        { label: "How it works", href: "/redax/#how-it-works" },
        { label: "Pipeline", href: "/redax/#pipeline" },
        { label: "Benchmarks", href: "/redax/#benchmarks" },
        { label: "Deployment", href: "/redax/#deploy" },
      ],
    },
    {
      title: "Docs",
      links: [
        { label: "HTTP API", href: DOCS.api },
        { label: "Architecture", href: DOCS.architecture },
        { label: "Integration", href: DOCS.integration },
        { label: "Policies", href: DOCS.policies },
      ],
    },
    {
      title: "Project",
      links: [
        { label: "GitHub", href: SITE.repo, external: true },
        { label: "Container registry", href: SITE.registry, external: true },
        { label: "Changelog", href: `${SITE.repo}/blob/master/CHANGELOG.md`, external: true },
        { label: "Contributing", href: `${SITE.repo}/blob/master/CONTRIBUTING.md`, external: true },
      ],
    },
  ],
} as const;

export const QUICKSTART: { curl: string[]; python: string[]; response: string[] } = {
  curl: [
    `curl -s -X POST http://localhost:8000/v1/redact \\`,
    `  -H 'Content-Type: application/json' \\`,
    `  -d '{"text": "Email me at alice@example.com or +1-415-555-2671."}'`,
  ],
  python: [
    `import asyncio`,
    `from app.redaction.redactor import Redactor`,
    `from app.redaction.strategy import Mask`,
    `from app.inference.regex import RegexDetector`,
    ``,
    `redactor = Redactor(`,
    `    detector=RegexDetector(),`,
    `    strategies={"mask": Mask()},`,
    `    replacement="[REDACTED]",`,
    `)`,
    ``,
    `result = asyncio.run(redactor.redact(`,
    `    "Email me at alice@example.com or +1-415-555-2671."`,
    `))`,
    `print(result.text)`,
  ],
  response: [
    `{`,
    `  "text": "Email me at [EMAIL_0000] or [PHONE_E164_0000].",`,
    `  "spans": [`,
    `    {"start": 12, "end": 29, "type": "EMAIL", "confidence": 1.0},`,
    `    {"start": 33, "end": 47, "type": "PHONE_E164", "confidence": 1.0}`,
    `  ],`,
    `  "digest": "8f1d2c..."`,
    `}`,
  ],
};
