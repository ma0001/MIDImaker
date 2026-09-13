"""
MIDImaker の共通キャッシュおよびモデル保存先パス管理モジュール
~/.cache/midimaker/ 配下に各種モデルを一元化します。
"""

import os
import shutil
from pathlib import Path

# MIDImaker 共通キャッシュルートディレクトリ
CACHE_DIR = Path.home() / ".cache" / "midimaker"

# 各機能ごとのモデル保存先
MODELS_DIR = CACHE_DIR / "models"          # audio-separator (BS-Roformer, Demucs等)
PIANO_DIR = CACHE_DIR / "piano"            # piano_transcription_inference (CRNN)
DRUMS_DIR = CACHE_DIR / "mdx23c_models"    # DrumSep / mdx23c


def ensure_cache_dirs() -> None:
    """
    キャッシュディレクトリ群を作成し、
    古い保存場所にファイルが存在する場合は自動的に新しい場所へ引っ越し（マイグレーション）を行う
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    PIANO_DIR.mkdir(parents=True, exist_ok=True)

    # 1. audio-separator の旧パス (/tmp/audio-separator-models) からの引っ越し
    old_separator_dir = Path("/tmp/audio-separator-models")
    if old_separator_dir.exists() and old_separator_dir.is_dir():
        for item in old_separator_dir.iterdir():
            target = MODELS_DIR / item.name
            if not target.exists():
                try:
                    shutil.move(str(item), str(target))
                    print(f"📦 [キャッシュ移行] {item.name} を {MODELS_DIR} に移動しました")
                except Exception:
                    pass

    # 2. ピアノの旧パス (~/piano_transcription_inference_data) からの引っ越し
    old_piano_dir = Path.home() / "piano_transcription_inference_data"
    if old_piano_dir.exists() and old_piano_dir.is_dir():
        for item in old_piano_dir.iterdir():
            target = PIANO_DIR / item.name
            if not target.exists():
                try:
                    shutil.move(str(item), str(target))
                    print(f"📦 [キャッシュ移行] ピアノモデル {item.name} を {PIANO_DIR} に移動しました")
                except Exception:
                    pass
        # 空になった旧ディレクトリは削除を試みる
        try:
            if not any(old_piano_dir.iterdir()):
                old_piano_dir.rmdir()
        except Exception:
            pass


def setup_environment_cache() -> None:
    """
    サードパーティライブラリ（mdx23c等）がキャッシュ先として ~/.cache/midimaker を参照するよう
    プロセス環境変数をセットアップする
    """
    ensure_cache_dirs()
    # mdx23c は XDG_CACHE_HOME を参照してその配下に mdx23c_models を作成する
    os.environ["XDG_CACHE_HOME"] = str(CACHE_DIR)
