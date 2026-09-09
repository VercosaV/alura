from pathlib import Path
from app import app, DOWNLOAD_DIR, safe_folder

client = app.test_client()
test_folder = safe_folder("Teste/Organizado")
test_file = test_folder / "amostra.mp4"
test_file.write_bytes(b"video-test")
try:
    response = client.get("/api/list")
    assert response.status_code == 200
    item = next(row for row in response.get_json() if row["path"] == "Teste/Organizado/amostra.mp4")
    assert client.get(item["stream_url"]).data == b"video-test"
    moved = client.post("/api/move", json={"path": item["path"], "folder": "Teste/Final"})
    assert moved.status_code == 200, moved.get_json()
    assert (DOWNLOAD_DIR / "Teste/Final/amostra.mp4").exists()
finally:
    import shutil
    shutil.rmtree(DOWNLOAD_DIR / "Teste", ignore_errors=True)
print("smoke tests passed")
