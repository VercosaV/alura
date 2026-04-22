# 🎬 VideoGet — Baixador de Vídeos Local

Aplicação web local para baixar vídeos do YouTube, Alura, e milhares de outros sites usando **yt-dlp**.

---

## ⚡ Instalação rápida

### 1. Pré-requisitos

- Python 3.10+ instalado
- `ffmpeg` instalado no sistema

**Instalar ffmpeg:**
- **Windows:** Baixe em https://ffmpeg.org/download.html e adicione ao PATH
- **macOS:** `brew install ffmpeg`
- **Linux:** `sudo apt install ffmpeg`

### 2. Instalar dependências

```bash
pip install -r requirements.txt
```

### 3. Rodar

```bash
python app.py
```

Acesse: **http://localhost:5000**

---

## 🔐 Baixar da Alura (ou outros sites com login)

A Alura exige autenticação. Para baixar os cursos:

1. Instale a extensão **"Get cookies.txt LOCALLY"** no Chrome ou Firefox
2. Faça login na Alura normalmente
3. Clique na extensão e exporte os cookies
4. Na interface do VideoGet, clique em **🍪 Usar cookies**
5. Cole o conteúdo do arquivo cookies.txt
6. Cole a URL do vídeo e clique em **Baixar**

---

---

## 🔍 Extração Automática de Vídeos

**Nova funcionalidade!** Você não precisa mais manualmente inspecionar o HTML para encontrar URLs de vídeo.

### Como funciona:

1. **Clique no botão "🔍 Analisar URL"** (localizado entre "+ URL" e "▶ Baixar")
2. **Cole a URL da página** que contém os vídeos (ex: página de curso)
3. **Clique em "🔎 Extrair Vídeos"** - o sistema irá automaticamente analisar o HTML e encontrar:
   - Tags `<video>` e `<source>`
   - URLs `.mp4`, `.m3u8`, `.ts`
   - Atributos de dados como `data-video-src`
4. **Selecione os vídeos desejados** (use as checkboxes)
5. **Clique em "➕ Adicionar Selecionados"**
6. **Baixe normalmente** clicando em "▶ Baixar"

### Funciona com:

- Sites de cursos (Alura, etc) desde que tenha acesso
- Playlists e páginas com múltiplos vídeos
- Vídeos em tags HTML padrão
- URLs de streaming (.m3u8) e arquivos MP4

### Se não encontrar vídeos:

- Alguns sites usam proteção que bloqueia extração automática
- Sites que requerem autenticação podem precisar de cookies
- Você ainda pode adicionar URLs manualmente clicando "+ URL"

---

## 🎛️ Qualidades disponíveis

| Opção     | Descrição                     |
|-----------|-------------------------------|
| Melhor    | Maior resolução disponível    |
| 1080p     | Full HD                       |
| 720p      | HD                            |
| 480p      | SD                            |
| Só áudio  | Extrai MP3 (192kbps)          |

---

## 📁 Arquivos baixados

Os vídeos são salvos na pasta `downloads/` no mesmo diretório do `app.py`.
Você também pode baixar diretamente pela interface clicando em **⬇ Salvar**.

---

## 🌐 Sites suportados

yt-dlp suporta mais de 1.000 sites. Exemplos:
- YouTube, YouTube Music
- Alura (com cookies)
- Vimeo, Dailymotion
- Twitter/X, Instagram, TikTok
- Twitch (VODs)
- E muito mais: https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md
