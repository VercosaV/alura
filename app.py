import os
import re
import time
import threading
import uuid
import shutil
import subprocess
from queue import Queue
from flask import Flask, request, jsonify, send_from_directory
import yt_dlp

# Novas importações para o Selenium
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager

# ─────────────────────────────
# ☁️ CLOUDFLARE R2 CONFIG (Mantido o seu original)
# ─────────────────────────────
USE_R2 = os.environ.get('USE_R2', 'false').lower() == 'true'

if USE_R2:
    import boto3
    from botocore.config import Config
    
    R2_ENDPOINT = os.environ.get('R2_ENDPOINT')
    R2_ACCESS_KEY = os.environ.get('R2_ACCESS_KEY')
    R2_SECRET_KEY = os.environ.get('R2_SECRET_KEY')
    R2_BUCKET = os.environ.get('R2_BUCKET')
    R2_PUBLIC_URL = os.environ.get('R2_PUBLIC_URL')
    
    s3_client = boto3.client(
        's3', endpoint_url=R2_ENDPOINT,
        aws_access_key_id=R2_ACCESS_KEY, aws_secret_access_key=R2_SECRET_KEY,
        region_name='auto', config=Config(signature_version='s3v4')
    )
    
    def upload_to_r2(local_path, s3_key):
        s3_client.upload_file(local_path, R2_BUCKET, s3_key)
        return f"{R2_PUBLIC_URL}/{s3_key}"

# ─────────────────────────────
# 📦 CONFIGURAÇÃO GERAL
# ─────────────────────────────
app = Flask(__name__, static_folder=".")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_ROOT = os.path.join(BASE_DIR, "downloads")
os.makedirs(DOWNLOAD_ROOT, exist_ok=True)

progress_store = {}
batch_store = {}

MAX_DOWNLOADS = 3
download_queue = Queue()

def sanitize(name):
    return re.sub(r'[\\/*?:"<>|]', "_", name)

# ─────────────────────────────
# 🔍 EXTRAÇÃO COM SELENIUM + JS INJECTION
# ─────────────────────────────
# ─────────────────────────────
# 🔍 EXTRAÇÃO COM SELENIUM + JS INJECTION (COM PERFIL SALVO)
# ─────────────────────────────
def extrair_urls_video_da_pagina(url):
    print(f"[SELENIUM] Iniciando análise na URL: {url}")
    
    chrome_options = Options()
    
    # 1. Aponta para a pasta do perfil_bot (usando a variável BASE_DIR que já existe no seu código)
    perfil_path = os.path.join(BASE_DIR, "perfil_bot")
    chrome_options.add_argument(f"--user-data-dir={perfil_path}")
    chrome_options.add_argument("--profile-directory=Default")
    
    # 2. Flags anti-detecção de bot
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--mute-audio")
    
    # ⚠️ IMPORTANTE: Se a extração falhar ou der erro de "Nenhum vídeo encontrado",
    # comente a linha abaixo (coloque um # na frente), pois a Alura pode estar bloqueando o modo invisível.
    chrome_options.add_argument("--headless=new") 
    
    # Inicia o navegador gerenciado automaticamente
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    
    videos_encontrados = []
    
    try:
        driver.get(url)
        # Pausa para dar tempo do site (React/Vue/Alura) renderizar o DOM e os vídeos
        time.sleep(5) 
        
        # A mágica do Python injetando JavaScript para caçar os vídeos
        script_js = """
            let resultados = [];
            
            // 1. Busca tags <video> diretas
            document.querySelectorAll('video').forEach(video => {
                if (video.src) {
                    resultados.push({ url: video.src, type: 'video/mp4', qualidade: 'auto' });
                }
                // Busca sources dentro do video
                video.querySelectorAll('source').forEach(source => {
                    if (source.src) {
                        resultados.push({ url: source.src, type: source.type || 'video/mp4', qualidade: 'auto' });
                    }
                });
            });
            
            // 2. Procura links M3U8 escondidos no código da página inteira
            let htmlCompleto = document.documentElement.innerHTML;
            let m3u8Links = htmlCompleto.match(/https?:\/\/[^\\s"']+?\\.m3u8[^\\s"']*/g);
            if (m3u8Links) {
                m3u8Links.forEach(link => {
                    resultados.push({ url: link, type: 'application/x-mpegURL', qualidade: 'HLS/m3u8' });
                });
            }
            
            return resultados;
        """
        
        resultados_js = driver.execute_script(script_js)
        
        # Filtra duplicatas e links blob
        urls_unicas = set()
        for res in resultados_js:
            link = res['url']
            if link.startswith('blob:'):
                print(f"[AVISO] Link protegido (blob) ignorado: {link}")
                continue
            
            if link not in urls_unicas:
                urls_unicas.add(link)
                videos_encontrados.append(res)
                
    except Exception as e:
        print(f"[ERRO SELENIUM]: {e}")
    finally:
        driver.quit()
        
    print(f"[EXTRAÇÃO] {len(videos_encontrados)} vídeos únicos encontrados.")
    return videos_encontrados


@app.route("/api/extract-video-urls", methods=["POST"])
def extract_video_urls():
    data = request.get_json()
    if not data or 'url' not in data:
        return jsonify({'error': 'URL é obrigatória'}), 400

    videos = extrair_urls_video_da_pagina(data.get('url'))

    if not videos:
        return jsonify({
            'videos': [],
            'message': 'Nenhum vídeo encontrado. Se for área logada, o acesso pode estar bloqueado ou o vídeo usa DRM fechado.'
        })

    return jsonify({
        'videos': videos,
        'count': len(videos),
        'message': f'{len(videos)} vídeo(s) encontrado(s)'
    })

# ─────────────────────────────
# 📥 DOWNLOAD MISTO (FFMPEG DIRETO ou YT-DLP)
# ─────────────────────────────
def baixar_video(download_id, url, folder, custom_name):
    filename = sanitize(custom_name or "video_extraido")
    local_path = os.path.join(folder, f"{filename}.mp4")
    
    progress_store[download_id] = {
        "status": "downloading",
        "percent": 0,
        "speed": "Calculando...",
        "eta": "Aguarde..."
    }

    try:
        # Se for um arquivo de streaming (m3u8), usamos o subprocess com FFmpeg nativo
        if '.m3u8' in url.lower():
            print(f"[FFMPEG] Iniciando download HLS: {url}")
            comando = [
                'ffmpeg', '-y',        # -y sobrescreve se existir
                '-i', url,             # input url
                '-c', 'copy',          # copia codec sem reencodar (muito rápido)
                '-bsf:a', 'aac_adtstoasc', 
                local_path
            ]
            
            # Executa o comando e bloqueia até terminar
            subprocess.run(comando, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            final_name = f"{filename}.mp4"
            
        else:
            # Para URLs normais ou YouTube, mantemos o yt-dlp
            print(f"[YT-DLP] Iniciando download: {url}")
            def hook(d):
                if d["status"] == "downloading":
                    total = d.get("total_bytes") or d.get("total_bytes_estimate") or 1
                    done = d.get("downloaded_bytes", 0)
                    percent = int(done / total * 100)
                    progress_store[download_id].update({"percent": percent})
            
            opts = {
                "format": "best",
                "outtmpl": os.path.join(folder, f"{filename}.%(ext)s"),
                "progress_hooks": [hook],
                "merge_output_format": "mp4",
                "quiet": True
            }
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.extract_info(url, download=True)
            final_name = f"{filename}.mp4"

        # ☁️ Lógica R2 mantida
        if USE_R2 and os.path.exists(local_path):
            s3_key = f"{folder}/{final_name}"
            file_url = upload_to_r2(local_path, s3_key)
            os.remove(local_path)
        else:
            file_url = final_name

        progress_store[download_id] = {
            "status": "done",
            "percent": 100,
            "filename": final_name,
            "url": file_url if USE_R2 else None
        }

    except subprocess.CalledProcessError:
        progress_store[download_id] = {"status": "error", "error": "Falha no FFmpeg."}
    except Exception as e:
        progress_store[download_id] = {"status": "error", "error": str(e)}

# ─────────────────────────────
# ⚙️ WORKER E ROTAS PADRÕES (MANTIDAS)
# ─────────────────────────────
def worker():
    while True:
        download_id, url, folder, custom_name = download_queue.get()
        try:
            baixar_video(download_id, url, folder, custom_name)
        finally:
            download_queue.task_done()

for _ in range(MAX_DOWNLOADS):
    threading.Thread(target=worker, daemon=True).start()

@app.route("/")
def index(): return send_from_directory(".", "index.html")

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
    download_id = uuid.uuid4().hex[:8]
    progress_store[download_id] = {"status": "queued", "percent": 0}
    download_queue.put((download_id, data.get("url"), batch_store.get(data.get("batch_id")), data.get("custom_name")))
    return jsonify({"download_id": download_id})

@app.route("/api/progress/<id>")
def progress(id): return jsonify(progress_store.get(id, {}))

@app.route("/api/list")
def list_files():
    files = []
    for root, dirs, filenames in os.walk(DOWNLOAD_ROOT):
        for f in filenames:
            files.append({"name": f, "size": os.path.getsize(os.path.join(root, f))})
    return jsonify(files)

@app.route("/api/file/<filename>")
def file(filename):
    for root, dirs, files in os.walk(DOWNLOAD_ROOT):
        if filename in files: return send_from_directory(root, filename, as_attachment=True)
    return "Não encontrado", 404

@app.route("/api/clear", methods=["POST"])
def clear():
    shutil.rmtree(DOWNLOAD_ROOT)
    os.makedirs(DOWNLOAD_ROOT)
    progress_store.clear()
    batch_store.clear()
    return jsonify({"ok": True})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)