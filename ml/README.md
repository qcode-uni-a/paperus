# paperus-ml

Machine learning service of [paperus](https://github.com/qcode-uni-a/paperus):
text embeddings for search by meaning, with ONNX Runtime on the CPU. Models
are downloaded from Hugging Face on first use and unloaded when idle.

```sh
pip install paperus-ml
PAPERUS_ML_TOKEN=… paperus-ml --host 0.0.0.0   # port 3003
```

Settings are environment variables:

| Variable | Default | Meaning |
| --- | --- | --- |
| `PAPERUS_ML_TOKEN` | none | Shared secret; requests need `Authorization: Bearer <token>` |
| `PAPERUS_ML_CACHE_PATH` | `~/.cache/paperus-ml` | Downloaded models |
| `PAPERUS_ML_PRELOAD` | `[]` | Models to load at start and keep, e.g. `["bge-m3"]` |
| `PAPERUS_ML_MODEL_TTL` | `300` | Unload other models after this many idle seconds (0: never) |
| `PAPERUS_ML_INTRA_OP_THREADS` | `0` | CPU cores per model (0: all it sees; in a container, set it, as the host's cores are seen) |
| `PAPERUS_ML_MAX_BATCH_TEXTS` / `_TOKENS` | `32` / `16384` | Batch size (memory grows with both) |

One batch runs at a time per model, using all its cores; simultaneous
requests take turns batch by batch.

Most installations use the `paperus-ml` container image instead. Status:
early version (0.0.x); expect breaking changes.
