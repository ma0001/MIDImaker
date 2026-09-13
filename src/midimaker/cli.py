"""
MIDImaker のコマンドラインインターフェース (CLI)
"""

import argparse
import os
import sys
import warnings

# 外部ライブラリの冗長な初期化ログや非推奨警告を抑制してCLI出力をスッキリさせる
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)


def build_parser() -> argparse.ArgumentParser:
    """CLIパーサーを構築する"""
    parser = argparse.ArgumentParser(
        prog="midimaker",
        description="🎵 MIDImaker: 音声ファイルから高精度なMIDIを生成するCLIツール",
    )

    subparsers = parser.add_subparsers(dest="command", help="使用するサブコマンド")

    # ----------------------------------------------------
    # サブコマンド: bass (ベース音源からMIDI生成)
    # ----------------------------------------------------
    bass_parser = subparsers.add_parser(
        "bass",
        help="ステム分離されたベース音源からクリーンなMIDIを生成",
        description="Spotify Basic Pitchをベースに、低音域最適化＆モノフォニック整形を行ってベースMIDIを出力します。",
    )

    bass_parser.add_argument(
        "input",
        type=str,
        help="入力音声ファイルのパス (WAV, MP3, FLAC等)",
    )
    bass_parser.add_argument(
        "-o", "--output",
        type=str,
        default=None,
        help="出力先MIDIファイルパス (省略時は入力ファイル名_bass.mid)",
    )
    bass_parser.add_argument(
        "--onset-threshold",
        type=float,
        default=0.55,
        help="アタック（Onset）の検出閾値 (0.0〜1.0, デフォルト: 0.55)",
    )
    bass_parser.add_argument(
        "--frame-threshold",
        type=float,
        default=0.35,
        help="音の持続フレーム判定の閾値 (0.0〜1.0, デフォルト: 0.35)",
    )
    bass_parser.add_argument(
        "--min-note-length",
        type=float,
        default=80.0,
        help="最小ノート長 (ミリ秒, デフォルト: 80.0ms)",
    )
    bass_parser.add_argument(
        "--min-freq",
        type=float,
        default=30.0,
        help="検出する最低周波数 (Hz, デフォルト: 30.0Hz)",
    )
    bass_parser.add_argument(
        "--max-freq",
        type=float,
        default=800.0,
        help="検出する最高周波数 (Hz, デフォルト: 800.0Hz)",
    )
    bass_parser.add_argument(
        "--min-volume-db",
        type=float,
        default=-45.0,
        help="ノイズゲートの音量閾値 dB (デフォルト: -45.0dB)。これ以下の微小音・無音区間のノートを除外 (無効にする場合は -999 等を指定)",
    )
    bass_parser.add_argument(
        "--no-monophonic",
        action="store_true",
        help="単音化（モノフォニック）整形を無効にする（和音重複を許可する場合に指定）",
    )
    bass_parser.add_argument(
        "-t", "--tempo",
        type=str,
        default="120.0",
        help="MIDIのテンポBPM数値（例: 120, 140）またはマージするテンポMIDI/解析元音声ファイルパス（.mid, .mp3等。デフォルト: 120.0）",
    )
    bass_parser.add_argument(
        "--tempo-tolerance",
        type=float,
        default=0.8,
        help="テンポ解析元の音声からテンポ抽出する際の揺らぎ平滑化許容幅 BPM (デフォルト: 0.8BPM)",
    )

    # ----------------------------------------------------
    # サブコマンド: drums (ドラム音源からMIDI生成)
    # ----------------------------------------------------
    drums_parser = subparsers.add_parser(
        "drums",
        help="ドラム音源から高精度なMIDI（Kick/Snare/HH/Cymbal/Tom）を生成",
        description="ADTOF Plusをベースに、ドラムキット分離・ベロシティ推定・オープン/クローズ判定を行ってGeneral MIDIドラムを出力します。",
    )

    drums_parser.add_argument(
        "input",
        type=str,
        help="入力音声ファイルのパス (WAV, MP3, FLAC等)",
    )
    drums_parser.add_argument(
        "-o", "--output",
        type=str,
        default=None,
        help="出力先MIDIファイルパス (省略時は入力ファイル名_drums.mid)",
    )
    drums_parser.add_argument(
        "--from-mix",
        action="store_true",
        help="フルミックス楽曲からドラムを分離してMIDI化する場合に指定（デフォルトはドラムステム音源想定）",
    )
    drums_parser.add_argument(
        "--min-volume-db",
        type=float,
        default=-45.0,
        help="ノイズゲートの音量閾値 dB (デフォルト: -45.0dB)。無音区間・ヒスノイズによる誤発火ノートを除去 (無効にする場合は -999 等を指定)",
    )
    drums_parser.add_argument(
        "--threshold",
        type=float,
        default=-float("inf"),
        help="Onset検出の閾値 (デフォルト: -inf)",
    )
    drums_parser.add_argument(
        "-t", "--tempo",
        type=str,
        default=None,
        help="ドラムMIDIに設定するテンポBPM数値（例: 120, 140）またはマージするテンポMIDI/解析元音声ファイルパス（.mid, .mp3等）",
    )
    drums_parser.add_argument(
        "--tempo-tolerance",
        type=float,
        default=0.8,
        help="テンポ解析元の音声からテンポ抽出する際の揺らぎ平滑化許容幅 BPM (デフォルト: 0.8BPM)",
    )

    # ----------------------------------------------------
    # サブコマンド: tempo (楽曲からテンポ専用MIDI生成)
    # ----------------------------------------------------
    tempo_parser = subparsers.add_parser(
        "tempo",
        help="楽曲からテンポ（BPM）やビートを解析し、テンポ専用MIDI（Tempo Track）を生成",
        description="Essentiaを活用して楽曲のテンポ変化（テンポマップ）を高精度に解析し、DAWのグリッド同期用MIDIを出力します。",
    )

    tempo_parser.add_argument(
        "input",
        type=str,
        help="入力音声ファイルのパス (MP3, WAV, FLAC, M4A等)",
    )
    tempo_parser.add_argument(
        "-o", "--output",
        type=str,
        default=None,
        help="出力先MIDIファイルパス (省略時は入力ファイル名_tempo.mid)",
    )
    tempo_parser.add_argument(
        "--fixed",
        action="store_true",
        help="テンポマップ（可変ビート追従）ではなく、楽曲全体の代表BPM単一で出力する場合に指定",
    )
    tempo_parser.add_argument(
        "--tolerance",
        type=float,
        default=0.8,
        help="テンポの微小な揺らぎ（ジッター）とみなして平均化する許容変動幅 BPM (デフォルト: 0.8BPM。0以下の場合は平滑化無効)",
    )

    # ----------------------------------------------------
    # サブコマンド: piano (ピアノ音源からMIDI生成)
    # ----------------------------------------------------
    piano_parser = subparsers.add_parser(
        "piano",
        help="ピアノ音源から高精度なMIDI（和音・ベロシティ・サステインペダル）を生成",
        description="piano_transcription_inference (ByteDance) をベースに、ポリフォニック和音、ペダル情報（CC64）、テンポ同期に対応したピアノMIDIを出力します。",
    )

    piano_parser.add_argument(
        "input",
        type=str,
        help="入力音声ファイルのパス (WAV, MP3, FLAC等)",
    )
    piano_parser.add_argument(
        "-o", "--output",
        type=str,
        default=None,
        help="出力先MIDIファイルパス (省略時は入力ファイル名_piano.mid)",
    )
    piano_parser.add_argument(
        "--onset-threshold",
        type=float,
        default=0.3,
        help="アタック（Onset）の検出閾値 (0.0〜1.0, デフォルト: 0.3)",
    )
    piano_parser.add_argument(
        "--frame-threshold",
        type=float,
        default=0.1,
        help="音の持続フレーム判定の閾値 (0.0〜1.0, デフォルト: 0.1)",
    )
    piano_parser.add_argument(
        "--pedal-threshold",
        type=float,
        default=0.2,
        help="サステインペダルの離鍵（Offset）判定閾値 (0.0〜1.0, デフォルト: 0.2)",
    )
    piano_parser.add_argument(
        "--min-volume-db",
        type=float,
        default=-45.0,
        help="ノイズゲートの音量閾値 dB (デフォルト: -45.0dB)。微小ノイズを除去 (無効にする場合は -999 等を指定)",
    )
    piano_parser.add_argument(
        "-t", "--tempo",
        type=str,
        default="120.0",
        help="MIDIのテンポBPM数値（例: 120, 140）またはマージするテンポMIDI/解析元音声ファイルパス（デフォルト: 120.0）",
    )
    piano_parser.add_argument(
        "--tempo-tolerance",
        type=float,
        default=0.8,
        help="テンポ解析元の音声からテンポ抽出する際の揺らぎ平滑化許容幅 BPM (デフォルト: 0.8BPM)",
    )
    piano_parser.add_argument(
        "--device",
        type=str,
        default="auto",
        choices=["auto", "cpu", "cuda", "mps"],
        help="推論を実行するデバイス (デフォルト: auto)",
    )
    piano_parser.add_argument(
        "--model-dir",
        type=str,
        default=None,
        help="モデルキャッシュ保存先ディレクトリ (デフォルト: ~/.cache/midimaker/piano/)",
    )

    # ----------------------------------------------------
    # サブコマンド: separate (ステム音源分離パイプライン)
    # ----------------------------------------------------
    separate_parser = subparsers.add_parser(
        "separate",
        help="audio-separator を利用した高精度ステム分離（楽器特化モデル・De-Echo/De-Reverb・WAV出力対応）",
        description="各楽器（ドラム、ベース等）の特化モデルやエコー・リバーブ除去を組み合わせたパイプラインを実行し、高音質なWAVE形式でステムを出力します。",
    )

    separate_parser.add_argument(
        "input",
        nargs="?",
        type=str,
        default=None,
        help="入力音声ファイルのパス (MP3, WAV, FLAC, M4A等)",
    )
    separate_parser.add_argument(
        "-c", "--config",
        type=str,
        default=None,
        help="パイプライン設定ファイルパス (.yaml, .toml, .json)。省略時はドラム＆ベース特化モデルの標準構成",
    )
    separate_parser.add_argument(
        "-o", "--output-dir",
        type=str,
        default=None,
        help="ステム音声の出力先ディレクトリ (省略時は入力ファイルと同じディレクトリ)",
    )
    separate_parser.add_argument(
        "--format",
        type=str,
        default="WAV",
        choices=["WAV", "FLAC", "MP3", "M4A", "OGG"],
        help="出力音声フォーマット (デフォルト: WAV)",
    )
    separate_parser.add_argument(
        "--model-dir",
        type=str,
        default=None,
        help="モデルキャッシュ保存先ディレクトリ (デフォルト: ~/.cache/midimaker/models/)",
    )
    separate_parser.add_argument(
        "-t", "--tempo",
        type=str,
        default=None,
        help="MIDIに設定するテンポBPM数値（例: 120, 140）またはマージするテンポMIDI/解析元音声ファイルパス ('input'なら元音声から自動解析)",
    )
    separate_parser.add_argument(
        "--list-models",
        action="store_true",
        help="おすすめモデルとエイリアス一覧を表示して終了",
    )
    separate_parser.add_argument(
        "--list-all",
        action="store_true",
        help="audio-separator が対応する全モデル一覧を表示して終了",
    )

    return parser


def main() -> None:
    """CLIのメインエントリーポイント"""
    parser = build_parser()

    # 引数なしで実行された場合はヘルプを表示
    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(0)

    args = parser.parse_args()

    if args.command == "bass":
        # ヘルプ表示を爆速にするため、実行時に初めて重い推論モジュールをインポートする
        from midimaker.bass import transcribe_bass

        try:
            transcribe_bass(
                audio_path=args.input,
                output_path=args.output,
                onset_threshold=args.onset_threshold,
                frame_threshold=args.frame_threshold,
                minimum_note_length=args.min_note_length,
                min_freq=args.min_freq,
                max_freq=args.max_freq,
                min_volume_db=args.min_volume_db if args.min_volume_db > -900 else None,
                monophonic=not args.no_monophonic,
                tempo=args.tempo,
                tempo_tolerance=args.tempo_tolerance,
            )
        except Exception as e:
            print(f"❌ エラーが発生しました: {e}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "drums":
        # ヘルプ表示を爆速にするため、実行時に初めて重い推論モジュールをインポートする
        from midimaker.drums import transcribe_drums

        try:
            transcribe_drums(
                audio_path=args.input,
                output_path=args.output,
                input_is_mix=args.from_mix,
                default_threshold=args.threshold,
                min_volume_db=args.min_volume_db if args.min_volume_db > -900 else None,
                tempo=args.tempo,
                tempo_tolerance=args.tempo_tolerance,
            )
        except Exception as e:
            print(f"❌ エラーが発生しました: {e}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "tempo":
        from midimaker.tempo import export_tempo_midi

        try:
            export_tempo_midi(
                audio_path=args.input,
                output_path=args.output,
                fixed_tempo=args.fixed,
                tolerance_bpm=args.tolerance,
            )
        except Exception as e:
            print(f"❌ エラーが発生しました: {e}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "separate":
        from midimaker.separator import (
            StemPipelineRunner,
            load_pipeline_config,
            print_all_supported_models,
            print_recommended_models,
        )

        # モデル一覧の表示オプション処理
        if args.list_models:
            print_recommended_models()
            sys.exit(0)

        if args.list_all:
            print_all_supported_models()
            sys.exit(0)

        if not args.input:
            print("❌ エラー: 入力音声ファイルパスを指定してください。", file=sys.stderr)
            print("   例: midimaker separate input.mp3 -c configs/pipeline_default.yaml", file=sys.stderr)
            print("   (モデル一覧を見るには: midimaker separate --list-models)", file=sys.stderr)
            sys.exit(1)

        try:
            config = load_pipeline_config(args.config)
            runner = StemPipelineRunner(
                config=config,
                output_dir=args.output_dir,
                output_format=args.format,
                model_file_dir=args.model_dir,
                tempo=args.tempo,
            )
            runner.run(args.input)
        except Exception as e:
            print(f"❌ エラーが発生しました: {e}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "piano":
        # ヘルプ表示を爆速にするため、実行時に初めて重い推論モジュールをインポートする
        from midimaker.piano import transcribe_piano

        try:
            transcribe_piano(
                audio_path=args.input,
                output_path=args.output,
                onset_threshold=args.onset_threshold,
                frame_threshold=args.frame_threshold,
                pedal_offset_threshold=args.pedal_threshold,
                min_volume_db=args.min_volume_db if args.min_volume_db > -900 else None,
                tempo=args.tempo,
                tempo_tolerance=args.tempo_tolerance,
                device=args.device,
                checkpoint_path=args.model_dir,
            )
        except Exception as e:
            print(f"❌ エラーが発生しました: {e}", file=sys.stderr)
            sys.exit(1)

    else:
        parser.print_help()


def bass_cli() -> None:
    """midimaker-bass コマンドとして直接ベース変換を実行するエントリーポイント"""
    if len(sys.argv) > 1 and sys.argv[1] != "bass":
        sys.argv.insert(1, "bass")
    main()


def drums_cli() -> None:
    """midimaker-drums コマンドとして直接ドラム変換を実行するエントリーポイント"""
    if len(sys.argv) > 1 and sys.argv[1] != "drums":
        sys.argv.insert(1, "drums")
    main()


def tempo_cli() -> None:
    """midimaker-tempo コマンドとして直接テンポMIDI生成を実行するエントリーポイント"""
    if len(sys.argv) > 1 and sys.argv[1] != "tempo":
        sys.argv.insert(1, "tempo")
    main()


def separate_cli() -> None:
    """midimaker-separate コマンドとして直接ステム分離を実行するエントリーポイント"""
    if len(sys.argv) > 1 and sys.argv[1] != "separate":
        sys.argv.insert(1, "separate")
    main()


def piano_cli() -> None:
    """midimaker-piano コマンドとして直接ピアノ変換を実行するエントリーポイント"""
    if len(sys.argv) > 1 and sys.argv[1] != "piano":
        sys.argv.insert(1, "piano")
    main()

