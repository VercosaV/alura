import os
import re
import threading
import tempfile
import urllib.request
import urllib.parse
import uuid
from flask import Flask, request, jsonify, send_from_directory
import yt_dlp

app = Flask(__name__, static_folder=".")

DOWNLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Dicionário em memória que guarda o progresso de cada download pelo seu ID único.
# Estrutura: { "download_id": { "status": "...", "percent": 0, ... } }
progress_store = {}

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# ─── Formatos disponíveis para download ──────────────────────────────────────
# Cada chave representa uma opção de qualidade/formato.
# Os valores são strings de seleção de formato do yt-dlp.
# "bestvideo+bestaudio" = combina melhor vídeo com melhor áudio (requer ffmpeg para mesclar).
# "height<=720" = filtra por altura máxima de pixels.
# "ext=mp4" = prefere o contêiner MP4, que é amplamente compatível com celulares.
FORMAT_MAP = {
    # "Melhor" — sem restrição, pega o melhor disponível. Pode vir como webm.
    "best":   "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best",

    # Formatos específicos — forçamos MP4 com H.264 para máxima compatibilidade móvel.
    # O yt-dlp tentará primeiro "vcodec^=avc1" (H.264), que todos os celulares reproduzem.
    # Se não encontrar, cai para qualquer MP4 na resolução pedida.
    "1080p":  "bestvideo[height<=1080][ext=mp4][vcodec^=avc1]+bestaudio[ext=m4a]/bestvideo[height<=1080][ext=mp4]+bestaudio/best[height<=1080]",
    "720p":   "bestvideo[height<=720][ext=mp4][vcodec^=avc1]+bestaudio[ext=m4a]/bestvideo[height<=720][ext=mp4]+bestaudio/best[height<=720]",
    "480p":   "bestvideo[height<=480][ext=mp4][vcodec^=avc1]+bestaudio[ext=m4a]/bestvideo[height<=480][ext=mp4]+bestaudio/best[height<=480]",
    "360p":   "bestvideo[height<=360][ext=mp4][vcodec^=avc1]+bestaudio[ext=m4a]/bestvideo[height<=360][ext=mp4]+bestaudio/best[height<=360]",

    # Apenas áudio — extrai e converte para MP3 (192kbps), compatível com qualquer celular.
    "audio":  "bestaudio[ext=m4a]/bestaudio",

    # Modo "celular" — vídeo compacto e de alta compatibilidade (720p H.264 + AAC = padrão universal).
    # Ideal para enviar por WhatsApp ou reproduzir sem app externo.
    "mobile": "bestvideo[height<=720][ext=mp4][vcodec^=avc1]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best[height<=720]",
}


def write_cookies_file(cookies_text: str) -> str:
    """Grava o conteúdo de cookies em um arquivo temporário no formato Netscape."""
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
    """Remove caracteres inválidos de nomes de arquivo."""
    return re.sub(r'[\\/*?:"<>|]', "_", name).strip()


def is_direct_video_url(url: str) -> bool:
    """Verifica se a URL aponta diretamente para um arquivo de vídeo."""
    parsed = urllib.parse.urlparse(url)
    path = parsed.path.lower()
    return any(path.endswith(ext) for ext in (".mp4", ".mkv", ".webm", ".m3u8", ".ts", ".mov"))


def is_youtube_url(url: str) -> bool:
    """Detecta se a URL é do YouTube para aplicar otimizações específicas."""
    return "youtube.com" in url or "youtu.be" in url


def friendly_error(err: str) -> str:
    """Traduz mensagens de erro técnicas para português amigável."""
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


# ─── Download direto (URL .mp4) ───────────────────────────────────────────────

def do_direct_download(download_id: str, url: str, filename_hint: str = "video.mp4", custom_name: str | None = None):
    """Faz download de URLs diretas (.mp4, .mkv, etc) sem usar o yt-dlp."""
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

    headers = {
        "User-Agent": USER_AGENT,
        "Referer": "https://cursos.alura.com.br/",
    }

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            chunk = 65536
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
                    speed = downloaded / elapsed
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
                        "status": "downloading", "percent": percent,
                        "speed": fmt_speed(speed), "eta": eta, "filename": base,
                    })

        progress_store[download_id].update({
            "status": "done", "percent": 100,
            "filename": base, "title": base,
            "thumbnail": "", "duration": "",
        })
    except Exception as e:
        err = str(e)
        if "403" in err or "401" in err: err = "Token expirado (403). Recarregue a página."
        elif "404" in err: err = "Arquivo não encontrado (404)."
        progress_store[download_id].update({"status": "error", "error": err})


# ─── Download via yt-dlp ─────────────────────────────────────────────────────

def build_opts(quality: str, cookies_path: str | None, progress_hook=None, skip_download: bool = False) -> dict:
    """
    Constrói o dicionário de opções para o yt-dlp.
    
    Parâmetros-chave:
    - format: qual stream de vídeo/áudio selecionar (nossa FORMAT_MAP acima)
    - merge_output_format: garante que o arquivo final seja sempre .mp4
    - postprocessors: usado para converter para mp3 no modo áudio
    - http_headers: simula um browser real (evita bloqueio do YouTube)
    """
    opts = {
        "format": FORMAT_MAP.get(quality, FORMAT_MAP["best"]),
        "outtmpl": os.path.join(DOWNLOAD_DIR, "%(title)s.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        # merge_output_format: quando o yt-dlp baixa vídeo e áudio separados,
        # o ffmpeg os mescla. Aqui garantimos que o resultado seja sempre .mp4.
        "merge_output_format": "mp4",
        "skip_download": skip_download,
        "http_headers": {
            "User-Agent": USER_AGENT,
            "Referer": "https://www.youtube.com/",
            # Accept-Language: o YouTube tenta servir legendas/títulos no idioma do cliente.
            # Definimos como inglês para evitar nomes de arquivo com caracteres especiais.
            "Accept-Language": "en-US,en;q=0.9",
        },
        "check_formats": False,
        # writesubtitles / subtitleslangs: baixa legendas automáticas em pt/en se disponíveis.
        # São salvas como .vtt ao lado do vídeo, mas não embutidas no MP4 por padrão.
        "writesubtitles": False,
        "writeautomaticsub": False,
        # retries: tenta novamente em caso de falha de rede (útil com YouTube)
        "retries": 5,
        "fragment_retries": 5,
    }

    if progress_hook:
        opts["progress_hooks"] = [progress_hook]

    # Pós-processador de áudio: extrai o stream de áudio e converte para MP3.
    # preferredcodec=mp3 e preferredquality=192 = 192kbps, boa qualidade para celular.
    if quality == "audio":
        opts["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192"
        }]

    # Pós-processador do modo "mobile": re-encode com H.264 + AAC via ffmpeg.
    # Isso garante que o arquivo seja reproduzível em QUALQUER celular, mesmo que
    # o YouTube sirva o vídeo em VP9/Opus (que alguns dispositivos não suportam).
    if quality == "mobile":
        opts["postprocessors"] = [{
            "key": "FFmpegVideoConvertor",
            "preferedformat": "mp4",
        }]
        # ffmpeg_location: se o ffmpeg não estiver no PATH, pode especificar aqui.
        # opts["ffmpeg_location"] = "/usr/bin/ffmpeg"

    if cookies_path:
        opts["cookiefile"] = cookies_path

    return opts


def do_yt_dlp_download(download_id: str, url: str, quality: str, cookies_path: str | None, custom_name: str | None = None):
    """Executa o download usando yt-dlp com rastreamento de progresso em tempo real."""

    def progress_hook(d):
        """
        Callback chamado pelo yt-dlp em cada chunk baixado.
        d["status"] pode ser: "downloading", "finished", "error"
        """
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
            # "finished" significa que o chunk foi baixado, mas o ffmpeg ainda pode
            # estar processando (mesclando vídeo+áudio). Por isso colocamos "processing".
            progress_store[download_id].update({
                "status": "processing",
                "percent": 99,
                "filename": os.path.basename(d["filename"]),
            })

    try:
        opts = build_opts(quality, cookies_path, progress_hook)

        # Se o usuário passou um nome personalizado, substituímos o template de saída.
        # %(ext)s garante que a extensão correta (.mp4/.mp3) seja mantida.
        if custom_name:
            safe = sanitize(custom_name)
            opts["outtmpl"] = os.path.join(DOWNLOAD_DIR, f"{safe}.%(ext)s")

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = sanitize(custom_name or info.get("title", "video"))
            ext = "mp3" if quality == "audio" else "mp4"

            progress_store[download_id].update({
                "status": "done",
                "percent": 100,
                "filename": f"{title}.{ext}",
                "title": info.get("title", ""),
                "thumbnail": info.get("thumbnail", ""),
                "duration": info.get("duration_string", ""),
                # Informações extras para o frontend exibir
                "resolution": info.get("resolution", ""),
                "filesize": info.get("filesize_approx", 0),
                "vcodec": info.get("vcodec", ""),
                "acodec": info.get("acodec", ""),
            })
    except Exception as e:
        progress_store[download_id].update({
            "status": "error",
            "error": friendly_error(str(e))
        })


def do_download(download_id: str, url: str, quality: str, cookies: str | None, custom_name: str | None = None):
    """
    Ponto de entrada para todos os downloads. Decide entre download direto ou yt-dlp.
    É executada em uma thread separada para não bloquear o servidor Flask.
    """
    progress_store[download_id] = {
        "status": "starting", "percent": 0, "filename": "", "error": ""
    }
    cookies_path = write_cookies_file(cookies) if cookies else None
    try:
        if is_direct_video_url(url):
            do_direct_download(download_id, url, custom_name=custom_name)
        else:
            do_yt_dlp_download(download_id, url, quality, cookies_path, custom_name=custom_name)
    finally:
        # Sempre remove o arquivo temporário de cookies ao finalizar.
        if cookies_path:
            try:
                os.remove(cookies_path)
            except:
                pass


# ─── Rotas da API ─────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(".", "index.html")

@app.route('/api/download', methods=['POST'])
def api_download():
    data = request.get_json()
    
    url = data.get('url')
    quality = data.get('quality', 'best')
    custom_name = data.get('custom_name', '').strip()
    cookies = data.get('cookies', '').strip()
    
    # 1. Captura os NOVOS CAMPOS vindos do frontend
    folder_name = data.get('folder', '').strip()
    mp4_only = data.get('mp4_only', False)

    if not url:
        return jsonify({'error': 'URL não fornecida'}), 400

    # 2. Lógica para determinar a pasta destino
    # DOWNLOAD_DIR é a sua pasta de downloads padrão do projeto
    if folder_name:
        # Cria uma subpasta com o nome fornecido se ela não existir
        save_path = os.path.join(DOWNLOAD_DIR, folder_name)
        os.makedirs(save_path, exist_ok=True)
    else:
        # Se não escreverem nada, guarda na pasta de downloads normal
        save_path = DOWNLOAD_DIR

    # 3. Define o nome do arquivo (usando o nome customizado ou o título original)
    if custom_name:
        outtmpl = os.path.join(save_path, f"{custom_name}.%(ext)s")
    else:
        outtmpl = os.path.join(save_path, '%(title)s.%(ext)s')

    # 4. Configurações básicas do yt-dlp
    ydl_opts = {
        'outtmpl': outtmpl,
        'noplaylist': True, # Garante que baixa só o vídeo se for URL única
        'quiet': True,
    }

    # 5. Configuração da Qualidade (Mantendo a sua lógica original)
    if quality == 'mobile':
        ydl_opts['format'] = 'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]'
    elif quality == 'audio':
        ydl_opts['format'] = 'bestaudio/best'
        ydl_opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }]
    elif quality != 'best':
        # ex: 1080p, 720p...
        height = quality.replace('p', '')
        ydl_opts['format'] = f'bestvideo[height<={height}]+bestaudio/best[height<={height}]'

    # 6. FORÇAR MP4 (Substitui a regra acima se a caixa estiver marcada e não for só áudio)
    if mp4_only and quality != 'audio':
        # Mesmo escolhendo 1080p, ele vai forçar o formato de saída para MP4
        if quality == 'best':
             ydl_opts['format'] = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
        ydl_opts['merge_output_format'] = 'mp4'

    # Adiciona os cookies se houver (para Alura, vídeos privados, etc)
    if cookies:
        # Dependendo de como você gere os cookies no seu app.py original
        # Pode ser que você salve num arquivo temp e passe o caminho:
        # ydl_opts['cookiefile'] = caminho_do_arquivo_temp
        pass 

    download_id = str(uuid.uuid4())
    
    # ... 
    # AQUI ENTRA A SUA LÓGICA DE THREADS / BACKGROUND QUE JÁ EXISTE NO SEU APP.PY
    # queue[download_id] = ...
    # threading.Thread(target=sua_funcao_de_download_em_background, args=(ydl_opts, url, download_id)).start()
    # ...

    return jsonify({
        'ok': True,
        'download_id': download_id,
        'is_youtube': 'youtube.com' in url or 'youtu.be' in url
    })

@app.route("/api/playlist", methods=["POST"])
def extract_playlist():
    """
    Extrai a lista de vídeos de uma playlist ou curso sem baixar nada.
    Usa extract_flat="in_playlist" do yt-dlp para obter apenas metadados.
    """
    data = request.get_json()
    url = data.get("url", "").strip()
    cookies = data.get("cookies", "").strip() or None

    if not url:
        return jsonify({"error": "URL é obrigatória"}), 400

    cookies_path = write_cookies_file(cookies) if cookies else None
    try:
        opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": "in_playlist",
            "http_headers": {
                "User-Agent": USER_AGENT,
                "Referer": "https://www.youtube.com/",
            }
        }
        if cookies_path:
            opts["cookiefile"] = cookies_path

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            entries_raw = info.get("entries", [info])
            course_title = info.get("title", "Playlist")
            entries = []

            for idx, e in enumerate(entries_raw):
                if not e:
                    continue
                e_url = e.get("url") or e.get("webpage_url") or ""
                # Para YouTube, a URL plana é apenas o ID. Montamos a URL completa.
                if e_url and not e_url.startswith("http"):
                    e_url = f"https://www.youtube.com/watch?v={e_url}"
                safe_title = sanitize(e.get("title", f"Video {idx+1}"))
                prefix = f"{(idx+1):02d} - "
                entries.append({
                    "title": prefix + safe_title,
                    "url": e_url,
                    "duration": e.get("duration_string", ""),
                    "thumbnail": e.get("thumbnail", ""),
                })

            return jsonify({"title": course_title, "entries": entries})
    except Exception as e:
        return jsonify({"error": friendly_error(str(e))}), 400
    finally:
        if cookies_path:
            try:
                os.remove(cookies_path)
            except:
                pass


@app.route("/api/info", methods=["POST"])
def get_info():
    """
    Retorna metadados de um vídeo (título, thumbnail, duração, formatos disponíveis)
    sem fazer o download. Útil para a prévia antes de confirmar o download.
    """
    data = request.get_json()
    url = data.get("url", "").strip()
    cookies = data.get("cookies", "").strip() or None

    if not url:
        return jsonify({"error": "URL é obrigatória"}), 400

    if is_direct_video_url(url):
        path = urllib.parse.urlparse(url).path
        return jsonify({
            "title": os.path.basename(path).split("?")[0],
            "uploader": "URL direta",
            "direct": True,
            "is_youtube": False,
        })

    cookies_path = write_cookies_file(cookies) if cookies else None
    try:
        opts = build_opts("best", cookies_path, skip_download=True)
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)

            # Coleta as resoluções disponíveis para informar o usuário
            formats = info.get("formats", [])
            resolutions = sorted(set(
                f.get("height") for f in formats
                if f.get("height") and f.get("vcodec") != "none"
            ), reverse=True)

            return jsonify({
                "title": info.get("title", ""),
                "thumbnail": info.get("thumbnail", ""),
                "duration": info.get("duration_string", ""),
                "uploader": info.get("uploader", ""),
                "formats_count": len(formats),
                "extractor": info.get("extractor", ""),
                "is_youtube": is_youtube_url(url),
                "resolutions": resolutions[:6],  # máx 6 opções para não poluir o frontend
                "view_count": info.get("view_count", 0),
                "upload_date": info.get("upload_date", ""),
            })
    except Exception as e:
        return jsonify({"error": friendly_error(str(e))}), 400
    finally:
        if cookies_path:
            try:
                os.remove(cookies_path)
            except:
                pass


@app.route("/api/progress/<download_id>")
def get_progress(download_id):
    """Retorna o estado atual de um download específico."""
    return jsonify(progress_store.get(download_id, {"status": "not_found"}))


@app.route("/api/file/<filename>")
def serve_file(filename):
    """Serve o arquivo baixado para o navegador com cabeçalho de download."""
    return send_from_directory(DOWNLOAD_DIR, filename, as_attachment=True)


@app.route("/api/list")
def list_downloads():
    """Lista todos os arquivos na pasta de downloads, ordenados por data de modificação."""
    files = []
    for f in os.listdir(DOWNLOAD_DIR):
        if f.endswith((".mp4", ".mp3", ".webm", ".mkv", ".m4a")):
            path = os.path.join(DOWNLOAD_DIR, f)
            files.append({
                "name": f,
                "size": os.path.getsize(path),
                "modified": os.path.getmtime(path),
            })
    files.sort(key=lambda x: x["modified"], reverse=True)
    return jsonify(files)


@app.route("/api/delete/<filename>", methods=["DELETE"])
def delete_file(filename):
    """
    Remove um arquivo baixado do disco.
    Usamos DELETE (método HTTP semântico) em vez de POST/GET por boa prática REST.
    """
    path = os.path.join(DOWNLOAD_DIR, filename)
    # Verificação de segurança: garante que o arquivo está dentro da pasta downloads
    # e que não estamos deletando algo fora (path traversal attack).
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