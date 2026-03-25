import os
import re
import threading
import tempfile
import urllib.request
import urllib.parse
from flask import Flask, request, jsonify, send_from_directory
from bs4 import BeautifulSoup
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

FORMAT_MAP = {
    "best":   "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best",
    "1080p":  "bestvideo[height<=1080][ext=mp4][vcodec^=avc1]+bestaudio[ext=m4a]/bestvideo[height<=1080][ext=mp4]+bestaudio/best[height<=1080]",
    "720p":   "bestvideo[height<=720][ext=mp4][vcodec^=avc1]+bestaudio[ext=m4a]/bestvideo[height<=720][ext=mp4]+bestaudio/best[height<=720]",
    "480p":   "bestvideo[height<=480][ext=mp4][vcodec^=avc1]+bestaudio[ext=m4a]/bestvideo[height<=480][ext=mp4]+bestaudio/best[height<=480]",
    "360p":   "bestvideo[height<=360][ext=mp4][vcodec^=avc1]+bestaudio[ext=m4a]/bestvideo[height<=360][ext=mp4]+bestaudio/best[height<=360]",
    "audio":  "bestaudio[ext=m4a]/bestaudio",
    "mobile": "bestvideo[height<=720][ext=mp4][vcodec^=avc1]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best[height<=720]",
}


def write_cookies_file(cookies_text: str) -> str:
    lines = cookies_text.strip().splitlines()
    if not any(line.startswith("# Netscape") for line in lines):
        lines.insert(0, "# Netscape HTTP Cookie File")
    content = "\n".join(lines) + "\n"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode="w", encoding="utf-8")
    tmp.write(content)
    tmp.close()
    return tmp.name


def sanitize(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "_", name).strip()


def is_direct_video_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    path = parsed.path.lower()
    return any(path.endswith(ext) for ext in (".mp4", ".mkv", ".webm", ".m3u8", ".ts", ".mov"))


def is_youtube_url(url: str) -> bool:
    return "youtube.com" in url or "youtu.be" in url


def friendly_error(err: str) -> str:
    e = err.lower()
    if "no video formats found" in e:
        return "Nenhum formato encontrado. Tente outra qualidade ou cole a URL .mp4 direta."
    if "sign in" in e or "login" in e or "private" in e:
        return "Acesso negado — cookie inválido, expirado ou vídeo privado."
    if "unsupported url" in e:
        return "URL não suportada pelo yt-dlp."
    if "ffmpeg" in e:
        return "ffmpeg não encontrado. Instale: https://ffmpeg.org/download.html"
    if "token" in e or "expired" in e or "403" in e:
        return "Token expirado. Recarregue a página do vídeo e tente novamente."
    if "http error 429" in e:
        return "YouTube bloqueou temporariamente (muitas requisições). Aguarde alguns minutos."
    if "video unavailable" in e:
        return "Vídeo indisponível ou removido."
    if "age" in e and "restrict" in e:
        return "Vídeo com restrição de idade — necessário fornecer cookies com login."
    return err


def do_direct_download(download_id: str, url: str, filename_hint: str = "video.mp4", custom_name: str | None = None):
    progress_store[download_id] = {
        "status": "downloading", "percent": 0,
        "speed": "", "eta": "", "filename": "", "error": ""
    }
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
    headers = {"User-Agent": USER_AGENT, "Referer": "https://cursos.alura.com.br/"}
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            import time
            start = time.time()
            with open(dest, "wb") as f:
                while True:
                    buf = resp.read(65536)
                    if not buf:
                        break
                    f.write(buf)
                    downloaded += len(buf)
                    elapsed = time.time() - start or 0.001
                    speed = downloaded / elapsed
                    percent = int(downloaded / total * 100) if total else 0
                    def fmt_speed(s):
                        if s > 1_000_000: return f"{s/1_000_000:.1f} MB/s"
                        if s > 1_000: return f"{s/1_000:.0f} KB/s"
                        return f"{s:.0f} B/s"
                    eta = f"{int((total - downloaded) / speed)}s" if total and speed else ""
                    progress_store[download_id].update({
                        "status": "downloading", "percent": percent,
                        "speed": fmt_speed(speed), "eta": eta, "filename": base,
                    })
        progress_store[download_id].update({"status": "done", "percent": 100, "filename": base, "title": base})
    except Exception as e:
        err = str(e)
        if "403" in err or "401" in err: err = "Token expirado (403). Recarregue a página."
        elif "404" in err: err = "Arquivo não encontrado (404)."
        progress_store[download_id].update({"status": "error", "error": err})


def build_opts(quality: str, cookies_path: str | None, progress_hook=None, skip_download: bool = False) -> dict:
    opts = {
        "format": FORMAT_MAP.get(quality, FORMAT_MAP["best"]),
        "outtmpl": os.path.join(DOWNLOAD_DIR, "%(title)s.%(ext)s"),
        "quiet": True, "no_warnings": True,
        "merge_output_format": "mp4",
        "skip_download": skip_download,
        "http_headers": {
            "User-Agent": USER_AGENT,
            "Referer": "https://www.youtube.com/",
            "Accept-Language": "en-US,en;q=0.9",
        },
        "check_formats": False,
        "writesubtitles": False,
        "writeautomaticsub": False,
        "retries": 5,
        "fragment_retries": 5,
    }
    if progress_hook:
        opts["progress_hooks"] = [progress_hook]
    if quality == "audio":
        opts["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}]
    if quality == "mobile":
        opts["postprocessors"] = [{"key": "FFmpegVideoConvertor", "preferedformat": "mp4"}]
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
            opts["outtmpl"] = os.path.join(DOWNLOAD_DIR, f"{sanitize(custom_name)}.%(ext)s")
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
                "resolution": info.get("resolution", ""),
                "vcodec": info.get("vcodec", ""),
                "acodec": info.get("acodec", ""),
            })
    except Exception as e:
        progress_store[download_id].update({"status": "error", "error": friendly_error(str(e))})


def do_download(download_id: str, url: str, quality: str, cookies: str | None, custom_name: str | None = None):
    progress_store[download_id] = {"status": "starting", "percent": 0, "filename": "", "error": ""}
    cookies_path = write_cookies_file(cookies) if cookies else None
    try:
        if is_direct_video_url(url):
            do_direct_download(download_id, url, custom_name=custom_name)
        else:
            do_yt_dlp_download(download_id, url, quality, cookies_path, custom_name=custom_name)
    finally:
        if cookies_path:
            try: os.remove(cookies_path)
            except: pass


# ─── Rotas ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(".", "index.html")


@app.route("/api/download", methods=["POST"])
def start_download():
    data = request.get_json()
    url = data.get("url", "").strip()
    quality = data.get("quality", "best")
    cookies = data.get("cookies", "").strip() or None
    custom_name = data.get("custom_name", "").strip() or None
    if not url:
        return jsonify({"error": "URL é obrigatória"}), 400
    if quality not in FORMAT_MAP:
        quality = "best"
    import uuid
    download_id = str(uuid.uuid4())[:8]
    threading.Thread(
        target=do_download,
        args=(download_id, url, quality, cookies, custom_name),
        daemon=True
    ).start()
    return jsonify({"download_id": download_id, "mode": "direct" if is_direct_video_url(url) else "yt-dlp", "is_youtube": is_youtube_url(url)})


@app.route("/api/playlist", methods=["POST"])
def extract_playlist():
    data = request.get_json()
    url = data.get("url", "").strip()
    cookies = data.get("cookies", "").strip() or None
    if not url:
        return jsonify({"error": "URL é obrigatória"}), 400
    cookies_path = write_cookies_file(cookies) if cookies else None
    try:
        opts = {
            "quiet": True, "no_warnings": True,
            "extract_flat": "in_playlist",
            "http_headers": {"User-Agent": USER_AGENT, "Referer": "https://www.youtube.com/"},
        }
        if cookies_path:
            opts["cookiefile"] = cookies_path
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            entries_raw = info.get("entries", [info])
            course_title = info.get("title", "Playlist")
            entries = []
            for idx, e in enumerate(entries_raw):
                if not e: continue
                e_url = e.get("url") or e.get("webpage_url") or ""
                if e_url and not e_url.startswith("http"):
                    e_url = f"https://www.youtube.com/watch?v={e_url}"
                safe_title = sanitize(e.get("title", f"Video {idx+1}"))
                entries.append({"title": f"{(idx+1):02d} - {safe_title}", "url": e_url, "duration": e.get("duration_string", ""), "thumbnail": e.get("thumbnail", "")})
            return jsonify({"title": course_title, "entries": entries})
    except Exception as e:
        return jsonify({"error": friendly_error(str(e))}), 400
    finally:
        if cookies_path:
            try: os.remove(cookies_path)
            except: pass


@app.route("/api/extract-mp4", methods=["POST"])
def extract_mp4():
    """
    Busca o HTML da URL informada e extrai todos os links de vídeo encontrados.
    Parâmetros JSON:
      - url: URL da página a ser escaneada (obrigatório)
      - tag_filter: tag HTML para filtrar (opcional, ex: "video", "a", "source")
    Retorna:
      - page_title: título da página
      - videos: lista de { url, tag, attribute, format, label }
      - total_found: quantidade total
    """
    data = request.get_json()
    page_url = data.get("url", "").strip()
    tag_filter = data.get("tag_filter", "").strip().lower() or None

    if not page_url:
        return jsonify({"error": "URL é obrigatória"}), 400

    # Atributos HTML que podem conter links de vídeo
    VIDEO_ATTRS = ["src", "data-src", "data-video", "data-video-url", "data-file", "href", "content"]
    VIDEO_EXTS = re.compile(r'\.(mp4|webm|m3u8|mov|mkv)(\?[^"'\s]*)?', re.IGNORECASE)
    # Regex para encontrar URLs de vídeo mesmo dentro de JSON/JS inline
    URL_PATTERN = re.compile(r'https?://[^\s"'<>]+\.(?:mp4|webm|m3u8|mov|mkv)(?:\?[^\s"'<>]*)?', re.IGNORECASE)

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    }

    try:
        req = urllib.request.Request(page_url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return jsonify({"error": f"Não foi possível acessar a página: {str(e)}"}), 400

    soup = BeautifulSoup(html, "html.parser")
    page_title = soup.title.string.strip() if soup.title and soup.title.string else page_url

    found = {}  # url -> info dict (para deduplicar)

    def add_video(url, tag, attribute, label=""):
        url = url.strip().split(" ")[0]
        if not url.startswith("http"):
            # Resolve URL relativa
            url = urllib.parse.urljoin(page_url, url)
        if url in found:
            return
        m = re.search(r'\.(mp4|webm|m3u8|mov|mkv)', url, re.IGNORECASE)
        fmt = m.group(1).lower() if m else "mp4"
        found[url] = {"url": url, "tag": tag, "attribute": attribute, "format": fmt, "label": label}

    # Tags a escanear
    tags_to_scan = [tag_filter] if tag_filter else ["video", "source", "a", "iframe", "object", "embed"]

    for tag_name in tags_to_scan:
        for el in soup.find_all(tag_name):
            label = el.get("title") or el.get("alt") or el.get_text(strip=True)[:60] or ""
            for attr in VIDEO_ATTRS:
                val = el.get(attr, "")
                if val and VIDEO_EXTS.search(val):
                    add_video(val, tag_name, attr, label)

    # Scan em divs/spans com data-* attributes (se não tiver tag_filter ou se for "div")
    if not tag_filter or tag_filter in ("div", "span"):
        for el in soup.find_all(True):
            for attr, val in el.attrs.items():
                if isinstance(val, str) and attr.startswith("data-") and VIDEO_EXTS.search(val):
                    add_video(val, el.name, attr, "")

    # Varredura extra: URLs de vídeo dentro de <script> e JSON inline
    if not tag_filter or tag_filter == "script":
        for script in soup.find_all("script"):
            if script.string:
                for match in URL_PATTERN.finditer(script.string):
                    add_video(match.group(0), "script", "inline", "")

    videos = list(found.values())
    return jsonify({"page_title": page_title, "videos": videos, "total_found": len(videos)})


@app.route("/api/info", methods=["POST"])
def get_info():
    data = request.get_json()
    url = data.get("url", "").strip()
    cookies = data.get("cookies", "").strip() or None
    if not url:
        return jsonify({"error": "URL é obrigatória"}), 400
    if is_direct_video_url(url):
        path = urllib.parse.urlparse(url).path
        return jsonify({"title": os.path.basename(path).split("?")[0], "uploader": "URL direta", "direct": True, "is_youtube": False})
    cookies_path = write_cookies_file(cookies) if cookies else None
    try:
        opts = build_opts("best", cookies_path, skip_download=True)
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            formats = info.get("formats", [])
            resolutions = sorted(set(f.get("height") for f in formats if f.get("height") and f.get("vcodec") != "none"), reverse=True)
            return jsonify({
                "title": info.get("title", ""),
                "thumbnail": info.get("thumbnail", ""),
                "duration": info.get("duration_string", ""),
                "uploader": info.get("uploader", ""),
                "is_youtube": is_youtube_url(url),
                "resolutions": resolutions[:6],
            })
    except Exception as e:
        return jsonify({"error": friendly_error(str(e))}), 400
    finally:
        if cookies_path:
            try: os.remove(cookies_path)
            except: pass


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
        if f.endswith((".mp4", ".mp3", ".webm", ".mkv", ".m4a")):
            path = os.path.join(DOWNLOAD_DIR, f)
            files.append({"name": f, "size": os.path.getsize(path), "modified": os.path.getmtime(path)})
    files.sort(key=lambda x: x["modified"], reverse=True)
    return jsonify(files)


@app.route("/api/delete/<filename>", methods=["DELETE"])
def delete_file(filename):
    path = os.path.join(DOWNLOAD_DIR, filename)
    if not os.path.abspath(path).startswith(os.path.abspath(DOWNLOAD_DIR)):
        return jsonify({"error": "Caminho inválido"}), 400
    try:
        os.remove(path)
        return jsonify({"ok": True})
    except FileNotFoundError:
        return jsonify({"error": "Arquivo não encontrado"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    print("\n🎬 VideoGet rodando em http://localhost:5000\n")
    app.run(debug=False, port=5000)
