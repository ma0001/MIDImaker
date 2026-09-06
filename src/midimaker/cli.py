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
        "--no-monophonic",
        action="store_true",
        help="単音化（モノフォニック）整形を無効にする（和音重複を許可する場合に指定）",
    )
    bass_parser.add_argument(
        "--tempo",
        type=float,
        default=120.0,
        help="MIDIのデフォルトテンポ BPM (デフォルト: 120.0)",
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
                monophonic=not args.no_monophonic,
                midi_tempo=args.tempo,
            )
        except Exception as e:
            print(f"❌ エラーが発生しました: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        parser.print_help()


def bass_cli() -> None:
    """midimaker-bass コマンドとして直接ベース変換を実行するエントリーポイント"""
    # 引数の先頭に 'bass' を補完して main を呼び出す
    if len(sys.argv) > 1 and sys.argv[1] != "bass":
        sys.argv.insert(1, "bass")
    main()
