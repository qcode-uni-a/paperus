"""Downloading models from Hugging Face: on first use into the cache, or
ahead of time into a folder (``python -m paperus_ml.download``), as the
image comes with the recommended ones for its device.

Imports only ``models`` from paperus-ml, so the image can download before
the rest of the code is in it (and keep that layer across releases)."""

import argparse
import shutil
from pathlib import Path

from huggingface_hub import snapshot_download

from paperus_ml.models import MODELS, ModelSpec, recommended


def fetch(spec: ModelSpec, device: str, directory: Path) -> None:
    """The model's files for ``device`` into ``directory``, as plain files;
    a changed revision downloads the changed files into the same folder."""
    snapshot_download(
        spec.repo,
        revision=spec.revision,
        local_dir=directory,
        allow_patterns=[f"{spec.onnx_file_for(device)}*", spec.tokenizer_file],
    )
    if spec.detector is not None:
        snapshot_download(
            spec.detector.repo,
            revision=spec.detector.revision,
            local_dir=directory / spec.detector.folder,
            allow_patterns=[f"{spec.detector.onnx_file}*"],
        )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m paperus_ml.download",
        description="Download models into a folder (<folder>/<task>/<model>), "
        "for PAPERUS_ML_BUILTIN_PATH.",
    )
    parser.add_argument("folder", type=Path)
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cpu")
    parser.add_argument(
        "models",
        nargs="*",
        choices=sorted(MODELS),
        metavar="model",
        help="default: the recommended ones for the device",
    )
    args = parser.parse_args(argv)
    for spec in [MODELS[name] for name in args.models] or recommended(args.device):
        directory = args.folder / spec.task / spec.name
        fetch(spec, args.device, directory)
        # Hugging Face's notes for later downloads: none into this folder.
        for notes in list(directory.rglob(".cache")):
            shutil.rmtree(notes)
        print(f"{spec.name}: {directory}")


if __name__ == "__main__":  # pragma: no cover
    main()
