# 環境構築

## python

uv ＋ direnv を使ってディレクトリ移動時の自動切り替えと高速なパッケージ管理を行う
ただし、uvではanacondaの環境構築が難しいのでpyenvの使用も併用する

併用時の注意点
- Conda 環境下で uv add や uv venv を実行しない: 依存関係の競合を防ぐため、pyenv local で Anaconda を選んだディレクトリでは conda コマンドで管理し、uv は使用しない運用にしてください。
- Python 実体の二重管理: pyenv install で入れた Python と、uv python install で入れた Python は別々の領域に保存されます。ディスク容量を過度に圧迫することはありませんが、別管理になる点は留意してください。

1. ツールをインストール
```bash
brew install uv direnv
```

2. シェルの設定（~/.zshrc に追記）

```bash
# direnv の設定（pyenv より後に読み込む）
eval "$(direnv hook zsh)"

# VIRTUAL_ENV_PROMPT がセットされている時だけプロジェクト名を表示
setopt PROMPT_SUBST
prompt_virtualenv() {
  if [[ -n "$VIRTUAL_ENV_PROMPT" ]]; then
    echo "%F{green}(${VIRTUAL_ENV_PROMPT:t})%f "
  fi
}

PROMPT='$(prompt_virtualenv)'"$PROMPT"
```

3. プロジェクト作成と設定
プロジェクトの作成
```bash
# Pythonバージョンの固定と仮想環境 (.venv) の作成
uv init --python 3.11

# direnvに .venv の自動ロードを指定
echo "source .venv/bin/activate" > .envrc
direnv allow
```

4. 子プロジェクトの作成（任意）

git cloneしたリポジトリにpyproject.tomlが存在するならuv syncで仮想環境が作られる。ただこれだと仮想環境がディレクトリ毎に
別々になってしまうのでワークスペース（Workspace）機能を使うのが良い

- 子ブロジェクトの作成
ワークスペースを使う場合は以下のような構成とする

```text
my-project/
├── .venv/               # 共有される単一の仮想環境
├── pyproject.toml       # 親（ルート）
└── packages/
    ├── lib-a/
    │   └── pyproject.toml
    └── lib-b/
        └── pyproject.toml
```

親の pyproject.toml に [tool.uv.workspace] を定義することで子プロジェクトを管理する

```toml
[project]
name = "my-project"
version = "0.1.0"
dependencies = [
    # ワークスペース内のパッケージを指定
    "lib-a",
]

[tool.uv.workspace]
members = ["packages/*"]

[tool.uv.sources]
lib-a = { workspace = true }
```

親ディレクトリで以下のコマンドを実行するだけでも自動追記されます。

```bash
uv add --workspace lib-a
```

4. uvの基本的な使い方

uvのコマンド体系はシンプルで、直感的に操作できます。

uv add: 依存関係を追加
uv remove: 依存関係を削除
uv sync: 環境を最新の状態に同期
uv run: スクリプトを実行
uv lock: ロックファイルを更新

uv sync を実行すると、自動的に仮想環境（.venv）が作成され、pyproject.toml や uv.lock に記載されている依存関係が高速でインストールされます。
ワークスペースを定義しておくと、子ディレクトリで uv sync などを実行しても別環境は作られず、親ディレクトリの .venv が自動で共有・同期されます。

# adtof_plus_drum_transcription
## インストール

子プロジェクトとしてインストールするとpackages以下もリポジトリに入れないとuv syncで再現できないので
リポジトリを指定する

python3.11の場合は最新のessentiaはコンパイルモジュールが存在しないので先にバージョンを指定してインストールしておく

```
uv add essentia==2.1b6.dev1389
uv add git+https://github.com/xavriley/adtof_plus_drum_transcription.git
```


## 実行
```bash
adtof-transcribe --audio_path samples/03\ 花と夢.mp3 --output_path samples/03\ 花と夢_drums.mid 
```

# Spotify Basic Pitch
## インストール

```bash
uv add basic-pitch
```


# ---------------- 参考
# OMNIZART

python 3.10 でないと動作しない
Spotify Basic Pitch(python3.11)と環境が違いすぎるのでインストールはしないことにした
ベースのMIDI化もイマイチだった

## インストール

インストールが失敗するので pyproject.tomlに以下を記載する
```toml
[tool.uv.extra-build-dependencies]
madmom = ["setuptools<72", "Cython<3", "numpy<2"]
vamp = ["setuptools<72", "numpy<2"]
omnizart = ["setuptools<72", "wheel", "Cython<3", "numpy<2"]
```

```bash
uv add omnizart
```

## 実行
```bash
omnizart download-checkpoints
omnizart music transcribe samples/03\ 花と夢.mp3 -o samples/03\ 花と夢.mid
```

# ---------------- 参考
# adtof_plus_drum_transcription

子プロジェクトとしてインストールした時の情報を残しておく

## インストール

### 子プロジェクトとしてインストールする

親の pyproject.toml に [tool.uv.workspace] を定義することで子プロジェクトを管理する

```toml
[tool.uv.workspace]
members = ["packages/*"]
```

python3.11の場合は最新のessentiaはコンパイルモジュールが存在しないのでバージョンを指定してインストールしておく
```
uv add essentia==2.1b6.dev1389
```

```bash
mkdir packages
cd packages
git clone https://github.com/xavriley/adtof_plus_drum_transcription.git
cd ..
uv add --workspace adtof_plus_drum_transcription
```

## MIDImaker CLI の使い方

### 🎸 ベース音源からクリーンなMIDIを生成 (Spotify Basic Pitch)

ステム分離されたベース音源（WAV, MP3等）から、低音域最適化＆モノフォニック（単音）整形を行ってMIDIを作成します。

```bash
# 基本的な使い方（入力ファイルと同じ場所に _bass.mid が出力されます）
uv run midimaker bass "path/to/bass_stem.wav"

# 出力ファイル名を指定する場合
uv run midimaker bass "path/to/bass_stem.wav" -o "output.mid"

# またはエイリアスコマンド
uv run midimaker-bass "path/to/bass_stem.wav"
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
| `--tempo` | `120.0` | MIDIのデフォルトテンポ (BPM) |

### 🥁 ドラム音源から高精度MIDIを生成 (ADTOF Plus)

ステム分離されたドラム音源（またはフルミックス楽曲）から、DrumSep 5-stems によるパーツ分離、ADTOF Frame_RNN による高精度打点検出、オープン/クローズハイハット判定、ベロシティ推定を行って General MIDI (Ch.10) のドラムMIDIを作成します。

```bash
# 基本的な使い方（入力ファイルと同じ場所に _drums.mid が出力されます）
midimaker drums "path/to/drums_stem.wav"

# 出力先を指定する場合
midimaker drums "path/to/drums_stem.wav" -o "output.mid"

# またはエイリアスコマンド
midimaker-drums "path/to/drums_stem.wav"

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
| `-t`, `--tempo-file` | なし | ドラムMIDIにマージするテンポMIDIファイル (`.mid`) またはテンポ解析元の音声ファイル (`.mp3`, `.wav`) |

> [!TIP]
> **GarageBandユーザーへのおすすめワークフロー**
> GarageBandはノートが存在しないテンポ専用MIDIのインポートに対応していません。
> `midimaker drums "drums.wav" -t "song.mp3"` で**テンポ情報をマージしたドラムMIDI**を生成し、FinderでそのドラムMIDIを **右クリック ＞「このアプリケーションで開く ＞ GarageBand」** することで、プロジェクトのテンポ（BPM）が自動設定された状態でプロジェクトをスタートできます。


### ⏱️ 楽曲からテンポ専用MIDI（Tempo Track）を生成 (Essentia)

フルミックス楽曲（またはステム音源）からテンポ（BPM）およびビート（拍のタイミング）を高精度に解析し、**テンポ情報のみを含むMIDIファイル（Conductor / Tempo Track MIDI）**を出力します。

DAW（Logic Pro, Cubase, Studio One, Ableton Live等）のプロジェクトに最初にこのテンポMIDIをインポートすることで、**プロジェクト全体のテンポマップが自動構築され、後から読み込むドラムMIDI・ベースMIDI・オーディオ波形が小節グリッドにピタッと吸着**します。

```bash
# 基本的な使い方（入力ファイルと同じ場所に _tempo.mid が出力されます）
# デフォルトで楽曲の揺らぎに追従する「テンポマップ」を出力（数秒で完了）
uv run midimaker tempo "path/to/song.mp3"

# 出力先を指定する場合
uv run midimaker tempo "path/to/song.mp3" -o "tempo_map.mid"

# またはエイリアスコマンド
uv run midimaker-tempo "path/to/song.mp3"

# テンポマップではなく、代表固定BPM単一で出力したい場合
uv run midimaker tempo "path/to/song.mp3" --fixed
```

#### 主なオプション設定

| オプション | デフォルト値 | 説明 |
| :--- | :--- | :--- |
| `-o`, `--output` | 自動命名 | 出力先MIDIファイルパス (省略時は `{入力名}_tempo.mid`) |
| `--fixed` | オフ (テンポマップ) | テンポマップ（可変ビート追従）ではなく、楽曲全体の代表BPM単一で出力 |




