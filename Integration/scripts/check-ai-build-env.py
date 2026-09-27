"""Verify the Python environment used to package the SIA AI sidecar."""

import torch
import torchaudio
import torchvision


expected = {
    "torch": (torch.__version__, "2.11.0+cu128"),
    "torchvision": (torchvision.__version__, "0.26.0+cu128"),
    "torchaudio": (torchaudio.__version__, "2.11.0+cu128"),
    "CUDA": (torch.version.cuda, "12.8"),
}

for name, (actual, required) in expected.items():
    if actual != required:
        raise SystemExit(f"{name}: expected {required}, got {actual}")

if not hasattr(torch.ops.torchvision, "nms"):
    raise SystemExit("torchvision nms operator is unavailable")

torchvision.models.resnet18(num_classes=2)
print("AI build environment OK:", *(f"{name}={actual}" for name, (actual, _) in expected.items()))
