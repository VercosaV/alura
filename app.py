import os
import re
import threading
import tempfile
import urllib.request
import urllib.parse
import uuid
import shutil
from flask import Flask, request, jsonify, send_from_directory
import yt_dlp

app = Flask(__name__, static_folder=".")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 🔥 pasta raiz de downloads
DOWNLOAD_ROOT = os.path.join(BASE_DIR, "downloads")
os.makedirs(DOWNLOAD_ROOT, exist_ok=True)

progress_store = {}
batch_store = {}

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# ─────────────────────────────────────────────
# 🧠 Helpers
# ─────────────────────────────────────────────

def sanitize(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "_", name)

def create_batch_folder():
    batch_id = f"batch_{uuid.uuid4().hex[:6]}"
    path = os.path.join(DOWNLOAD_ROOT, batch_id)
    os.makedirs(path, exist_ok=True)
    batch_store[batch_id] = path
    return batch_id, path

def friendly_error(err: str) -> str:
    e = err.lower()
    if "ffmpeg" in e:
        return "FFmpeg não encontrado"
    if "403" in e or "token" in e:
        return "Token expirado — gere outro link"
    return err

def is_direct_video_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    return parsed.path.lower().endswith((".mp4", ".mkv", ".webm", ".mov"))

# ─────────────────────────────────────────────
# 📥 DOWNLOAD DIRETO
# ─────────────────────────────────────────────

def do_direct_download(download_id, url, folder, custom_name=None):
    try:
        filename = sanitize(custom_name or os.path.basename(url).split("?")[0] or "video.mp4")
        if not filename.endswith(".mp4"):
            filename += ".mp4"

        filepath = os.path.join(folder, filename)

        progress_store[download_id] = {"status": "downloading", "percent": 0}

        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req) as resp, open(filepath, "wb") as f:
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0

            while True:
                chunk = resp.read(8192)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)

                percent = int(downloaded / total * 100) if total else 0
                progress_store[download_id].update({
                    "percent": percent,
                    "filename": filename
                })

        progress_store[download_id]["status"] = "done"

    except Exception as e:
        progress_store[download_id] = {
            "status": "error",
            "error": friendly_error(str(e))
        }

# ─────────────────────────────────────────────
# 🎬 yt-dlp DOWNLOAD
# ─────────────────────────────────────────────

def do_yt_download(download_id, url, folder, quality, custom_name=None):
    def hook(d):
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 1
            downloaded = d.get("downloaded_bytes", 0)
            percent = int(downloaded / total * 100)

            progress_store[download_id].update({
                "status": "downloading",
                "percent": percent,
                "speed": d.get("_speed_str", ""),
                "eta": d.get("_eta_str", "")
            })

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
            "error": friendly_error(str(e))
        }

# ─────────────────────────────────────────────
# 🚀 DOWNLOAD CONTROLLER
# ─────────────────────────────────────────────

def start_download_thread(download_id, url, quality, batch_id, custom_name):
    folder = batch_store.get(batch_id)

    if not folder:
        progress_store[download_id] = {"status": "error", "error": "Batch inválido"}
        return

    if is_direct_video_url(url):
        do_direct_download(download_id, url, folder, custom_name)
    else:
        do_yt_download(download_id, url, folder, quality, custom_name)

# ─────────────────────────────────────────────
# 🌐 ROTAS
# ─────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(".", "index.html")

@app.route("/api/start-batch", methods=["POST"])
def start_batch():
    batch_id, path = create_batch_folder()
    return jsonify({"batch_id": batch_id})

@app.route("/api/download", methods=["POST"])
def download():
    data = request.get_json()

    url = data.get("url")
    quality = data.get("quality", "best")
    batch_id = data.get("batch_id")
    custom_name = data.get("custom_name")

    if not batch_id:
        return jsonify({"error": "Batch não informado"}), 400

    download_id = uuid.uuid4().hex[:8]

    threading.Thread(
        target=start_download_thread,
        args=(download_id, url, quality, batch_id, custom_name),
        daemon=True
    ).start()

    return jsonify({"download_id": download_id})

@app.route("/api/progress/<download_id>")
def progress(download_id):
    return jsonify(progress_store.get(download_id, {"status": "not_found"}))

@app.route("/api/list")
def list_files():
    all_files = []

    for batch_id, folder in batch_store.items():
        for f in os.listdir(folder):
            path = os.path.join(folder, f)
            all_files.append({
                "name": f,
                "size": os.path.getsize(path)
            })

    return jsonify(all_files)

@app.route("/api/file/<filename>")
def serve_file(filename):
    for folder in batch_store.values():
        path = os.path.join(folder, filename)
        if os.path.exists(path):
            return send_from_directory(folder, filename, as_attachment=True)

    return "Arquivo não encontrado", 404

@app.route("/api/clear", methods=["POST"])
def clear_downloads():
    shutil.rmtree(DOWNLOAD_ROOT)
    os.makedirs(DOWNLOAD_ROOT, exist_ok=True)
    batch_store.clear()
    progress_store.clear()
    return jsonify({"status": "ok"})

# ─────────────────────────────────────────────

if __name__ == "__main__":
    print("\n🔥 VideoGet TURBINADO rodando em http://localhost:5000\n")
    app.run(port=5000)