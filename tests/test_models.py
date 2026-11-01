import hashlib
import os
import time

import pytest

from meeting_local import models


def _sparse(path, size):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.truncate(size)
    return path


def test_catalog_shape():
    cat = models.load_catalog()
    assert cat["version"] == 1
    assert cat["shared_dir"]["mac"] == "~/.cache/twtools/models"
    files = {e.file for e in models.entries()}
    assert set(models.PREFERRED_ORDER) <= files
    for e in models.entries():
        assert e.family == models.WHISPER_FAMILY
        assert e.url == f"https://huggingface.co/ggerganov/whisper.cpp/resolve/main/{e.file}"
        assert len(e.sha256) == 64 and int(e.sha256, 16) >= 0
        assert e.size > 100_000_000


def test_shared_dir_override(monkeypatch, tmp_path):
    monkeypatch.delenv("TWTOOLS_MODELS", raising=False)
    assert models.shared_dir(tmp_path) == tmp_path / ".cache/twtools/models"
    monkeypatch.setenv("TWTOOLS_MODELS", str(tmp_path / "x"))
    assert models.shared_dir(tmp_path) == tmp_path / "x"


def test_find_prefers_full_model_across_dirs(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    q5 = models.entry("ggml-large-v3-turbo-q5_0.bin")
    full = models.entry("ggml-large-v3-turbo.bin")
    _sparse(a / q5.file, q5.size)
    assert models.find_whisper([a, b]) == a / q5.file  # 只有 q5_0（例如裝過看懂）也能用
    _sparse(b / full.file, full.size)
    assert models.find_whisper([a, b]) == b / full.file  # 未量化版優先，不管在哪個資料夾


def test_find_ignores_wrong_size(tmp_path):
    q5 = models.entry("ggml-large-v3-turbo-q5_0.bin")
    _sparse(tmp_path / q5.file, q5.size - 1)  # 下載到一半
    assert models.find_whisper([tmp_path]) is None


def test_part_in_use(tmp_path):
    part = tmp_path / "m.bin.part"
    assert not models.part_in_use(part)
    part.write_bytes(b"x")
    assert models.part_in_use(part)
    old = time.time() - 600
    os.utime(part, (old, old))
    assert not models.part_in_use(part)


def test_download_refuses_when_other_program_downloading(tmp_path):
    target = tmp_path / "m.bin"
    (tmp_path / "m.bin.part").write_bytes(b"x")
    with pytest.raises(RuntimeError, match="另一個程式正在下載"):
        models.download("file:///dev/null", target, None, 1, "測試模型")


def test_download_verifies_sha256(tmp_path):
    src = tmp_path / "src.bin"
    src.write_bytes(b"hello model")
    good = hashlib.sha256(b"hello model").hexdigest()
    target = tmp_path / "out" / "m.bin"
    with pytest.raises(RuntimeError, match="SHA256 不符"):
        models.download(src.as_uri(), target, "0" * 64, 11, "測試模型")
    assert not target.exists() and not (target.parent / "m.bin.part").exists()
    assert models.download(src.as_uri(), target, good, 11, "測試模型") == target
    assert target.read_bytes() == b"hello model"
