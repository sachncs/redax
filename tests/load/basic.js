import http from "k6/http";
import { check, sleep } from "k6";

const baseUrl = __ENV.BASE_URL || "http://localhost:8000";
const apiKey = __ENV.REDAX_API_KEY || "";
const text = __ENV.TEXT || "Synthetic contact alice@example.com";

export const options = {
  vus: Number(__ENV.VUS || 5),
  duration: __ENV.DURATION || "30s",
  thresholds: {
    http_req_failed: ["rate<0.01"],
    http_req_duration: ["p(95)<1000"],
  },
};

export default function () {
  const health = http.get(`${baseUrl}/healthz`);
  check(health, { "health is 200": (response) => response.status === 200 });

  const ready = http.get(`${baseUrl}/readyz`);
  check(ready, {
    "readiness is 200": (response) => response.status === 200,
    "readiness is ready": (response) => response.status === 200 && response.body.includes('"status":"ready"'),
  });

  const metrics = http.get(`${baseUrl}/metrics`);
  check(metrics, {
    "metrics are available": (response) => response.status === 200,
    "metrics expose request counter": (response) => response.status === 200 && response.body.includes("redax_requests_total"),
  });

  const headers = { "Content-Type": "application/json" };
  if (apiKey) {
    headers["X-API-Key"] = apiKey;
  }
  const redact = http.post(
    `${baseUrl}/v1/redact`,
    JSON.stringify({ text }),
    { headers },
  );
  check(redact, {
    "redaction is successful": (response) => response.status === 200,
    "redaction removes the synthetic email": (response) =>
      response.status === 200 && !response.body.includes(text),
  });

  sleep(1);
}
