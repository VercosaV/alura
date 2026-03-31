import os
import re
import threading
import uuid
import shutil
from queue import Queue
from flask import Flask, request, jsonify, send_from_directory
import yt_dlp

from queue import Queue

MAX_DOWNLOADS = 3  # 🔥 limite simultâneo
download_queue = Queue()
active_downloads = 0

app = Flask(__name__, static_folder=".")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_ROOT = os.path.join(BASE_DIR, "downloads")
os.makedirs(DOWNLOAD_ROOT, exist_ok=True)

progress_store = {}
batch_store = {}

# 🔥 CONTROLE DE CONCORRÊNCIA
MAX_DOWNLOADS = 3
download_queue = Queue()

def sanitize(name):
    return re.sub(r'[\\/*?:"<>|]', "_", name)

# ─────────────────────────────
# 📥 DOWNLOAD
# ─────────────────────────────

def baixar_video(download_id, url, folder, custom_name):
    def hook(d):
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 1
            done = d.get("downloaded_bytes", 0)
            percent = int(done / total * 100)

            progress_store[download_id] = {
                "status": "downloading",
                "percent": percent,
                "speed": d.get("_speed_str", ""),
                "eta": d.get("_eta_str", "")
            }

        elif d["status"] == "finished":
            progress_store[download_id]["status"] = "processing"

    try:
        filename = sanitize(custom_name or "%(title)s")

        opts = {
            "format": "best",
            "outtmpl": os.path.join(folder, f"{filename}.%(ext)s"),
            "progress_hooks": [hook],
            "merge_output_format": "mp4",
            "quiet": True
        }

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            final_name = sanitize(custom_name or info.get("title", "video")) + ".mp4"

            progress_store[download_id] = {
                "status": "done",
                "percent": 100,
                "filename": final_name
            }

    except Exception as e:
        progress_store[download_id] = {
            "status": "error",
            "error": str(e)
        }

# ─────────────────────────────
# ⚙️ WORKER
# ─────────────────────────────

def worker():
    while True:
        download_id, url, folder, custom_name = download_queue.get()

        try:
            baixar_video(download_id, url, folder, custom_name)
        finally:
            download_queue.task_done()

# inicia workers
for _ in range(MAX_DOWNLOADS):
    threading.Thread(target=worker, daemon=True).start()

# ─────────────────────────────
# 🌐 ROTAS
# ─────────────────────────────

@app.route("/")
def index():
    return send_from_directory(".", "index.html")

@app.route("/api/start-batch", methods=["POST"])
def start_batch():
    data = request.get_json()
    folder_name = sanitize(data.get("folder") or f"batch_{uuid.uuid4().hex[:4]}")

    path = os.path.join(DOWNLOAD_ROOT, folder_name)
    os.makedirs(path, exist_ok=True)

    batch_store[folder_name] = path

    return jsonify({"batch_id": folder_name})

@app.route("/api/download", methods=["POST"])
def download():
    data = request.get_json()

    url = data.get("url")
    batch_id = data.get("batch_id")
    custom_name = data.get("custom_name")

    folder = batch_store.get(batch_id)

    if not folder:
        return jsonify({"error": "Batch inválido"}), 400

    download_id = uuid.uuid4().hex[:8]

    progress_store[download_id] = {
        "status": "queued",
        "percent": 0
    }

    download_queue.put((download_id, url, folder, custom_name))

    return jsonify({"download_id": download_id})

@app.route("/api/progress/<id>")
def progress(id):
    return jsonify(progress_store.get(id, {}))

@app.route("/api/list")
def list_files():
    files = []

    for root, dirs, filenames in os.walk(DOWNLOAD_ROOT):
        for f in filenames:
            path = os.path.join(root, f)
            files.append({
                "name": f,
                "size": os.path.getsize(path)
            })

    return jsonify(files)

@app.route("/api/file/<filename>")
def file(filename):
    for root, dirs, files in os.walk(DOWNLOAD_ROOT):
        if filename in files:
            return send_from_directory(root, filename, as_attachment=True)
    return "Não encontrado", 404

@app.route("/api/clear", methods=["POST"])
def clear():
    shutil.rmtree(DOWNLOAD_ROOT)
    os.makedirs(DOWNLOAD_ROOT)
    progress_store.clear()
    batch_store.clear()
    return jsonify({"ok": True})

# ─────────────────────────────

if __name__ == "__main__":
    print("🔥 VideoGet rodando em http://localhost:5000")
    app.run(debug=True)