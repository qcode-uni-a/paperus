"""Downloading a model from Hugging Face, on its first use."""

from pathlib import Path

from huggingface_hub import snapshot_download

from paperus_ml.models import ModelSpec


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
