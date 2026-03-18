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
