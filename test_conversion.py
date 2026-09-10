import time
from pathlib import Path
from app import app, DOWNLOAD_DIR

folder = DOWNLOAD_DIR / "Teste"
folder.mkdir(parents=True, exist_ok=True)
source = folder / "amostra.mp4"
client = app.test_client()
response = client.post('/api/convert', json={'path': 'Teste/amostra.mp4', 'format': 'mp3'})
print('convert_without_source', response.status_code)
print(response.get_json())

if source.exists():
    response = client.post('/api/convert', json={'path': 'Teste/amostra.mp4', 'format': 'mp3'})
    data = response.get_json()
    print('convert_with_source', response.status_code, data)
    for _ in range(30):
        progress = client.get('/api/progress/' + data['convert_id']).get_json()
        if progress.get('status') in {'done', 'error'}:
            print('final', progress)
            break
        time.sleep(0.2)
    print('source_exists', source.exists())
    print('audio_exists', any(folder.glob('amostra*.mp3')))
