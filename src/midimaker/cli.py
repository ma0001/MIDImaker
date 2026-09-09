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

