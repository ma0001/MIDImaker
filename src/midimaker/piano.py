"""
ピアノ音源（WAV/MP3等）から高精度なMIDIを生成するモジュール
ByteDanceの piano_transcription_inference をベースに、
和音（ポリフォニック）、ベロシティ、サステインペダル（CC64）の検出、
およびノイズゲート・連打デバウンス・半音衝突抑制・テンポマップ同期を行います。
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


def filter_debounce_notes(
    instrument,
    debounce_ms: int = 120,
) -> int:
    """
    エコー、ディレイ、リバーブの跳ね返りやサステイン揺らぎによる
    同一ピッチの連続誤検知（マシンガン連打・ゴーストノート）を抑制するデバウンス関数。

    Parameters:
        instrument: pretty_midi の Instrument オブジェクト
        debounce_ms: 連打とみなす最小発音間隔（ミリ秒）。
                     直前ノートからこの時間未満、または直前ノートが持続中に
                     同等以下の音量で再発音された場合、エコーとみなして直前ノートに統合（タイ化）する。

    Returns:
        除去・マージされたゴーストノート数
    """
    if debounce_ms <= 0 or not instrument.notes:
        return 0

    min_gap_sec = debounce_ms / 1000.0
    notes_by_pitch = {}
    for n in instrument.notes:
        notes_by_pitch.setdefault(n.pitch, []).append(n)

    cleaned_notes = []
    removed_count = 0

    for pitch, p_notes in notes_by_pitch.items():
        # 発音開始時刻順にソート
        p_notes.sort(key=lambda x: x.start)
        last_note = None

        for n in p_notes:
            if last_note is None:
                last_note = n
                cleaned_notes.append(n)
            else:
                gap = n.start - last_note.start
                # 判定: 最小間隔未満での発音、または直前ノートが持続中の減衰再発音
                is_rapid_repeat = gap < min_gap_sec
                is_overlap_ghost = (n.start < last_note.end) and (n.velocity <= last_note.velocity * 1.05)

                if is_rapid_repeat or is_overlap_ghost:
                    # エコー・残響の跳ね返りと判定して直前ノートの終端を延長（タイ結合）
                    last_note.end = max(last_note.end, n.end)
                    removed_count += 1
                else:
                    last_note = n
                    cleaned_notes.append(n)

    # 全ノートを開始時刻順に再ソートして書き戻し
    cleaned_notes.sort(key=lambda x: (x.start, x.pitch))
    instrument.notes = cleaned_notes
    return removed_count


def filter_short_and_quiet_notes(
    instrument,
    min_duration_ms: int = 40,
    min_velocity: int = 25,
) -> tuple[int, int]:
    """
    物理的な打鍵ではあり得ない極小持続時間（チリチリした打撃ノイズや分離アーティファクト）や
    微弱ベロシティ（ゴーストノート）を除去する関数。

    Parameters:
        instrument: pretty_midi の Instrument オブジェクト
        min_duration_ms: 最小持続ミリ秒（これ未満のノートを除去、0で無効）
        min_velocity: 最小ベロシティ（これ未満のノートを除去、0で無効）

    Returns:
        (短小ノート除去数, 微弱ノート除去数)
    """
    if not instrument.notes:
        return 0, 0

    min_duration_sec = (min_duration_ms / 1000.0) if min_duration_ms > 0 else 0.0
    cleaned_notes = []
    removed_short = 0
    removed_quiet = 0

    for note in instrument.notes:
        duration = note.end - note.start
        # 1. 最小持続時間チェック (40ms未満などの極短ノイズ)
        if min_duration_sec > 0 and duration < min_duration_sec:
            removed_short += 1
            continue
        # 2. 最小ベロシティチェック (25未満などの微弱ゴースト音)
        if min_velocity > 0 and note.velocity < min_velocity:
            removed_quiet += 1
            continue
        cleaned_notes.append(note)

    instrument.notes = cleaned_notes
    return removed_short, removed_quiet


def filter_semitone_clash(
    instrument,
    clash_window_ms: int = 80,
    velocity_ratio: float = 0.85,
    min_overlap_ratio: float = 0.3,
) -> int:
    """
    半音（短2度: ピッチ差1）離れたノートが時間的に重複している場合、
    音響リークや分離アーティファクトによる不協和音ゴーストノートを検出し、
    弱い側を除去するインテリジェントフィルター。

    Parameters:
        instrument: pretty_midi の Instrument オブジェクト
        clash_window_ms: 同時発音とみなすアタック時間差（ミリ秒）。
                         この時間差以内の半音衝突は、ベロシティが低い側を確実にゴーストと判定。
        velocity_ratio: ゴースト判定のベロシティ比率閾値（弱い方のvelocity / 強い方のvelocity）。
                        同時発音時または重複時に、この比率以下なら弱い方を削除。
        min_overlap_ratio: 重なり時間の比率閾値（短い方のノート長に対する重複割合）。

    Returns:
        除去された半音ゴーストノート数
    """
    if not instrument.notes:
        return 0

    # 発音開始時刻順にソート
    notes = sorted(instrument.notes, key=lambda x: (x.start, x.pitch))
    clash_window_sec = clash_window_ms / 1000.0 if clash_window_ms > 0 else 0.08

    to_remove = set()
    n_count = len(notes)

    for i in range(n_count):
        n1 = notes[i]
        if id(n1) in to_remove:
            continue

        for j in range(i + 1, n_count):
            n2 = notes[j]
            if id(n2) in to_remove:
                continue

            # n2の開始がn1の終了以降、かつ同時発音ウィンドウ外であれば、これ以降のノートは衝突しない
            if n2.start >= n1.end and (n2.start - n1.start) > clash_window_sec:
                break

            # ピッチ差が半音（1）かチェック
            if abs(n1.pitch - n2.pitch) != 1:
                continue

            # 重なり時間の計算
            overlap = min(n1.end, n2.end) - max(n1.start, n2.start)
            attack_diff = abs(n1.start - n2.start)

            # 重なりがない場合（かつアタックウィンドウ外）はスキップ
            if overlap <= 0 and attack_diff > clash_window_sec:
                continue

            shorter_dur = min(n1.end - n1.start, n2.end - n2.start)
            overlap_ratio = (overlap / shorter_dur) if shorter_dur > 0 else 0.0

            # 判定ロジック:
            # 1. 同時アタック（clash_window_sec 以内）
            # ピアノで半音の同時打鍵は音楽的に極めて稀。
            # 音量が小さい側、または持続が短い側を確実にゴーストとして除去。
            if attack_diff <= clash_window_sec:
                if n1.velocity > n2.velocity:
                    to_remove.add(id(n2))
                elif n2.velocity > n1.velocity:
                    to_remove.add(id(n1))
                    break  # n1が除去されたので内側ループ終了
                else:
                    # ベロシティが全く同一の場合は持続時間が短い方をゴースト判定
                    dur1 = n1.end - n1.start
                    dur2 = n2.end - n2.start
                    if dur1 >= dur2:
                        to_remove.add(id(n2))
                    else:
                        to_remove.add(id(n1))
                        break

            # 2. 時間的重複がある半音（先行音のサステイン中に後続音が鳴る、など）
            # 重複割合が有意で、かつ音量差が大きい（弱い方が強い方の85%以下、または微弱音）場合
            elif overlap_ratio >= min_overlap_ratio:
                # 強い音と弱い音を識別
                if n1.velocity >= n2.velocity:
                    strong_n, weak_n = n1, n2
                    weak_is_n1 = False
                else:
                    strong_n, weak_n = n2, n1
                    weak_is_n1 = True

                is_weak_ratio = weak_n.velocity <= (strong_n.velocity * velocity_ratio)
                is_weak_absolute = weak_n.velocity < 40  # 絶対音量が小さく紛れ込んだゴースト

                if is_weak_ratio or is_weak_absolute:
                    if weak_is_n1:
                        to_remove.add(id(n1))
                        break  # n1が除去されたので内側ループ終了
                    else:
                        to_remove.add(id(n2))

    cleaned_notes = [n for n in notes if id(n) not in to_remove]
    removed_count = len(instrument.notes) - len(cleaned_notes)
    instrument.notes = cleaned_notes
    return removed_count


def transcribe_piano(
    audio_path: Union[str, Path],
    output_path: Optional[Union[str, Path]] = None,
    onset_threshold: float = 0.3,
    frame_threshold: float = 0.1,
    pedal_offset_threshold: float = 0.2,
    min_volume_db: Optional[float] = -45.0,
    debounce_ms: Optional[int] = 120,
    filter_semitone: bool = True,
    clash_window_ms: int = 80,
    min_duration_ms: Optional[int] = 40,
    min_velocity: Optional[int] = 25,
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
        debounce_ms: エコー・残響による同一キー連打抑制ミリ秒（デフォルト: 120ms、0で無効）
        filter_semitone: 半音衝突（短2度ゴースト）除去フィルターを有効にするか（デフォルト: True）
        clash_window_ms: 同時発音とみなすアタック時間差ミリ秒（デフォルト: 80ms）
        min_duration_ms: 最小持続ミリ秒（40ms未満などの極短ノイズノートを除去、0またはNoneで無効）
        min_velocity: 最小ベロシティ（25未満などの微小音量ノートを除去、0またはNoneで無効）
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
    if (min_duration_ms is not None and min_duration_ms > 0) or (min_velocity is not None and min_velocity > 0):
        print(f"   ├─ ノイズ除去: 最小持続={min_duration_ms or 0}ms, 最小Velocity={min_velocity or 0}")
    if debounce_ms is not None and debounce_ms > 0:
        print(f"   ├─ 連打抑制 (デバウンス): {debounce_ms} ms 以内のエコー誤検知をマージ")
    if filter_semitone:
        print(f"   ├─ 半音衝突抑制: 同時発音窓={clash_window_ms}ms (短2度不協和音ゴーストを除去)")
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

    # 後処理（ノイズゲート・短小/微弱カット・連打デバウンス・半音衝突フィルター）
    if output_file.exists():
        pm = pretty_midi.PrettyMIDI(str(output_file))
        modified = False
        for inst in pm.instruments:
            if not inst.is_drum:
                # 1. 音量ノイズゲート
                if min_volume_db is not None:
                    filter_by_volume_gate(inst, audio, sr=sample_rate, min_volume_db=min_volume_db)
                    modified = True

                # 2. 短小ノート＆微弱ベロシティフィルター
                if (min_duration_ms is not None and min_duration_ms > 0) or (
                    min_velocity is not None and min_velocity > 0
                ):
                    rem_short, rem_quiet = filter_short_and_quiet_notes(
                        inst,
                        min_duration_ms=min_duration_ms or 0,
                        min_velocity=min_velocity or 0,
                    )
                    if rem_short > 0 or rem_quiet > 0:
                        print(
                            f"   ├─ 🧹 [ノイズ除去] 極短ノート {rem_short} 件 / 微弱ノート {rem_quiet} 件を除去しました"
                        )
                        modified = True

                # 3. エコー・残響による同一キー連打抑制（デバウンス）
                if debounce_ms is not None and debounce_ms > 0:
                    removed_notes = filter_debounce_notes(inst, debounce_ms=debounce_ms)
                    if removed_notes > 0:
                        print(f"   ├─ 🔇 [連打抑制] エコー/残響による重複ノート {removed_notes} 件をマージ除去しました")
                        modified = True

                # 4. 半音衝突（短2度ゴースト）抑制フィルター
                if filter_semitone:
                    removed_clashes = filter_semitone_clash(
                        inst,
                        clash_window_ms=clash_window_ms,
                    )
                    if removed_clashes > 0:
                        print(f"   ├─ 🎹 [半音衝突抑制] 不協和音ゴーストノート {removed_clashes} 件を除去しました")
                        modified = True

        if modified:
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
