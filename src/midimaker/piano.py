"""
ピアノ音源（WAV/MP3等）から高精度なMIDIを生成するモジュール
ByteDanceの piano_transcription_inference をベースに、
和音（ポリフォニック）、ベロシティ、サステインペダル（CC64）の検出、
およびノイズゲート・テンポマップ同期を行います。
"""

import os
import sys
from pathlib import Path
from typing import Optional, Union
import urllib.request
import numpy as np


from midimaker.paths import PIANO_DIR, ensure_cache_dirs

# モデルのダウンロード先と公式ZenodoのURL
DEFAULT_CHECKPOINT_DIR = PIANO_DIR
DEFAULT_CHECKPOINT_PATH = DEFAULT_CHECKPOINT_DIR / "note_F1=0.9677_pedal_F1=0.9186.pth"
ZENODO_MODEL_URL = (
    "https://zenodo.org/record/4034264/files/CRNN_note_F1%3D0.9677_pedal_F1%3D0.9186.pth?download=1"
)
EXPECTED_MIN_FILE_SIZE = 160 * 1024 * 1024  # 約160MB以上


def ensure_model_checkpoint(checkpoint_path: Optional[Path] = None) -> Path:
    """
    ピアノ採譜モデルの重みファイルが存在するか確認し、
    存在しない場合は安全に自動ダウンロード（プログレス表示付き）を行う関数。
    ※ macOSで標準の wget コマンドがない環境でも urllib を用いて確実に取得します。
    """
    ensure_cache_dirs()
    if checkpoint_path is not None:
        cp = Path(checkpoint_path).resolve()
        if cp.is_dir() or not cp.suffix:
            target_path = cp / DEFAULT_CHECKPOINT_PATH.name
        else:
            target_path = cp
    else:
        target_path = DEFAULT_CHECKPOINT_PATH.resolve()

    if target_path.exists() and target_path.stat().st_size >= EXPECTED_MIN_FILE_SIZE:
        return target_path

    target_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"📥 [MIDImaker] ピアノ採譜モデルの重みをダウンロード中 (約165MB): {target_path.name}")
    print(f"   └─ 保存先: {target_path}")

    # プログレスバー表示用コールバック
    def _progress_hook(block_num: int, block_size: int, total_size: int):
        downloaded = block_num * block_size
        if total_size > 0:
            percent = min(100.0, downloaded * 100.0 / total_size)
            mb_downloaded = downloaded / (1024 * 1024)
            mb_total = total_size / (1024 * 1024)
            sys.stdout.write(f"\r   ├─ 進捗: {percent:5.1f}% [{mb_downloaded:5.1f}MB / {mb_total:5.1f}MB]")
            sys.stdout.flush()
        else:
            mb_downloaded = downloaded / (1024 * 1024)
            sys.stdout.write(f"\r   ├─ 進捗: {mb_downloaded:5.1f}MB ダウンロード完了")
            sys.stdout.flush()

    try:
        urllib.request.urlretrieve(ZENODO_MODEL_URL, str(target_path), reporthook=_progress_hook)
        sys.stdout.write("\n")
        print("   └─ ✨ モデルのダウンロードが完了しました！")
    except Exception as e:
        sys.stdout.write("\n")
        if target_path.exists():
            target_path.unlink(missing_ok=True)
        raise RuntimeError(f"ピアノモデルのダウンロードに失敗しました: {e}") from e

    return target_path


def filter_by_volume_gate(
    instrument,
    audio: np.ndarray,
    sr: int,
    min_volume_db: float = -45.0,
):
    """
    元の音声波形の音量（RMS）をノート区間ごとに計算し、
    指定したデシベル（dB）未満の微小ノイズノートを除去するノイズゲート関数
    """
    audio_len = len(audio)
    gated_notes = []

    for note in instrument.notes:
        start_idx = max(0, int(note.start * sr))
        end_idx = min(audio_len, int(note.end * sr))

        if start_idx >= end_idx:
            continue

        chunk = audio[start_idx:end_idx]
        rms = np.sqrt(np.mean(chunk**2))
        db = 20 * np.log10(rms) if rms > 1e-7 else -100.0

        # 音量が閾値以上のノートのみ採用
        if db >= min_volume_db:
            gated_notes.append(note)

    instrument.notes = gated_notes


def transcribe_piano(
    audio_path: Union[str, Path],
    output_path: Optional[Union[str, Path]] = None,
    onset_threshold: float = 0.3,
    frame_threshold: float = 0.1,
    pedal_offset_threshold: float = 0.2,
    min_volume_db: Optional[float] = -45.0,
    tempo: Optional[Union[float, int, str, Path]] = 120.0,
    tempo_tolerance: float = 0.8,
    device: Optional[str] = None,
    checkpoint_path: Optional[Union[str, Path]] = None,
) -> Path:
    """
    ピアノ音源を解析し、ペダル情報付きの高精度MIDIファイルを出力するメイン関数。

    Parameters:
        audio_path: 入力音声ファイル（WAV, MP3, FLAC等）
        output_path: 出力先MIDIファイルパス（省略時は入力と同じディレクトリに _piano.mid で保存）
        onset_threshold: 発音（アタック）の検出閾値（0.0〜1.0、デフォルト: 0.3）
        frame_threshold: 音の持続判定閾値（0.0〜1.0、デフォルト: 0.1）
        pedal_offset_threshold: ペダル離鍵判定閾値（0.0〜1.0、デフォルト: 0.2）
        min_volume_db: ノイズゲート音量閾値（dB）。これ以下の微小音・無音区間のノートを除外
        tempo: 出力MIDIのテンポBPM数値（例: 120, 140）またはテンポMIDI/解析元音声ファイルパス
        tempo_tolerance: テンポ解析元の音声からテンポ抽出する際の揺らぎ平滑化許容幅（BPM、デフォルト: 0.8）
        device: 実行デバイス ('cpu', 'cuda', 'mps' または None で自動選択)
        checkpoint_path: モデル重みファイルパス（未指定時はデフォルトキャッシュパス）

    Returns:
        生成されたMIDIファイルの Path オブジェクト
    """
    import torch
    import librosa
    import pretty_midi
    from piano_transcription_inference import PianoTranscription, sample_rate
    from midimaker.tempo import parse_tempo_input, merge_tempo_into_midi

    audio_file = Path(audio_path).resolve()
    if not audio_file.exists():
        raise FileNotFoundError(f"音声ファイルが見つかりません: {audio_file}")

    if output_path is None:
        output_file = audio_file.with_name(f"{audio_file.stem}_piano.mid")
    else:
        output_file = Path(output_path).resolve()

    # デバイスの自動判定
    if device is None or device.lower() == "auto":
        if torch.cuda.is_available():
            selected_device = torch.device("cuda")
        elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            # MPSをサポートしている場合はMPSを優先
            selected_device = torch.device("mps")
        else:
            selected_device = torch.device("cpu")
    else:
        selected_device = torch.device(device)

    # テンポ指定の解決
    parsed_bpm, target_tempo_file = parse_tempo_input(tempo)
    inference_bpm = parsed_bpm if parsed_bpm is not None else 120.0

    print(f"🎹 [MIDImaker] ピアノ音源を解析中: {audio_file.name}")
    print(f"   ├─ 実行デバイス: {selected_device}")
    print(
        f"   ├─ 感度設定: Onset={onset_threshold}, Frame={frame_threshold}, PedalOffset={pedal_offset_threshold}"
    )
    if min_volume_db is not None:
        print(f"   ├─ ノイズゲート: {min_volume_db} dB 以下の微弱音を除外")
    if target_tempo_file is not None:
        print(f"   ├─ テンポ音源/MIDI: {target_tempo_file.name} (完了後にマージ)")
    else:
        print(f"   ├─ テンポ: {inference_bpm:.1f} BPM")
    print(f"   └─ 出力先: {output_file.name}")

    # 重みファイルの安全な確保（存在確認＆自動DL）
    cp_path = ensure_model_checkpoint(Path(checkpoint_path) if checkpoint_path else None)

    # 音声の読み込み (piano_transcription_inference は 16kHz モノラルを想定)
    # ※ piano_transcription_inference 付属の load_audio は古い librosa の位置引数 resample() を呼んで
    #   librosa 0.10+ でエラーになるため、標準の librosa.load を使用します
    print("   ├─ 音声データをロード中 (16kHz モノラル)...")
    audio, _ = librosa.load(str(audio_file), sr=sample_rate, mono=True)

    # PianoTranscription インスタンスの生成
    transcriber = PianoTranscription(
        model_type="Note_pedal",
        checkpoint_path=str(cp_path),
        device=selected_device,
    )
    # パラメータ設定の上書き
    transcriber.onset_threshold = onset_threshold
    transcriber.offset_threshod = onset_threshold  # offset判定もアタックに追従
    transcriber.frame_threshold = frame_threshold
    transcriber.pedal_offset_threshold = pedal_offset_threshold

    # 出力先ディレクトリの作成
    output_file.parent.mkdir(parents=True, exist_ok=True)

    # 推論実行＆初期MIDI書き出し
    print("   ├─ ニューラルネットワーク推論を実行中...")
    transcriber.transcribe(audio, str(output_file))

    # ノイズゲート処理
    if min_volume_db is not None and output_file.exists():
        pm = pretty_midi.PrettyMIDI(str(output_file))
        for inst in pm.instruments:
            if not inst.is_drum:
                filter_by_volume_gate(inst, audio, sr=sample_rate, min_volume_db=min_volume_db)
        pm.write(str(output_file))

    # テンポ情報のマージ（テンポMIDI、音声ファイル、またはBPMが指定されている場合）
    if output_file.exists():
        tempo_source = target_tempo_file if target_tempo_file is not None else inference_bpm
        merge_tempo_into_midi(
            target_midi_path=output_file,
            tempo_source=tempo_source,
            tolerance_bpm=tempo_tolerance,
        )

    print(f"✨ [完了] ピアノMIDIを出力しました: {output_file}")
    return output_file
