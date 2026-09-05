// Browser-side entry point. Loads the quantized GLiNER2 model and exposes
// a single async function: `redact(text)`.
//
// The exported ONNX model lives in wasm/model.int8.onnx; this file uses
// @huggingface/transformers which serves it via WASM ORT under the hood.
//
// In production, host model.int8.onnx alongside pkg/redax.js in a
// static-served directory.

import { pipeline, env } from "@huggingface/transformers";

env.allowLocalModels = true;
env.allowRemoteModels = false;

let pipePromise = null;

async function getPipe() {
  if (!pipePromise) {
    pipePromise = pipeline(
      "token-classification",
      "/models/redax/model.int8",
    );
  }
  return pipePromise;
}

export async function redact(text) {
  const pipe = await getPipe();
  const out = await pipe(text, {
    threshold: 0.5,
    aggregation_strategy: "max",
  });
  let redacted = text;
  const sorted = [...out].sort((a, b) => b.end - a.start);
  for (const span of sorted) {
    redacted =
      redacted.slice(0, span.start) +
      `[${(span.entity_group || span.label).toUpperCase()}]` +
      redacted.slice(span.end);
  }
  return { text: redacted, entities: out };
}
