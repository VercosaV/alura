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


## ✨ Novas funcionalidades

### Progresso total de playlists

Ao baixar uma playlist, a barra principal representa a tarefa inteira. A interface informa o percentual agregado, o item atual, o total de itens, quantos já foram concluídos, o percentual do item atual, a velocidade e o ETA quando fornecidos pelo `yt-dlp`. Assim, uma playlist com 87 vídeos pode ser acompanhada como uma única tarefa.

### Criar áudio sem apagar o vídeo

Na biblioteca, vídeos possuem o botão **Criar áudio**. Escolha MP3 (192 kbps), M4A/AAC ou WAV. A conversão usa o `ffmpeg`, cria um novo arquivo na mesma pasta e mantém o vídeo original intacto. Se já existir um nome igual, um nome alternativo é usado para evitar sobrescrita. Áudios aparecem com player próprio e também podem ser salvos pelo botão **Salvar**.

A biblioteca agora lista vídeos e áudios, permitindo reproduzir, salvar e mover ambos os tipos.

## Observação sobre o GitHub

Esta versão foi preparada localmente para testes. Nenhum commit ou push foi feito no repositório remoto.


### Conversão em lote

Na seção **Vídeos e áudios baixados**, use o painel **Converter todos os vídeos**. Escolha MP3, M4A ou WAV e clique em **Criar áudios de todos**. O sistema processa todos os vídeos encontrados em `downloads/`, cria um novo áudio para cada um na mesma pasta e mantém os vídeos originais. A barra mostra o total de itens, o item atual, os concluídos e eventuais falhas.
