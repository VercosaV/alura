import os
import re
import threading
import uuid
import shutil
from queue import Queue
from flask import Flask, request, jsonify, send_from_directory
import yt_dlp
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

# ─────────────────────────────
# ☁️ CLOUDFLARE R2 CONFIG
# ─────────────────────────────
USE_R2 = os.environ.get('USE_R2', 'false').lower() == 'true'

if USE_R2:
    import boto3
    from botocore.config import Config
    
    R2_ENDPOINT = os.environ.get('R2_ENDPOINT')  # ex: https://account-id.r2.cloudflarestorage.com
    R2_ACCESS_KEY = os.environ.get('R2_ACCESS_KEY')
    R2_SECRET_KEY = os.environ.get('R2_SECRET_KEY')
    R2_BUCKET = os.environ.get('R2_BUCKET')
    R2_PUBLIC_URL = os.environ.get('R2_PUBLIC_URL')  # ex: https://files.seusite.com
    
    s3_client = boto3.client(
        's3',
        endpoint_url=R2_ENDPOINT,
        aws_access_key_id=R2_ACCESS_KEY,
        aws_secret_access_key=R2_SECRET_KEY,
        region_name='auto',
        config=Config(signature_version='s3v4')
    )
    
    def upload_to_r2(local_path, s3_key):
        """Faz upload do arquivo para R2"""
        s3_client.upload_file(local_path, R2_BUCKET, s3_key)
        # Retorna URL pública direta
        return f"{R2_PUBLIC_URL}/{s3_key}"
    
    def delete_from_r2(s3_key):
        """Remove arquivo do R2"""
        s3_client.delete_object(Bucket=R2_BUCKET, Key=s3_key)
    
    def list_r2_files():
        """Lista arquivos no R2"""
        try:
            response = s3_client.list_objects_v2(Bucket=R2_BUCKET)
            files = []
            if 'Contents' in response:
                for obj in response['Contents']:
                    files.append({
                        "name": obj['Key'],
                        "size": obj['Size'],
                        "url": f"{R2_PUBLIC_URL}/{obj['Key']}"
                    })
            return files
        except Exception as e:
            print(f"Erro ao listar R2: {e}")
            return []

# ─────────────────────────────
# 📦 CONFIGURAÇÃO GERAL
# ─────────────────────────────

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

# FUNÇÕES AUXILIARES PARA EXTRAÇÃO

def video_pattern_check(url):
    """Checa se a URL corresponde a um padrão de vídeo"""
    if not url or not isinstance(url, str):
        return False
    video_extensions = ['.mp4', '.m3u8', '.ts', '.mpd', '.mov', '.avi', '.wmv', '.webm', '.mkv', '.flv']
    url_lower = url.lower()
    return any(ext in url_lower for ext in video_extensions)

def get_mime_type_for_video(video_type):
    """Retorna o tipo MIME baseado na extensão"""
    mime_types = {
        'mp4': 'video/mp4',
        'm3u8': 'application/x-mpegURL',
        'mpd': 'application/dash+xml',
        'ts': 'video/mp2t',
        'mov': 'video/quicktime',
        'avi': 'video/x-msvideo',
        'wmv': 'video/x-ms-wmv',
        'webm': 'video/webm',
        'mkv': 'video/x-matroska',
        'flv': 'video/x-flv'
    }
    return mime_types.get(video_type, 'video/mp4')

def get_quality_from_url(url):
    """Tenta extrair qualidade da URL ou parâmetros"""
    try:
        # Procurar por números na URL (720, 1080, 480, etc)
        quality_match = re.search(r'(\d{3,4})p?', url)
        if quality_match:
            return f"{quality_match.group(1)}p"

        # Procurar por qualidade em parâmetros da URL
        quality_params = ['quality', 'res', 'resolution', 'q', 'bitrate', 'br']
        from urllib.parse import parse_qs, urlparse
        parsed = urlparse(url)
        params = parse_qs(parsed.query)

        for param in quality_params:
            if param in params:
                return params[param][0]

        return 'unknown'
    except:
        return 'unknown'

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
        local_path = os.path.join(folder, f"{filename}.mp4")

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
            
            # Encontrar o arquivo baixado (pode ter extensão diferente)
            downloaded_files = [f for f in os.listdir(folder) if f.startswith(filename)]
            if downloaded_files:
                local_path = os.path.join(folder, downloaded_files[0])

            # ☁️ Se R2 está habilitado, fazer upload
            if USE_R2:
                s3_key = f"{folder}/{final_name}"
                file_url = upload_to_r2(local_path, s3_key)
                # Remove arquivo local após upload
                try:
                    os.remove(local_path)
                except:
                    pass
            else:
                file_url = final_name

            progress_store[download_id] = {
                "status": "done",
                "percent": 100,
                "filename": final_name,
                "url": file_url if USE_R2 else None
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
# 🔍 EXTRAÇÃO AUTOMÁTICA DE VÍDEOS
# ─────────────────────────────

def extrair_urls_video_da_pagina(url, headers=None, cookies=None):
    """
    Extrai todas as URLs de vídeo de uma página HTML.
    Retorna lista de dicts com url, tipo e qualidade (se disponível).
    """
    video_urls = []

    try:
        # Configurar request com headers mais realistas
        req_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "pt-BR,pt;q=0.8,en-US;q=0.5,en;q=0.3",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none"
        }
        if headers:
            req_headers.update(headers)

        # Fazer requisição
        response = requests.get(url, headers=req_headers, cookies=cookies or {}, timeout=30)
        response.raise_for_status()

        # Parser automático (usa html.parser se lxml não estiver disponível)
        try:
            soup = BeautifulSoup(response.content, 'lxml')
        except Exception:
            soup = BeautifulSoup(response.content, 'html.parser')

        # REGEX para detectar vídeos (mais abrangente)
        VIDEO_PATTERNS = {
            'm3u8': r'https?://[^\s"<>]+\.m3u8[^\s"<>]*',
            'mp4': r'https?://[^\s"<>]+\.mp4[^\s"<>]*',
            'mpd': r'https?://[^\s"<>]+\.mpd[^\s"<>]*',
            'ts': r'https?://[^\s"<>]+\.ts[^\s"<>]*',
            'mov': r'https?://[^\s"<>]+\.mov[^\s"<>]*',
            'avi': r'https?://[^\s"<>]+\.avi[^\s"<>]*',
            'wmv': r'https?://[^\s"<>]+\.wmv[^\s"<>]*',
            'webm': r'https?://[^\s"<>]+\.webm[^\s"<>]*',
            'mkv': r'https?://[^\s"<>]+\.mkv[^\s"<>]*',
            'flv': r'https?://[^\s"<>]+\.flv[^\s"<>]*'
        }

        # Tipos MIME para vídeo
        VIDEO_MIME_TYPES = [
            'video/mp4', 'video/webm', 'video/ogg', 'video/quicktime',
            'video/x-msvideo', 'video/x-flv', 'video/mpeg', 'video/mp2t',
            'application/x-mpegURL', 'application/dash+xml'
        ]

        # 1. Extrair de tags <video>
        for video in soup.find_all('video'):
            # Atributo src da tag video
            if video.get('src'):
                video_url = urljoin(url, video.get('src'))
                if video_url:
                    video_urls.append({
                        'url': video_url,
                        'type': 'video/mp4',
                        'qualidade': video.get('data-quality') or video.get('data-quality-src') or video.get('quality') or 'unknown'
                    })

            # Tags <source> dentro de <video>
            for source in video.find_all('source'):
                src = source.get('src')
                if src:
                    video_url = urljoin(url, src)
                    if video_url:
                        mime_type = source.get('type') or ('video/mp4' if '.mp4' in src else 'video/mp4')
                        qualidade = source.get('data-quality') or source.get('label') or source.get('res') or source.get('type')
                        video_urls.append({
                            'url': video_url,
                            'type': mime_type,
                            'qualidade': qualidade or 'unknown'
                        })

        # 2. Extrair de atributos comuns de dados
        video_attrs = [
            'data-video-src', 'data-video-url', 'data-url', 'data-src', 'data-source',
            'data-video', 'data-video-path', 'data-video-file', 'data-stream', 'data-video-urls'
        ]
        for attr in video_attrs:
            for tag in soup.find_all(attrs={attr: True}):
                attr_value = tag.get(attr)
                if attr_value and video_pattern_check(attr_value):
                    video_url = urljoin(url, attr_value)
                    if video_url:
                        video_urls.append({
                            'url': video_url,
                            'type': 'video/mp4',
                            'qualidade': tag.get('data-quality') or tag.get('data-resolution') or 'unknown'
                        })

        # 3. Procurar em links <a> que apontam para vídeos
        for link in soup.find_all('a', href=True):
            href = link.get('href')
            if href and video_pattern_check(href):
                video_url = urljoin(url, href)
                if video_url:
                    text = link.get_text(strip=True)
                    video_urls.append({
                        'url': video_url,
                        'type': 'video/mp4',
                        'qualidade': text or 'unknown'
                    })

        # 4. Procurar em iframes (YouTube, Vimeo, etc)
        for iframe in soup.find_all('iframe', src=True):
            src = iframe.get('src')
            if src and any(domain in src.lower() for domain in ['youtube', 'vimeo', 'player.vimeo']):
                video_url = urljoin(url, src)
                if video_url:
                    video_urls.append({
                        'url': video_url,
                        'type': 'video/embed',
                        'qualidade': 'embed'
                    })

        # 5. Rastrear todos os padrões de vídeo no HTML
        html_text = response.text
        for video_type, pattern in VIDEO_PATTERNS.items():
            for match in re.finditer(pattern, html_text, re.IGNORECASE):
                video_url = match.group(0)
                if video_url and video_url.startswith(('http://', 'https://')):
                    mime_type = get_mime_type_for_video(video_type)
                    video_urls.append({
                        'url': video_url,
                        'type': mime_type,
                        'qualidade': get_quality_from_url(video_url)
                    })

        # Remover duplicatas (usando url como chave)
        urls_unicas = {}
        for video in video_urls:
            urls_unicas[video['url']] = video

        # Validar URLs (verificar se são acessíveis opcionalmente)
        videos_filtrados = list(urls_unicas.values())

        print(f"[EXTRAÇÃO] Encontrados {len(videos_filtrados)} vídeos únicos")
        return videos_filtrados

    except Exception as e:
        print(f"Erro ao extrair vídeos: {e}")
        return []

@app.route("/api/extract-video-urls", methods=["POST"])
def extract_video_urls():
    """
    Endpoint para extrair URLs de vídeo de uma página.
    Recebe JSON com url, opcionalmente headers e cookies.
    """
    data = request.get_json()

    if not data or 'url' not in data:
        return jsonify({'error': 'URL é obrigatória'}), 400

    url = data.get('url')
    headers = data.get('headers', None)
    cookies = data.get('cookies', None)

    videos = extrair_urls_video_da_pagina(url, headers, cookies)

    if not videos:
        return jsonify({
            'videos': [],
            'message': 'Nenhum vídeo encontrado na página. Verifique se a URL está correta e se você tem acesso (talvez necessite de cookies/autenticação).'
        })

    return jsonify({
        'videos': videos,
        'count': len(videos),
        'message': f'{len(videos)} vídeo(s) encontrado(s)'
    })

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

#if __name__ == "__main__":
#    print("** VideoGet running at http://localhost:5000")
#    app.run(debug=True)

import os

# ... resto do seu código ...

if __name__ == '__main__':
    # O Render define a variável PORT. Se não encontrar (rodando local), usa 5000.
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)