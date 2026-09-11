"""
MIDImaker 音源分離 (Stem Separation) & MIDI自動生成パイプラインモジュール

audio-separator をバックエンドに採用した高精度ステム分離に加え、
分離されたドラム・ベース音源からのMIDI生成（ADTOF Plus / Spotify Basic Pitch）、
およびテンポ解析・同期（Essentia）を一気通貫で実行します。
"""

import json
import logging
import os
import shutil
import sys
import tomllib
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import yaml
from audio_separator.separator import Separator

# ロガーの設定
logger = logging.getLogger("midimaker.separator")


# -----------------------------------------------------------------------------
# モデル設定ファイル (models.yaml) の検索・読み込み
# -----------------------------------------------------------------------------
def find_models_config_path(explicit_path: Optional[str | Path] = None) -> Optional[Path]:
    """
    モデル定義ファイル (models.yaml) のパスを検索して返す。
    指定されたパスを優先し、未指定時はカレントディレクトリやプロジェクトルートを探索する。
    """
    candidates = []
    if explicit_path:
        candidates.append(Path(explicit_path))

    # カレントディレクトリ配下
    candidates.append(Path("configs/models.yaml"))
    candidates.append(Path("models.yaml"))

    # パッケージルートからの相対パス
    package_root = Path(__file__).resolve().parent.parent.parent
    candidates.append(package_root / "configs" / "models.yaml")

    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate.resolve()

    return None


def load_models_definition(
    models_config_path: Optional[str | Path] = None,
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, str]]:
    """
    外部設定ファイル (models.yaml) からモデル一覧情報とエイリアスマッピングを読み込む。
    戻り値: (models_dict, aliases_dict)
    """
    path = find_models_config_path(models_config_path)
    if path is None or not path.exists():
        return {}, {}

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        models = data.get("models", {})
        aliases = data.get("aliases", {})

        # キーを小文字正規化
        normalized_aliases = {str(k).strip().lower(): str(v).strip() for k, v in aliases.items()}
        return models, normalized_aliases
    except Exception as e:
        logger.warning(f"モデル定義ファイル '{path}' の読み込みに失敗しました: {e}")
        return {}, {}


# -----------------------------------------------------------------------------
# パイプライン設定ファイルのロードとバリデーション
# -----------------------------------------------------------------------------
def load_pipeline_config(config_path: Optional[str | Path]) -> Dict[str, Any]:
    """
    YAML / TOML / JSON 形式のパイプライン設定ファイルを読み込む。
    未指定の場合は configs/pipeline_default.yaml のロードを試み、
    存在しない場合は最小限のデフォルト設定を生成する。
    また、モデル設定ファイル (models.yaml) のエイリアスをマージする。
    """
    data: Dict[str, Any] = {}

    if config_path is not None:
        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(f"設定ファイルが見つかりません: {path}")

        ext = path.suffix.lower()
        with open(path, "r", encoding="utf-8") as f:
            if ext in (".yaml", ".yml"):
                data = yaml.safe_load(f) or {}
            elif ext == ".toml":
                with open(path, "rb") as bf:
                    data = tomllib.load(bf)
            elif ext == ".json":
                data = json.load(f)
            else:
                try:
                    data = yaml.safe_load(f) or {}
                except Exception:
                    with open(path, "rb") as bf:
                        data = tomllib.load(bf)
    else:
        # 未指定時は configs/pipeline_default.yaml の探索を試みる
        default_yaml_path = find_default_pipeline_config_path()
        if default_yaml_path and default_yaml_path.exists():
            with open(default_yaml_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        else:
            # フォールバック用の最小限構成（実ファイル名を直接指定）
            data = {
                "output_format": "WAV",
                "sample_rate": 44100,
                "steps": [
                    {
                        "name": "drums",
                        "model": "kuielab_a_drums.onnx",
                        "input": "input",
                        "target_stems": ["drums"],
                        "output_name": "{basename}_drums",
                    },
                    {
                        "name": "bass",
                        "model": "kuielab_a_bass.onnx",
                        "input": "input",
                        "target_stems": ["bass"],
                        "output_name": "{basename}_bass",
                    },
                ],
            }

    if not isinstance(data, dict):
        raise ValueError("設定ファイルのルートは辞書形式である必要があります。")

    # 出力フォーマットのデフォルトを補完 (明示指定がなければ WAV)
    if "output_format" not in data:
        data["output_format"] = "WAV"

    if "steps" not in data or not isinstance(data["steps"], list):
        raise ValueError("設定ファイル内に 'steps' リストが定義されていません。")

    # 外部 models.yaml からエイリアスを読み込んでマージ
    models_config_ref = data.get("models_config")
    _, external_aliases = load_models_definition(models_config_ref)

    # パイプライン設定ファイル内の aliases で上書き・補完
    merged_aliases = external_aliases.copy()
    local_aliases = data.get("aliases", {})
    if isinstance(local_aliases, dict):
        for k, v in local_aliases.items():
            merged_aliases[str(k).strip().lower()] = str(v).strip()

    data["aliases"] = merged_aliases
    return data


def find_default_pipeline_config_path() -> Optional[Path]:
    """デフォルトのパイプライン設定ファイル (pipeline_default.yaml) を探索する"""
    candidates = [
        Path("configs/pipeline_default.yaml"),
        Path("pipeline_default.yaml"),
        Path(__file__).resolve().parent.parent.parent / "configs" / "pipeline_default.yaml",
    ]
    for c in candidates:
        if c.exists() and c.is_file():
            return c.resolve()
    return None


# -----------------------------------------------------------------------------
# パイプライン実行クラス
# -----------------------------------------------------------------------------
class StemPipelineRunner:
    """
    音源分離 (audio-separator) および MIDI生成 (ADTOF Plus / Basic Pitch) を統合実行するランナー
    """

    def __init__(
        self,
        config: Dict[str, Any],
        output_dir: Optional[str | Path] = None,
        output_format: Optional[str] = None,
        model_file_dir: Optional[str | Path] = None,
        tempo: Optional[Union[float, int, str, Path]] = None,
        log_level: int = logging.INFO,
    ):
        self.config = config
        self.output_format = (output_format or config.get("output_format", "WAV")).upper()
        self.output_dir = Path(output_dir) if output_dir else None
        self.model_file_dir = str(model_file_dir) if model_file_dir else "/tmp/audio-separator-models/"
        self.log_level = log_level

        # CLI または設定ファイルからのテンポ指定（CLI指定があれば優先上書き）
        if tempo is not None:
            self.config["tempo"] = tempo
        self.global_tempo = self.config.get("tempo")

        # 設定ファイルから読み込まれたエイリアスマッピング
        self.aliases: Dict[str, str] = config.get("aliases", {})

        # 出力フォーマットの検証
        valid_formats = ["WAV", "FLAC", "MP3", "M4A", "OGG"]
        if self.output_format not in valid_formats:
            raise ValueError(f"無効な出力フォーマットです: {self.output_format} (有効値: {valid_formats})")

        # 内部状態
        self.separator: Optional[Separator] = None
        self.current_model_filename: Optional[str] = None

    def resolve_model(self, model_name_or_alias: str) -> str:
        """
        設定ファイルのエイリアス辞書を参照して正式なモデルファイル名に解決する。
        エイリアスが存在しない場合は渡された名前をそのまま使用する。
        """
        cleaned = model_name_or_alias.strip()
        return self.aliases.get(cleaned.lower(), cleaned)

    def _get_or_create_separator(self, work_dir: Path) -> Separator:
        """Separator インスタンスを初期化（または作業ディレクトリ更新）して取得する"""
        if self.separator is None:
            self.separator = Separator(
                log_level=self.log_level,
                model_file_dir=self.model_file_dir,
                output_dir=str(work_dir.resolve()),
                output_format=self.output_format,
            )
        else:
            self.separator.output_dir = str(work_dir.resolve())
            self.separator.output_format = self.output_format

        return self.separator

    def _resolve_step_tempo(
        self,
        step_tempo_ref: Optional[Union[str, int, float, Path]],
        initial_input_path: Path,
        step_outputs: Dict[str, Dict[str, Any]],
    ) -> Optional[Union[float, int, str, Path]]:
        """
        ステップまたはパイプライン全体に指定されたテンポ情報を実体（BPM数値、MIDIパス、音声パス）に解決する。
        """
        ref = step_tempo_ref if step_tempo_ref is not None else self.global_tempo
        if ref is None:
            return None

        # 数値（float/int）ならそのままBPM
        if isinstance(ref, (int, float)):
            return ref

        ref_str = str(ref).strip()

        # 数値文字列（例: "120", "135.5"）ならfloatへ
        try:
            return float(ref_str)
        except ValueError:
            pass

        # "input" の場合は初期入力音声（フルミックス）のパスを返す（transcribe側でEssentia解析＆同期）
        if ref_str.lower() == "input":
            return initial_input_path

        # 他ステップのMIDI出力参照（例: "tempo_track.tempo", "tempo_track.mid"）
        if "." in ref_str:
            step_key, stem_key = ref_str.split(".", 1)
            if step_key in step_outputs:
                stem_map = step_outputs[step_key].get("stem_map", {})
                for k, v in stem_map.items():
                    if k.lower() == stem_key.lower():
                        return v
                files = step_outputs[step_key].get("all_files", [])
                if files:
                    return files[0]

        # ステップ名単体での参照（例: "tempo_track"）
        if ref_str in step_outputs:
            files = step_outputs[ref_str].get("all_files", [])
            if files:
                return files[0]

        # 直接ファイルが存在する場合
        p = Path(ref_str)
        if p.exists():
            return p.resolve()

        return ref_str

    def run(self, input_audio_path: str | Path) -> List[Path]:
        """
        指定された音声ファイルに対してパイプラインを実行し、最終出力ファイルのパス一覧を返す。
        """
        input_path = Path(input_audio_path).resolve()
        if not input_path.exists():
            raise FileNotFoundError(f"入力音声ファイルが見つかりません: {input_path}")

        basename = input_path.stem
        target_output_dir = self.output_dir or input_path.parent
        target_output_dir.mkdir(parents=True, exist_ok=True)

        # 一時作業ディレクトリ（中間ファイルの退避用）
        work_dir = target_output_dir / f".tmp_midimaker_{basename}"
        work_dir.mkdir(parents=True, exist_ok=True)

        # 各ステップの出力を記録する辞書
        # { step_name: { "all_files": [Path], "stem_map": { stem_name: Path } } }
        step_outputs: Dict[str, Dict[str, Any]] = {}
        # 最終的にユーザーに渡す成果物ファイルのリスト
        final_published_files: List[Path] = []

        try:
            steps = self.config.get("steps", [])

            print(f"🚀 MIDImaker パイプラインを開始します: {input_path.name}")
            print(f"📁 最終出力先: {target_output_dir} (音声形式: {self.output_format})")
            if self.global_tempo:
                print(f"⏱️  共通テンポ設定: {self.global_tempo}")
            print(f"⚙️  実行ステップ数: {len(steps)}")

            for idx, step in enumerate(steps, start=1):
                step_name = step.get("name", f"step_{idx}")
                # ステップ種別 (separate / drums_midi / bass_midi / tempo_midi)
                step_type = (step.get("type") or step.get("action") or "separate").lower()

                print(f"\n[{idx}/{len(steps)}] 🎯 ステップ実行: '{step_name}' (種別: {step_type})")

                # =============================================================
                # 種別 A: 音源分離 (audio-separator)
                # =============================================================
                if step_type in ("separate", "audio", "stem"):
                    raw_model = step.get("model")
                    if not raw_model:
                        raise ValueError(f"音源分離ステップ '{step_name}' に 'model' が指定されていません。")

                    model_filename = self.resolve_model(raw_model)
                    input_ref = step.get("input", "input")
                    target_stems = step.get("target_stems")
                    if isinstance(target_stems, str):
                        target_stems = [target_stems]
                    output_name_template = step.get("output_name")

                    # 入力音声ファイルの解決
                    source_file_path = self._resolve_step_input(
                        input_ref=input_ref,
                        initial_input_path=input_path,
                        step_outputs=step_outputs,
                    )

                    print(f"    - 使用モデル: {model_filename} (指定: {raw_model})")
                    print(f"    - 入力音源: {source_file_path.name}")

                    separator = self._get_or_create_separator(work_dir)

                    # モデルのロード（同じモデルならリロードをスキップ）
                    if self.current_model_filename != model_filename:
                        print(f"    - モデルをロード中...")
                        separator.load_model(model_filename=model_filename)
                        self.current_model_filename = model_filename

                    # 分離の実行
                    print(f"    - 音源分離を実行中...")
                    raw_output_paths = separator.separate(str(source_file_path))
                    output_paths = [
                        (work_dir / p).resolve() if not Path(p).is_absolute() else Path(p)
                        for p in raw_output_paths
                    ]

                    # 出力ファイルからステム名を抽出・マッピング
                    stem_map = self._map_stems_from_filenames(output_paths)
                    step_outputs[step_name] = {
                        "all_files": output_paths,
                        "stem_map": stem_map,
                    }

                    print(f"    - 分離完了: {len(output_paths)} 個のステムを出力 ({', '.join(stem_map.keys())})")

                    # 成果物ファイルを配置
                    published_for_step = self._publish_step_outputs(
                        step_name=step_name,
                        basename=basename,
                        target_output_dir=target_output_dir,
                        stem_map=stem_map,
                        all_output_paths=output_paths,
                        target_stems=target_stems,
                        output_name_template=output_name_template,
                    )
                    final_published_files.extend(published_for_step)

                # =============================================================
                # 種別 B: ドラムMIDI生成 (ADTOF Plus)
                # =============================================================
                elif step_type in ("drums_midi", "drums", "drum_midi", "drum"):
                    from midimaker.drums import transcribe_drums

                    input_ref = step.get("input", "input")
                    source_audio = self._resolve_step_input(
                        input_ref=input_ref,
                        initial_input_path=input_path,
                        step_outputs=step_outputs,
                    )
                    print(f"    - 入力音源: {source_audio.name}")

                    # テンポ解決
                    resolved_tempo = self._resolve_step_tempo(
                        step_tempo_ref=step.get("tempo"),
                        initial_input_path=input_path,
                        step_outputs=step_outputs,
                    )
                    if resolved_tempo is not None:
                        print(f"    - テンポ指定/解析同期: {resolved_tempo}")

                    # 出力先MIDIパスの決定
                    output_template = step.get("output_name", "{basename}_drums.mid")
                    if isinstance(output_template, dict):
                        output_template = output_template.get("midi", "{basename}_drums.mid")
                    formatted_midi_name = output_template.format(basename=basename, step=step_name)
                    if not formatted_midi_name.lower().endswith(".mid"):
                        formatted_midi_name = f"{formatted_midi_name}.mid"
                    dest_midi_path = target_output_dir / formatted_midi_name

                    print(f"    - ドラムMIDI変換を実行中 (ADTOF Plus)...")
                    created_midi = transcribe_drums(
                        audio_path=source_audio,
                        output_path=dest_midi_path,
                        input_is_mix=step.get("from_mix", False),
                        default_threshold=step.get("threshold", -float("inf")),
                        min_volume_db=step.get("min_volume_db", -45.0),
                        tempo=resolved_tempo,
                        tempo_tolerance=step.get("tempo_tolerance", 0.8),
                    )

                    step_outputs[step_name] = {
                        "all_files": [created_midi],
                        "stem_map": {"midi": created_midi, "drums": created_midi},
                    }
                    final_published_files.append(created_midi)
                    print(f"    - ドラムMIDI生成完了: {created_midi.name}")

                # =============================================================
                # 種別 C: ベースMIDI生成 (Basic Pitch)
                # =============================================================
                elif step_type in ("bass_midi", "bass"):
                    from midimaker.bass import transcribe_bass

                    input_ref = step.get("input", "input")
                    source_audio = self._resolve_step_input(
                        input_ref=input_ref,
                        initial_input_path=input_path,
                        step_outputs=step_outputs,
                    )
                    print(f"    - 入力音源: {source_audio.name}")

                    # テンポ解決
                    resolved_tempo = self._resolve_step_tempo(
                        step_tempo_ref=step.get("tempo"),
                        initial_input_path=input_path,
                        step_outputs=step_outputs,
                    )
                    if resolved_tempo is not None:
                        print(f"    - テンポ指定/解析同期: {resolved_tempo}")

                    # 出力先MIDIパスの決定
                    output_template = step.get("output_name", "{basename}_bass.mid")
                    if isinstance(output_template, dict):
                        output_template = output_template.get("midi", "{basename}_bass.mid")
                    formatted_midi_name = output_template.format(basename=basename, step=step_name)
                    if not formatted_midi_name.lower().endswith(".mid"):
                        formatted_midi_name = f"{formatted_midi_name}.mid"
                    dest_midi_path = target_output_dir / formatted_midi_name

                    print(f"    - ベースMIDI変換を実行中 (Spotify Basic Pitch)...")
                    created_midi = transcribe_bass(
                        audio_path=source_audio,
                        output_path=dest_midi_path,
                        onset_threshold=step.get("onset_threshold", 0.55),
                        frame_threshold=step.get("frame_threshold", 0.35),
                        minimum_note_length=step.get("min_note_length", 80.0),
                        min_freq=step.get("min_freq", 30.0),
                        max_freq=step.get("max_freq", 800.0),
                        min_volume_db=step.get("min_volume_db", -45.0),
                        monophonic=step.get("monophonic", True),
                        tempo=resolved_tempo or 120.0,
                        tempo_tolerance=step.get("tempo_tolerance", 0.8),
                    )

                    step_outputs[step_name] = {
                        "all_files": [created_midi],
                        "stem_map": {"midi": created_midi, "bass": created_midi},
                    }
                    final_published_files.append(created_midi)
                    print(f"    - ベースMIDI生成完了: {created_midi.name}")

                # =============================================================
                # 種別 D: テンポMIDI生成 (Essentia)
                # =============================================================
                elif step_type in ("tempo_midi", "tempo"):
                    from midimaker.tempo import export_tempo_midi

                    input_ref = step.get("input", "input")
                    source_audio = self._resolve_step_input(
                        input_ref=input_ref,
                        initial_input_path=input_path,
                        step_outputs=step_outputs,
                    )
                    print(f"    - 入力音源: {source_audio.name}")

                    output_template = step.get("output_name", "{basename}_tempo.mid")
                    formatted_midi_name = output_template.format(basename=basename, step=step_name)
                    if not formatted_midi_name.lower().endswith(".mid"):
                        formatted_midi_name = f"{formatted_midi_name}.mid"
                    dest_midi_path = target_output_dir / formatted_midi_name

                    print(f"    - テンポ解析＆MIDI生成を実行中 (Essentia)...")
                    created_midi = export_tempo_midi(
                        audio_path=source_audio,
                        output_path=dest_midi_path,
                        fixed_tempo=step.get("fixed", False),
                        tolerance_bpm=step.get("tolerance", 0.8),
                    )

                    step_outputs[step_name] = {
                        "all_files": [created_midi],
                        "stem_map": {"midi": created_midi, "tempo": created_midi},
                    }
                    final_published_files.append(created_midi)
                    print(f"    - テンポMIDI生成完了: {created_midi.name}")

                else:
                    raise ValueError(f"未知のステップ種別です: '{step_type}' (有効値: separate, drums_midi, bass_midi, tempo_midi)")

            print(f"\n✨ すべてのパイプラインステップが正常に完了しました！")
            for f in final_published_files:
                print(f"  ✓ {f.name}")

            return final_published_files

        finally:
            # 中間作業ディレクトリのクリーンアップ
            keep_intermediates = self.config.get("keep_intermediates", False)
            if not keep_intermediates and work_dir.exists():
                shutil.rmtree(work_dir, ignore_errors=True)

    def _resolve_step_input(
        self,
        input_ref: str,
        initial_input_path: Path,
        step_outputs: Dict[str, Dict[str, Any]],
    ) -> Path:
        """
        ステップの入力参照（'input', 'step_name.stem', 'step_name' 等）から
        実ファイルパスを解決する。
        """
        if input_ref == "input":
            return initial_input_path

        if "." in input_ref:
            ref_step, ref_stem = input_ref.split(".", 1)
            ref_stem_clean = ref_stem.strip().lower()

            if ref_step not in step_outputs:
                raise ValueError(f"参照されたステップ '{ref_step}' の出力が見つかりません。")

            stem_map = step_outputs[ref_step]["stem_map"]
            # 完全一致検索
            for stem_key, file_path in stem_map.items():
                if stem_key.lower() == ref_stem_clean:
                    return file_path

            # 部分一致検索 (例: "dry" で "no dry" ではなく "dry" を探す)
            matches = [
                (k, p) for k, p in stem_map.items()
                if ref_stem_clean in k.lower()
            ]
            if matches:
                # 完全一致に近いものを優先
                matches.sort(key=lambda x: len(x[0]))
                return matches[0][1]

            available = list(stem_map.keys())
            raise ValueError(
                f"ステップ '{ref_step}' 内にステム '{ref_stem}' が見つかりません。(利用可能: {available})"
            )

        # ステム指定がなくステップ名のみの場合
        if input_ref in step_outputs:
            all_files = step_outputs[input_ref]["all_files"]
            if all_files:
                return all_files[0]
            raise ValueError(f"ステップ '{input_ref}' に出力ファイルがありません。")

        # ファイルパスが直接指定された場合
        direct_path = Path(input_ref)
        if direct_path.exists():
            return direct_path

        raise ValueError(f"入力指定 '{input_ref}' を解決できませんでした。")

    def _map_stems_from_filenames(self, paths: List[Path]) -> Dict[str, Path]:
        """
        audio-separator のファイル名パターン `{base}_({stem})_{model}.ext` から
        ステム名（vocals, drums, dry など）を抽出してマップする。
        """
        stem_map: Dict[str, Path] = {}
        for p in paths:
            name = p.stem
            stem_name = "output"
            # _(StemName)_ パターンを抽出
            if "_(" in name and ")_" in name:
                try:
                    parts = name.split("_(")
                    stem_part = parts[-1].split(")_")[0]
                    stem_name = stem_part.strip()
                except Exception:
                    stem_name = p.stem
            elif "_(" in name and name.endswith(")"):
                try:
                    stem_name = name.split("_(")[-1][:-1].strip()
                except Exception:
                    stem_name = p.stem

            stem_map[stem_name] = p

        return stem_map

    def _publish_step_outputs(
        self,
        step_name: str,
        basename: str,
        target_output_dir: Path,
        stem_map: Dict[str, Path],
        all_output_paths: List[Path],
        target_stems: Optional[List[str]],
        output_name_template: Optional[Union[str, Dict[str, str]]],
    ) -> List[Path]:
        """
        各ステップの成果物（ターゲットステム）を最終出力ディレクトリにリネーム・移動する。
        """
        published: List[Path] = []
        ext = self.output_format.lower()

        # 対象とするステムの絞り込み
        stems_to_publish: List[Tuple[str, Path]] = []
        if target_stems:
            target_stems_lower = [s.strip().lower() for s in target_stems]
            for ts in target_stems_lower:
                # 1. まず完全一致を探す (例: "drums" == "drums")
                matched = False
                for stem_key, file_path in stem_map.items():
                    if stem_key.lower() == ts:
                        stems_to_publish.append((stem_key, file_path))
                        matched = True
                        break
                if matched:
                    continue

                # 2. "no " や "no_" 等の否定形を除外した部分一致を探す (例: "drums" in "instrumental drums")
                for stem_key, file_path in stem_map.items():
                    sk_lower = stem_key.lower()
                    if ts in sk_lower and not sk_lower.startswith("no ") and not sk_lower.startswith("no_"):
                        stems_to_publish.append((stem_key, file_path))
                        matched = True
                        break
                if matched:
                    continue

                # 3. フォールバック
                for stem_key, file_path in stem_map.items():
                    if ts in stem_key.lower():
                        stems_to_publish.append((stem_key, file_path))
                        break
        else:
            # 指定がなければ全ステムを対象
            stems_to_publish = list(stem_map.items())

        for stem_name, src_file in stems_to_publish:
            stem_key_clean = stem_name.lower().replace(" ", "_")

            # 命名テンプレートの決定
            if isinstance(output_name_template, dict):
                # 辞書形式の場合、該当ステムのテンプレートを検索 (例: {"vocals": "...", "instrumental": "..."})
                template = None
                for k, v in output_name_template.items():
                    if k.lower() == stem_key_clean or k.lower() in stem_key_clean:
                        template = str(v)
                        break
                if not template:
                    template = output_name_template.get("default", "{basename}_{stem}")

                formatted_name = template.format(
                    basename=basename,
                    stem=stem_key_clean,
                    step=step_name,
                )
            elif isinstance(output_name_template, str) and output_name_template:
                formatted_name = output_name_template.format(
                    basename=basename,
                    stem=stem_key_clean,
                    step=step_name,
                )
            else:
                formatted_name = f"{basename}_{step_name}_{stem_key_clean}.{ext}"

            if not formatted_name.lower().endswith(f".{ext}"):
                formatted_name = f"{formatted_name}.{ext}"

            dest_path = target_output_dir / formatted_name

            # コピーして配置（元の一時ファイルは中間ステップで再利用される可能性があるためcopy）
            shutil.copy2(src_file, dest_path)
            published.append(dest_path)

        return published


# -----------------------------------------------------------------------------
# モデル一覧表示ヘルパー関数
# -----------------------------------------------------------------------------
def print_recommended_models(models_config_path: Optional[str | Path] = None) -> None:
    """
    設定ファイル (configs/models.yaml) に定義されたおすすめモデルと
    エイリアス一覧をフォーマットして表示する。
    """
    models_dict, aliases_dict = load_models_definition(models_config_path)

    print("\n🌟 【MIDImaker おすすめ音源分離モデル一覧】")
    print("=" * 80)
    print(f"{'エイリアス (指定名)':<18} | {'カテゴリ':<16} | {'説明'}")
    print("-" * 80)

    if not models_dict:
        print("  ※ 設定ファイル (configs/models.yaml) にモデルが定義されていないか、見つかりません。")
    else:
        for alias, info in models_dict.items():
            category = info.get("category", "N/A")
            desc = info.get("description", "")
            fn = info.get("filename", "")
            stems = info.get("stems", [])

            print(f"{alias:<18} | {category:<16} | {desc}")
            print(f"  └ 内部ファイル: {fn}")
            if stems:
                print(f"  └ 分離ステム: {', '.join(stems)}")
            print("-" * 80)

    print("\n💡 ヒント: 設定ファイル (configs/models.yaml やパイプライン設定) で自由にエイリアスを追加できます！\n")


def print_all_supported_models() -> None:
    """audio-separator がサポートしている全モデル一覧を表示する"""
    print("\n📦 【audio-separator サポート対象 全モデル一覧】")
    print("=" * 80)
    try:
        sep = Separator(info_only=True)
        supported = sep.list_supported_model_files()
        for cat, model_dict in supported.items():
            print(f"\n▼ カテゴリ: {cat} ({len(model_dict)} models)")
            print("-" * 80)
            for name, details in model_dict.items():
                fn = details.get("filename", "N/A")
                stems = details.get("stems", [])
                stems_str = f" [stems: {', '.join(stems)}]" if stems else ""
                print(f"  • {fn:<45} : {name}{stems_str}")
    except Exception as e:
        print(f"モデル一覧の取得中にエラーが発生しました: {e}", file=sys.stderr)
