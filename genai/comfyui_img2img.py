"""
ComfyUI Image-to-Image Web Server
Exposes a single endpoint that accepts an image and returns the processed result.
"""

import json
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


def find_and_update_load_image_node(workflow: dict, new_image_name: str) -> dict:
    """Find LoadImage nodes in the workflow and update the image name."""
    for node_id, node in workflow.items():
        class_type = node.get("class_type", "")
        # Handle various load image node types
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

        # Handle RandomNoise nodes
        if class_type == "RandomNoise" and "noise_seed" in inputs:
            new_seed = random.randint(0, 2**63 - 1)
            print(f"  Randomized noise_seed in [{node_id}] {class_type}: {new_seed}")
            node["inputs"]["noise_seed"] = new_seed
        # Handle KSampler and similar sampler nodes as fallback
        elif ("Sampler" in class_type or "sampler" in class_type.lower()) and "seed" in inputs:
            new_seed = random.randint(0, 2**63 - 1)
            print(f"  Randomized seed in [{node_id}] {class_type}: {new_seed}")
            node["inputs"]["seed"] = new_seed
    return workflow


def replace_style_placeholder(workflow: dict, style: str) -> dict:
    """Replace <STYLE> placeholder in CLIPTextEncode nodes with the actual style."""
    for node_id, node in workflow.items():
        class_type = node.get("class_type", "")
        if class_type == "CLIPTextEncode":
            inputs = node.get("inputs", {})
            if "text" in inputs and "<STYLE>" in inputs["text"]:
                original_text = inputs["text"]
                new_text = original_text.replace("<STYLE>", style)
                node["inputs"]["text"] = new_text
                print(f"  Replaced <STYLE> in [{node_id}]: '{style}'")
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


def process_image(image_data: bytes, style: str = "cartoon") -> tuple[bytes, str]:
    """Process an image through ComfyUI and return the result bytes and output path."""
    import os
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    client_id = str(uuid.uuid4())
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    output_filename = f"output_{timestamp}.png"
    output_path = os.path.join(OUTPUT_DIR, output_filename)

    print("Loading workflow from", WORKFLOW_FILE)
    workflow = load_workflow(WORKFLOW_FILE)

    # Upload the input image
    print("Uploading image...")
    upload_result = upload_image_bytes(image_data, f"input_{timestamp}.png")
    input_image_name = upload_result["name"]
    print(f"Uploaded as: {input_image_name}")

    # Update the workflow to use our uploaded image
    print("Updating workflow with input image...")
    workflow = find_and_update_load_image_node(workflow, input_image_name)

    # Replace style placeholder
    print(f"Applying style: {style}")
    workflow = replace_style_placeholder(workflow, style)

    # Randomize seeds for varied outputs
    print("Randomizing seeds...")
    workflow = randomize_seeds(workflow)

    # Queue the prompt
    print("Queueing workflow...")
    result = queue_prompt(workflow, client_id)
    prompt_id = result["prompt_id"]
    print(f"Prompt ID: {prompt_id}")

    # Wait for completion by polling
    print("Processing...")
    while True:
        history = get_history(prompt_id)
        if prompt_id in history:
            break
        time.sleep(0.5)

    # Get the output images from history
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
                    # Save to disk with timestamp
                    image = Image.open(io.BytesIO(result_data))
                    image.save(output_path)
                    print(f"Saved output to: {output_path}")
                    return result_data, output_path

    raise Exception("No output images found!")


@app.route("/process", methods=["POST"])
def process_endpoint():
    """Accept an image and optional style parameter, return the processed result."""
    if "image" not in request.files:
        return jsonify({"error": "No image file provided"}), 400

    file = request.files["image"]
    if file.filename == "":
        return jsonify({"error": "No file selected"}), 400

    # Get style from form data, default to "cartoon"
    style = request.form.get("style", "cartoon")
    print(f"Received style: {style}")

    try:
        image_data = file.read()
        result_data, output_path = process_image(image_data, style)

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
    print("POST an image to /process endpoint")
    app.run(host="0.0.0.0", port=5000, debug=False)
