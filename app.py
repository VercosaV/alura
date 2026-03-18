import os
import re
import threading
import tempfile
import urllib.request
import urllib.parse
from flask import Flask, request, jsonify, send_from_directory, Response, stream_with_context
import yt_dlp

app = Flask(__name__, static_folder=".")

DOWNLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

progress_store = {}

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def write_cookies_file(cookies_text: str) -> str:
    lines = cookies_text.strip().splitlines()
    if not any(line.startswith("# Netscape") for line in lines):
        lines.insert(0, "# Netscape HTTP Cookie File")
    content = "\n".join(lines) + "\n"
    tmp = tempfile.NamedTemporaryFile(
        delete=False, suffix=".txt", mode="w", encoding="utf-8"
    )
    tmp.write(content)
    tmp.close()
    return tmp.name


def sanitize(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "_", name)


def is_direct_video_url(url: str) -> bool:
    """Check if the URL points directly to a video file (mp4, m3u8, etc.)"""
    parsed = urllib.parse.urlparse(url)
    path = parsed.path.lower()
    return any(path.endswith(ext) for ext in (".mp4", ".mkv", ".webm", ".m3u8", ".ts", ".mov"))


def friendly_error(err: str) -> str:
    e = err.lower()
    if "no video formats found" in e:
        return (
            "Nenhum formato encontrado via yt-dlp. "
            "Se você tem a URL direta do vídeo (.mp4), cole ela diretamente!"
        )
    if "sign in" in e or "login" in e or "private" in e:
        return "Acesso negado — cookie inválido ou expirado."
    if "unsupported url" in e:
        return "URL não suportada pelo yt-dlp. Tente extrair a URL direta do vídeo .mp4 no DevTools."
    if "ffmpeg" in e:
        return "ffmpeg não encontrado. Instale: https://ffmpeg.org/download.html"
    if "token" in e or "expired" in e or "403" in e:
        return "Token expirado. Extraia uma nova URL do vídeo — o token dura poucos minutos."
    return err


# ─── Direct download (for signed mp4 URLs like Alura) ────────────────────────

def do_direct_download(download_id: str, url: str, filename_hint: str = "video.mp4", custom_name: str | None = None):
    progress_store[download_id] = {
        "status": "downloading", "percent": 0,
        "speed": "", "eta": "", "filename": "", "error": ""
    }

    # Derive a filename
    if custom_name:
        base = sanitize(custom_name)
        if not base.endswith((".mp4", ".mkv", ".webm", ".mov", ".mp3")):
            base += ".mp4"
    else:
        path = urllib.parse.urlparse(url).path
        base = os.path.basename(path) or filename_hint
        base = base.split("?")[0]
        if not base.endswith((".mp4", ".mkv", ".webm", ".mov")):
            base += ".mp4"
        base = sanitize(base)
    dest = os.path.join(DOWNLOAD_DIR, base)

    headers = {
        "User-Agent": USER_AGENT,
        "Referer": "https://cursos.alura.com.br/",
    }

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            chunk = 65536  # 64 KB
            import time
            start = time.time()

            with open(dest, "wb") as f:
                while True:
                    buf = resp.read(chunk)
                    if not buf:
                        break
                    f.write(buf)
                    downloaded += len(buf)
                    elapsed = time.time() - start or 0.001
                    speed = downloaded / elapsed  # bytes/s
                    percent = int(downloaded / total * 100) if total else 0

                    def fmt_speed(s):
                        if s > 1_000_000: return f"{s/1_000_000:.1f} MB/s"
                        if s > 1_000: return f"{s/1_000:.0f} KB/s"
                        return f"{s:.0f} B/s"

                    eta = ""
                    if total and speed:
                        remaining = (total - downloaded) / speed
                        eta = f"{int(remaining)}s"

                    progress_store[download_id].update({
                        "status": "downloading",
                        "percent": percent,
                        "speed": fmt_speed(speed),
                        "eta": eta,
                        "filename": base,
                    })

        progress_store[download_id].update({
            "status": "done", "percent": 100,
            "filename": base, "title": base,
            "thumbnail": "", "duration": "",
        })
    except Exception as e:
        err = str(e)
        if "403" in err or "401" in err:
            err = "Token expirado (403). Extraia uma nova URL do vídeo — o token dura apenas alguns minutos."
        elif "404" in err:
            err = "Arquivo não encontrado (404). Verifique a URL."
        progress_store[download_id].update({"status": "error", "error": err})


# ─── yt-dlp download ──────────────────────────────────────────────────────────

def build_opts(quality: str, cookies_path: str | None,
               progress_hook=None, skip_download: bool = False) -> dict:
    format_map = {
        "best":  "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best",
        "1080":  "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
        "720":   "bestvideo[height<=720]+bestaudio/best[height<=720]/best",
        "480":   "bestvideo[height<=480]+bestaudio/best[height<=480]/best",
        "audio": "bestaudio",
    }
    opts = {
        "format": format_map.get(quality, format_map["best"]),
        "outtmpl": os.path.join(DOWNLOAD_DIR, "%(title)s.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "merge_output_format": "mp4",
        "skip_download": skip_download,
        "http_headers": {
            "User-Agent": USER_AGENT,
            "Referer": "https://cursos.alura.com.br/",
        },
        "check_formats": False,
    }
    if progress_hook:
        opts["progress_hooks"] = [progress_hook]
    if quality == "audio":
        opts["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }]
    if cookies_path:
        opts["cookiefile"] = cookies_path
    return opts


def do_yt_dlp_download(download_id: str, url: str, quality: str, cookies_path: str | None, custom_name: str | None = None):
    def progress_hook(d):
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 1
            downloaded = d.get("downloaded_bytes", 0)
            progress_store[download_id].update({
                "status": "downloading",
                "percent": int(downloaded / total * 100),
                "speed": d.get("_speed_str", ""),
                "eta": d.get("_eta_str", ""),
            })
        elif d["status"] == "finished":
            progress_store[download_id].update({
                "status": "processing", "percent": 99,
                "filename": os.path.basename(d["filename"]),
            })

    try:
        opts = build_opts(quality, cookies_path, progress_hook)
        if custom_name:
            safe = sanitize(custom_name)
            ext_token = "%(ext)s"
            opts["outtmpl"] = os.path.join(DOWNLOAD_DIR, f"{safe}.{ext_token}")
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = sanitize(custom_name or info.get("title", "video"))
            ext = "mp3" if quality == "audio" else "mp4"
            progress_store[download_id].update({
                "status": "done", "percent": 100,
                "filename": f"{title}.{ext}",
                "title": info.get("title", ""),
                "thumbnail": info.get("thumbnail", ""),
                "duration": info.get("duration_string", ""),
            })
    except Exception as e:
        progress_store[download_id].update({
            "status": "error",
            "error": friendly_error(str(e)),
        })


def do_download(download_id: str, url: str, quality: str, cookies: str | None, custom_name: str | None = None):
    progress_store[download_id] = {
        "status": "starting", "percent": 0, "filename": "", "error": ""
    }
    cookies_path = write_cookies_file(cookies) if cookies else None
    try:
        if is_direct_video_url(url):
            # Direct MP4/video URL — bypass yt-dlp
            do_direct_download(download_id, url, custom_name=custom_name)
        else:
            do_yt_dlp_download(download_id, url, quality, cookies_path, custom_name=custom_name)
    finally:
        if cookies_path:
            try: os.remove(cookies_path)
            except: pass


# ─── Routes ──────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(".", "index.html")


@app.route("/api/download", methods=["POST"])
def start_download():
    data = request.get_json()
    url = data.get("url", "").strip()
    quality = data.get("quality", "best")
    cookies     = data.get("cookies", "").strip() or None
    custom_name = data.get("custom_name", "").strip() or None
    if not url:
        return jsonify({"error": "URL é obrigatória"}), 400

    import uuid
    download_id = str(uuid.uuid4())[:8]
    threading.Thread(
        target=do_download, args=(download_id, url, quality, cookies, custom_name), daemon=True
    ).start()

    # Tell the frontend if it's a direct download
    return jsonify({
        "download_id": download_id,
        "mode": "direct" if is_direct_video_url(url) else "yt-dlp",
    })


@app.route("/api/progress/<download_id>")
def get_progress(download_id):
    return jsonify(progress_store.get(download_id, {"status": "not_found"}))


@app.route("/api/file/<filename>")
def serve_file(filename):
    return send_from_directory(DOWNLOAD_DIR, filename, as_attachment=True)


@app.route("/api/list")
def list_downloads():
    files = []
    for f in os.listdir(DOWNLOAD_DIR):
        if f.endswith((".mp4", ".mp3", ".webm", ".mkv")):
            path = os.path.join(DOWNLOAD_DIR, f)
            files.append({
                "name": f,
                "size": os.path.getsize(path),
                "modified": os.path.getmtime(path),
            })
    files.sort(key=lambda x: x["modified"], reverse=True)
    return jsonify(files)


@app.route("/api/info", methods=["POST"])
def get_info():
    data = request.get_json()
    url = data.get("url", "").strip()
    cookies = data.get("cookies", "").strip() or None
    if not url:
        return jsonify({"error": "URL é obrigatória"}), 400

    # For direct URLs just return basic info
    if is_direct_video_url(url):
        path = urllib.parse.urlparse(url).path
        return jsonify({
            "title": os.path.basename(path).split("?")[0],
            "thumbnail": "",
            "duration": "",
            "uploader": "URL direta",
            "direct": True,
        })

    cookies_path = write_cookies_file(cookies) if cookies else None
    try:
        opts = build_opts("best", cookies_path, skip_download=True)
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return jsonify({
                "title": info.get("title", ""),
                "thumbnail": info.get("thumbnail", ""),
                "duration": info.get("duration_string", ""),
                "uploader": info.get("uploader", ""),
                "formats_count": len(info.get("formats", [])),
                "extractor": info.get("extractor", ""),
            })
    except Exception as e:
        return jsonify({"error": friendly_error(str(e))}), 400
    finally:
        if cookies_path:
            try: os.remove(cookies_path)
            except: pass


if __name__ == "__main__":
    print("\n🎬  VideoGet rodando em http://localhost:5000\n")
    app.run(debug=False, port=5000)