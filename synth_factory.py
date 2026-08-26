"""音色合成工厂（用户可增量开发的「音色 DLC」内核）。

围绕技能 electronic-instrument-synthesis 的信号链（OSC → FILTER → AMP/ADSR），
提供一套参数化、可实时试听、可导出为独立 .py 模块的合成器内核。

设计目标（对应需求）：
- 用户在「音色合成工坊」选函数类型 + 拖动参数滑块，即可试听；
- 点「合成」把当前参数烘焙成一个自包含的 .py 模块，写入 instrument_dlc/；
- 该模块可被主程序即插即用注册（运行时随添随删），也可作为 DLC 分发给他人。

导出模块约定（由 build_dlc_source 生成，self-contained）：
    DLC = {'label':..., 'family':'我的DLC', 'needs_freq':True,
           'kind':'tonal', 'sustain':..., 'func':'render',
           'type':<函数类型>, 'params':{...}}
    from synth_factory import render as _sf_render
    def render(freq, dur=2.0, sr=44100, **kwargs):
        return _sf_render(DLC['type'], freq, dur, sr, DLC['params'])

本文件只依赖 numpy，无任何循环导入（synth.py 反向 import 本文件的 DLC_DIR）。
"""
import os
import re
import sys
import shutil
import numpy as np

SR = 44100

# DLC 存放目录（与 synth.py 共享同一路径；synth.py 通过 `from synth_factory import DLC_DIR` 复用）
#
# 冻结（PyInstaller 单文件 exe）时，本模块被解压到临时只读目录（sys._MEIPASS），
# 不能直接往里写 DLC——而用户需要「生成 / 注册 / 编辑 / 删除」DLC，目录必须可写。
# 因此冻结后把 DLC_DIR 解析到可写位置：优先 exe 同级（便携），不可写则回退 LOCALAPPDATA。
# 首次运行时，若 exe 内打包了 instrument_dlc（_MEIPASS/instrument_dlc）则播种到可写目录；
# 现已不再打包任何示例 DLC，该目录为空，播种逻辑自动跳过——用户得到干净的 DLC 空间。
def _resolve_dlc_dir():
    base = os.path.dirname(os.path.abspath(__file__))
    if getattr(sys, 'frozen', False):
        # 用户要求：用户管理的 DLC 严格绑定 exe 同级 instrument_dlc/（便携、可写），
        # 不再回退 LOCALAPPDATA，避免「打包时打错目录」导致 DLC 落到别处 / 与旧缓存混淆。
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        cand = os.path.join(exe_dir, 'instrument_dlc')
        try:
            os.makedirs(cand, exist_ok=True)
        except Exception:
            pass
        return cand
    return os.path.join(base, 'instrument_dlc')


DLC_DIR = _resolve_dlc_dir()


def _seed_bundled_dlc():
    """冻结后首次运行：把打包进 exe 的示例 DLC 复制到可写 DLC_DIR（已存在则跳过，避免覆盖用户编辑）。"""
    if not getattr(sys, 'frozen', False):
        return
    bundled = os.path.join(getattr(sys, '_MEIPASS', ''), 'instrument_dlc')
    if not os.path.isdir(bundled):
        return
    os.makedirs(DLC_DIR, exist_ok=True)
    for fn in os.listdir(bundled):
        if not fn.endswith('.py'):
            continue
        if fn in ('synth_factory.py', 'dlc_base.py'):
            continue
        dst = os.path.join(DLC_DIR, fn)
        if not os.path.exists(dst):
            try:
                shutil.copy(os.path.join(bundled, fn), dst)
            except Exception:
                pass


_seed_bundled_dlc()

# ---------------------------------------------------------------------------
# 函数类型
# ---------------------------------------------------------------------------
SYNTH_TYPES = ['sine', 'saw', 'square', 'triangle', 'pulse', 'fm', 'additive', 'noise',
                'pluck', 'piano', 'bell', 'flute', 'bowed', 'brass']
TYPE_LABELS = {
    'sine':     '正弦 Sine',
    'saw':      '锯齿 Saw',
    'square':   '方波 Square',
    'triangle': '三角 Triangle',
    'pulse':    '脉冲 Pulse',
    'fm':       'FM 合成',
    'additive': '加法合成',
    'noise':    '噪声 Noise',
    'pluck':    '拨弦 Karplus',
    'piano':    '钢琴 Piano',
    'bell':     '钟声 Bell',
    'flute':    '长笛 Flute',
    'bowed':    '弦乐 Bowed',
    'brass':    '铜管 Brass',
}

# 每个参数的 (最小值, 最大值, 步进, 默认值)
PARAM_SCHEMA = {
    'attack_ms':    (0, 2000, 10, 20),
    'decay_ms':     (0, 2000, 10, 120),
    'sustain':      (0.0, 1.0, 0.01, 0.8),
    'release_ms':   (0, 3000, 10, 250),
    'gain':         (0.1, 1.0, 0.01, 0.9),
    'detune_cents': (-50, 50, 1, 0),
    'harmonics':    (1, 40, 1, 16),
    'cutoff':       (200, 12000, 50, 7000),
    'resonance':    (0.0, 1.0, 0.01, 0.15),
    'pulse_width':  (5, 95, 1, 50),
    'fm_ratio':     (0.25, 8.0, 0.05, 2.0),
    'fm_index':     (0.0, 20.0, 0.1, 5.0),
    'brightness':   (0.0, 1.0, 0.01, 0.3),
    'noise_color':  (0.0, 1.0, 0.01, 0.0),
    # —— 物理建模 / 模态合成（复刻真实乐器）——
    'pluck_decay':  (0.90, 0.999, 0.001, 0.996),   # KS 反馈衰减：0.996 中速吉他，0.999 长延音
    'pluck_stretch':(0.0, 1.0, 0.01, 0.5),          # KS 加权比 S：0.5 平衡；<0.5 更亮更短，>0.5 更闷更长
    'piano_ih':     (0.0, 0.003, 0.0001, 0.0006),   # 钢琴刚性非谐系数 B（拉伸分音）
    'piano_decay':  (0.5, 6.0, 0.1, 2.5),           # 基音衰减时间尺度 T60(s)
    'bell_decay':   (0.5, 12.0, 0.1, 6.0),          # 钟声基分音衰减时间(s)
    'bell_partials':(4, 12, 1, 9),                  # 钟声非谐分音数量
    'flute_breath': (0.0, 0.6, 0.01, 0.15),         # 长笛气息噪声量
    'flute_vib':    (0.0, 1.0, 0.01, 0.4),          # 长笛颤音深度
    'bow_vib':      (0.0, 1.0, 0.01, 0.3),          # 弓弦颤音深度
    'bow_noise':    (0.0, 0.3, 0.01, 0.05),         # 弓弦摩擦噪声量
    'brass_bright': (0.0, 1.0, 0.01, 0.6),          # 铜管亮度（低通截止）
}
PARAM_LABELS = {
    'attack_ms':    '起音 A (ms)',
    'decay_ms':     '衰减 D (ms)',
    'sustain':      '延音 S (电平)',
    'release_ms':   '释音 R (ms)',
    'gain':         '音量',
    'detune_cents': '失谐 (音分)',
    'harmonics':    '谐波数',
    'cutoff':       '滤波截止 (Hz)',
    'resonance':    '共振 Q',
    'pulse_width':  '脉冲占空 (%)',
    'fm_ratio':     'FM 比率',
    'fm_index':     'FM 深度',
    'brightness':   '亮度',
    'noise_color':  '噪声色调 (白→粉)',
    # 物理建模 / 模态
    'pluck_decay':  '拨弦延音 γ',
    'pluck_stretch':'拨弦明亮度 S',
    'piano_ih':     '钢琴非谐性 B',
    'piano_decay':  '钢琴衰减 T60',
    'bell_decay':   '钟声衰减 T60',
    'bell_partials':'钟声分音数',
    'flute_breath': '长笛气息',
    'flute_vib':    '长笛颤音',
    'bow_vib':      '弓弦颤音',
    'bow_noise':    '弓弦摩擦',
    'brass_bright': '铜管亮度',
}
# 每个函数类型使用的参数（顺序即 UI 滑块顺序）
TYPE_PARAMS = {
    'sine':     ['attack_ms', 'decay_ms', 'sustain', 'release_ms', 'gain', 'detune_cents'],
    'saw':      ['harmonics', 'cutoff', 'resonance', 'attack_ms', 'decay_ms', 'sustain', 'release_ms', 'gain', 'detune_cents'],
    'square':   ['harmonics', 'cutoff', 'resonance', 'attack_ms', 'decay_ms', 'sustain', 'release_ms', 'gain', 'detune_cents'],
    'triangle': ['harmonics', 'cutoff', 'resonance', 'attack_ms', 'decay_ms', 'sustain', 'release_ms', 'gain', 'detune_cents'],
    'pulse':    ['pulse_width', 'harmonics', 'cutoff', 'resonance', 'attack_ms', 'decay_ms', 'sustain', 'release_ms', 'gain', 'detune_cents'],
    'fm':       ['fm_ratio', 'fm_index', 'harmonics', 'attack_ms', 'decay_ms', 'sustain', 'release_ms', 'gain', 'detune_cents'],
    'additive': ['harmonics', 'brightness', 'attack_ms', 'decay_ms', 'sustain', 'release_ms', 'gain', 'detune_cents'],
    'noise':    ['noise_color', 'cutoff', 'resonance', 'attack_ms', 'decay_ms', 'sustain', 'release_ms', 'gain'],
    # 物理建模 / 模态合成（复刻真实乐器）
    'pluck':    ['pluck_decay', 'pluck_stretch', 'detune_cents', 'gain'],
    'piano':    ['piano_ih', 'piano_decay', 'harmonics', 'brightness', 'detune_cents', 'gain'],
    'bell':     ['bell_decay', 'bell_partials', 'detune_cents', 'gain'],
    'flute':    ['flute_breath', 'flute_vib', 'attack_ms', 'release_ms', 'detune_cents', 'gain'],
    'bowed':    ['bow_noise', 'bow_vib', 'attack_ms', 'sustain', 'release_ms', 'detune_cents', 'gain'],
    'brass':    ['brass_bright', 'attack_ms', 'sustain', 'release_ms', 'detune_cents', 'gain'],
}

PARAM_DEFAULTS = {k: v[3] for k, v in PARAM_SCHEMA.items()}


# ---------------------------------------------------------------------------
# 滤波器（RBJ 双二阶低通；优先用 scipy 的 lfilter 加速，否则回落到矢量/循环实现）
# ---------------------------------------------------------------------------
def _rbj_lowpass(sr, fc, q):
    fc = min(max(fc, 20.0), sr * 0.45)
    w0 = 2 * np.pi * fc / sr
    cw = np.cos(w0)
    sw = np.sin(w0)
    alpha = sw / (2.0 * q)
    b0 = (1.0 - cw) / 2.0
    b1 = 1.0 - cw
    b2 = (1.0 - cw) / 2.0
    a0 = 1.0 + alpha
    a1 = -2.0 * cw
    a2 = 1.0 - alpha
    return (np.array([b0, b1, b2]) / a0, np.array([1.0, a1, a2]) / a0)


def _lowpass(x, sr, fc, q):
    try:
        from scipy.signal import lfilter
        b, a = _rbj_lowpass(sr, fc, q)
        return lfilter(b, a, x)
    except Exception:
        # 无 scipy 时的回落：RBJ 双二阶直接Ⅰ型实现。
        # 旧实现用的是状态变量(SVF)递归，在截止频率偏高(q 较小)时极点
        # 落到单位圆外、状态量指数溢出成 NaN/Inf（实测 brass 拉满亮度即触发）。
        # 直接Ⅰ型用已归一化的系数递推，对「稳定低通」系数恒稳健，不再溢出。
        return _biquad_lowpass(x, sr, fc, q)


def _biquad_lowpass(x, sr, fc, q):
    """RBJ 双二阶低通的直接Ⅰ型实现（无 scipy 时的数值稳健回落）。

    系数来自 _rbj_lowpass（已除以 a0），直接Ⅰ型递推 y = b0·x + b1·x1 + b2·x2
    − a1·y1 − a2·y2；对合法低通系数（极点恒在单位圆内）不会发散。
    """
    x = np.asarray(x, dtype=np.float64)
    b, a = _rbj_lowpass(sr, fc, q)  # b,a 均已按 a0 归一
    b0, b1, b2 = b
    a1, a2 = a[1], a[2]
    n = len(x)
    y = np.empty(n, dtype=np.float64)
    x1 = x2 = 0.0
    y1 = y2 = 0.0
    for i in range(n):
        xi = x[i]
        yi = b0 * xi + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
        y[i] = yi
        x2 = x1
        x1 = xi
        y2 = y1
        y1 = yi
    return y


# ---------------------------------------------------------------------------
# 振荡器（谐波结构决定音色亮度；全谐波 saw 最亮，纯正弦最干净）
# ---------------------------------------------------------------------------
def _partials(type_name, freq, dur, sr, p):
    n = int(dur * sr)
    if n <= 0:
        return np.zeros(0, dtype=np.float64)
    t = np.arange(n) / sr
    nyq = sr / 2.0
    maxh = int(min(p.get('harmonics', 16), max(1, int(nyq // max(freq, 20.0)))))
    maxh = max(1, maxh)

    if type_name == 'sine':
        return np.sin(2.0 * np.pi * freq * t)

    if type_name == 'saw':
        y = np.zeros(n)
        for k in range(1, maxh + 1):
            y = y + ((-1) ** (k + 1) / k) * np.sin(2.0 * np.pi * k * freq * t)
        return y * (2.0 / np.pi)

    if type_name == 'square':
        y = np.zeros(n)
        for k in range(1, maxh + 1, 2):
            y = y + (1.0 / k) * np.sin(2.0 * np.pi * k * freq * t)
        return y * (4.0 / np.pi)

    if type_name == 'triangle':
        y = np.zeros(n)
        for k in range(1, maxh + 1, 2):
            y = y + ((-1) ** ((k - 1) // 2) / (k ** 2)) * np.sin(2.0 * np.pi * k * freq * t)
        return y * (8.0 / np.pi ** 2)

    if type_name == 'pulse':
        d = max(0.02, min(0.98, p.get('pulse_width', 50) / 100.0))
        y = np.zeros(n)
        for k in range(1, maxh + 1):
            y = y + (2.0 / (k * np.pi) * np.sin(k * np.pi * d)) * np.sin(2.0 * np.pi * k * freq * t)
        return y + (2.0 * d - 1.0)

    if type_name == 'fm':
        ratio = p.get('fm_ratio', 2.0)
        idx = p.get('fm_index', 5.0)
        return np.sin(2.0 * np.pi * freq * t + idx * np.sin(2.0 * np.pi * ratio * freq * t))

    if type_name == 'additive':
        b = p.get('brightness', 0.3)
        y = np.zeros(n)
        for k in range(1, maxh + 1):
            w = 1.0 / (k ** (1.0 + b * 3.0))
            y = y + w * np.sin(2.0 * np.pi * k * freq * t)
        return y

    if type_name == 'noise':
        x = np.random.uniform(-1.0, 1.0, n)
        col = p.get('noise_color', 0.0)
        if col > 0.01:
            pink = _lowpass(x, sr, 1400.0, 0.7)
            x = (1.0 - col) * np.random.uniform(-1.0, 1.0, n) + col * pink
        return x

    return np.sin(2.0 * np.pi * freq * t)


def _adsr(dur, sr, p):
    n = int(dur * sr)
    if n <= 0:
        return np.zeros(0, dtype=np.float64)
    a = max(1, int(p.get('attack_ms', 20) / 1000.0 * sr))
    d = max(0, int(p.get('decay_ms', 120) / 1000.0 * sr))
    s = float(p.get('sustain', 0.8))
    r = max(0, int(p.get('release_ms', 250) / 1000.0 * sr))
    env = np.ones(n, dtype=np.float64)
    if a < n:
        env[:a] = np.linspace(0.0, 1.0, a)
    else:
        return np.linspace(0.0, 1.0, n)
    if d > 0 and a + d < n:
        env[a:a + d] = np.linspace(1.0, s, d)
        env[a + d:] = s
    else:
        env[a:] = s
    if r > 0:
        rr = min(r, n - a)
        if rr > 0:
            env[n - rr:] = env[n - rr:] * np.linspace(1.0, 0.0, rr)
    return env


# ---------------------------------------------------------------------------
# 物理建模 / 模态合成（复刻真实乐器，非纯电音）
# 这些类型自带包络/衰减，绕过通用「低通+ADSR」管线，由 _render_physical 产出完整波形
# ---------------------------------------------------------------------------
_PHYSICAL_TYPES = {'pluck', 'piano', 'bell', 'flute', 'bowed', 'brass'}


def render(type_name, freq, dur=2.0, sr=SR, params=None):
    """按函数类型 + 参数合成单音（float32, -1..1）。

    type_name: 'sine'/'saw'/'square'/'triangle'/'pulse'/'fm'/'additive'/'noise'
               'pluck'/'piano'/'bell'/'flute'/'bowed'/'brass'（物理建模/模态）
    freq:      基频 Hz
    params:    覆盖默认参数的字典（见 PARAM_SCHEMA）
    """
    p = dict(PARAM_DEFAULTS)
    if params:
        p.update(params)
    det = p.get('detune_cents', 0) or 0
    f = freq * (2.0 ** (det / 1200.0)) if det else float(freq)

    if type_name in _PHYSICAL_TYPES:
        sig = _render_physical(type_name, f, dur, sr, p)
    else:
        raw = _partials(type_name, f, dur, sr, p)
        if raw.size == 0:
            return np.zeros(1, dtype=np.float32)
        pk = float(np.max(np.abs(raw)))
        raw = raw / pk if pk > 1e-6 else raw

        # 滤波（纯正弦保持干净，其余按 cutoff/resonance 做低通）
        if type_name != 'sine':
            cutoff = p.get('cutoff', 7000)
            if cutoff < 12000:
                q = 0.5 + p.get('resonance', 0.15) * 8.0
                raw = _lowpass(raw, sr, cutoff, q)

        sig = raw * _adsr(dur, sr, p)

    sig = sig * p.get('gain', 0.9)
    pk = float(np.max(np.abs(sig)))
    if pk > 1e-6:
        sig = sig / pk * 0.9
    return sig.astype(np.float32)


def _render_physical(type_name, f, dur, sr, p):
    """物理建模/模态合成的统一入口（返回 float64 波形，未做最终归一）。"""
    if type_name == 'pluck':
        return _ks_pluck(f, dur, sr, p)
    if type_name == 'piano':
        return _piano_voice(f, dur, sr, p)
    if type_name == 'bell':
        return _bell_voice(f, dur, sr, p)
    if type_name == 'flute':
        return _wind_voice(f, dur, sr, p, kind='flute')
    if type_name == 'bowed':
        return _wind_voice(f, dur, sr, p, kind='bowed')
    if type_name == 'brass':
        return _brass_voice(f, dur, sr, p)
    return np.sin(2.0 * np.pi * f * np.arange(int(dur * sr)) / sr)


def _ks_pluck(f, dur, sr, p):
    """Karplus-Strong 拨弦（吉他/竖琴/琵琶/拨奏）。

    算法：延迟线 N=fs/f 填白噪声，反馈 y=decay*((1-S)*y[n-N]+S*y[n-N+1])（两点平均=低通）。
    decay γ：0.90 短促、0.996 中速吉他、0.999 长延音；S：0.5 平衡，<0.5 更亮更短，>0.5 更闷更长。
    来源：Karplus & Strong 1983；Jaffe & Smith 扩展（S 加权、分数延迟）。
    """
    n = int(dur * sr)
    if n <= 0:
        return np.zeros(0, dtype=np.float64)
    decay = float(min(0.999, max(0.90, p.get('pluck_decay', 0.996))))
    bright = float(p.get('pluck_stretch', 0.5))
    N = sr / f
    Nint = max(2, int(round(N)))
    buf = np.random.uniform(-1.0, 1.0, Nint).astype(np.float64)
    out = np.empty(n, dtype=np.float64)
    S = 0.5 + (bright - 0.5) * 0.8   # 映射到 0.1..0.9
    pos = 0
    L = Nint
    for i in range(n):
        cur = buf[pos]
        nxt = buf[(pos + 1) % L]
        out[i] = cur
        buf[pos] = decay * ((1.0 - S) * cur + S * nxt)
        pos = (pos + 1) % L
    return out


def _piano_voice(f, dur, sr, p):
    """钢琴 additive 合成（刚性弦非谐拉伸 + 高次分音衰减更快 + 槌击噪声）。

    分音：f_k = k·f0·√(1+B·k²)（B 非谐系数，钢琴约 1e-3 量级）；
    振幅 ~ 1/k^(0.8+brightness)；衰减 τ_k = T60/√k（高次更快）；
    起始加一段短促槌击噪声。来源：Stanford CCRMA / Bank & Välimäki 2003。
    """
    n = int(dur * sr)
    if n <= 0:
        return np.zeros(0, dtype=np.float64)
    t = np.arange(n) / sr
    K = int(min(p.get('harmonics', 24), 60))
    B = float(p.get('piano_ih', 0.0006))
    T60 = float(p.get('piano_decay', 2.5))
    bright = float(p.get('brightness', 0.3))
    out = np.zeros(n, dtype=np.float64)
    # 槌击噪声（短促起音 click）
    clk = int(0.0025 * sr)
    if clk > 0:
        out[:clk] += np.random.uniform(-0.25, 0.25, clk)
    for k in range(1, K + 1):
        fk = k * f * (1.0 + B * k * k / 2.0)
        if fk >= sr * 0.45:
            break
        amp = 1.0 / (k ** (0.8 + bright))
        tau = max(0.05, T60 / (k ** 0.5))
        out += amp * np.sin(2.0 * np.pi * fk * t) * np.exp(-t / tau)
    return out


def _bell_voice(f, dur, sr, p):
    """钟声/锣 模态合成（各分音独立指数衰减，高次更快）。

    非谐分音比取真实教堂钟（Fletcher & Rossing）：hum 0.5 / prime 1.0 / tierce 1.183 /
    quint 1.5 / nominal 2.0 / maj3 2.5 / 4th 2.667 / 12th 3.0 / 8.0 倍… 各分音 exp 衰减。
    """
    n = int(dur * sr)
    if n <= 0:
        return np.zeros(0, dtype=np.float64)
    t = np.arange(n) / sr
    T60 = float(p.get('bell_decay', 6.0))
    npart = int(min(p.get('bell_partials', 9), 12))
    ratios = [0.5, 1.0, 1.183, 1.5, 2.0, 2.5, 2.667, 3.0, 4.0, 5.33, 6.67, 8.0]
    amps = [0.55, 1.0, 0.8, 0.7, 0.9, 0.5, 0.4, 0.6, 0.5, 0.35, 0.3, 0.25]
    out = np.zeros(n, dtype=np.float64)
    for i in range(npart):
        fk = f * ratios[i]
        if fk >= sr * 0.45:
            break
        a = amps[i]
        tau = T60 / (1.0 + i * 0.5)
        out += a * np.sin(2.0 * np.pi * fk * t) * np.exp(-t / tau)
    # 起始敲击瞬态
    clk = int(0.002 * sr)
    if clk > 0:
        out[:clk] += np.random.uniform(-0.3, 0.3, clk)
    return out


def _wind_voice(f, dur, sr, p, kind='flute'):
    """管乐近似：长笛（纯音+气息噪声+颤音）/ 弓弦（锯齿+摩擦噪声+慢起音+颤音）。"""
    n = int(dur * sr)
    if n <= 0:
        return np.zeros(0, dtype=np.float64)
    t = np.arange(n) / sr
    vib_rate = 5.0
    if kind == 'flute':
        vib = 1.0 + (p.get('flute_vib', 0.4) * 0.01) * np.sin(2.0 * np.pi * vib_rate * t)
    else:
        vib = 1.0 + (p.get('bow_vib', 0.3) * 0.01) * np.sin(2.0 * np.pi * vib_rate * t)
    env = _adsr(dur, sr, p)
    if kind == 'flute':
        breath = p.get('flute_breath', 0.15)
        tone = np.sin(2.0 * np.pi * f * t * vib)
        noise = _lowpass(np.random.uniform(-1.0, 1.0, n), sr, 2200.0, 0.7) * breath
        return (tone + noise) * env
    else:  # bowed string
        bnoise = p.get('bow_noise', 0.05)
        maxh = min(40, int(sr * 0.45 // max(f, 20.0)))
        tone = np.zeros(n)
        for k in range(1, maxh + 1):
            tone += (1.0 / k) * np.sin(2.0 * np.pi * k * f * t * vib)
        tone = tone * (2.0 / np.pi)
        noise = _lowpass(np.random.uniform(-1.0, 1.0, n), sr, 3000.0, 0.7) * bnoise
        return (tone + noise) * env


def _brass_voice(f, dur, sr, p):
    """铜管近似：双失谐锯齿叠加 + 亮度低通 + ADSR（小号/长号/圆号感）。"""
    n = int(dur * sr)
    if n <= 0:
        return np.zeros(0, dtype=np.float64)
    t = np.arange(n) / sr
    env = _adsr(dur, sr, p)
    bright = float(p.get('brass_bright', 0.6))
    maxh = min(40, int(sr * 0.45 // max(f, 20.0)))
    out = np.zeros(n)
    for k in range(1, maxh + 1):
        out += (1.0 / k) * np.sin(2.0 * np.pi * k * f * t)
        out += (1.0 / k) * np.sin(2.0 * np.pi * k * f * 1.005 * t)  # 失谐 5 音分增厚
    out = out * (1.0 / np.pi)
    cutoff = 800.0 + bright * 9000.0
    out = _lowpass(out, sr, cutoff, 0.7)
    return out * env


def make_preview(type_name, params, midi=69, dur=2.0, sr=SR):
    """UI 试听便捷入口：按 MIDI 音高合成一段可循环波形。"""
    from synth import midi_to_freq  # 延迟导入避免循环（synth 反向 import 本文件仅取 DLC_DIR）
    return render(type_name, midi_to_freq(midi), dur, sr, params)


def _midi_to_freq(m):
    """半音 → 频率（本文件自包含，避免顶层 import synth 造成循环）。"""
    return 440.0 * (2.0 ** ((m - 69) / 12.0))


def render_chord(type_name, midi, offsets, dur=2.0, sr=SR, params=None):
    """和弦合成：用同一音色(type + params)叠加多个相对半音偏移的音调。

    offsets : 相对根音的半音列表（如 [0, 4, 7] = 大三和弦）；midi 为根音音高。
    返回归一化到峰值 0.9 的 float32 波形（与 render 同规格，可直接 preview_raw）。
    与 build_dlc_source(chord=...) 生成的模块、以及 synth.render_one_shot 的 DLC 和弦分支
    在数学上完全一致（同一 _sf_render 逐音叠加 + 峰值归一）。
    """
    base = _midi_to_freq(midi)
    n = int(dur * sr)
    out = np.zeros(n, dtype=np.float64)
    for off in offsets:
        f = base * (2.0 ** (off / 12.0))
        out = out + render(type_name, f, dur, sr, params)
    peak = float(np.max(np.abs(out))) if out.size else 0.0
    if peak > 1e-6:
        out = out / peak * 0.9
    return out.astype(np.float32)


# ---------------------------------------------------------------------------
# DLC 模块生成 / 写入
# ---------------------------------------------------------------------------
def slugify(name):
    s = re.sub(r'[^\w一-鿿]+', '_', name.strip())
    s = s.strip('_')
    if not s:
        s = 'dlc'
    if s[0].isdigit():
        s = 'd_' + s
    return s[:48]


def new_dlc_key():
    """生成 32 位十六进制随机 UUID（16 字节），作为用户 DLC 文件的唯一主键。

    展示名（label）与 uuid 主键彻底解耦：名称可任意重复、可改，永不撞名、
    绝不复用旧文件，从根上消除「名称撞名 → 旧缓存/旧设定被复用」导致的
    「设定固定、改不了」问题。
    """
    import secrets
    return secrets.token_hex(16)


def build_dlc_source(name, type_name, params, chord=None, label=None):
    """生成自包含的 DLC 模块源码（字符串）。

    chord: 可选，相对根音的半音偏移列表（如 [0, 4, 7]）；若给出则生成的音色
           为「同一音色叠加若干音调」的和弦音色（chord 字段 + 自求和 render）。
    label: 可选，覆盖写入 DLC['label'] 的展示名。默认跟随 name。
           撞名另存为 '<base>_N' 时传入唯一 key，使选择器展示可区分的标签，
           避免出现多个同名「我的音色」导致用户误选原始版本（旧缓存设定的假象）。
    """
    safe = slugify(name)
    label = label or name
    p = {k: params.get(k, PARAM_DEFAULTS[k]) for k in TYPE_PARAMS.get(type_name, [])}
    chord_src = ""
    if chord:
        chord_src = "    'chord': %r,\n" % (list(chord),)
    # 仅保留该类型相关参数，减小体积
    return (
        "# 抖坤音乐工坊 · 音色 DLC（自动生成，可手动微调后重新合成）\n"
        f"# name: {name}\n"
        "import numpy as np\n"
        "from synth_factory import render as _sf_render\n\n"
        "DLC = {\n"
        f"    'label': {label!r},\n"
        "    'family': '我的DLC',\n"
        "    'needs_freq': True,\n"
        "    'kind': 'tonal',\n"
        f"    'sustain': {float(p.get('sustain', 0.8))!r},\n"
        "    'func': 'render',\n"
        f"    'type': {type_name!r},\n"
        f"    'params': {p!r},\n"
        + chord_src +
        "}\n\n"
        "def render(freq, dur=2.0, sr=44100, **kwargs):\n"
        "    chord = DLC.get('chord')\n"
        "    if chord:\n"
        "        out = np.zeros(int(dur * sr), dtype=np.float64)\n"
        "        for off in chord:\n"
        "            f = freq * (2.0 ** (off / 12.0))\n"
        "            out = out + _sf_render(DLC['type'], f, dur, sr, DLC['params'])\n"
        "        peak = float(np.max(np.abs(out)))\n"
        "        if peak > 1e-6:\n"
        "            out = out / peak * 0.9\n"
        "        return out.astype(np.float32)\n"
        "    return _sf_render(DLC['type'], freq, dur, sr, DLC['params'])\n"
    )


def write_dlc(key, src):
    """把 DLC 源码写入 instrument_dlc/<key>.py，返回绝对路径。"""
    os.makedirs(DLC_DIR, exist_ok=True)
    path = os.path.join(DLC_DIR, key + '.py')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(src)
    return path


def resolve_dlc_save(name, *, editing_key=None, editing_name=None,
                     dlc_keys=None, dlc_dir=None, builtin_keys=None,
                     on_collide=None):
    """解析保存 DLC 时的目标文件名 key（不含 .py）。

    主键规则（用户 DLC 一律用随机 32 位 UUID 作文件名主键，与展示名彻底解耦）：
    - 新建 / 改名另存 → 返回全新 UUID key，action='new'（绝不撞名、绝不复用旧 key）；
    - 回炉重造（editing_key 已设）→ 返回原 UUID key，action='edit'（覆盖同一文件，
      无论名称是否改动，因为 uuid 才是唯一身份）。

    dlc_keys / dlc_dir / builtin_keys / on_collide 保留为兼容形参（UUID 主键下不再
    触发撞名逻辑），可从 headless 冒烟测试直接调用断言。
    返回 (key, action)，action ∈ {'new','edit'}。
    """
    name = (name or '').strip() or '我的音色'
    if editing_key is not None:
        # 回炉重造：保持同一 uuid 主键，覆盖原文件（uuid 即身份，与名称无关）
        return editing_key, 'edit'
    # 新建：永远使用全新随机 UUID 作为文件名主键
    return new_dlc_key(), 'new'


def load_dlc_for_edit(key):
    """读取已落盘的 DLC 模块，提取可编辑信息（回炉重造）。

    返回 dict: {'name': str, 'type': str, 'params': dict, 'chord': list|None}
    读取失败返回 None。
    """
    import importlib.util
    path = os.path.join(DLC_DIR, key + '.py')
    if not os.path.exists(path):
        return None
    try:
        spec = importlib.util.spec_from_file_location('dlc_edit_' + key, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        dlc = mod.DLC
        chord = dlc.get('chord')
        return {
            'name': dlc.get('label', key),
            'type': dlc.get('type', 'sine'),
            'params': dict(dlc.get('params', {})),
            'chord': list(chord) if chord else None,
        }
    except Exception:
        return None
