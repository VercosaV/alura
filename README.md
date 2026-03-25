# 🎬 VideoGet — Baixador de Vídeos Local

Aplicação web local para baixar vídeos do YouTube, Alura, e milhares de outros sites usando **yt-dlp**, com suporte a formatos otimizados para celular e extrator de MP4 de páginas HTML.

---

## ⚡ Instalação rápida

### 1. Pré-requisitos

- Python 3.10+ instalado
- `ffmpeg` instalado no sistema

**Instalar ffmpeg:**
- **Windows:** Baixe em https://ffmpeg.org/download.html e adicione ao PATH
- **macOS:** `brew install ffmpeg`
- **Linux:** `sudo apt install ffmpeg`

### 2. Instalar Dependências

O `requirements.txt` deve conter:
```
flask>=3.0
yt-dlp>=2024.1.1
beautifulsoup4>=4.12
```

**Windows / macOS:**
```bash
pip install -r requirements.txt
```

**Linux (Zorin OS, Ubuntu e distribuições recentes):**
```bash
sudo apt install python3-venv
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Rodar a Aplicação

**Windows / macOS:**
```bash
python app.py
```

**Linux:**
```bash
source venv/bin/activate  # se usou venv
python3 app.py
```

Acesse no navegador: **http://localhost:5000**

---

## 📱 Formatos otimizados para celular

A aba **⬇ Baixar Vídeos** agora inclui qualidades pensadas para celular:

| Opção    | Descrição                                  | Recomendado para        |
|----------|--------------------------------------------|-------------------------|
| Melhor   | Maior resolução disponível                 | PC / TV                 |
| 1080p    | Full HD                                    | PC / TV                 |
| 720p ★   | HD — boa qualidade, tamanho médio          | PC / Celular top        |
| **480p 📱** | SD — leve, ótimo para celular           | ✅ Celular (recomendado) |
| **360p 📱** | SD — muito leve, streaming em 3G/4G     | ✅ Celular (dados móveis)|
| Só áudio | Extrai MP3                                 | Podcasts / Músicas      |

> **Dica:** Os formatos 480p e 360p usam codec H.264/AAC, compatíveis nativamente com iOS e Android sem precisar de app externo.

---

## 🔍 Extrator MP4 de Páginas HTML (NOVO)

A aba **🔍 Extrator MP4** permite escanear qualquer página web e encontrar todos os links de vídeo no HTML.

### Como usar:
1. Vá na aba **🔍 Extrator MP4**
2. Cole a URL da página que contém vídeos
3. (Opcional) Ative **"Filtrar por tag HTML"** para buscar apenas em tags específicas:
   - `<video>` — players HTML5 nativos
   - `<source>` — fontes de vídeo dentro de `<video>`
   - `<a>` — links diretos para download
   - `<iframe>` — players embutidos
   - `<div>` — elementos com atributos `data-src`, `data-video`
   - Ou escreva qualquer tag manualmente
4. Clique em **🔎 Escanear**
5. Os links encontrados (.mp4, .webm, .m3u8) são listados com botões de:
   - **📋 Copiar URL** — copia o link direto
   - **⬇ Abrir / Baixar** — abre o vídeo diretamente no navegador
   - **＋ Importar para fila** — envia todos para a aba de downloads

### Como funciona o backend:

O frontend chama `POST /api/extract-mp4` com:
```json
{
  "url": "https://exemplo.com/pagina",
  "tag_filter": "video"
}
```

O `app.py` faz o fetch do HTML e usa **BeautifulSoup** para:
- Escanear atributos `src`, `href`, `data-src`, `data-video`, etc.
- Varrer tags `<video>`, `<source>`, `<a>`, `<iframe>`, `<div>`
- Extrair URLs de vídeo de blocos `<script>` e JSON inline
- Retornar lista com url, tag, atributo e formato

> **Atenção:** O `app.py` agora depende de `beautifulsoup4`. Atualize o requirements.txt (veja abaixo).

---

## 🔐 Baixar da Alura (ou outros sites com login)

1. Instale a extensão **"Get cookies.txt LOCALLY"** no Chrome ou Firefox
2. Faça login na Alura
3. Exporte os cookies pela extensão
4. Cole o conteúdo na área de **🍪 Autenticação**
5. Use a aba de downloads normalmente

---

## 🌐 Sites suportados

yt-dlp suporta mais de 1.000 sites. Exemplos:
- YouTube, YouTube Music, YouTube Shorts
- Alura (com cookies)
- Vimeo, Dailymotion
- Twitter/X, Instagram, TikTok
- Twitch (VODs)
- E muito mais: https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md

---

## 📁 Arquivos baixados

Os vídeos são salvos na pasta `downloads/` no mesmo diretório do `app.py`.
Você também pode baixar pela interface clicando em **⬇ Salvar**.

---

## 🗂 Estrutura do projeto

```
videoget/
├── index.html        ← Interface web (este arquivo)
├── app.py            ← Servidor Flask + API
├── requirements.txt  ← Dependências Python
├── downloads/        ← Vídeos baixados (criado automaticamente)
└── README.md
```