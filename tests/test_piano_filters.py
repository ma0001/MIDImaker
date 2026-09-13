"""
ピアノフィルター（半音衝突抑制・短小・微弱ノート除去・連打抑制）の単体テスト
"""
import pretty_midi
from midimaker.piano import (
    filter_debounce_notes,
    filter_short_and_quiet_notes,
    filter_semitone_clash,
)


def create_mock_instrument(notes_data):
    """
    notes_data: list of tuples (pitch, start, end, velocity)
    """
    inst = pretty_midi.Instrument(program=0, is_drum=False, name="Piano")
    for pitch, start, end, vel in notes_data:
        inst.notes.append(pretty_midi.Note(velocity=vel, pitch=pitch, start=start, end=end))
    return inst


def test_filter_short_and_quiet_notes():
    # 正常音 (C4: 0.0〜0.5s, vel 80)
    # 短小ゴミ音 (D4: 0.1〜0.12s [20ms], vel 70)
    # 微弱ゴミ音 (E4: 0.2〜0.6s [400ms], vel 15)
    inst = create_mock_instrument([
        (60, 0.0, 0.5, 80),
        (62, 0.1, 0.12, 70),
        (64, 0.2, 0.6, 15),
    ])

    rem_short, rem_quiet = filter_short_and_quiet_notes(inst, min_duration_ms=40, min_velocity=25)
    assert rem_short == 1, "20msの短小ノートが1件除去されること"
    assert rem_quiet == 1, "ベロシティ15の微弱ノートが1件除去されること"
    assert len(inst.notes) == 1, "正常なノートのみ残ること"
    assert inst.notes[0].pitch == 60


def test_filter_semitone_clash_simultaneous_attack():
    # 同時アタック（アタック差 10ms）での半音衝突:
    # C4 (60, start=1.0, end=1.5, vel=85) 主音
    # C#4 (61, start=1.01, end=1.3, vel=45) リークゴースト音
    inst = create_mock_instrument([
        (60, 1.0, 1.5, 85),
        (61, 1.01, 1.3, 45),
    ])

    rem_clashes = filter_semitone_clash(inst, clash_window_ms=80)
    assert rem_clashes == 1, "弱い側の半音ゴーストが除去されること"
    assert len(inst.notes) == 1
    assert inst.notes[0].pitch == 60
    assert inst.notes[0].velocity == 85


def test_filter_semitone_clash_same_velocity():
    # ベロシティが同じ場合の同時アタック半音衝突:
    # 短い方がゴースト判定されて除去されること
    # C4 (60, start=1.0, end=1.8, vel=75) 長い主音
    # B3 (59, start=1.0, end=1.2, vel=75) 短い誤検知音
    inst = create_mock_instrument([
        (60, 1.0, 1.8, 75),
        (59, 1.0, 1.2, 75),
    ])

    rem_clashes = filter_semitone_clash(inst, clash_window_ms=80)
    assert rem_clashes == 1
    assert len(inst.notes) == 1
    assert inst.notes[0].pitch == 60
    assert inst.notes[0].end == 1.8


def test_filter_semitone_clash_preserves_whole_tones():
    # 全音以上離れた音（例: C4=60 と D4=62）は同時打鍵でも両方残ること
    inst = create_mock_instrument([
        (60, 1.0, 1.5, 80),
        (62, 1.0, 1.5, 50),
    ])

    rem_clashes = filter_semitone_clash(inst, clash_window_ms=80)
    assert rem_clashes == 0, "全音離れた音は衝突判定されないこと"
    assert len(inst.notes) == 2


def test_filter_semitone_clash_preserves_legitimate_melody():
    # サステイン中に次の小節・拍でしっかりした音量で移行するメロディは保護されること
    # C4 (60, start=0.0, end=2.0, vel=80) サステイン中
    # B3 (59, start=1.0, end=2.0, vel=78) 次の音（十分なベロシティ）
    inst = create_mock_instrument([
        (60, 0.0, 2.0, 80),
        (59, 1.0, 2.0, 78),
    ])

    rem_clashes = filter_semitone_clash(inst, clash_window_ms=80, velocity_ratio=0.85)
    assert rem_clashes == 0, "しっかりした音量の正当なメロディ進行は削除されないこと"
    assert len(inst.notes) == 2


if __name__ == "__main__":
    print("🧪 Running piano filter tests...")
    test_filter_short_and_quiet_notes()
    print("  ✅ test_filter_short_and_quiet_notes passed")
    test_filter_semitone_clash_simultaneous_attack()
    print("  ✅ test_filter_semitone_clash_simultaneous_attack passed")
    test_filter_semitone_clash_same_velocity()
    print("  ✅ test_filter_semitone_clash_same_velocity passed")
    test_filter_semitone_clash_preserves_whole_tones()
    print("  ✅ test_filter_semitone_clash_preserves_whole_tones passed")
    test_filter_semitone_clash_preserves_legitimate_melody()
    print("  ✅ test_filter_semitone_clash_preserves_legitimate_melody passed")
    print("🎉 All 5 tests passed successfully!")

