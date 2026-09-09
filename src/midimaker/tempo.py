"""
楽曲（フルミックスやステム音源）からテンポ（BPM）とビートを解析し、
テンポマップ情報のみを含むMIDIファイル（Conductor / Tempo Track）を生成するモジュール
"""

from pathlib import Path
from typing import List, Optional, Tuple, Union
import mido
import numpy as np


def extract_tempo_and_beats(
    audio_path: Union[str, Path],
) -> Tuple[float, List[float], float]:
    """
    音声ファイルから楽曲全体の代表BPM、ビート時刻配列（秒）、信頼度を抽出する。

    Parameters:
        audio_path: 音声ファイルのパス (MP3, WAV, FLAC, M4A等)

    Returns:
        tuple: (overall_bpm, beat_times_in_seconds, confidence)
    """
    audio_file = Path(audio_path).resolve()
    if not audio_file.exists():
        raise FileNotFoundError(f"音声ファイルが見つかりません: {audio_file}")

    # librosaで音声をロード（モノラル, 44.1kHz）
    # 幅広い音声フォーマット（MP3, M4A, FLAC, WAV等）を確実にデコード
    import librosa

    audio, sr = librosa.load(str(audio_file), sr=44100, mono=True)
    audio_float32 = audio.astype(np.float32)

    # 1. Essentia RhythmExtractor2013 による高速・高精度なリズム抽出
    try:
        import essentia.standard as es

        rhythm_extractor = es.RhythmExtractor2013(method="multifeature")
        bpm, beats, confidence, _, _ = rhythm_extractor(audio_float32)
        beat_times = [float(b) for b in beats]
        return float(bpm), beat_times, float(confidence)

    except Exception as e:
        # Essentia が失敗した場合は librosa にフォールバック
        print(f"⚠️ Essentiaでのリズム抽出に失敗したため、librosaにフォールバックします: {e}")
        tempo, beat_frames = librosa.beat.beat_track(y=audio, sr=sr)
        beat_times = librosa.frames_to_time(beat_frames, sr=sr).tolist()
        bpm_val = float(tempo[0]) if hasattr(tempo, "__len__") else float(tempo)
        return bpm_val, beat_times, 1.0


def calculate_tempo_map(
    overall_bpm: float,
    beat_times: List[float],
    min_bpm: float = 40.0,
    max_bpm: float = 300.0,
    tolerance_bpm: float = 0.8,
    min_change_bpm: float = 0.1,
) -> List[Tuple[float, float]]:
    """
    ビート時刻列から各拍ごとの局所BPMを計算し、テンポマップのキーポイント列を生成する。
    微小な揺らぎ（ジッター）は適応型セグメンテーションで平均化してイベント連打を防ぎつつ、
    徐々に加速・減速するリタルダンド（rit.）やアッチェランド（accel.）は確実に追従する。

    Parameters:
        overall_bpm: 楽曲全体の代表BPM
        beat_times: ビート発生時刻（秒）のリスト
        min_bpm: 許容する最小BPM
        max_bpm: 許容する最大BPM
        tolerance_bpm: 同一区間のテンポ揺らぎとみなして平均化する最大変動幅（BPM）。
                       0.0以下の場合は平滑化を行わず毎拍出力する。
        min_change_bpm: 新たなテンポチェンジイベントを出力するための直前イベントとの最小BPM差。

    Returns:
        list of (time_in_seconds, bpm)
    """
    tempo_points: List[Tuple[float, float]] = []

    # 0.0 秒時点の初期テンポを設定
    initial_bpm = round(overall_bpm, 2)
    tempo_points.append((0.0, initial_bpm))

    if len(beat_times) < 2:
        return tempo_points

    # 各拍区間における局所テンポ（BPM）を算出
    raw_points: List[Tuple[float, float]] = []
    for i in range(len(beat_times) - 1):
        t_start = beat_times[i]
        t_end = beat_times[i + 1]
        dt = t_end - t_start

        if dt <= 0.02:
            # 異常に短い間隔はスキップ
            continue

        local_bpm = 60.0 / dt

        # 誤検出による極端なオクターブ飛び（2倍速/半速）の簡易補正
        # 代表BPMに対して極端に乖離している場合はクリップ
        if local_bpm < min_bpm:
            local_bpm = min_bpm
        elif local_bpm > max_bpm:
            local_bpm = max_bpm

        raw_points.append((t_start, local_bpm))

    if not raw_points:
        return tempo_points

    # 平滑化が無効（tolerance_bpm <= 0）の場合は全拍をそのまま出力
    if tolerance_bpm <= 0.0:
        for t_start, local_bpm in raw_points:
            if t_start > 0.05:
                tempo_points.append((t_start, round(local_bpm, 2)))
        return tempo_points

    # 適応型セグメンテーション（Adaptive Segmentation）による揺らぎ平均化
    # 変動幅（max - min）が tolerance_bpm 以内に収まる区間を同一グループとしてまとめ、
    # 区間終了時にその平均BPMを代表値として出力する。
    # 徐々に変化するトレンド（rit./accel.）は変動幅を超えた時点で次の区間へ移行するため正確に追従可能。
    seg_times: List[float] = [raw_points[0][0]]
    seg_bpms: List[float] = [raw_points[0][1]]
    last_emitted_bpm = initial_bpm

    for t_start, bpm in raw_points[1:]:
        curr_min = min(min(seg_bpms), bpm)
        curr_max = max(max(seg_bpms), bpm)

        if curr_max - curr_min <= tolerance_bpm:
            # 許容揺らぎ範囲内: セグメントを継続
            seg_times.append(t_start)
            seg_bpms.append(bpm)
        else:
            # 許容範囲を超過: 直前までのセグメントの平均BPMを計算して確定
            avg_bpm = round(float(np.mean(seg_bpms)), 2)
            seg_start_time = seg_times[0]

            # 0.05秒以前の頭出し直後を除き、直前のテンポと有意な差があれば出力
            if seg_start_time > 0.05 and abs(avg_bpm - last_emitted_bpm) >= min_change_bpm:
                tempo_points.append((seg_start_time, avg_bpm))
                last_emitted_bpm = avg_bpm

            # 新しいセグメントを開始
            seg_times = [t_start]
            seg_bpms = [bpm]

    # 末尾の残余セグメントを確定出力
    if seg_bpms:
        avg_bpm = round(float(np.mean(seg_bpms)), 2)
        seg_start_time = seg_times[0]
        if seg_start_time > 0.05 and abs(avg_bpm - last_emitted_bpm) >= min_change_bpm:
            tempo_points.append((seg_start_time, avg_bpm))

    return tempo_points


def create_tempo_midi_file(
    tempo_points: List[Tuple[float, float]],
    ticks_per_beat: int = 480,
) -> mido.MidiFile:
    """
    テンポチェンジ情報のみを含むStandard MIDI File (Type 1) を生成する。

    Parameters:
        tempo_points: (time_in_seconds, bpm) のリスト（時刻昇順）
        ticks_per_beat: MIDIの分解能 (PPQ / ticks per quarter note)

    Returns:
        mido.MidiFile オブジェクト
    """
    mid = mido.MidiFile(type=1, ticks_per_beat=ticks_per_beat)

    # Track 0: Conductor Track (テンポ & 拍子情報)
    track = mido.MidiTrack()
    mid.tracks.append(track)

    # トラック名と拍子（4/4）を設定
    track.append(mido.MetaMessage("track_name", name="Tempo Track", time=0))
    track.append(
        mido.MetaMessage(
            "time_signature",
            numerator=4,
            denominator=4,
            clocks_per_click=24,
            notated_32nd_notes_per_beat=8,
            time=0,
        )
    )

    current_time = 0.0
    current_bpm = tempo_points[0][1]

    for i, (t_sec, bpm) in enumerate(tempo_points):
        if i == 0:
            delta_ticks = 0
            current_time = 0.0
        else:
            dt = t_sec - current_time
            if dt < 0:
                dt = 0
            # 直前のBPMにおける tick 換算デルタタイム
            delta_ticks = int(round(dt * (current_bpm * ticks_per_beat) / 60.0))
            current_time = t_sec

        tempo_val = mido.bpm2tempo(bpm)
        track.append(mido.MetaMessage("set_tempo", tempo=tempo_val, time=delta_ticks))
        current_bpm = bpm

    # トラック末尾の終了イベント
    track.append(mido.MetaMessage("end_of_track", time=ticks_per_beat))

    return mid


def export_tempo_midi(
    audio_path: Union[str, Path],
    output_path: Optional[Union[str, Path]] = None,
    fixed_tempo: bool = False,
    tolerance_bpm: float = 0.8,
) -> Path:
    """
    音声ファイルからテンポを解析し、テンポ専用MIDIファイルを出力するメイン関数。

    Parameters:
        audio_path: 入力音声ファイル（フルミックス、ステム等）
        output_path: 出力先MIDIファイル（省略時は入力と同じディレクトリに _tempo.mid で保存）
        fixed_tempo: Trueの場合、テンポマップではなく全体代表BPM単一で出力
        tolerance_bpm: 同一区間のテンポ揺らぎとみなして平均化する最大変動幅（BPM、デフォルト: 0.8）

    Returns:
        生成されたMIDIファイルの Path オブジェクト
    """
    audio_file = Path(audio_path).resolve()
    if not audio_file.exists():
        raise FileNotFoundError(f"音声ファイルが見つかりません: {audio_file}")

    if output_path is None:
        output_file = audio_file.with_name(f"{audio_file.stem}_tempo.mid")
    else:
        output_file = Path(output_path).resolve()

    print(f"⏱️ [MIDImaker] 楽曲のテンポを解析中: {audio_file.name}")
    print(f"   ├─ 出力モード: {'固定BPM (代表テンポ単一)' if fixed_tempo else 'テンポマップ (可変ビート追従)'}")
    if not fixed_tempo:
        print(f"   ├─ 揺らぎ平滑化許容幅: {tolerance_bpm} BPM")
    print(f"   └─ 出力先: {output_file.name}")

    # テンポとビートを解析
    overall_bpm, beat_times, confidence = extract_tempo_and_beats(audio_file)

    print(f"   ├─ 推定代表テンポ: {overall_bpm:.2f} BPM (検出ビート数: {len(beat_times)}拍, 信頼度: {confidence:.2f})")

    if fixed_tempo or len(beat_times) < 2:
        # 固定BPMモード
        tempo_points = [(0.0, round(overall_bpm, 2))]
    else:
        # テンポマップモード（適応型セグメンテーションによる揺らぎ平均化）
        tempo_points = calculate_tempo_map(overall_bpm, beat_times, tolerance_bpm=tolerance_bpm)
        print(f"   ├─ 生成テンポチェンジ数: {len(tempo_points)} ポイント")

    # MIDIファイル作成
    mid = create_tempo_midi_file(tempo_points)

    output_file.parent.mkdir(parents=True, exist_ok=True)
    mid.save(str(output_file))

    print(f"✨ [完了] テンポMIDIを出力しました: {output_file}")
    return output_file


def parse_tempo_input(
    tempo_val: Optional[Union[float, int, str, Path]],
) -> Tuple[Optional[float], Optional[Path]]:
    """
    テンポ引数（数値BPMまたはファイルパス）を判定・解析するヘルパー関数。

    Parameters:
        tempo_val: BPM数値（float/int、または数値文字列 "120" 等）、
                   またはテンポMIDI/解析元音声のファイルパス（str, Path）

    Returns:
        tuple: (bpm, tempo_file)
            - 数値の場合: (float(bpm), None)
            - ファイルパスの場合: (None, Path(tempo_file))
            - None または空文字の場合: (None, None)
    """
    if tempo_val is None:
        return None, None

    if isinstance(tempo_val, (int, float)):
        return float(tempo_val), None

    if isinstance(tempo_val, Path):
        return None, tempo_val

    val_str = str(tempo_val).strip()
    if not val_str:
        return None, None

    # 数値文字列かどうかを判定（例: "120", "140.5"）
    try:
        bpm = float(val_str)
        if bpm > 0:
            return bpm, None
    except ValueError:
        pass

    # 数値に変換できない文字列はファイルパスとして解釈
    return None, Path(val_str)


def merge_tempo_into_midi(
    target_midi_path: Union[str, Path],
    tempo_source: Union[str, Path, float, int],
    tolerance_bpm: float = 0.8,
) -> None:
    """
    ドラムやベースなどのMIDIファイルに、テンポ情報（固定BPM数値、MIDIファイル、または音声ファイルから抽出）を
    解像度（PPQ）の整合性を保ちながらマージ（上書き保存）する。
    ノートの実時間（秒）を厳密に保持し、新しいテンポマップのグリッドに再配置する。

    Parameters:
        target_midi_path: テンポをマージする対象のMIDIファイル（ドラムMIDI等）
        tempo_source: テンポ情報の提供元（float/int等の数値BPM、.mid/.midi ファイル、または音声ファイル .mp3/.wav/.m4a 等）
        tolerance_bpm: 音声からテンポ抽出する際の揺らぎ平滑化許容幅（BPM、デフォルト: 0.8）
    """
    import pretty_midi

    target_file = Path(target_midi_path).resolve()
    if not target_file.exists():
        raise FileNotFoundError(f"対象MIDIファイルが見つかりません: {target_file}")

    # 数値BPMかファイルパスかを判定
    bpm_val, file_path = parse_tempo_input(tempo_source)

    if bpm_val is not None:
        # 1-a. 数値BPMが指定された場合: 単一の固定テンポを設定
        times_list = [0.0]
        bpms_list = [bpm_val]
    elif file_path is not None:
        # 1-b. ファイルパスが指定された場合: MIDIファイルまたは音声ファイルからテンポ抽出
        source_path = file_path.resolve()
        if not source_path.exists():
            raise FileNotFoundError(f"テンポ音源/MIDIファイルが見つかりません: {source_path}")

        suffix = source_path.suffix.lower()
        if suffix in [".mid", ".midi"]:
            # テンポMIDIファイルから取得
            pm_source = pretty_midi.PrettyMIDI(str(source_path))
            times, bpms = pm_source.get_tempo_changes()
            times_list = times.tolist()
            bpms_list = bpms.tolist()
        else:
            # 音声ファイルからその場でテンポ解析
            print(f"⏱️ テンポ音源（{source_path.name}）からビート解析を実行中...")
            overall_bpm, beat_times, _ = extract_tempo_and_beats(source_path)
            tempo_points = calculate_tempo_map(overall_bpm, beat_times, tolerance_bpm=tolerance_bpm)
            times_list = [t for t, _ in tempo_points]
            bpms_list = [b for _, b in tempo_points]
    else:
        print("⚠️ テンポ情報が指定されていないため、マージをスキップします")
        return

    if not times_list:
        print("⚠️ テンポ情報が取得できなかったため、マージをスキップします")
        return

    # 2. 対象MIDIを読み込み、解像度に合わせて _tick_scales を再構築
    pm_target = pretty_midi.PrettyMIDI(str(target_file))
    res = pm_target.resolution

    tick_scales = []
    current_tick = 0
    current_time = 0.0

    for i, (t_sec, bpm) in enumerate(zip(times_list, bpms_list)):
        tick_scale = 60.0 / (bpm * res)
        if i == 0:
            tick_scales.append((0, tick_scale))
            current_tick = 0
            current_time = 0.0
        else:
            prev_tick_scale = tick_scales[-1][1]
            dt = t_sec - current_time
            if dt < 0:
                dt = 0
            delta_ticks = int(round(dt / prev_tick_scale))
            current_tick += delta_ticks
            current_time = t_sec
            tick_scales.append((current_tick, tick_scale))

    pm_target._tick_scales = tick_scales

    # ノートが存在する場合は最大tickを計算してタイムライン更新
    max_note_end = 0.0
    for inst in pm_target.instruments:
        for note in inst.notes:
            if note.end > max_note_end:
                max_note_end = note.end

    max_tick = pm_target.time_to_tick(max_note_end + 5.0) + int(res * 10)
    pm_target._update_tick_to_time(max_tick)

    # 3. 上書き保存
    pm_target.write(str(target_file))
    print(f"🔗 [マージ完了] テンポ情報（初期 {bpms_list[0]:.2f} BPM, {len(bpms_list)}ポイント）を {target_file.name} に統合しました")

