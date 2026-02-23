"""Custom ComfyUI nodes for the Poslaroid project.

Provides SaveConditioning and LoadConditioning nodes so that CLIP embeddings
can be pre-computed once and cached to disk.  At inference time the Qwen CLIP
model is never loaded, saving ~3-7 GB of RAM.

INSTALLATION
------------
Place this file (or a symlink to it) inside ComfyUI's custom_nodes/ directory
and restart ComfyUI.  The server script (comfyui_img2img.py) will then be able
to submit pre-compute workflows at startup and use cached embeddings afterwards.
"""

import os
import torch


class SaveConditioning:
    """Save a CONDITIONING tensor to disk."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "conditioning": ("CONDITIONING",),
                "cache_path": ("STRING", {"default": "conditioning.pt"}),
            }
        }

    RETURN_TYPES = ()
    OUTPUT_NODE = True
    FUNCTION = "save"
    CATEGORY = "poslaroid"

    def save(self, conditioning, cache_path):
        os.makedirs(os.path.dirname(os.path.abspath(cache_path)), exist_ok=True)
        torch.save(conditioning, cache_path)
        print(f"[Poslaroid] Saved conditioning to: {cache_path}")
        return {}


class LoadConditioning:
    """Load a pre-computed CONDITIONING tensor from disk, bypassing the CLIP model."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "cache_path": ("STRING", {"default": "conditioning.pt"}),
            }
        }

    RETURN_TYPES = ("CONDITIONING",)
    FUNCTION = "load"
    CATEGORY = "poslaroid"

    def load(self, cache_path):
        if not os.path.exists(cache_path):
            raise FileNotFoundError(
                f"[Poslaroid] Conditioning cache not found: {cache_path}\n"
                "Run the server once to trigger pre-computation."
            )
        # weights_only=False is required: conditioning objects contain Python
        # dicts alongside tensors and cannot be loaded in restricted mode.
        conditioning = torch.load(cache_path, weights_only=False)
        print(f"[Poslaroid] Loaded conditioning from: {cache_path}")
        return (conditioning,)


NODE_CLASS_MAPPINGS = {
    "SaveConditioning": SaveConditioning,
    "LoadConditioning": LoadConditioning,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SaveConditioning": "Save Conditioning (Poslaroid)",
    "LoadConditioning": "Load Conditioning (Poslaroid)",
}
