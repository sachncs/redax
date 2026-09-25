// Single source of truth for site copy. Plain data, no markdown.
// Anything rendered to the page comes from here.

export const SITE = {
  name: "Redax",
  title: "Redax — Self-hosted PII redaction for the LLM era",
  description:
    "A self-hosted PII redaction boundary for teams that want to inspect and replace sensitive text before it reaches a model. Local-first, policy-driven, and explicit about its limits.",
  repo: "https://github.com/sachncs/redax",
  registry: "https://ghcr.io/sachncs/redax",
} as const;

export const DOCS = {
  api: "/redax/docs/api",
  architecture: "/redax/docs/architecture",
  integration: "/redax/docs/integration",
  policies: "/redax/docs/policies",
  bench: "/redax/docs/bench",
  deployment: "/redax/docs/deployment",
  security: "/redax/docs/security",
  dataFlow: "/redax/docs/data-flow",
  status: "/redax/docs/status",
} as const;

export const HERO = {
  eyebrow: "Self-hosted · Apache-2.0",
  title: ["Redact before", "you prompt."],
  subtitle:
    "Redax is a local-first PII redaction boundary that detects structured identifiers and optional contextual entities, then returns safer text before your application calls an LLM. You control the host, model files, network, and retention.",
  ctas: [
    { label: "Get started", href: "#start", variant: "primary" as const },
    { label: "Read the docs", href: DOCS.api, variant: "ghost" as const },
  ],
  proof: ["Apache-2.0", "No hosted inference", "Runs on your host", "CPU-friendly path"],
} as const;

export const NAV = [
  { label: "Product", href: "/redax/#product" },
  { label: "How it works", href: "/redax/#how-it-works" },
  { label: "Benchmarks", href: "/redax/#benchmarks" },
  { label: "Deploy", href: "/redax/#deploy" },
  { label: "Security", href: DOCS.security },
  { label: "Docs", href: DOCS.api },
  { label: "GitHub", href: SITE.repo, external: true },
] as const;

export const VALUE_PROPS = [
  {
    eyebrow: "01",
    title: "Deterministic by design",
    body:
      "The regex and replacement paths are deterministic under the same code and configuration. Model-backed results depend on the pinned model and runtime, so Redax exposes that boundary instead of hiding it.",
  },
  {
    eyebrow: "02",
    title: "Privacy is the architecture",
    body:
      "Redax does not require a hosted inference hop. Keep model files local, control egress, and configure telemetry deliberately for the boundary you operate.",
  },
  {
    eyebrow: "03",
    title: "Drop-in, not rip-and-replace",
    body:
      "A single POST endpoint and a small integration surface. Put Redax immediately before your existing model call and keep your provider unchanged.",
  },
  {
    eyebrow: "04",
    title: "Production foundations",
    body:
      "Operational foundations include idempotency, rate limiting, response caching, Prometheus metrics, OpenTelemetry hooks, and a local JSONL audit log. Review the deployment limits before calling it production-ready.",
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
    name: "Consensus fusion",
    detail:
      "Spans are merged across detectors, deduped by overlap, and typed with the highest-confidence label.",
    tone: "merge",
  },
  {
    n: "04",
    name: "Replacement + relex",
    detail:
      "Deterministic typed placeholders ([EMAIL_0001]) plus optional hiding-in-plain-sight relexicalization.",
    tone: "shape",
  },
  {
    n: "05",
    name: "Audit log",
    detail:
      "Counts, types, timing, and request metadata — not original values. The local JSONL backend supports rotation and optional fsync; it is not a tamper-proof ledger.",
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
    title: "Explicit detector modes",
    body: "The current server supports the deterministic regex path and the pinned local GLiNER2 path. Choose the mode deliberately and verify readiness before sending traffic.",
  },
  {
    icon: "lock",
    title: "Typed placeholders",
    body: "`[EMAIL_0001]` is easier to inspect than a generic mask. Treat any re-identification map as sensitive; the HTTP boundary is for safe text, not automatic restoration.",
  },
  {
    icon: "spark",
    title: "Hiding-in-Plain-Sight relex",
    body: "An optional relexicalization strategy can keep text readable. It is not a privacy guarantee and should be reviewed for collisions and downstream use.",
  },
  {
    icon: "policy",
    title: "Versioned YAML policies",
    body: "Field-by-field redaction rules checked into git. Reviewed in PRs, not runtime configs.",
  },
  {
    icon: "audit",
    title: "Append-only audit log",
    body: "Records redaction metadata without original values in the event payload. Rotation, retention, and fsync are configurable; integrity signing is not provided by the current file backend.",
  },
  {
    icon: "obs",
    title: "Prometheus + OpenTelemetry",
    body: "`/metrics` for scraping, OTLP gRPC for traces. SRE-friendly without bolting on a sidecar.",
  },
  {
    icon: "rate",
    title: "Rate limit + idempotency",
    body: "Per-API-key fixed-window limiting in Redis. `Idempotency-Key` can short-circuit retries; clients should reuse it only for the same request body.",
  },
  {
    icon: "wasm",
    title: "Browser demo (experimental)",
    body: "The public browser demo runs the structured regex detector locally. It is not parity with the optional server-side model and should not be treated as a complete DLP control.",
  },
  {
    icon: "rfc",
    title: "RFC 7807 errors",
    body: "Every error path returns a problem-details JSON body. Easier debugging, predictable SDKs.",
  },
  {
    icon: "bench",
    title: "Quantified against a benchmark",
    body: "A published RedactionBench snapshot against `ai4privacy/pii-masking-200k`. Use the methodology and your own workload before setting an SLO.",
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
    "This is a published RedactionBench snapshot on a 5,060-document stratified sample of `ai4privacy/pii-masking-200k`. The metric rewards recall and format precision. Treat the numbers as comparative evidence, not a production SLA; see the benchmark methodology for model, hardware, and run details.",
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
      role: "Reference snapshot",
      params: "434M",
      redactionbench: 0.272,
      pii200k: 0.385,
      latency: "168 ms*",
    },
    {
      detector: "gliner2",
      role: "Default",
      params: "205M",
      redactionbench: 0.454,
      pii200k: 0.552,
      latency: "123 ms*",
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
    body: "Experimental browser package. The current public demo is regex-only; model parity, packaging, and bundle provenance are not yet production guarantees.",
    code: ["import { redact } from '@sachncs/redax/wasm'", "await redact(text)"],
  },
] as const;

export const FOOTER = {
  tagline: "Self-hosted PII redaction. Control the host, egress, model files, and retention.",
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
        { label: "Deployment", href: DOCS.deployment },
        { label: "Security boundary", href: DOCS.security },
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
