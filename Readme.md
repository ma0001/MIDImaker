# MIDImaker

**MIDImaker** は、楽曲などの音声ファイル（MP3, WAV等）から、音源分離による各楽器ステム（WAV）の出力、およびドラム・ベース・テンポ情報のMIDIファイルを生成するためのCLIツールです。

音声入力から「テンポ・ビート解析」「音源分離」「ドラムおよびベースのMIDI抽出」を実行し、DAW（Logic Pro、Cubase、Studio One、GarageBand等）で利用可能なファイルを出力します。

---

### 機能概要

- **音源分離パイプライン (`midimaker separate`)**
  - `audio-separator` をバックエンドに使用し、BS-Roformer、MDX-Net、Demucs、De-Echo / De-Reverb などのモデルを用いた分離処理を実行。
  - YAML 設定ファイルにより、複数モデルの組み合わせや処理順序（例: リバーブ除去を適用した後に各楽器の分離を行うなど）をパイプラインとして定義可能。
- **ドラムMIDI生成 (`midimaker drums`)**
  - DrumSep によるパーツ分離と ADTOF Plus（Frame_RNN）を用いた打点検出を行い、General MIDI (Ch.10) 形式のMIDIを出力。
- **ベースMIDI生成 (`midimaker bass`)**
  - Spotify Basic Pitch を用いてベース音域のピッチ検出を実施。
  - 単音（モノフォニック）整形および音量閾値によるフィルタリングを適用したMIDIを出力。
- **テンポ解析・テンポトラックMIDI生成 (`midimaker tempo`)**
  - Essentia を用いてテンポ（BPM）およびビート位置を解析し、テンポ情報を含むMIDIファイル（Conductor Track）を出力。
  - 拍ごとの微小な変動を閾値内で平均化する適応型平滑化（Adaptive Segmentation）機能を搭載。
  - 生成したドラムMIDIやベースMIDIにテンポ情報を埋め込むことで、DAW上での小節グリッド同期に対応。
- **パッケージ管理**
  - `uv` を用いた依存関係の管理に対応。

---

## インストール

### 1. 前提条件

MIDImaker は音声処理・フォーマット変換に **ffmpeg** を使用し、パッケージ管理には高速な **[uv](https://docs.astral.sh/uv/)** を使用します。

- **uv** (推奨パッケージマネージャー)
  ```bash
  # macOS / Linux
  curl -LsSf https://astral.sh/uv/install.sh | sh
  # または Homebrew (macOS)
  brew install uv
  ```
- **ffmpeg** (音声処理・フォーマット変換用)
  ```bash
  # macOS (Homebrew)
  brew install ffmpeg
  # Ubuntu / Debian
  sudo apt update && sudo apt install ffmpeg
  ```

> [!NOTE]
> 音声解析ライブラリ（Essentia等）のビルド互換性のため、**Python 3.11** を推奨・指定しています。リポジトリ内に `.python-version`（3.11）が含まれているため、`uv` が自動的に適切な Python 3.11 環境をセットアップしてくれます。

---

### 2. クローンとセットアップ

リポジトリをクローン後、プロジェクトルートで `uv sync` を実行するだけで仮想環境の作成と依存パッケージのインストールが完了します。

```bash
# リポジトリのクローンと移動
git clone https://github.com/ma0001/MIDImaker.git
cd MIDImaker

# 依存パッケージのインストールと仮想環境構築
uv sync
```

> [!TIP]
> `pyproject.toml` と `uv.lock` に基づき、ドラム解析用の `adtof-plus-drum-transcription`（GitHubリポジトリ依存）や `audio-separator[cpu]`、`essentia` など必要なパッケージがすべて自動で正しく導入されます。

---

### 3. 動作確認

セットアップが完了したら、以下のいずれかの方法でコマンドが実行できるか確認してください。

```bash
# 方法A: uv run で直接実行する場合
uv run midimaker --help

# 方法B: 仮想環境をアクティベートして実行する場合
source .venv/bin/activate
midimaker --help
```



## MIDImaker CLI の使い方

### 🎛️ 音源分離（ステム分離）パイプライン (audio-separator)

`audio-separator` を活用し、各楽器（ドラム、ベース等）それぞれに最も適した特化モデルの適用や、De-Echo / De-Reverb（エコー・リバーブ除去）の前処理を組み合わせた多段パイプラインを実行します。
出力はデフォルトで **高音質なWAVE（WAV）形式** になっています。

```bash
# 基本的な使い方（ドラム特化＋ベース特化モデルで WAV を出力）
midimaker separate "path/to/song.mp3"

# またはエイリアスコマンド
midimaker-separate "path/to/song.mp3"

# 設定ファイルを指定して高度なパイプラインを実行（De-Echo/De-Reverb → ドラム特化＆ベース特化）
midimaker separate "path/to/song.mp3" -c "configs/pipeline_default.yaml" -o "./stems"

# おすすめモデル・エイリアス一覧を表示
midimaker separate --list-models

# サポートされている全モデル一覧を表示
midimaker separate --list-all
```

#### 主なオプション設定

| オプション | デフォルト値 | 説明 |
| :--- | :--- | :--- |
| `-c`, `--config` | 省略（標準構成） | パイプライン設定ファイルパス (`.yaml`, `.toml`, `.json`) |
| `-o`, `--output-dir` | 入力ファイルと同階層 | ステムWAVファイルおよびMIDIファイルの出力先ディレクトリ |
| `-t`, `--tempo` | `input` (自動解析) | MIDIのテンポBPM数値（例: `120`）または外部テンポMIDI/音声ファイルパス（設定ファイル値を上書き） |
| `--format` | `WAV` | 出力フォーマット (`WAV`, `FLAC`, `MP3`, `M4A`, `OGG`) |
| `--model-dir` | `/tmp/audio-separator-models/` | モデルキャッシュ保存先ディレクトリ |
| `--list-models` | - | おすすめモデルとエイリアス一覧を表示して終了 |
| `--list-all` | - | 対応する全モデル一覧を表示して終了 |

#### パイプライン設定ファイル (`pipeline.yaml`) の書き方

設定ファイルを使うことで、任意のモデルを好きな順序で繋ぎ、前ステップの特定のステム（例: `dereverb.dry`）を次ステップの入力に渡すことができます。
モデルエイリアスはプログラム内には固定されておらず、**`configs/models.yaml` またはパイプライン設定ファイルの `aliases:` セクション** で自由に管理・追加できます。

```yaml
# 出力フォーマット (デフォルト: WAV)
output_format: "WAV"
sample_rate: 44100
keep_intermediates: false  # 中間作業ファイルを残すか (true/false)

# 共通モデル定義ファイルの指定 (省略時は configs/models.yaml を自動参照)
models_config: "configs/models.yaml"

# テンポ同期のデフォルト設定 ("input" で元音声から自動解析、またはBPM数値 / 外部テンポMIDIパス)
tempo: "input"

# パイプライン固有のエイリアス定義（追加・上書きも自由自在！）
aliases:
  drums-kuielab: "kuielab_a_drums.onnx"
  bass-kuielab: "kuielab_a_bass.onnx"
  bs-roformer-inst: "model_bs_roformer_ep_317_sdr_12.9755.ckpt"
  demucs-ft: "htdemucs_ft.yaml"
  dereverb-echo: "dereverb-echo_mel_band_roformer_sdr_13.4843_v2.ckpt"

steps:
  # Step 1: ドラム特化モデルでドラムWAVを抽出 (元音源から直接)
  - name: "drums"
    type: "separate"
    model: "drums-kuielab"
    input: "input"
    target_stems: ["drums"]
    output_name: "{basename}_drums"

  # Step 2: ベース特化モデルでベースWAVを抽出 (元音源から直接)
  - name: "bass"
    type: "separate"
    model: "bass-kuielab"
    input: "input"
    target_stems: ["bass"]
    output_name: "{basename}_bass"

  # Step 3: 最高精度のボーカル抽出 (BS-Roformer)
  - name: "vocal_sep"
    type: "separate"
    model: "bs-roformer-inst"
    input: "input"
    target_stems: ["vocals"]
    output_name: "{basename}_vocals"

  # Step 4: ドラム・ベース・ボーカルを除いたその他（Other）の抽出 (Demucs v4)
  - name: "other_sep"
    type: "separate"
    model: "demucs-ft"
    input: "input"
    target_stems: ["other"]
    output_name: "{basename}_other"

  # Step 5: ボーカルのみに De-Echo / De-Reverb を適用（完全ドライボーカル化）
  - name: "vocal_dereverb"
    type: "separate"
    model: "dereverb-echo"
    input: "vocal_sep.vocals"  # Step 3 で抽出されたボーカルを入力！
    target_stems: ["dry"]
    output_name: "{basename}_vocals_dry"

  # Step 6: テンポ解析＆テンポトラックMIDI生成 (Essentia)
  - name: "tempo_track"
    type: "tempo_midi"
    input: "input"             # 元音源からテンポマップを解析してテンポMIDIを出力
    output_name: "{basename}_tempo.mid"

  # Step 7: ドラムWAVからドラムMIDIを自動生成 (Step 6 のテンポMIDIを同期元に入力！)
  - name: "drums_midi"
    type: "drums_midi"
    input: "drums.drums"       # Step 1 で分離されたドラムWAVを入力！
    output_name: "{basename}_drums.mid"
    tempo: "tempo_track"       # 👈 Step 6 のテンポMIDIファイルを入力！

  # Step 8: ベースWAVからベースMIDIを自動生成 (Step 6 のテンポMIDIを同期元に入力！)
  - name: "bass_midi"
    type: "bass_midi"
    input: "bass.bass"         # Step 2 で分離されたベースWAVを入力！
    output_name: "{basename}_bass.mid"
    tempo: "tempo_track"       # 👈 Step 6 のテンポMIDIファイルを入力！
```

##### 各ステップの `input`（入力音源）の指定方法

パイプラインの各ステップで処理する入力音源（`input`）は、以下の4つの記法で柔軟にルーティングできます：

| 指定パターン | 書式例 | 説明 |
| :--- | :--- | :--- |
| **元音声ファイル** | `input: "input"` | コマンドライン引数で指定された最初の元音声（MP3/WAV等）を入力にします（並列抽出に最適） |
| **前ステップの特定ステム** | `input: "{step_name}.{stem_name}"`<br>（例: `"dereverb.dry"`, `"drums.drums"`） | 前のステップ名（`name`）と、モデルが分離したステム名（`dry`, `drums` 等）をドット（`.`）で繋いでピンポイントにパイプします（★一番よく使う記法） |
| **前ステップの出力全体** | `input: "{step_name}"`<br>（例: `"drums"`） | ステム名を省略してステップ名のみを指定した場合、そのステップで出力された音声が自動的に渡されます |
| **外部固定ファイル** | `input: "path/to/audio.wav"` | 実在するローカルの音声ファイルパスを直接指定して入力にします |

##### テンポ同期（`tempo`）の指定方法

MIDI生成ステップ（`drums_midi`, `bass_midi`）やパイプライン全体（トップレベル）で、以下のテンポ指定が可能です：

| 指定パターン | 書式例 | 説明 |
| :--- | :--- | :--- |
| **元音声から自動解析** | `tempo: "input"` | 元の楽曲（フルミックス）から Essentia でテンポマップ（可変テンポ・ビート）を高精度に自動解析してMIDIに埋め込みます（★推奨・完全同期！） |
| **固定BPM** | `tempo: 128`<br>`tempo: 135.5` | 指定した固定BPMテンポをMIDIに設定します |
| **外部テンポMIDI** | `tempo: "path/to/tempo.mid"` | DAW等で作成したテンポMIDIファイル（Tempo Track）のテンポ情報をそのままマージします |
| **外部音声ファイル** | `tempo: "path/to/song.mp3"` | 外部音声ファイルからテンポ解析してマージします |
| **前ステップのテンポ出力** | `tempo: "tempo_step"` | パイプライン内のテンポ生成ステップ（`tempo_midi`）の出力を参照します |

#### 🌟 おすすめモデル一覧 (`configs/models.yaml` で定義)

エイリアスや説明などのメタデータは `configs/models.yaml` で一元管理されています。

- **`dereverb-echo`** (`dereverb-echo_mel_band_roformer_sdr_13.4843_v2.ckpt`): リバーブとエコーを同時に除去して完全ドライな音源を抽出（最高品質）
- **`dereverb`** (`dereverb_mel_band_roformer_anvuew_sdr_19.1729.ckpt`): リバーブのみを高精度除去
- **`drums-kuielab`** (`kuielab_a_drums.onnx`): ドラム抽出特化モデル（MDX-Net）
- **`bass-kuielab`** (`kuielab_a_bass.onnx`): ベース抽出特化モデル（MDX-Net）
- **`drumsep`** (`MDX23C-DrumSep-aufr33-jarredou.ckpt`): ドラムを6パーツ（Kick, Snare, Toms, HH, Ride, Crash）に分解
- **`bs-roformer-inst`** (`model_bs_roformer_ep_317_sdr_12.9755.ckpt`): ボーカルとインストを分離する超高精度モデル
- **`demucs-ft`** (`htdemucs_ft.yaml`): 定番のDemucs v4 4-stems一括分離


### 🎸 ベース音源からクリーンなMIDIを生成 (Spotify Basic Pitch)

ステム分離されたベース音源（WAV, MP3等）から、低音域最適化＆モノフォニック（単音）整形を行ってMIDIを作成します。

```bash
# 基本的な使い方（入力ファイルと同じ場所に _bass.mid が出力されます）
midimaker bass "path/to/bass_stem.wav"

# 出力ファイル名を指定する場合
midimaker bass "path/to/bass_stem.wav" -o "output.mid"

# またはエイリアスコマンド
midimaker-bass "path/to/bass_stem.wav"

# テンポBPMを指定する場合（例: 135 BPM）
midimaker bass "path/to/bass_stem.wav" -t 135

# テンポ情報（テンポMIDIまたはフルミックス音源）をベースMIDIにマージする場合
midimaker bass "path/to/bass_stem.wav" -t "path/to/full_mix_tempo.mid"
# またはフルミックス音源を直接指定して自動マージ（ドラムとタイミングが完全一致します）
midimaker bass "path/to/bass_stem.wav" -t "path/to/full_mix.mp3"
```

#### 主なオプション設定

| オプション | デフォルト値 | 説明 |
| :--- | :--- | :--- |
| `-o`, `--output` | 自動命名 | 出力先MIDIファイルパス |
| `--onset-threshold` | `0.55` | アタック判定感度 (0.0〜1.0)。数値を上げるとゴースト音やノイズが減ります |
| `--frame-threshold` | `0.35` | 持続判定感度 (0.0〜1.0) |
| `--min-note-length` | `80.0` | 最小ノート長 (ms)。短すぎるノイズをスキップ |
| `--min-freq` | `30.0` | 検出最低周波数 (Hz)。5弦ベースのLow-Bまでカバー |
| `--max-freq` | `800.0` | 検出最高周波数 (Hz)。ベース帯域に絞り、不要な高域ノイズをカット |
| `--min-volume-db` | `-45.0` | ノイズゲート音量閾値 (dB)。これ以下の微小音・休符・無音区間のノートを除外 |
| `--no-monophonic` | オフ | 和音の重複をそのまま残す（デフォルトは単音ラインに自動クリーンアップ） |
| `-t`, `--tempo` | `120.0` | テンポ設定。数字（例: `135`）なら指定BPM、ファイルパス（`.mid`, `.mp3`, `.wav` 等）ならテンポ解析・マージ |
| `--tempo-tolerance` | `0.8` | テンポ解析元の音声からテンポ抽出する際の揺らぎ平滑化許容幅 (BPM) |


### 🥁 ドラム音源から高精度MIDIを生成 (ADTOF Plus)

ステム分離されたドラム音源（またはフルミックス楽曲）から、DrumSep 5-stems によるパーツ分離、ADTOF Frame_RNN による高精度打点検出、オープン/クローズハイハット判定、ベロシティ推定を行って General MIDI (Ch.10) のドラムMIDIを作成します。

```bash
# 基本的な使い方（入力ファイルと同じ場所に _drums.mid が出力されます）
midimaker drums "path/to/drums_stem.wav"

# 出力先を指定する場合
midimaker drums "path/to/drums_stem.wav" -o "output.mid"

# またはエイリアスコマンド
midimaker-drums "path/to/drums_stem.wav"

# テンポBPMを指定する場合（例: 130 BPM）
midimaker drums "path/to/drums_stem.wav" -t 130

# フルミックス楽曲から直接ドラム分離してMIDI化する場合
midimaker drums "path/to/full_mix.mp3" --from-mix

# テンポ情報（テンポMIDIまたはフルミックス音源）をドラムMIDIにマージする場合（GarageBandにおすすめ！）
midimaker drums "path/to/drums_stem.wav" -t "path/to/full_mix_tempo.mid"
# またはフルミックス音源を直接指定して自動マージ
midimaker drums "path/to/drums_stem.wav" -t "path/to/full_mix.mp3"
```

#### 主なオプション設定

| オプション | デフォルト値 | 説明 |
| :--- | :--- | :--- |
| `-o`, `--output` | 自動命名 | 出力先MIDIファイルパス |
| `--from-mix` | オフ | フルミックス楽曲からドラムを自動分離して処理（ドラムステム時は不要） |
| `--min-volume-db` | `-45.0` | ノイズゲート音量閾値 (dB)。休符や無音区間のヒスノイズ誤発火を除外 |
| `--threshold` | `-inf` | Onset検出感度閾値 |
| `-t`, `--tempo` | なし | テンポ設定。数字（例: `135`）なら固定BPMを適用、ファイルパス（`.mid`, `.mp3`, `.wav` 等）ならテンポ解析・マージ |
| `--tempo-tolerance` | `0.8` | テンポ解析元の音声からテンポ抽出する際の揺らぎ平滑化許容幅 (BPM) |

> [!TIP]
> **GarageBandユーザーへのおすすめワークフロー**
> GarageBandはノートが存在しないテンポ専用MIDIのインポートに対応していません。
> `midimaker drums "drums.wav" -t "song.mp3"` で**テンポ情報をマージしたドラムMIDI**を生成し、FinderでそのドラムMIDIを **右クリック ＞「このアプリケーションで開く ＞ GarageBand」** することで、プロジェクトのテンポ（BPM）が自動設定された状態でプロジェクトをスタートできます。


### ⏱️ 楽曲からテンポ専用MIDI（Tempo Track）を生成 (Essentia)

フルミックス楽曲（またはステム音源）からテンポ（BPM）およびビート（拍のタイミング）を高精度に解析し、**テンポ情報のみを含むMIDIファイル（Conductor / Tempo Track MIDI）**を出力します。

DAW（Logic Pro, Cubase, Studio One, Ableton Live等）のプロジェクトに最初にこのテンポMIDIをインポートすることで、**プロジェクト全体のテンポマップが自動構築され、後から読み込むドラムMIDI・ベースMIDI・オーディオ波形が小節グリッドにピタッと吸着**します。

微小なテンポ揺らぎ（ジッター）は**適応型セグメンテーション（Adaptive Segmentation）**によって一定範囲内で平均化されるため、DAW上で同じBPMが毎拍連打されることなくスッキリしたテンポマップが得られます。同時に、徐々に減速するリタルダンド（rit.）や加速（accel.）のトレンド変化には高精度に追従します。

```bash
# 基本的な使い方（入力ファイルと同じ場所に _tempo.mid が出力されます）
# デフォルトで楽曲の揺らぎに追従する「テンポマップ」を出力（数秒で完了）
midimaker tempo "path/to/song.mp3"

# 出力先を指定する場合
midimaker tempo "path/to/song.mp3" -o "tempo_map.mid"

# またはエイリアスコマンド
midimaker-tempo "path/to/song.mp3"

# テンポマップではなく、代表固定BPM単一で出力したい場合
midimaker tempo "path/to/song.mp3" --fixed

# テンポ揺らぎの平滑化幅を調整する場合（0以下の場合は平滑化無効）
midimaker tempo "path/to/song.mp3" --tolerance 1.0
```

#### 主なオプション設定

| オプション | デフォルト値 | 説明 |
| :--- | :--- | :--- |
| `-o`, `--output` | 自動命名 | 出力先MIDIファイルパス (省略時は `{入力名}_tempo.mid`) |
| `--fixed` | オフ (テンポマップ) | テンポマップ（可変ビート追従）ではなく、楽曲全体の代表BPM単一で出力 |
| `--tolerance` | `0.8` | 同一区間のテンポ揺らぎとみなして平均化する許容変動幅 (BPM)。0以下の場合は平滑化無効 |




