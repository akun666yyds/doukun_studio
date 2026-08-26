"""AI 采样导入工具（对应「轻量:AI 离线批量生成 samples/*.wav 覆盖」路线）。

用法:
  python ingest_samples.py                  # 扫描 ./samples_incoming/ 并导入到 ./samples/
  python ingest_samples.py <源目录>          # 指定源目录
  python ingest_samples.py --check          # 只检查 ./samples/ 当前覆盖情况, 不写入
  python ingest_samples.py --dry            # 仅解析/转换并报告, 不写入

导入约定(文件名必须这样, 否则无法识别):
  {乐器key}_{MIDI音高}.wav   例如  synth_lead_60.wav   kick_36.wav
  乐器 key 取值(11 个):
    synth_lead bass pluck pad piano strings brass kick snare hihat vocal
  MIDI 音高范围 36..72 (C2..C5, 共 3 个八度)。缺失的音高会自动回退到程序化合成, 不会报错。

格式: 脚本会把任意输入(立体声/48k/24bit 等)统一转成 44100Hz / 单声道 / 16bit PCM,
       因此你导出的 AI 采样无需手动预处理, 直接丢进来即可。
"""
import os
import re
import argparse
import numpy as np

import synth
import audio_engine as ae

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
INCOMING = os.path.join(SCRIPT_DIR, 'samples_incoming')
SAMPLE_DIR = ae.SAMPLE_DIR

_NAME_RE = re.compile(r'^(.+)[_-](\d{1,3})$')


def _parse_name(fname):
    """返回 (key, midi) 或 None。"""
    base = os.path.splitext(fname)[0]
    m = _NAME_RE.match(base)
    if not m:
        return None
    stem, midi_str = m.group(1), m.group(2)
    midi = int(midi_str)
    if stem in synth.INSTRUMENT_KEYS:
        key = stem
    elif stem in synth.LABEL_TO_KEY:
        key = synth.LABEL_TO_KEY[stem]
    else:
        return None
    if not (synth.MIDI_LOW <= midi <= synth.MIDI_HIGH):
        return None
    return key, midi


def _load_any(path):
    """读取任意格式音频 -> (mono float32 [-1,1], sr)。优先 soundfile, 退化用 wave。"""
    try:
        import soundfile as sf
        data, sr = sf.read(path, always_2d=False)
        data = np.asarray(data, dtype=np.float64)
        if data.ndim > 1:
            data = data.mean(axis=1)
        return data.astype(np.float32), int(sr)
    except Exception:
        pass
    import wave
    with wave.open(path, 'r') as w:
        n = w.getnframes()
        sr = w.getframerate()
        raw = w.readframes(n)
    data = np.frombuffer(raw, dtype='<i2').astype(np.float32) / 32767.0
    return data, int(sr)


def _resample(data, sr):
    if sr == ae.SR:
        return data
    n_new = int(round(len(data) * ae.SR / sr))
    try:
        from scipy.signal import resample as sp_resample
        return sp_resample(data, n_new).astype(np.float32)
    except Exception:
        t_old = np.linspace(0.0, 1.0, len(data), endpoint=False)
        t_new = np.linspace(0.0, 1.0, n_new, endpoint=False)
        return np.interp(t_new, t_old, data).astype(np.float32)


def _normalize(data):
    return np.clip(data, -1.0, 1.0).astype(np.float32)


def ingest(source_dir, do_write=True):
    os.makedirs(SAMPLE_DIR, exist_ok=True)
    matched = 0
    unmatched = []
    for fname in sorted(os.listdir(source_dir)):
        if not fname.lower().endswith(('.wav', '.flac', '.ogg', '.aif', '.aiff')):
            continue
        parsed = _parse_name(fname)
        if parsed is None:
            unmatched.append(fname)
            continue
        key, midi = parsed
        try:
            data, sr = _load_any(os.path.join(source_dir, fname))
        except Exception as e:
            unmatched.append(f'{fname} (读失败: {e})')
            continue
        data = _normalize(_resample(data, sr))
        if do_write:
            ae._write_wav(ae._sample_path(key, midi), data, ae.SR)
        matched += 1
    return matched, unmatched


def coverage_report():
    total = len(synth.INSTRUMENT_KEYS) * (synth.MIDI_HIGH - synth.MIDI_LOW + 1)
    have = 0
    missing = []
    for key in synth.INSTRUMENT_KEYS:
        for midi in range(synth.MIDI_LOW, synth.MIDI_HIGH + 1):
            if os.path.exists(ae._sample_path(key, midi)):
                have += 1
            else:
                missing.append((key, midi))
    print(f"\n采样覆盖: {have}/{total}")
    if missing:
        by_key = {}
        for k, m in missing:
            by_key.setdefault(k, []).append(m)
        print("缺失(将自动回退到程序化合成):")
        for k in synth.INSTRUMENT_KEYS:
            if k in by_key:
                ms = by_key[k]
                print(f"  {k}: {len(ms)} 个 (如 {ms[0]}..{ms[-1]})")
    else:
        print("全部 407 个采样已就绪 ✓")


def main():
    ap = argparse.ArgumentParser(description='AI 采样导入工具')
    ap.add_argument('source', nargs='?', default=INCOMING, help='源目录(默认 ./samples_incoming)')
    ap.add_argument('--check', action='store_true', help='只检查 samples/ 覆盖情况')
    ap.add_argument('--dry', action='store_true', help='只解析/转换但不写入')
    args = ap.parse_args()

    if args.check:
        coverage_report()
        return

    if args.source.lower().endswith('.sf2'):
        print("SoundFont(.sf2) 需要额外渲染器(pyfluidsynth), 当前未实现。请先导出为 WAV 再导入。")
        return

    if not os.path.isdir(args.source):
        print(f"源目录不存在: {args.source}\n请把 AI 生成的 WAV 放到该目录(命名 key_midi.wav), 或指定源目录。")
        return

    matched, unmatched = ingest(args.source, do_write=not args.dry)
    print(f"已识别并导入: {matched} 个")
    if args.dry:
        print("(dry 模式, 未写入)")
    if unmatched:
        print(f"\n未能识别/失败 {len(unmatched)} 个(已跳过):")
        for u in unmatched[:50]:
            print("  -", u)
    coverage_report()


if __name__ == '__main__':
    main()
