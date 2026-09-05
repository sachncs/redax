# Redax — in-browser PII redaction

Run `make build-wasm` to export and quantize the model, then serve this directory.

```bash
cd examples/wasm-demo
python3 -m http.server 8080
# Open http://localhost:8080
```

The model (`model.int8.onnx`) is fetched on demand by `@huggingface/transformers`.
For fully-offline deployment, place the quantized ONNX under `/models/redax/`
relative to your static root so the WASM bundle finds it locally.
