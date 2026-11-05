"""paperus-ml: the machine learning service of paperus.

No telemetry: Hugging Face Hub reads its switch when imported, so it is set
here, before any submodule imports it; ONNX Runtime's is switched off too.
"""

import os

os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"

import onnxruntime

onnxruntime.disable_telemetry_events()
