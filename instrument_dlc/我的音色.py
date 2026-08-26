# 抖坤音乐工坊 · 音色 DLC（自动生成，可手动微调后重新合成）
# name: 我的音色
import numpy as np
from synth_factory import render as _sf_render

DLC = {
    'label': '我的音色',
    'family': '我的DLC',
    'needs_freq': True,
    'kind': 'tonal',
    'sustain': 0.8,
    'func': 'render',
    'type': 'sine',
    'params': {'attack_ms': 20.0, 'decay_ms': 120.0, 'sustain': 0.8, 'release_ms': 250.0, 'gain': 0.9, 'detune_cents': 0.0},
}

def render(freq, dur=2.0, sr=44100, **kwargs):
    chord = DLC.get('chord')
    if chord:
        out = np.zeros(int(dur * sr), dtype=np.float64)
        for off in chord:
            f = freq * (2.0 ** (off / 12.0))
            out = out + _sf_render(DLC['type'], f, dur, sr, DLC['params'])
        peak = float(np.max(np.abs(out)))
        if peak > 1e-6:
            out = out / peak * 0.9
        return out.astype(np.float32)
    return _sf_render(DLC['type'], freq, dur, sr, DLC['params'])
