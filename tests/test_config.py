from meeting_local import config, models


def test_vad_model_pinned_to_official_v620_file() -> None:
    # ggml-org 的 ggml-silero-v6.2.0.bin＝885,098 bytes（2026-11-01 對 HF x-linked-size／etag 實查）。
    # 0.1.2 曾把下限誤設 1 MB，把完整檔判成不完整；現在改成比對確切大小＋SHA256。
    assert config.VAD_MODEL_SIZE == 885_098
    assert config.VAD_MODEL_SHA256 == "2aa269b785eeb53a82983a20501ddf7c1d9c48e33ab63a41391ac6c9f7fb6987"
    assert config.VAD_MODEL_URL.endswith("/" + config.VAD_MODEL_FILENAME)


def test_default_download_is_in_catalog() -> None:
    assert models.entry(config.WHISPER_DOWNLOAD_FILE).family == models.WHISPER_FAMILY
    assert config.SHARED_MODELS_DIR in config.WHISPER_SEARCH_DIRS
    assert config.WHISPER_SEARCH_DIRS[0] == config.SHARED_MODELS_DIR


def test_search_dirs_cover_existing_kandong_caches() -> None:
    # 2026-11-03：Charlie 的機器上 q5_0 只躺在 FloatTranslate 舊快取，沒掃到就會白下載 1.6 GB。
    dirs = [str(d) for d in config.WHISPER_SEARCH_DIRS]
    assert any(d.endswith(".cache/floattranslate/whisper") for d in dirs)
    assert any(d.endswith(".cache/kandong/models") for d in dirs)
