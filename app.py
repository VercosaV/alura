import mimetypes
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

import yt_dlp
from flask import Flask, jsonify, request, send_from_directory

app = Flask(__name__, static_folder=".")
BASE_DIR = Path(__file__).resolve().parent
DOWNLOAD_DIR = BASE_DIR / "downloads"
DOWNLOAD_DIR.mkdir(exist_ok=True)
progress_store = {}
progress_lock = threading.Lock()
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".mov", ".m4v", ".avi"}
AUDIO_EXTENSIONS = {".mp3", ".m4a", ".wav", ".aac", ".flac", ".ogg", ".opus"}
MEDIA_EXTENSIONS = VIDEO_EXTENSIONS | AUDIO_EXTENSIONS


def sanitize(value: str, fallback: str = "video") -> str:
    value = re.sub(r'[\\/*?:"<>|\x00-\x1f]', "_", value).strip(" .")
    return value or fallback


def safe_folder(value: str | None) -> Path:
    """Resolve a user folder without allowing traversal outside downloads/."""
    raw = (value or "Geral").replace("\\", "/").strip(" /")
    parts = [sanitize(part, "Pasta") for part in raw.split("/") if part and part not in {".", ".."}]
    relative = Path(*parts) if parts else Path("Geral")
    target = (DOWNLOAD_DIR / relative).resolve()
    if target != DOWNLOAD_DIR.resolve() and DOWNLOAD_DIR.resolve() not in target.parents:
        raise ValueError("Pasta inválida")
    target.mkdir(parents=True, exist_ok=True)
    return target


def safe_media_path(relative: str) -> Path:
    path = (DOWNLOAD_DIR / (relative or "")).resolve()
    if DOWNLOAD_DIR.resolve() not in path.parents or not path.is_file():
        raise ValueError("Arquivo de mídia não encontrado")
    if path.suffix.lower() not in MEDIA_EXTENSIONS:
        raise ValueError("Formato de mídia não suportado")
    return path


def relative_name(path: Path) -> str:
    return path.resolve().relative_to(DOWNLOAD_DIR.resolve()).as_posix()


def is_direct_video_url(url: str) -> bool:
    path = urllib.parse.urlparse(url).path.lower()
    return any(path.endswith(ext) for ext in VIDEO_EXTENSIONS)


def write_cookies_file(cookies_text: str) -> str:
    lines = cookies_text.strip().splitlines()
    if not any(line.startswith("# Netscape") for line in lines):
        lines.insert(0, "# Netscape HTTP Cookie File")
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode="w", encoding="utf-8")
    tmp.write("\n".join(lines) + "\n")
    tmp.close()
    return tmp.name


def friendly_error(err: str) -> str:
    text = err.lower()
    if "no video formats found" in text:
        return "Nenhum formato encontrado. Para a Alura, cole a URL direta do .mp4."
    if any(word in text for word in ("sign in", "login", "private")):
        return "Acesso negado — cookie inválido, expirado ou conteúdo privado."
    if "unsupported url" in text:
        return "URL não suportada pelo yt-dlp."
    if "ffmpeg" in text:
        return "ffmpeg não encontrado. Instale-o e tente novamente."
    if any(code in text for code in ("token", "expired", "403", "401")):
        return "Token expirado ou acesso negado. Extraia uma nova URL direta."
    return err


def update_progress(download_id: str, **values):
    with progress_lock:
        progress_store.setdefault(download_id, {}).update(values)


def direct_filename(url: str, hint: str) -> str:
    path_name = Path(urllib.parse.urlparse(url).path).name
    candidate = path_name if path_name else sanitize(hint, "video.mp4")
    candidate = sanitize(candidate, "video.mp4")
    if Path(candidate).suffix.lower() not in MEDIA_EXTENSIONS:
        candidate += ".mp4"
    return candidate


def do_direct_download(download_id: str, url: str, folder: Path, filename_hint: str):
    name = direct_filename(url, filename_hint)
    destination = folder / name
    temporary = destination.with_suffix(destination.suffix + ".part")
    headers = {"User-Agent": USER_AGENT, "Referer": "https://cursos.alura.com.br/"}
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=60) as response, open(temporary, "wb") as output:
            total = int(response.headers.get("Content-Length", 0))
            downloaded = 0
            started = time.time()
            while chunk := response.read(1024 * 256):
                output.write(chunk)
                downloaded += len(chunk)
                elapsed = max(time.time() - started, 0.001)
                speed = downloaded / elapsed
                percent = int(downloaded / total * 100) if total else 0
                update_progress(download_id, status="downloading", percent=percent, current_percent=percent,
                                items_total=1, items_completed=0, current_item=1, speed=format_speed(speed),
                                eta=format_eta(total, downloaded, speed), filename=name)
        temporary.replace(destination)
        update_progress(download_id, status="done", percent=100, current_percent=100,
                        items_total=1, items_completed=1, current_item=1,
                        filename=relative_name(destination), title=Path(name).stem)
    except Exception as exc:
        temporary.unlink(missing_ok=True)
        update_progress(download_id, status="error", error=friendly_error(str(exc)))


def format_speed(speed: float) -> str:
    if speed > 1_000_000:
        return f"{speed / 1_000_000:.1f} MB/s"
    if speed > 1_000:
        return f"{speed / 1_000:.0f} KB/s"
    return f"{speed:.0f} B/s"


def format_eta(total: int, downloaded: int, speed: float) -> str:
    return f"{int((total - downloaded) / speed)}s" if total and speed else ""


def build_opts(quality: str, folder: Path, cookies_path: str | None, progress_hook=None, skip_download=False):
    formats = {
        "best": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best",
        "1080": "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
        "720": "bestvideo[height<=720]+bestaudio/best[height<=720]/best",
        "480": "bestvideo[height<=480]+bestaudio/best[height<=480]/best",
        "audio": "bestaudio",
    }
    options = {
        "format": formats.get(quality, formats["best"]),
        "outtmpl": str(folder / "%(title)s [%(id)s].%(ext)s"),
        "quiet": True, "no_warnings": True, "merge_output_format": "mp4",
        "noplaylist": False, "continuedl": True, "retries": 3, "fragment_retries": 3,
        "concurrent_fragment_downloads": 4, "skip_download": skip_download,
        "http_headers": {"User-Agent": USER_AGENT, "Referer": "https://cursos.alura.com.br/"},
        "check_formats": False,
    }
    if progress_hook:
        options["progress_hooks"] = [progress_hook]
    if quality == "audio":
        options["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}]
    if cookies_path:
        options["cookiefile"] = cookies_path
    return options


def do_yt_dlp_download(download_id: str, url: str, quality: str, folder: Path, cookies_path: str | None):
    state = {"items_total": 1, "items_completed": 0, "current_item": 1, "current_percent": 0}

    def progress_hook(data):
        info = data.get("info_dict") or {}
        item_index = int(info.get("playlist_index") or state["current_item"] or 1)
        total = int(info.get("playlist_count") or info.get("n_entries") or state["items_total"] or 1)
        state.update(items_total=max(total, item_index), current_item=item_index)
        if data["status"] == "downloading":
            total_bytes = data.get("total_bytes") or data.get("total_bytes_estimate") or 1
            item_percent = min(100, int(data.get("downloaded_bytes", 0) / total_bytes * 100))
            state["current_percent"] = item_percent
            aggregate = int(((item_index - 1) * 100 + item_percent) / state["items_total"])
            update_progress(download_id, status="downloading", percent=aggregate,
                            current_percent=item_percent, items_total=state["items_total"],
                            items_completed=item_index - 1, current_item=item_index,
                            speed=data.get("_speed_str", ""), eta=data.get("_eta_str", ""),
                            current_title=info.get("title", ""))
        elif data["status"] == "finished":
            state["items_completed"] = max(state["items_completed"], item_index)
            aggregate = int(state["items_completed"] * 100 / state["items_total"])
            filename = data.get("filename")
            update_progress(download_id, status="processing", percent=min(99, aggregate),
                            current_percent=100, items_total=state["items_total"],
                            items_completed=state["items_completed"], current_item=item_index,
                            filename=relative_name(Path(filename)) if filename else "",
                            current_title=info.get("title", ""))

    try:
        update_progress(download_id, status="starting", percent=0, current_percent=0,
                        items_total=1, items_completed=0, current_item=1)
        with yt_dlp.YoutubeDL(build_opts(quality, folder, cookies_path, progress_hook)) as ydl:
            info = ydl.extract_info(url, download=True)
        if info.get("_type") == "playlist":
            entries = [entry for entry in (info.get("entries") or []) if entry]
            state["items_total"] = max(state["items_total"], len(entries))
        title = sanitize(info.get("title", "video"))
        extension = "mp3" if quality == "audio" else "mp4"
        matches = sorted(folder.glob(f"{title}*"), key=lambda path: path.stat().st_mtime, reverse=True)
        filename = relative_name(matches[0]) if matches else f"{folder.name}/{title}.{extension}"
        update_progress(download_id, status="done", percent=100, current_percent=100,
                        items_total=state["items_total"], items_completed=state["items_total"],
                        current_item=state["items_total"], filename=filename,
                        title=info.get("title", title), thumbnail=info.get("thumbnail", ""),
                        duration=info.get("duration_string", ""))
    except Exception as exc:
        update_progress(download_id, status="error", error=friendly_error(str(exc)))


def do_download(download_id: str, url: str, quality: str, cookies: str | None, folder_name: str, filename_hint: str):
    update_progress(download_id, status="starting", percent=0, current_percent=0,
                    items_total=1, items_completed=0, current_item=1, filename="", error="")
    cookies_path = write_cookies_file(cookies) if cookies else None
    try:
        folder = safe_folder(folder_name)
        if is_direct_video_url(url):
            do_direct_download(download_id, url, folder, filename_hint)
        else:
            do_yt_dlp_download(download_id, url, quality, folder, cookies_path)
    finally:
        if cookies_path:
            os.unlink(cookies_path) if os.path.exists(cookies_path) else None


def unique_output(source: Path, extension: str) -> Path:
    candidate = source.with_suffix(f".{extension}")
    if candidate.resolve() == source.resolve() or candidate.exists():
        candidate = source.with_name(f"{source.stem} (áudio).{extension}")
    counter = 2
    while candidate.exists():
        candidate = source.with_name(f"{source.stem} (áudio {counter}).{extension}")
        counter += 1
    return candidate


def do_convert(convert_id: str, source: Path, target: Path, audio_format: str):
    update_progress(convert_id, status="processing", percent=5, source=relative_name(source),
                    filename=relative_name(target), audio_format=audio_format)
    codec_args = {
        "mp3": ["-vn", "-codec:a", "libmp3lame", "-b:a", "192k"],
        "m4a": ["-vn", "-codec:a", "aac", "-b:a", "192k"],
        "wav": ["-vn", "-codec:a", "pcm_s16le"],
    }
    try:
        command = ["ffmpeg", "-y", "-i", str(source), *codec_args[audio_format], str(target)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=3600)
        if result.returncode:
            raise RuntimeError(result.stderr[-1200:] or "Falha ao converter o arquivo")
        update_progress(convert_id, status="done", percent=100, filename=relative_name(target),
                        title=target.stem, source=relative_name(source))
    except Exception as exc:
        target.unlink(missing_ok=True)
        update_progress(convert_id, status="error", error=friendly_error(str(exc)))


@app.route("/")
def index():
    return send_from_directory(BASE_DIR, "index.html")


@app.post("/api/download")
def start_download():
    data = request.get_json(silent=True) or {}
    url = data.get("url", "").strip()
    if not url:
        return jsonify(error="URL é obrigatória"), 400
    try:
        safe_folder(data.get("folder"))
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    download_id = uuid.uuid4().hex[:8]
    threading.Thread(target=do_download, args=(download_id, url, data.get("quality", "best"),
                                                data.get("cookies", "").strip() or None,
                                                data.get("folder", "Geral"), data.get("filename", "video.mp4")), daemon=True).start()
    return jsonify(download_id=download_id, mode="direct" if is_direct_video_url(url) else "yt-dlp")


@app.get("/api/progress/<download_id>")
def get_progress(download_id):
    with progress_lock:
        return jsonify(progress_store.get(download_id, {"status": "not_found"}))


@app.post("/api/convert")
def convert_media():
    data = request.get_json(silent=True) or {}
    audio_format = (data.get("format") or "mp3").lower()
    if audio_format not in {"mp3", "m4a", "wav"}:
        return jsonify(error="Formato de áudio inválido"), 400
    try:
        source = safe_media_path(data.get("path", ""))
        if source.suffix.lower() in AUDIO_EXTENSIONS:
            return jsonify(error="Este arquivo já é um áudio"), 400
        target = unique_output(source, audio_format)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    convert_id = uuid.uuid4().hex[:8]
    with progress_lock:
        progress_store[convert_id] = {"status": "starting", "percent": 0, "items_total": 1, "items_completed": 0}
    threading.Thread(target=do_convert, args=(convert_id, source, target, audio_format), daemon=True).start()
    return jsonify(convert_id=convert_id, source=relative_name(source), target=relative_name(target))


@app.get("/api/list")
def list_downloads():
    files = []
    for path in DOWNLOAD_DIR.rglob("*"):
        if path.is_file() and path.suffix.lower() in MEDIA_EXTENSIONS:
            stat = path.stat()
            is_audio = path.suffix.lower() in AUDIO_EXTENSIONS
            files.append({"name": path.name, "path": relative_name(path),
                          "folder": str(path.parent.relative_to(DOWNLOAD_DIR)).replace(os.sep, "/") if path.parent != DOWNLOAD_DIR else "Geral",
                          "size": stat.st_size, "modified": stat.st_mtime, "kind": "audio" if is_audio else "video",
                          "stream_url": "/api/stream/" + urllib.parse.quote(relative_name(path), safe="/")})
    files.sort(key=lambda item: item["modified"], reverse=True)
    return jsonify(files)


@app.get("/api/folders")
def list_folders():
    folders = {"Geral"}
    folders.update(str(path.relative_to(DOWNLOAD_DIR)).replace(os.sep, "/") for path in DOWNLOAD_DIR.rglob("*") if path.is_dir())
    return jsonify(sorted(folders, key=str.casefold))


@app.post("/api/folders")
def create_folder():
    try:
        folder = request.get_json(silent=True).get("name", "")
        safe_folder(folder)
        return jsonify(name=folder.strip(" /")), 201
    except (AttributeError, ValueError) as exc:
        return jsonify(error=str(exc) or "Nome de pasta inválido"), 400


@app.post("/api/move")
def move_file():
    data = request.get_json(silent=True) or {}
    relative = (data.get("path") or "").replace("\\", "/")
    source = (DOWNLOAD_DIR / relative).resolve()
    try:
        if DOWNLOAD_DIR.resolve() not in source.parents or not source.is_file():
            raise ValueError("Arquivo não encontrado")
        target_folder = safe_folder(data.get("folder"))
        target = target_folder / source.name
        if target.exists() and target.resolve() != source:
            target = target_folder / f"{source.stem}-{uuid.uuid4().hex[:6]}{source.suffix}"
        shutil.move(str(source), str(target))
        return jsonify(path=relative_name(target))
    except (OSError, ValueError) as exc:
        return jsonify(error=str(exc)), 400


@app.get("/api/file/<path:filename>")
def download_file(filename):
    return send_from_directory(DOWNLOAD_DIR, filename, as_attachment=True, conditional=True)


@app.get("/api/stream/<path:filename>")
def stream_file(filename):
    response = send_from_directory(DOWNLOAD_DIR, filename, as_attachment=False, conditional=True)
    response.headers["Accept-Ranges"] = "bytes"
    return response


@app.post("/api/info")
def get_info():
    data = request.get_json(silent=True) or {}
    url = data.get("url", "").strip()
    if not url:
        return jsonify(error="URL é obrigatória"), 400
    if is_direct_video_url(url):
        return jsonify(title=Path(urllib.parse.urlparse(url).path).name or "Vídeo", direct=True)
    cookies_path = write_cookies_file(data.get("cookies", "").strip()) if data.get("cookies", "").strip() else None
    try:
        with yt_dlp.YoutubeDL(build_opts("best", DOWNLOAD_DIR, cookies_path, skip_download=True)) as ydl:
            info = ydl.extract_info(url, download=False)
        return jsonify(title=info.get("title", ""), thumbnail=info.get("thumbnail", ""), duration=info.get("duration_string", ""), uploader=info.get("uploader", ""), entries=len(info.get("entries") or []) if info.get("_type") == "playlist" else 1)
    except Exception as exc:
        return jsonify(error=friendly_error(str(exc))), 400
    finally:
        if cookies_path and os.path.exists(cookies_path):
            os.unlink(cookies_path)


if __name__ == "__main__":
    print("\nVideoGet rodando em http://localhost:5000\n")
    app.run(debug=False, host="0.0.0.0", port=5000)
