# 環境構築

## python

# adtof_plus_drum_transcription
## インストール
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

# Audio Separator
## インストール

```bash
uv add "audio-separator[cpu]"
```

# add piano_transcription_inference
## インストール

```bash
uv add piano_transcription_inference
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

