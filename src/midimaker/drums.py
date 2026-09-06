"""
ドラム音源（WAV/MP3等）から高精度なMIDIを生成するモジュール
ADTOF Plus (DrumSep + ADTOF Frame_RNN) をベースに、
ドラムパーツ分離、ベロシティ推定、オープン/クローズ判定、ノイズゲートを行います。
"""

from pathlib import Path
from typing import Optional, Union
import numpy as np
import pretty_midi
import soundfile as sf


def filter_drums_by_volume_gate(
    midi_path: Path,
    audio_path: Path,
    min_volume_db: float = -45.0,
) -> None:
    """
    生成されたドラムMIDIに対し、元の音声波形の実効音量（RMS）が
    閾値（dB）未満の微弱ノイズ区間に発音されたノートを除外する
    """
    midi = pretty_midi.PrettyMIDI(str(midi_path))
    audio, sr = sf.read(str(audio_path))
    if audio.ndim > 1:
        audio = audio.mean(axis=1)

    audio_len = len(audio)

    for instrument in midi.instruments:
        gated_notes: list[pretty_midi.Note] = []
        for note in instrument.notes:
            # ドラムのアタック（打撃）瞬間（50ms間）の実効音量を計算
            start_idx = max(0, int(note.start * sr))
            end_idx = min(audio_len, int((note.start + 0.05) * sr))

            if start_idx >= end_idx:
                continue

            chunk = audio[start_idx:end_idx]
            rms = np.sqrt(np.mean(chunk**2))
            db = 20 * np.log10(rms) if rms > 1e-7 else -100.0

            if db >= min_volume_db:
                gated_notes.append(note)

        instrument.notes = gated_notes

    # フィルタリング後のMIDIで上書き保存
    midi.write(str(midi_path))


def transcribe_drums(
    audio_path: Union[str, Path],
    output_path: Optional[Union[str, Path]] = None,
    input_is_mix: bool = False,
    default_threshold: float = -float("inf"),
    min_volume_db: Optional[float] = -45.0,
    tempo_file: Optional[Union[str, Path]] = None,
    tempo_tolerance: float = 0.8,
) -> Path:
    """
    ドラム音源を解析し、General MIDI規格のドラムMIDIファイルを出力する

    Parameters:
        audio_path: 入力音声ファイル（WAV, MP3, FLAC等）
        output_path: 出力先MIDIファイルパス（省略時は入力と同じディレクトリに _drums.mid で保存）
        input_is_mix: フルミックス音源の場合はTrue（ドラム分離を行う）。
                      すでにステム分離されたドラム音源の場合はFalse（高速処理）。
        default_threshold: ADTOFのOnset検出閾値
        min_volume_db: ノイズゲート音量閾値（dB）。これ以下の微弱音・無音区間のノートを除外
        tempo_file: マージするテンポMIDIファイルパス、またはテンポ解析元の音声ファイルパス
        tempo_tolerance: テンポ解析時の揺らぎ平滑化許容幅（BPM、デフォルト: 0.8）

    Returns:
        生成されたドラムMIDIファイルの Path オブジェクト
    """
    audio_file = Path(audio_path).resolve()
    if not audio_file.exists():
        raise FileNotFoundError(f"音声ファイルが見つかりません: {audio_file}")

    if output_path is None:
        output_file = audio_file.with_name(f"{audio_file.stem}_drums.mid")
    else:
        output_file = Path(output_path).resolve()

    print(f"🥁 [MIDImaker] ドラム音源を解析中: {audio_file.name}")
    print(f"   ├─ 入力モード: {'フルミックス（自動分離）' if input_is_mix else 'ドラムステム（パーツ分離＆転写）'}")
    if min_volume_db is not None:
        print(f"   ├─ ノイズゲート: {min_volume_db} dB 以下の微弱音を除外")
    if tempo_file is not None:
        print(f"   ├─ テンポ音源/MIDI: {Path(tempo_file).name} (完了後にマージ)")
    print(f"   └─ 出力先: {output_file.name}")

    # ADTOF Plus の推論モジュールを遅延インポート
    from adtof_plus_drum_transcription.core import transcribe_drums as adtof_transcribe_drums

    output_file.parent.mkdir(parents=True, exist_ok=True)

    # ドラムパーツ分離 ＆ ADTOF MIDI転写を実行
    adtof_transcribe_drums(
        audio_path=str(audio_file),
        output_path=str(output_file),
        input_is_mix=input_is_mix,
        default_threshold=default_threshold,
    )

    # ノイズゲートフィルターの適用
    if min_volume_db is not None and output_file.exists():
        print(f"🧹 ノイズゲート（音量閾値: {min_volume_db} dB）を適用中...")
        filter_drums_by_volume_gate(
            midi_path=output_file,
            audio_path=audio_file,
            min_volume_db=min_volume_db,
        )

    # テンポ情報のマージ（テンポMIDIまたは音声ファイルが指定されている場合）
    if tempo_file is not None and output_file.exists():
        from midimaker.tempo import merge_tempo_into_midi

        merge_tempo_into_midi(
            target_midi_path=output_file,
            tempo_source=tempo_file,
            tolerance_bpm=tempo_tolerance,
        )

    print(f"✨ [完了] ドラムMIDIを出力しました: {output_file}")
    return output_file

