#!/usr/bin/env python3
"""Script para atualizar o README.md com documentação da nova funcionalidade"""

with open('README.md', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find where to insert (before '## 🎛️ Qualidades disponíveis')
insert_idx = None
for i, line in enumerate(lines):
    if line.strip() == '## 🎛️ Qualidades disponíveis':
        insert_idx = i
        break

if insert_idx is None:
    print('Seção não encontrada')
    exit(1)

new_section = '''---

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

'''

lines.insert(insert_idx, new_section)

with open('README.md', 'w', encoding='utf-8') as f:
    f.writelines(lines)

print('README atualizado com sucesso!')