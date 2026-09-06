"""
ベース音源（WAV/MP3等）からクリーンなMIDIを生成するモジュール
Basic Pitchをベースに、低域最適化とモノフォニック（単音）整形を行います。
"""

import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Optional, Union
import pretty_midi


@contextmanager
def suppress_c_stdout():
    """
    CoreMLやC++バックエンドなどのネイティブ層が出力する
    不要なデバッグプリント（shape/isfinite等）を抑制するコンテキストマネージャ
    """
    # バッファ内の出力を事前に画面へ出し切る
    sys.stdout.flush()
    sys.stderr.flush()
    try:
        # /dev/null をオープン
        null_fd = os.open(os.devnull, os.O_RDWR)
        # 現在の stdout, stderr のファイルディスクリプタを退避
        save_stdout_fd = os.dup(1)
        save_stderr_fd = os.dup(2)
        # stdout, stderr を /dev/null にリダイレクト
        os.dup2(null_fd, 1)
        os.dup2(null_fd, 2)
        yield
    finally:
        # 元の stdout, stderr に復元
        os.dup2(save_stdout_fd, 1)
        os.dup2(save_stderr_fd, 2)
        os.close(null_fd)
        os.close(save_stdout_fd)
        os.close(save_stderr_fd)


def make_monophonic(instrument: pretty_midi.Instrument) -> pretty_midi.Instrument:
    """
    ベースパートをモノフォニック（単音）に整形する関数
    
    - 同時発音がある場合: より低いピッチ（ベースの基音）を優先
    - 音が被っている場合: 次のノートが発音されたタイミングで前のノートを終了
    """
    if not instrument.notes:
        return instrument

    # 開始時間順、同じ開始時間ならピッチが低い順（基音優先）にソート
    sorted_notes = sorted(instrument.notes, key=lambda n: (n.start, n.pitch))

    monophonic_notes: list[pretty_midi.Note] = []

    for current_note in sorted_notes:
        if not monophonic_notes:
            monophonic_notes.append(current_note)
            continue

        prev_note = monophonic_notes[-1]

        # 1. ほぼ同時に鳴った音（誤差15ms以内）の場合:
        # すでにピッチ昇順でソートされているので、最初に追加された低い音（基音）を保持し、
        # 高い方の音（倍音誤検出の可能性大）はスキップする
        if abs(current_note.start - prev_note.start) < 0.015:
            continue

        # 2. 前のノートが鳴っている最中に次のノートが始まった場合:
        # 前のノートの終了時間を次のノートの開始時間に揃えてカット（チョーク）する
        if prev_note.end > current_note.start:
            prev_note.end = current_note.start

        # ノートの長さが正である場合のみ追加
        if current_note.end > current_note.start:
            monophonic_notes.append(current_note)

    # 整形したノートリストで更新
    instrument.notes = monophonic_notes
    return instrument


def filter_by_volume_gate(
    instrument: pretty_midi.Instrument,
    audio_path: Path,
    min_volume_db: float = -45.0,
) -> pretty_midi.Instrument:
    """
    元の音声波形の音量（RMS）をノート区間ごとに計算し、
    指定したデシベル（dB）未満の微小ノイズノートを除去するノイズゲート関数
    """
    import numpy as np
    import soundfile as sf

    audio, sr = sf.read(str(audio_path))
    # ステレオの場合はモノラル化
    if audio.ndim > 1:
        audio = audio.mean(axis=1)

    audio_len = len(audio)
    gated_notes: list[pretty_midi.Note] = []

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
    return instrument


def transcribe_bass(
    audio_path: Union[str, Path],
    output_path: Optional[Union[str, Path]] = None,
    onset_threshold: float = 0.55,
    frame_threshold: float = 0.35,
    minimum_note_length: float = 80.0,
    min_freq: float = 30.0,
    max_freq: float = 800.0,
    min_volume_db: Optional[float] = -45.0,
    monophonic: bool = True,
    midi_tempo: float = 120.0,
    tempo_file: Optional[Union[str, Path]] = None,
    tempo_tolerance: float = 0.8,
) -> Path:
    """
    ベース音源を解析し、MIDIファイルを出力する

    Parameters:
        audio_path: 入力音声ファイル（WAV, MP3, FLAC等）
        output_path: 出力先MIDIファイルパス（省略時は入力と同じディレクトリに _bass.mid で保存）
        onset_threshold: 発音（アタック）の検出閾値（0.0〜1.0）。上げるほど誤検出が減る
        frame_threshold: 音の持続判定の閾値（0.0〜1.0）
        minimum_note_length: 最小ノート長（ミリ秒）。短すぎるノイズを除外
        min_freq: 検出する最低周波数（Hz）。5弦ベースのLow B (~31Hz) を考慮してデフォルト30Hz
        max_freq: 検出する最高周波数（Hz）。ベース帯域に絞り高域ノイズ・他パート漏れをカット
        min_volume_db: ノイズゲート音量閾値（dB）。これ以下の微小音・無音区間のノートを除外
        monophonic: Trueの場合、和音重複を解消して単音ラインに整形
        midi_tempo: 出力MIDIのデフォルトテンポ（BPM）
        tempo_file: マージするテンポMIDIファイルパス、またはテンポ解析元の音声ファイルパス
        tempo_tolerance: テンポ解析時の揺らぎ平滑化許容幅（BPM、デフォルト: 0.8）

    Returns:
        生成されたMIDIファイルの Path オブジェクト
    """
    audio_file = Path(audio_path).resolve()
    if not audio_file.exists():
        raise FileNotFoundError(f"音声ファイルが見つかりません: {audio_file}")

    if output_path is None:
        output_file = audio_file.with_name(f"{audio_file.stem}_bass.mid")
    else:
        output_file = Path(output_path).resolve()

    print(f"🎸 [MIDImaker] ベース音源を解析中: {audio_file.name}")
    print(f"   ├─ 周波数範囲: {min_freq} Hz ~ {max_freq} Hz")
    print(f"   ├─ 感度設定: Onset={onset_threshold}, Frame={frame_threshold}, MinLength={minimum_note_length}ms")
    if min_volume_db is not None:
        print(f"   ├─ ノイズゲート: {min_volume_db} dB 以下の微弱音を除外")
    print(f"   ├─ 単音化 (Monophonic): {'有効' if monophonic else '無効'}")
    if tempo_file is not None:
        print(f"   ├─ テンポ音源/MIDI: {Path(tempo_file).name} (完了後にマージ)")
    print(f"   └─ 出力先: {output_file.name}")

    # 不要なC層/CoreML等のデバッグ出力や警告を抑制しながら Basic Pitch で推論実行
    with suppress_c_stdout():
        from basic_pitch.inference import predict

        _, midi_data, _ = predict(
            audio_path=audio_file,
            onset_threshold=onset_threshold,
            frame_threshold=frame_threshold,
            minimum_note_length=minimum_note_length,
            minimum_frequency=min_freq,
            maximum_frequency=max_freq,
            multiple_pitch_bends=False,  # ベースラインを安定させるためOFF
            midi_tempo=midi_tempo,
        )

    # 1. 音量ノイズゲート処理（休符や無音区間のヒスノイズ誤検出を一掃）
    if min_volume_db is not None:
        for instrument in midi_data.instruments:
            if not instrument.is_drum:
                filter_by_volume_gate(instrument, audio_file, min_volume_db=min_volume_db)

    # 2. モノフォニック（単音）整形処理
    if monophonic:
        for instrument in midi_data.instruments:
            # ドラム以外のトラックを整形
            if not instrument.is_drum:
                make_monophonic(instrument)

    # 出力先ディレクトリが存在しない場合は作成
    output_file.parent.mkdir(parents=True, exist_ok=True)

    # MIDIファイル書き出し
    midi_data.write(str(output_file))

    # 3. テンポ情報のマージ（テンポMIDIまたは音声ファイルが指定されている場合）
    if tempo_file is not None and output_file.exists():
        from midimaker.tempo import merge_tempo_into_midi

        merge_tempo_into_midi(
            target_midi_path=output_file,
            tempo_source=tempo_file,
            tolerance_bpm=tempo_tolerance,
        )

    print(f"✨ [完了] ベースMIDIを出力しました: {output_file}")
    return output_file

