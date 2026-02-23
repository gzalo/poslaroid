"""
ComfyUI Image-to-Image Web Server
Exposes a single endpoint that accepts an image and returns the processed result.

At startup the server pre-computes CLIP conditioning tensors for every style and
saves them to genai/conditioning_cache/.  Subsequent runs load from disk so the
Qwen CLIP model (~3-7 GB) never needs to stay in memory during inference.

Requires poslaroid_nodes.py to be installed in ComfyUI's custom_nodes/ directory.
"""

import copy
import json
import os
import urllib.request
import urllib.parse
import uuid
import time
import io
import random
from datetime import datetime
from flask import Flask, request, send_file, jsonify
from PIL import Image

app = Flask(__name__)

COMFYUI_URL = "127.0.0.1:8188"
WORKFLOW_FILE = "workflow_api.json"  # Export from ComfyUI with "Save (API Format)"
OUTPUT_DIR = "outputs"
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "conditioning_cache")

# Each style has a display name and a complete prompt tailored for thermal printer output.
STYLES = {
    "cartoon": {
        "name": "CARTOON",
        "prompt": (
            "Transform this photo into a bold cartoon illustration with thick black outlines "
            "and flat color areas. Use strong contrast between light and dark regions. "
            "Keep large white areas and avoid heavy shading. "
            "Preserve facial features and expression faithfully. "
            "The result should print well on a thermal printer with limited grayscale."
        ),
    },
    "anime": {
        "name": "ANIME",
        "prompt": (
            "Convert this photo into a clean anime illustration style with sharp linework "
            "and cel-shaded lighting. Use minimal gradients, prefer flat tones with clear "
            "separation between light and shadow. Keep backgrounds simple and bright. "
            "Preserve the person's facial features and expression. "
            "Optimize for black and white thermal printing with good contrast."
        ),
    },
    "pencil_sketch": {
        "name": "BOCETO",
        "prompt": (
            "Transform this photo into a detailed pencil sketch drawing on white paper. "
            "Use fine hatching and cross-hatching for shading. Keep most of the image light "
            "with darker pencil strokes only for shadows and contours. "
            "The sketch should feel hand-drawn with visible pencil texture. "
            "Preserve the subject's likeness and facial features. "
            "Ideal for thermal printer: mostly white with delicate gray linework."
        ),
    },
    "8bit": {
        "name": "8-BIT RETRO",
        "prompt": (
            "Convert this photo into a retro 8-bit pixel art style, as if from a classic "
            "video game console. Use large visible square pixels with a very limited palette. "
            "Simplify details into blocky shapes. Add a slight scanline or CRT feel. "
            "Keep the overall image bright with good contrast between pixel blocks. "
            "Preserve the subject's recognizable features in simplified pixel form. "
            "Should work well as a small, high-contrast image on a thermal printer."
        ),
    },
    #"woodcut": {
    #    "name": "GRABADO",
    #    "prompt": (
    #        "Transform this photo into a traditional woodcut print illustration. "
    #        "Use bold black lines carved into white space, with parallel line hatching "
    #        "for mid-tones. The style should resemble a hand-carved woodblock print "
    #        "with strong graphic contrast. Keep large areas of pure white and pure black. "
    #        "Preserve the subject's facial features with simplified but recognizable forms. "
    #        "Perfect for thermal printing: naturally high contrast black and white."
    #    ),
    #},
    "pop_art": {
        "name": "POP ART",
        "prompt": (
            "Convert this photo into a bold pop art style inspired by Roy Lichtenstein "
            "and Andy Warhol. Use high contrast with strong outlines, quite big Ben-Day dots pattern "
            "for shading, and dramatic light/shadow separation. "
            "Make the image graphic and punchy with simplified forms. "
            "Preserve the subject's face with stylized but recognizable features. "
            "The pop art dots and bold lines will create interesting dithering patterns "
            "on a thermal printer."
        ),
    },
    "caricature": {
        "name": "CARICATURA",
        "prompt": (
            "Transform this photo into a fun caricature with slightly exaggerated facial "
            "features and proportions. Use a clean cartoon style with bold outlines "
            "and playful exaggeration of distinctive features like nose, eyes, or smile. "
            "Keep the background minimal and white. Use light shading with good contrast. "
            "The caricature should be humorous and flattering, clearly recognizable "
            "as the subject. Works great on thermal printer with bold lines and white space."
        ),
    },
    "manga": {
        "name": "MANGA",
        "prompt": (
            "Convert this photo into a Japanese manga panel illustration. "
            "Use clean black ink lines, screentone dot patterns for shading, "
            "and dramatic manga-style lighting with speed lines or effect lines. "
            "Add manga-typical sparkle or emphasis effects where appropriate. "
            "Preserve the subject's features in manga proportions with expressive eyes. "
            "Black and white only, like a printed manga page. "
            "Naturally suited for thermal printing with pure black and white contrast."
        ),
    },
    #"stencil": {
    #    "name": "STENCIL",
    #    "prompt": (
    #        "Transform this photo into a high-contrast stencil art style, similar to "
    #        "Banksy or Shepard Fairey street art. Reduce the image to 2-3 tonal layers "
    #        "with sharp cutoffs between light and dark. No gradients, only flat areas "
    #        "of black and white with maybe one mid-gray tone. Bold and graphic. "
    #        "Preserve the subject's recognizable silhouette and key facial features. "
    #        "Extremely well suited for thermal printer output with stark contrast."
    #    ),
    #},
    #"oil_painting": {
    #    "name": "OLEO",
    #    "prompt": (
    #        "Transform this photo into a classical oil painting with visible brushstrokes "
    #        "and rich texture. Use an impressionist approach with dabs of varied tones. "
    #        "Keep the overall palette lighter to avoid large dark areas. "
    #        "Emphasize light falling on the subject with a warm, painterly glow. "
    #        "Preserve the subject's likeness and expression with artistic brushwork. "
    #        "The textured brushstrokes will create interesting patterns when dithered "
    #        "for thermal printing."
    #    ),
    #},
}


# ---------------------------------------------------------------------------
# ComfyUI HTTP helpers
# ---------------------------------------------------------------------------

def upload_image(filepath: str, subfolder: str = "", image_type: str = "input") -> dict:
    """Upload an image to ComfyUI."""
    with open(filepath, "rb") as f:
        image_data = f.read()

    filename = filepath.replace("\\", "/").split("/")[-1]
    boundary = "----WebKitFormBoundary" + uuid.uuid4().hex[:16]

    body = []
    body.append(f"--{boundary}".encode())
    body.append(f'Content-Disposition: form-data; name="image"; filename="{filename}"'.encode())
    body.append(b"Content-Type: image/jpeg")
    body.append(b"")
    body.append(image_data)

    if subfolder:
        body.append(f"--{boundary}".encode())
        body.append(b'Content-Disposition: form-data; name="subfolder"')
        body.append(b"")
        body.append(subfolder.encode())

    body.append(f"--{boundary}".encode())
    body.append(b'Content-Disposition: form-data; name="type"')
    body.append(b"")
    body.append(image_type.encode())

    body.append(f"--{boundary}--".encode())

    body_bytes = b"\r\n".join(body)

    req = urllib.request.Request(
        f"http://{COMFYUI_URL}/upload/image",
        data=body_bytes,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}
    )

    with urllib.request.urlopen(req) as response:
        return json.loads(response.read())


def queue_prompt(prompt: dict, client_id: str) -> dict:
    """Queue a prompt for execution."""
    data = json.dumps({"prompt": prompt, "client_id": client_id}).encode("utf-8")
    req = urllib.request.Request(
        f"http://{COMFYUI_URL}/prompt",
        data=data,
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as response:
        return json.loads(response.read())


def get_image(filename: str, subfolder: str, folder_type: str) -> bytes:
    """Download an image from ComfyUI."""
    params = urllib.parse.urlencode({"filename": filename, "subfolder": subfolder, "type": folder_type})
    with urllib.request.urlopen(f"http://{COMFYUI_URL}/view?{params}") as response:
        return response.read()


def get_history(prompt_id: str) -> dict:
    """Get the history for a prompt."""
    with urllib.request.urlopen(f"http://{COMFYUI_URL}/history/{prompt_id}") as response:
        return json.loads(response.read())


def load_workflow(workflow_path: str) -> dict:
    """Load a workflow JSON file."""
    with open(workflow_path, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Workflow mutation helpers
# ---------------------------------------------------------------------------

def find_and_update_load_image_node(workflow: dict, new_image_name: str) -> dict:
    """Find LoadImage nodes in the workflow and update the image name."""
    for node_id, node in workflow.items():
        class_type = node.get("class_type", "")
        if "LoadImage" in class_type or "Cargar" in class_type.lower():
            if "inputs" in node and "image" in node["inputs"]:
                print(f"  Found image loader node [{node_id}]: {class_type}")
                node["inputs"]["image"] = new_image_name
    return workflow


def randomize_seeds(workflow: dict) -> dict:
    """Randomize seed values in noise/sampler nodes for varied outputs."""
    for node_id, node in workflow.items():
        class_type = node.get("class_type", "")
        inputs = node.get("inputs", {})

        if class_type == "RandomNoise" and "noise_seed" in inputs:
            new_seed = random.randint(0, 2**63 - 1)
            print(f"  Randomized noise_seed in [{node_id}] {class_type}: {new_seed}")
            node["inputs"]["noise_seed"] = new_seed
        elif ("Sampler" in class_type or "sampler" in class_type.lower()) and "seed" in inputs:
            new_seed = random.randint(0, 2**63 - 1)
            print(f"  Randomized seed in [{node_id}] {class_type}: {new_seed}")
            node["inputs"]["seed"] = new_seed
    return workflow


def replace_style_prompt(workflow: dict, prompt: str) -> dict:
    """Replace the text in CLIPTextEncode nodes that contain <STYLE> with the full prompt."""
    for node_id, node in workflow.items():
        class_type = node.get("class_type", "")
        if class_type == "CLIPTextEncode":
            inputs = node.get("inputs", {})
            if "text" in inputs and "<STYLE>" in inputs["text"]:
                node["inputs"]["text"] = prompt
                print(f"  Set prompt in [{node_id}]: '{prompt[:60]}...'")
    return workflow


def use_cached_conditioning(workflow: dict, style_id: str) -> dict:
    """Replace CLIPLoader + CLIPTextEncode with a LoadConditioning node.

    Removes nodes 75:71 (CLIPLoader) and 75:74 (CLIPTextEncode) and inserts a
    LoadConditioning node that reads the pre-computed tensor from disk.  All
    downstream references to node 75:74 are redirected to the new node.
    """
    workflow = copy.deepcopy(workflow)
    cache_path = os.path.join(CACHE_DIR, f"{style_id}.pt").replace("\\", "/")

    # Drop the CLIP loader and text encoder
    workflow.pop("75:71", None)
    workflow.pop("75:74", None)

    # Insert the cached conditioning loader
    workflow["75:cond"] = {
        "class_type": "LoadConditioning",
        "inputs": {"cache_path": cache_path},
        "_meta": {"title": "Load Cached Conditioning"},
    }

    # Redirect every input that referenced node 75:74 to the new node
    for node_id, node in workflow.items():
        if node_id == "75:cond":
            continue
        for key, val in node.get("inputs", {}).items():
            if isinstance(val, list) and len(val) == 2 and val[0] == "75:74":
                node["inputs"][key] = ["75:cond", 0]

    return workflow


def upload_image_bytes(image_data: bytes, filename: str) -> dict:
    """Upload image bytes to ComfyUI."""
    boundary = "----WebKitFormBoundary" + uuid.uuid4().hex[:16]

    body = []
    body.append(f"--{boundary}".encode())
    body.append(f'Content-Disposition: form-data; name="image"; filename="{filename}"'.encode())
    body.append(b"Content-Type: image/png")
    body.append(b"")
    body.append(image_data)

    body.append(f"--{boundary}".encode())
    body.append(b'Content-Disposition: form-data; name="type"')
    body.append(b"")
    body.append(b"input")

    body.append(f"--{boundary}--".encode())

    body_bytes = b"\r\n".join(body)

    req = urllib.request.Request(
        f"http://{COMFYUI_URL}/upload/image",
        data=body_bytes,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}
    )

    with urllib.request.urlopen(req) as response:
        return json.loads(response.read())


# ---------------------------------------------------------------------------
# Pre-computation helpers
# ---------------------------------------------------------------------------

def wait_for_comfyui(timeout: int = 120):
    """Block until ComfyUI responds, or raise after timeout seconds."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(
                f"http://{COMFYUI_URL}/system_stats", timeout=2
            ) as r:
                if r.status == 200:
                    print("[Precompute] ComfyUI is ready.")
                    return
        except Exception:
            pass
        print("[Precompute] Waiting for ComfyUI to start...")
        time.sleep(2)
    raise RuntimeError(f"ComfyUI not reachable at {COMFYUI_URL} after {timeout}s")


def free_comfyui_memory():
    """Ask ComfyUI to unload all models from memory."""
    try:
        data = json.dumps({"unload_models": True, "free_memory": True}).encode("utf-8")
        req = urllib.request.Request(
            f"http://{COMFYUI_URL}/free",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req):
            print("[Precompute] ComfyUI memory freed.")
    except Exception as e:
        print(f"[Precompute] Warning: could not free ComfyUI memory: {e}")


def build_precompute_workflow(prompt: str, cache_path: str) -> dict:
    """Build a minimal workflow: CLIPLoader → CLIPTextEncode → SaveConditioning."""
    return {
        "p_clip": {
            "class_type": "CLIPLoader",
            "inputs": {
                "clip_name": "qwen_3_4b.safetensors",
                "type": "flux2",
                "device": "cpu",
            },
        },
        "p_encode": {
            "class_type": "CLIPTextEncode",
            "inputs": {
                "text": prompt,
                "clip": ["p_clip", 0],
            },
        },
        "p_save": {
            "class_type": "SaveConditioning",
            "inputs": {
                "conditioning": ["p_encode", 0],
                "cache_path": cache_path.replace("\\", "/"),
            },
        },
    }


def wait_for_prompt(prompt_id: str):
    """Poll ComfyUI history until the given prompt has finished executing."""
    while True:
        history = get_history(prompt_id)
        if prompt_id in history:
            return
        time.sleep(0.5)


def precompute_embeddings():
    """Pre-compute and cache CLIP conditioning tensors for all styles.

    Skipped entirely if all cache files already exist.  After writing the last
    file, asks ComfyUI to unload models so the Qwen CLIP model is freed from
    memory before any inference request arrives.
    """
    os.makedirs(CACHE_DIR, exist_ok=True)

    missing = [
        sid for sid in STYLES
        if not os.path.exists(os.path.join(CACHE_DIR, f"{sid}.pt"))
    ]

    if not missing:
        print(f"[Precompute] All {len(STYLES)} conditioning caches present. Skipping.")
        return

    print(f"[Precompute] Need to compute {len(missing)} embedding(s): {missing}")
    wait_for_comfyui()

    client_id = str(uuid.uuid4())
    for style_id in missing:
        prompt = STYLES[style_id]["prompt"]
        cache_path = os.path.join(CACHE_DIR, f"{style_id}.pt")

        print(f"[Precompute] Encoding style '{style_id}'...")
        workflow = build_precompute_workflow(prompt, cache_path)
        result = queue_prompt(workflow, client_id)
        wait_for_prompt(result["prompt_id"])
        print(f"[Precompute] Saved: {cache_path}")

    free_comfyui_memory()
    print("[Precompute] Done. CLIP model unloaded from memory.")


# ---------------------------------------------------------------------------
# Core inference
# ---------------------------------------------------------------------------

def process_image(image_data: bytes, style_id: str) -> tuple[bytes, str]:
    """Process an image through ComfyUI and return the result bytes and output path."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    client_id = str(uuid.uuid4())
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    output_path = os.path.join(OUTPUT_DIR, f"output_{timestamp}.png")

    print("Loading workflow from", WORKFLOW_FILE)
    workflow = load_workflow(WORKFLOW_FILE)

    print("Uploading image...")
    upload_result = upload_image_bytes(image_data, f"input_{timestamp}.png")
    input_image_name = upload_result["name"]
    print(f"Uploaded as: {input_image_name}")

    workflow = find_and_update_load_image_node(workflow, input_image_name)

    cache_path = os.path.join(CACHE_DIR, f"{style_id}.pt")
    if os.path.exists(cache_path):
        print(f"Using cached conditioning for style '{style_id}'")
        workflow = use_cached_conditioning(workflow, style_id)
    else:
        print(f"Cache missing for '{style_id}', falling back to full CLIP encoding")
        workflow = replace_style_prompt(workflow, STYLES[style_id]["prompt"])

    print("Randomizing seeds...")
    workflow = randomize_seeds(workflow)

    print("Queueing workflow...")
    result = queue_prompt(workflow, client_id)
    prompt_id = result["prompt_id"]
    print(f"Prompt ID: {prompt_id}")

    print("Processing...")
    wait_for_prompt(prompt_id)

    print("Fetching output...")
    history = get_history(prompt_id)

    if prompt_id in history:
        outputs = history[prompt_id]["outputs"]
        for _, node_output in outputs.items():
            if "images" in node_output:
                for img_info in node_output["images"]:
                    result_data = get_image(
                        img_info["filename"],
                        img_info.get("subfolder", ""),
                        img_info["type"]
                    )
                    image = Image.open(io.BytesIO(result_data))
                    image.save(output_path)
                    print(f"Saved output to: {output_path}")
                    return result_data, output_path

    raise Exception("No output images found!")


# ---------------------------------------------------------------------------
# Flask endpoints
# ---------------------------------------------------------------------------

@app.route("/styles", methods=["GET"])
def styles_endpoint():
    """Return the list of available styles with their IDs and display names."""
    styles_list = [{"id": sid, "name": s["name"]} for sid, s in STYLES.items()]
    return jsonify(styles_list)


@app.route("/process", methods=["POST"])
def process_endpoint():
    """Accept an image and a style ID, return the processed result."""
    if "image" not in request.files:
        return jsonify({"error": "No image file provided"}), 400

    file = request.files["image"]
    if file.filename == "":
        return jsonify({"error": "No file selected"}), 400

    style_id = request.form.get("style", "cartoon")
    print(f"Received style: {style_id}")

    if style_id not in STYLES:
        return jsonify({"error": f"Unknown style: {style_id}"}), 400

    try:
        image_data = file.read()
        result_data, output_path = process_image(image_data, style_id)

        return send_file(
            io.BytesIO(result_data),
            mimetype="image/png",
            as_attachment=False,
            download_name="result.png"
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    print("Starting ComfyUI img2img web server on http://127.0.0.1:5000")
    print(f"Available styles: {list(STYLES.keys())}")
    precompute_embeddings()
    print("GET /styles - list available styles")
    print("POST /process - process an image with a style")
    app.run(host="0.0.0.0", port=5000, debug=False)
