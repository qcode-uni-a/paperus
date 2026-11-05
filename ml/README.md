# paperus-ml

Machine learning service of [paperus](https://github.com/qcode-uni-a/paperus):
text embeddings for search by meaning, with ONNX Runtime on the CPU. Models
are downloaded from Hugging Face on first use and unloaded when idle.

```sh
pip install paperus-ml
PAPERUS_ML_TOKEN=… paperus-ml --host 0.0.0.0   # port 3003
```

Most installations use the `paperus-ml` container image instead. Status:
early version (0.0.x); expect breaking changes.
