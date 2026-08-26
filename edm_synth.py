"""
edm_synth.py — 电子音乐（Alan Walker / Progressive House / Future Bass 风格）
常用音色的数学合成库。

所有音色均以纯 numpy 实现：加法 / 减法 / FM / Karplus-Strong / 共振峰 合成。
无外部音频依赖，仅依赖 numpy。可独立运行生成 demo WAV 并做频谱校验。

设计依据（权威社区调研结论，见 SKILL.md）：
- 主音: Supersaw（7 路失谐锯齿，Roland JP-8000 逆向工程结论）、Pluck（快衰减锯齿+低通）、
        Bright Square+Saw 双波主音
- 弦乐: 失谐锯齿 Pad（慢起音+颤音+低通）、Orchestral Stab（短促亮弦）、Pizzicato（Karplus-Strong）
- 管乐: Brass Stab（锯齿+滤波包络膨胀+颤音）、Flute/Wind（正弦+气声噪声+颤音）
- 打击乐: Kick（正弦俯冲音高包络+咔哒）、Snare（三角体+带通噪声）、Hi-Hat（噪声高通+极短衰减）
- 模拟人声: Formant Vocal（声门源+三共振峰带通）
- 木琴: Xylophone（非谐分音加法合成，条形振动模态 1:2.76:5.40:8.93）
- 低频(新增): Sub Bass（干净正弦 sub 层）、Saw/Reese Bass（失谐锯齿+低通LFO+sub层）
- 键盘(新增): Piano（拉伸非谐分音+逐分音衰减加法合成）
- 过渡FX(新增): Riser（白噪声带通扫频+渐强）

本次新增（补全原清单缺失的"低频"与"过渡FX"两大块，由权威社区调研确认强烈推荐）：
- 低频: Sub Bass、Saw/Reese Bass
- 打击乐补全: Hi-Hat（与 kick/snare 并列的 EDM 鼓组三件套）
- 键盘: Piano（Alan Walker《Faded》的 melancholic 根基即钢琴和弦）
- 过渡FX: Riser（几乎所有 EDM 子流派通用的落拍前张力工具）

本次再新增（不拘泥于原技能，补全"管弦乐 / 弹拨 / 中国民乐 / 玻璃感打击"四大类，
音调高饱和、各音色类型鲜明；三角铁/八音盒/钢鼓参考 C418 的玻璃感/钟铃 palette）：
- 管弦乐: Violin（弓弦+颤音）、Cello（暖弓弦）、French Horn（圆润铜管）
- 弹拨: Harp（亮 KS）、Nylon Guitar（暖 KS+琴体）、Pipa（明亮金属拨弦）
- 中国民乐: Erhu（鼻音共振峰+强颤音拉弦）、Taiko Drum（中国大鼓，定音低频打击）
- 玻璃感打击: Triangle（金属杆非谐分音）、Music Box（八音盒钟铃）、Steel Drum（钢鼓加勒比金属）
"""

import numpy as np
import wave
import os

SR = 44100

# ----------------------------------------------------------------------------
# 基础工具
# ----------------------------------------------------------------------------
def note_freq(note):
    """解析音名 -> 频率。例: 'A4', 'C#5', 'Eb3'。A4=440。"""
    names = {'C': 0, 'C#': 1, 'Db': 1, 'D': 2, 'D#': 3, 'Eb': 3,
             'E': 4, 'F': 5, 'F#': 6, 'Gb': 6, 'G': 7, 'G#': 8, 'Ab': 8,
             'A': 9, 'A#': 10, 'Bb': 10, 'B': 11}
    # 拆分字母与八度
    i = 1
    while i < len(note) and note[i].isdigit():
        i += 1
    letter = note[:i if False else (1 if len(note) > 1 and note[1] in '#b' else 1)]
    # 更稳妥的拆分
    if len(note) >= 2 and note[1] in '#b':
        letter = note[:2]
        octv = int(note[2:])
    else:
        letter = note[:1]
        octv = int(note[1:])
    semis = names[letter]
    midi = (octv + 1) * 12 + semis
    return 440.0 * 2 ** ((midi - 69) / 12)


def phase_array(freq, dur, sr=SR, vib=0.0, vib_rate=5.5):
    """生成相位数组，可选颤音（vib 单位: cents）。"""
    n = int(dur * sr)
    t = np.arange(n) / sr
    phase = 2 * np.pi * freq * t
    if vib:
        # 颤音深度修正：vib 单位为 cents，瞬时频率需按指数(2^x)调制，
        # 相位的调制幅度为 A = freq·(vib/1200)·ln2/vib_rate。
        # 旧写法少乘 ln2 且多乘 2π，深度约为名义值的 2π/ln2≈9 倍，
        # 导致小提琴/大提琴/圆号/二胡等持续音的颤音过深、听感崩坏。
        A = freq * (vib / 1200.0) * np.log(2.0) / vib_rate
        phase = phase + A * np.sin(2 * np.pi * vib_rate * t)
    return phase, t


def saw_from_phase(phase, max_h=None, sr=SR):
    """限带宽锯齿（加法合成），避免混叠。phase: 预计算相位数组。"""
    if max_h is None:
        # 由相位最大瞬时频率估算上限 -> 粗略取 80 谐波（混叠由后续低通/听感控制）
        max_h = 80
    k = np.arange(1, max_h + 1)
    # 矩阵: sin(k[:,None] * phase[None,:])，但相位已含 2πf t，故直接 k*phase
    m = np.sin(np.outer(k, phase)) * (((-1) ** (k + 1)) / k)[:, None]
    return (2.0 / np.pi) * m.sum(axis=0)


def onepole_lp(x, sr=SR, fc=3000.0):
    a = 1.0 - np.exp(-2 * np.pi * fc / sr)
    y = np.zeros_like(x, dtype=np.float64)
    if len(x):
        y[0] = x[0]
        y[1:] = y[:-1] + a * (x[1:] - y[:-1])
    return y


def onepole_hp(x, sr=SR, fc=90.0):
    """一阶高通（DC blocker 形式，正确实现，逐样本递推）。

    旧实现 y[n]=a*(y[n-1]+x[n]-x[n-1]) 把信号整体压低约 1/a 倍，且向量化写法
    y[1:]=...R*y[:-1] 因 RHS 先用全零 y 求值，反馈项恒为 0，退化成纯微分器
    （增益∝频率），把 261Hz 主音压到 ~0.026 -> 听起来“没声/发闷”。
    正确递推：y[n]=x[n]-x[n-1]+R*y[n-1]（R 越接近 1 截止越低）。
    """
    w0 = 2.0 * np.pi * fc / sr
    R = (1.0 - w0 / 2.0) / (1.0 + w0 / 2.0)   # 双线性一阶高通极点
    y = np.zeros_like(x, dtype=np.float64)
    prev_x = 0.0
    prev_y = 0.0
    for i in range(len(x)):
        xc = x[i]
        yc = xc - prev_x + R * prev_y
        y[i] = yc
        prev_x = xc
        prev_y = yc
    return y


def onepole_lp_varying(x, sr=SR, fc=None):
    """时变截止频率的低通（用于 brass 滤波包络）。fc: 与 x 等长数组。"""
    y = np.zeros_like(x, dtype=np.float64)
    y0 = 0.0
    for i in range(len(x)):
        a = 1.0 - np.exp(-2 * np.pi * fc[i] / sr)
        y0 = y0 + a * (x[i] - y0)
        y[i] = y0
    return y


def biquad_bandpass(x, sr=SR, f0=1000.0, Q=5.0):
    """RBJ 二阶带通，直接 II 型转置实现。"""
    w0 = 2 * np.pi * f0 / sr
    alpha = np.sin(w0) / (2 * Q)
    b0 = alpha
    b1 = 0.0
    b2 = -alpha
    a0 = 1.0 + alpha
    a1 = -2.0 * np.cos(w0)
    a2 = 1.0 - alpha
    b = np.array([b0, b1, b2]) / a0
    a = np.array([1.0, a1, a2]) / a0
    y = np.zeros_like(x, dtype=np.float64)
    x1 = x2 = y1 = y2 = 0.0
    b0, b1, b2 = b
    a1c, a2c = a[1], a[2]
    for i in range(len(x)):
        x0 = x[i]
        y0 = b0 * x0 + b1 * x1 + b2 * x2 - a1c * y1 - a2c * y2
        y[i] = y0
        x2 = x1; x1 = x0
        y2 = y1; y1 = y0
    return y


def softclip(x, amount=1.0):
    return np.tanh(x * amount)


def normalize(x, peak=0.9):
    m = np.max(np.abs(x))
    if m < 1e-9:
        return x
    return x / m * peak


def additive(freq, dur, sr=SR, partials=(1.0,), amps=(1.0,), taus=None,
             vib=0.0, vib_rate=5.5):
    """通用加法合成（抗混叠：丢弃超 ~0.45·SR 的分音）。

    partials : 各分音相对基频的频率比(list)
    amps     : 各分音幅度(list)
    taus     : 各分音的指数衰减时间常数(秒, None=不衰减); 高次分音给更小值 => 金属/木质"闪光"
    vib      : 颤音幅度(cents, 0=无)
    返回未归一化波形（调用方负责 amp_env / normalize）。
    """
    n = int(dur * sr)
    if n <= 0:
        return np.zeros(0, dtype=np.float64)
    t = np.arange(n) / sr
    out = np.zeros(n, dtype=np.float64)
    if vib:
        # 颤音深度修正（同 phase_array）：vib 单位 cents，
        # A = freq·(vib/1200)·ln2/vib_rate，否则深度被放大约 9 倍。
        A = freq * (vib / 1200.0) * np.log(2.0) / vib_rate
        vib_phase = A * np.sin(2 * np.pi * vib_rate * t)
    else:
        vib_phase = 0.0
    tau_iter = taus if taus is not None else [None] * len(partials)
    for r, a, tau in zip(partials, amps, tau_iter):
        f = freq * r
        if f >= 0.45 * sr:          # 抗混叠
            continue
        s = a * np.sin(2 * np.pi * f * t + vib_phase)
        if tau:
            s = s * np.exp(-t / tau)
        out = out + s
    return out


def amp_env(dur, sr=SR, a=0.005, d=0.15, s=0.0, r=0.1, sustain_level=0.8):
    """ADSR 振幅包络数组（s=0 表示无延音的敲击音）。"""
    n = max(1, int(dur * sr))   # 与合成函数缓冲区的 int(dur*sr) 保持一致，避免非整数采样点时 off-by-one
    env = np.zeros(n)
    if n == 1:
        env[0] = 1.0
        return env
    a_n = max(1, int(round(a * sr)))
    d_n = max(0, int(round(d * sr)))
    r_n = max(1, int(round(r * sr)))
    # 若三段总长超出可用长度，按比例压缩，保证任意短音符都不崩
    fixed = a_n + d_n + r_n
    if fixed > n:
        k = n / fixed
        a_n = max(1, int(a_n * k))
        d_n = int(d_n * k)
        r_n = max(1, int(r_n * k))
    if a_n > n:
        a_n = n
    # attack 0 -> 1
    env[:a_n] = np.linspace(0, 1, a_n)
    # decay 1 -> sustain_level（修正原公式衰减方向）
    if d_n > 0 and a_n < n:
        L = min(d_n, n - a_n)
        env[a_n:a_n + L] = 1.0 - (1.0 - sustain_level) * np.linspace(0, 1, L)
    # hold sustain
    if s > 0:
        seg_end = a_n + d_n
        hold = max(0, n - seg_end - r_n)
        if hold > 0:
            env[seg_end:seg_end + hold] = sustain_level
        rel_start = seg_end + hold
        if rel_start < n:
            env[rel_start:] = sustain_level * np.linspace(1, 0, n - rel_start)
    else:
        # 无延音: 衰减到接近 0，然后 release
        body_end = max(a_n + d_n, n - r_n)
        if body_end < n:
            env[body_end:] = env[body_end - 1] * np.linspace(1, 0, n - body_end)
    return env


def write_wav(path, x, sr=SR):
    x = np.asarray(x, dtype=np.float64)
    x = np.clip(x, -1, 1)
    data = (x * 32767).astype(np.int16)
    with wave.open(path, 'w') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(data.tobytes())
    return path


# ----------------------------------------------------------------------------
# 主音 LEAD
# ----------------------------------------------------------------------------
def supersaw_lead(freq, dur=0.7, sr=SR, detune_cents=10.0, voices=7, vib=0.0):
    """Supersaw 主音 — 7 路失谐限带宽锯齿 + 高通去 Mud + 轻颤音。
    依据: Roland JP-8000/8080 逆向工程（7 路失谐锯齿 + 高通 + 自由相位）。"""
    cents = np.linspace(-detune_cents, detune_cents, voices)
    out = np.zeros(int(dur * sr))
    for c in cents:
        f = freq * 2 ** (c / 1200.0)
        ph, _ = phase_array(f, dur, sr, vib=vib)
        out = out + saw_from_phase(ph, max_h=70)
    out = onepole_hp(out, sr, fc=90.0)           # 去 Mud
    env = amp_env(dur, sr, a=0.005, d=0.18, s=0.8, r=0.12)
    out = out * env
    return normalize(out)


def pluck_lead(freq, dur=0.5, sr=SR, vib=0.0):
    """Pluck 拨弦主音 — 锯齿 + 静态低通，快起音快衰减（progressive house pluck）。"""
    ph, _ = phase_array(freq, dur, sr, vib=vib)
    out = saw_from_phase(ph, max_h=70)
    out = onepole_lp(out, sr, fc=5000.0)        # 更通透的拨弦
    env = amp_env(dur, sr, a=0.003, d=0.28, s=0.0, r=0.05, sustain_level=0.0)
    out = out * env
    return normalize(out)


def bright_lead(freq, dur=0.6, sr=SR, vib=0.0):
    """Bright 双波主音 — Square + Saw 叠加（Alan Walker 常用 square+saw 组合），
    高失谐 + 轻高通，明亮穿透。"""
    ph, _ = phase_array(freq, dur, sr, vib=vib)
    saw = saw_from_phase(ph, max_h=70)
    # 方波近似（加法，奇次谐波）
    sq = saw_from_phase(ph, max_h=70)  # 占位，下面用专门方波
    # 用奇次谐波重建方波
    k = np.arange(1, 40, 2)
    sq = (4.0 / np.pi) * (np.sin(np.outer(k, ph)) * (1.0 / k)[:, None]).sum(axis=0)
    out = 0.5 * saw + 0.5 * sq
    out = onepole_hp(out, sr, fc=120.0)
    env = amp_env(dur, sr, a=0.004, d=0.2, s=0.7, r=0.1)
    out = out * env
    return normalize(out)


# ----------------------------------------------------------------------------
# 弦乐 STRINGS
# ----------------------------------------------------------------------------
def string_pad(freq, dur=1.6, sr=SR, vib=5.0):
    """String Pad — 3 路失谐锯齿慢起音 + 颤音 + 低通，长延音铺底。"""
    cents = [-7, 0, 7]
    out = np.zeros(int(dur * sr))
    for c in cents:
        f = freq * 2 ** (c / 1200.0)
        ph, _ = phase_array(f, dur, sr, vib=vib, vib_rate=5.5)
        out = out + saw_from_phase(ph, max_h=45)
    out = out / len(cents)
    out = onepole_lp(out, sr, fc=3500.0)        # 温润但更通透的铺底
    # 慢起音/慢释放的 pad 包络
    env = amp_env(dur, sr, a=0.8, d=0.3, s=0.85, r=1.2, sustain_level=0.85)
    out = out * env
    return normalize(out)


def orchestral_stab(freq, dur=0.9, sr=SR, vib=6.0):
    """Orchestral Stab — 短促亮弦，双路失谐 + 中高截止 + 颤音（现场管弦叠加感）。"""
    cents = [-5, 5]
    out = np.zeros(int(dur * sr))
    for c in cents:
        f = freq * 2 ** (c / 1200.0)
        ph, _ = phase_array(f, dur, sr, vib=vib, vib_rate=6.0)
        out = out + saw_from_phase(ph, max_h=60)
    out = out / len(cents)
    out = onepole_lp(out, sr, fc=6500.0)            # 提亮：更高截止，去掉“阴暗”
    env = amp_env(dur, sr, a=0.02, d=0.25, s=0.8, r=0.3, sustain_level=0.8)
    out = out * env
    return normalize(out)


def pizzicato(freq, dur=0.6, sr=SR, decay=0.996):
    """Pizzicato — Karplus-Strong 拨弦弦乐（物理建模，短促有弹性）。"""
    N = max(2, int(sr / freq))
    buf = np.random.uniform(-1, 1, N)
    buf = (buf + np.roll(buf, 1)) / 2.0           # 初始低通 -> 亮度
    ring = buf.copy()
    n = int(dur * sr)
    out = np.zeros(n)
    for i in range(n):
        out[i] = ring[0]
        new = decay * 0.5 * (ring[0] + ring[1])
        ring = np.roll(ring, -1)
        ring[-1] = new
    env = amp_env(dur, sr, a=0.002, d=0.4, s=0.0, r=0.05)
    out = out * env
    return normalize(out)


# ----------------------------------------------------------------------------
# 管乐 BRASS / WIND
# ----------------------------------------------------------------------------
def brass_stab(freq, dur=0.7, sr=SR, vib=4.0):
    """Brass Stab — 锯齿 + 滤波包络（起音膨胀再回落）+ 颤音 + 轻失谐
    （减法合成铜管标准做法：saw + LPF + envelope on cutoff）。"""
    cents = [-4, 4]
    out = np.zeros(int(dur * sr))
    for c in cents:
        f = freq * 2 ** (c / 1200.0)
        ph, _ = phase_array(f, dur, sr, vib=vib, vib_rate=5.5)
        out = out + saw_from_phase(ph, max_h=60)
    out = out / len(cents)
    # 滤波包络: 起音 600->5200Hz（更亮），延音回落到 ~1400Hz
    n = len(out)
    t = np.arange(n) / sr
    fc = np.ones(n) * 1400.0
    atk = min(int(0.04 * sr), n)
    if atk > 0:
        fc[:atk] = np.linspace(600, 5200, atk)
    # 之后缓降
    dec = int(0.4 * sr)
    if dec + atk < n:
        fc[atk:atk + dec] = np.linspace(5200, 1400, dec)
        fc[atk + dec:] = 1400.0
    out = onepole_lp_varying(out, sr, fc)
    env = amp_env(dur, sr, a=0.03, d=0.25, s=0.8, r=0.2, sustain_level=0.8)
    out = out * env
    return normalize(out)


def flute_wind(freq, dur=1.0, sr=SR, vib=5.0):
    """Flute / Wind — 基频正弦 + 少量三角（泛音） + 气声噪声（带通）+ 颤音。"""
    n = int(dur * sr)
    t = np.arange(n) / sr
    ph, _ = phase_array(freq, dur, sr, vib=vib, vib_rate=5.0)
    tone = np.sin(ph) + 0.25 * np.sin(2 * ph)   # 基频 + 八度泛音
    # 气声
    noise = np.random.uniform(-1, 1, n)
    breath = biquad_bandpass(noise, sr, f0=2500.0, Q=0.7) * 0.12
    out = tone * 0.8 + breath
    env = amp_env(dur, sr, a=0.05, d=0.2, s=0.85, r=0.3, sustain_level=0.85)
    out = out * env
    return normalize(out)


# ----------------------------------------------------------------------------
# 打击乐 PERCUSSION
# ----------------------------------------------------------------------------
def kick(dur=0.5, sr=SR, f_start=165.0, f_end=45.0, sweep=0.06):
    """Kick — 基频俯冲(165->45Hz) + 2/3 次谐波(增加冲击与可闻度) + 咔哒瞬态。
    更长衰减与更结实的谐波，让底鼓在混音里更"响"、更有重量。"""
    n = int(dur * sr)
    t = np.arange(n) / sr
    freq = f_end + (f_start - f_end) * np.exp(-t / sweep)
    phase = 2 * np.pi * np.cumsum(freq) / sr
    out = (np.sin(phase)
           + 0.42 * np.sin(2 * phase)          # 二次谐波：punch / 中频可闻
           + 0.25 * np.sin(3 * phase))         # 三次谐波：颗粒感
    # 振幅包络（更长衰减，鼓声更"实"）
    env = np.zeros(n)
    atk = max(1, int(0.001 * sr))
    env[:atk] = np.linspace(0, 1, atk)
    env[atk:] = np.exp(-t[atk:] / 0.30)
    out = out * env
    # 咔哒（更突出）
    click_len = int(0.004 * sr)
    click = np.random.uniform(-1, 1, click_len)
    click = onepole_hp(click, sr, fc=1800.0)
    cenv = np.exp(-np.arange(click_len) / sr / 0.002)
    out[:click_len] += click * cenv * 0.85
    return normalize(out, peak=0.92)


def snare(dur=0.25, sr=SR, body_hz=200.0, noise_fc=1800.0):
    """Snare — 三角体（~200Hz 短衰减） + 带通噪声（1.8kHz 咔哒）。"""
    n = int(dur * sr)
    t = np.arange(n) / sr
    # 体
    body = np.sin(2 * np.pi * body_hz * t + np.pi / 2) * np.exp(-t / 0.12)
    # 噪声
    noise = np.random.uniform(-1, 1, n)
    noise = biquad_bandpass(noise, sr, f0=noise_fc, Q=0.8) * 0.9
    nenv = np.exp(-t / 0.09)
    out = body * 0.5 + noise * nenv
    return normalize(out)


# ----------------------------------------------------------------------------
# 模拟人声 VOCAL (Formant)
# ----------------------------------------------------------------------------
VOWELS = {
    'ah': [(730, 90, 1.0), (1090, 110, 0.6), (2400, 170, 0.3)],
    'ee': [(270, 60, 1.0), (2290, 120, 0.7), (3000, 200, 0.3)],
    'oo': [(300, 70, 1.0), (870, 90, 0.7), (2400, 170, 0.3)],
    'eh': [(530, 80, 1.0), (1840, 110, 0.6), (2500, 180, 0.3)],
}


def vocal_formant(freq, dur=1.2, sr=SR, vowel='ah', vib=3.0):
    """模拟人声 — 声门源（限带宽锯齿，富含谐波）经三个共振峰带通
    （F1/F2/F3 取自 Peterson & Barney 元音空间），音高独立于共振峰。
    洪厚度由强基频 + 二次谐波 + 更宽的低共振峰共同提供，高频尖刺收敛。"""
    ph, _ = phase_array(freq, dur, sr, vib=vib, vib_rate=5.5)
    source = saw_from_phase(ph, max_h=60)        # 更亮的声门源（谐波丰富）
    out = np.zeros(int(dur * sr))
    for (f, bw, amp) in VOWELS[vowel]:
        Q = f / bw
        out = out + (amp * 1.5) * biquad_bandpass(source, sr, f0=f, Q=Q)  # 加强共振峰
    out = out + 0.5 * np.sin(ph)                 # 强基频赋予“厚度/力度”
    out = out + 0.18 * np.sin(2 * ph)            # 二次谐波增加胸腔暖意
    env = amp_env(dur, sr, a=0.06, d=0.2, s=0.9, r=0.35, sustain_level=0.9)
    out = out * env
    out = softclip(out, 1.1)                     # 轻度饱和，更"实"
    return normalize(out)


# ----------------------------------------------------------------------------
# 木琴 XYLOPHONE (inharmonic additive)
# ----------------------------------------------------------------------------
def xylophone(freq, dur=0.6, sr=SR):
    """木琴 — 非谐分音加法合成。条形自由振动模态比 1 : 2.76 : 5.40 : 8.93
    （均匀杆理论值），高次分音衰减更快 -> 明亮、木质、快速衰减。
    低音区"饱和度"(谐波丰富度)偏低、易闷: 低音时提升上方分音幅度 + 轻度软削波引入谐波，
    使低音也明亮饱满(不闷不虚)；高音本就富含分音，基本不动。

    2026-08-26 修复：
    - 衰减时间改为固定值（不再乘以 dur），避免长缓冲下木琴变成"长铃"而崩坏。
    - 加入抗混叠：跳过超过 0.45·sr 的非谐分音。
    - 缩短 release，让短音符更干脆。
    """
    ratios = [1.0, 2.76, 5.40, 8.93]
    amps = [1.0, 0.6, 0.35, 0.18]
    taus = [0.22, 0.10, 0.05, 0.025]   # 高次分音衰减更快（固定值，不随 dur 拉伸）
    sat = 1.1
    if freq < 400.0:
        lf = (400.0 - freq) / 400.0          # 越低越大(0..1)
        amps = [amps[0],
                amps[1] * (1.0 + 0.8 * lf),  # 提升上方分音 -> 低音更丰富/饱和
                amps[2] * (1.0 + 1.0 * lf),
                amps[3] * (1.0 + 1.0 * lf)]
        sat = 1.1 + 0.8 * lf                  # 软削波加谐波(低音更强)
    n = int(dur * sr)
    t = np.arange(n) / sr
    out = np.zeros(n)
    for r, a, tau in zip(ratios, amps, taus):
        f = freq * r
        if f >= 0.45 * sr:                    # 抗混叠：避免超高非谐分音产生刺耳混叠
            continue
        out = out + a * np.sin(2 * np.pi * f * t) * np.exp(-t / tau)
    out = softclip(out, sat)                  # 谐波饱和度(低音受益最大)
    env = amp_env(dur, sr, a=0.001, d=0.18, s=0.0, r=0.04)
    out = out * env
    return normalize(out)


# ----------------------------------------------------------------------------
# 低频 BASS（新增，补全原清单缺失的最关键一块）
# ----------------------------------------------------------------------------
def sub_bass(freq, dur=0.5, sr=SR, with_sub_octave=True):
    """Sub Bass — 干净正弦基频 + 下方八度 sub 层（提供重量），极低通守住 sub 频段。
    依据: Reese 教程一致结论 — sub 用干净正弦, 比主 bass 低八度提供低频重量,
    与中频 reese 分工明确(各自 EQ 不打架)。"""
    n = int(dur * sr)
    t = np.arange(n) / sr
    # 基频 + 2/3/4 次谐波（带衰减幅度）: 保证在笔记本小喇叭上也“听得见”，
    # 而非只有 <60Hz 的纯 sub（小喇叭无法重放 -> 听起来像没声）。
    out = (np.sin(2 * np.pi * freq * t)
           + 0.5 * np.sin(2 * np.pi * 2 * freq * t)
           + 0.3 * np.sin(2 * np.pi * 3 * freq * t)
           + 0.18 * np.sin(2 * np.pi * 4 * freq * t))
    if with_sub_octave:
        out = out + 0.9 * np.sin(2 * np.pi * (freq / 2) * t)  # 下方八度 sub 层给重量
    out = onepole_lp(out, sr, fc=800.0)                     # 守住 sub/low 但保留中频实体
    env = amp_env(dur, sr, a=0.008, d=0.0, s=0.9, r=0.08, sustain_level=0.9)
    out = out * env
    return normalize(out)


def saw_bass(freq, dur=0.5, sr=SR, detune_cents=14.0, with_sub=True):
    """Saw/Reese Bass — 3 路失谐锯齿(±14 cents) + 低通(慢 LFO 扫截止) + 轻微软削波,
    下方叠加干净正弦 sub 层。依据: 多源一致 — 2~3 路失谐锯齿是 reese 的核心,
    慢 LFO 调制滤波截止产生"滚动"运动, sub 层给低频重量; 失谐量决定"咀嚼感"快慢。"""
    n = int(dur * sr)
    t = np.arange(n) / sr
    cents = [-detune_cents, 0.0, detune_cents]
    out = np.zeros(n)
    for c in cents:
        f = freq * 2 ** (c / 1200.0)
        ph, _ = phase_array(f, dur, sr)
        out = out + saw_from_phase(ph, max_h=60)
    out = out / len(cents)
    # 慢 LFO 调制截止: 1000<->1900Hz，更亮的 reese 扫频，产生“滚动”运动
    lfo = 0.5 * (1 + np.sin(2 * np.pi * 0.7 * t))
    fc = 1000.0 + 900.0 * lfo
    out = onepole_lp_varying(out, sr, fc)
    out = softclip(out, 1.3)                               # 轻微谐波 enrichment
    if with_sub:
        sub = np.sin(2 * np.pi * (freq / 2) * t) * 0.8
        sub = onepole_lp(sub, sr, fc=180.0)
        out = out + sub
    env = amp_env(dur, sr, a=0.002, d=0.05, s=0.95, r=0.06, sustain_level=0.95)
    out = out * env
    return normalize(out)


# ----------------------------------------------------------------------------
# 打击乐补全: Hi-Hat（新增）
# ----------------------------------------------------------------------------
def hihat(dur=0.06, sr=SR, open=False, fc_hp=7000.0):
    """Hi-Hat — 白噪声经高通(~7kHz)+带通塑形, 极短指数衰减。
    closed 极短(~60ms), open 较长(~300ms)。与 kick/snare 并列的 EDM 鼓组三件套。"""
    if open:
        dur = max(dur, 0.3)
    n = int(dur * sr)
    noise = np.random.uniform(-1, 1, n)
    hp = onepole_hp(noise, sr, fc=fc_hp)                  # 去掉低频, hat 全在高频
    bp = biquad_bandpass(hp, sr, f0=10000.0, Q=0.8) * 1.2 + hp * 0.4  # 金属"tss"塑形
    decay = 0.02 if not open else 0.12
    env = np.exp(-np.arange(n) / sr / decay)
    out = bp * env
    return normalize(out)


# ----------------------------------------------------------------------------
# 键盘: Piano（新增）
# ----------------------------------------------------------------------------
def piano(freq, dur=1.4, sr=SR):
    """电子琴标准钢琴音色（市售家用电子琴的 Piano / E.Piano 预置观感）。

    设计取向：干净、明亮、全音域高饱和，**严禁**黯淡/嘶哑/颤音。
    - 整数谐波加法合成（不拉伸 -> 电子琴特有的规整明亮感），谐波配到 6 次 + 电钢"叮"泛音；
    - 快起音 + 适度延音（按住持续、松手缓释），听感接近真实按键而非死板敲击；
    - 极轻击键瞬态（高通去 DC、快速衰减）只作"按键质感"，绝不喧宾夺主（非噪声轰鸣）。
    """
    n = int(dur * sr)
    if n <= 0:
        return np.zeros(0, dtype=np.float64)
    t = np.arange(n) / sr
    # 干净整数谐波（明亮配比）+ 电钢 shimmer 高次泛音
    partials = (1.0, 2.0, 3.0, 4.0, 5.0, 6.0)
    amps = (1.0, 0.55, 0.36, 0.22, 0.13, 0.08)
    out = np.zeros(n, dtype=np.float64)
    for r, a in zip(partials, amps):
        out = out + a * np.sin(2 * np.pi * freq * r * t)
    # 电钢"叮"泛音（第 8 次谐波，极快衰减），增加明亮颗粒感
    shimmer = 0.12 * np.sin(2 * np.pi * freq * 8.0 * t) * np.exp(-t / 0.06)
    out = out + shimmer
    # 极轻击键瞬态：仅作"按下"质感，幅度低、高通去 DC、5ms 内衰减完
    hn_n = int(0.008 * sr)
    if hn_n > 0:
        hn = np.random.uniform(-1, 1, hn_n)
        hn = onepole_hp(hn, sr, fc=3500.0) * np.exp(-np.arange(hn_n) / sr / 0.004)
        out[:hn_n] = out[:hn_n] + hn * 0.08
    # 快起音 + 适度延音：电子琴按键后持续发声，松手缓释
    env = amp_env(dur, sr, a=0.003, d=0.22, s=0.5, r=0.20)
    out = out * env
    return normalize(out)


def chord_voice(freq, dur=1.2, sr=SR, bright=1.0):
    """类正弦波音色单元（和弦预制件）。

    一个"音"内部由多个**同音色**的正弦分音叠加而成，明亮高饱和，**严禁颤音/嘶哑/
    灰色黯然**：无颤音(vib=0)、无噪声、无低通黯淡。供 render_one_shot 的 chord 分支
    把多个 chord_voice（不同音高）相加，得到"一个音符内多个音调同时作响"的和弦音。
    """
    n = int(dur * sr)
    if n <= 0:
        return np.zeros(0, dtype=np.float64)
    partials = (1.0, 2.0, 3.0, 4.0, 5.0)
    amps = (1.0, 0.50 * bright, 0.30 * bright, 0.18 * bright, 0.10 * bright)
    taus = (dur * 1.4, dur * 0.7, dur * 0.45, dur * 0.30, dur * 0.20)
    sig = additive(freq, dur, sr, partials=partials, amps=amps, taus=taus)
    env = amp_env(dur, sr, a=0.004, d=0.05, s=0.80, r=0.20)
    return sig * env


def gong(freq, dur=1.2, sr=SR):
    """敲锣（中国民族打击乐）— 金属非谐分音 + 长尾泛响 + 轻击瞬态。

    设计取向：明亮、高饱和、全音域通透，**严禁颤音/嘶哑/灰色黯然**。
    - 非谐分音比（钟/锣类金属体固有泛音）叠加，长指数衰减形成"余音缭绕"的锣声；
    - 起音带一点金属击打瞬态（高通去 DC），随后是持续泛响；
    - 高音取小锣、低音取大锣，按音符音高映射（needs_freq=True）。
    """
    n = int(dur * sr)
    if n <= 0:
        return np.zeros(0, dtype=np.float64)
    dur = max(dur, 1.6)                 # 锣须有充分余音，短音符也至少响 ~1.6s
    t = np.arange(int(dur * sr)) / sr
    # 锣/钟类金属非谐分音比（权威钟体模态近似）
    partials = (1.0, 1.48, 1.93, 2.41, 2.83, 3.62, 4.21)
    amps = (1.0, 0.72, 0.52, 0.38, 0.28, 0.18, 0.12)
    taus = (dur * 1.5, dur * 1.2, dur * 0.9, dur * 0.7, dur * 0.55, dur * 0.4, dur * 0.3)
    out = np.zeros(len(t), dtype=np.float64)
    for r, a, tau in zip(partials, amps, taus):
        f = freq * r
        if f >= 0.45 * sr:
            continue
        out = out + a * np.sin(2 * np.pi * f * t) * np.exp(-t / tau)
    # 极轻金属击打瞬态（高通去 DC，~12ms 衰减）
    hn_n = int(0.012 * sr)
    if hn_n > 0:
        hn = np.random.uniform(-1, 1, hn_n)
        hn = onepole_hp(hn, sr, fc=2500.0) * np.exp(-np.arange(hn_n) / sr / 0.012)
        out[:hn_n] = out[:hn_n] + hn * 0.10
    env = amp_env(dur, sr, a=0.002, d=0.08, s=0.0, r=0.05)
    out = out * env
    return normalize(out)




# ----------------------------------------------------------------------------
# 新增音色（不拘泥于原 EDM 技能，补全"管弦乐 / 弹拨 / 中国民乐 / 玻璃感打击"四大类）
# 设计取向：音调高饱和、各音色类型鲜明可辨；三角铁/八音盒/钢鼓参考 C418 的玻璃感/钟铃 palette。
# ----------------------------------------------------------------------------

# ---- 管弦乐 Orchestral（弓弦 / 铜管各取不同家族，拉开音色类型）----

def violin(freq, dur=1.4, sr=SR, vib=38.0):
    """小提琴 — 弓弦(锯齿) + 紧致双路失谐 + 适度颤音 + 高频"空气感"层, 主打"细腻·明朗"。
    与大提琴拉开的真正手段: 叠加一层 2.5k 以上高频(明亮/通透), 并削去最低端厚度(轻盈),
    而非仅靠低通(单极点斜率太缓, 切止差异可闻性弱)。"""
    cents = [-3.0, 3.0]
    out = np.zeros(int(dur * sr))
    for c in cents:
        f = freq * 2 ** (c / 1200.0)
        ph, _ = phase_array(f, dur, sr, vib=vib, vib_rate=5.7)
        out = out + saw_from_phase(ph, max_h=70)
    out = out / len(cents)
    air = onepole_hp(out, sr, fc=2500.0) * 0.35   # 高频空气感: cello 没有, 拉开"明朗"
    out = out + air
    out = onepole_hp(out, sr, fc=180.0)           # 去最低端厚度 -> 轻盈细腻
    out = onepole_lp(out, sr, fc=7200.0)           # 明朗
    env = amp_env(dur, sr, a=0.02, d=0.12, s=0.88, r=0.20, sustain_level=0.88)
    out = out * env
    return normalize(out)


def cello(freq, dur=1.8, sr=SR, vib=32.0):
    """大提琴 — 弓弦(锯齿) + 轻失谐 + 适度颤音 + 较暖低通(中高频收敛), 低沉厚实。
    比小提琴更低更暖(截止更低)、更厚实。"""

    cents = [-4.0, 4.0]
    out = np.zeros(int(dur * sr))
    for c in cents:
        f = freq * 2 ** (c / 1200.0)
        ph, _ = phase_array(f, dur, sr, vib=vib, vib_rate=5.2)
        out = out + saw_from_phase(ph, max_h=55)
    out = out / len(cents)
    out = onepole_lp(out, sr, fc=2800.0)         # 更暖
    env = amp_env(dur, sr, a=0.05, d=0.15, s=0.90, r=0.30, sustain_level=0.90)
    out = out * env
    return normalize(out)


def french_horn(freq, dur=1.6, sr=SR, vib=28.0):
    """圆号 — 铜管(锯齿) + 温和滤波包络(起音稍亮后回落) + 适度颤音, 圆润不刺。
    与 brass_stab 区别: 滤波扫描更温和、低通更低、更"圆"。"""
    cents = [-3.0, 3.0]
    out = np.zeros(int(dur * sr))
    for c in cents:
        f = freq * 2 ** (c / 1200.0)
        ph, _ = phase_array(f, dur, sr, vib=vib, vib_rate=5.0)
        out = out + saw_from_phase(ph, max_h=50)
    out = out / len(cents)
    n = len(out)
    atk = min(int(0.06 * sr), n)
    fc = np.ones(n) * 2200.0
    if atk > 0:
        fc[:atk] = np.linspace(1500, 3000, atk)   # 温和膨胀
    out = onepole_lp_varying(out, sr, fc)
    out = softclip(out, 1.1)                       # 轻微饱和, 圆润
    env = amp_env(dur, sr, a=0.06, d=0.20, s=0.85, r=0.30, sustain_level=0.85)
    out = out * env
    return normalize(out)


# ---- 弹拨 Plucked（与已有 pizzicato 拉开：竖琴更亮更长 / 古典吉他更暖更短 / 琵琶最亮带金属感）----

def harp(freq, dur=1.2, sr=SR, decay=0.997):
    """竖琴 — Karplus-Strong 拨弦(比 pizzicato 更亮更长), 清透的分解和弦音色。"""
    N = max(2, int(sr / freq))
    buf = np.random.uniform(-1, 1, N)
    buf = (buf + 0.5 * np.roll(buf, 1)) / 1.5       # 较少初始低通 => 更亮
    ring = buf.copy()
    n = int(dur * sr)
    out = np.zeros(n)
    for i in range(n):
        out[i] = ring[0]
        new = decay * 0.5 * (ring[0] + ring[1])
        ring = np.roll(ring, -1)
        ring[-1] = new
    env = amp_env(dur, sr, a=0.002, d=0.5, s=0.0, r=0.05)
    out = out * env
    return normalize(out)


def nylon_guitar(freq, dur=1.3, sr=SR, decay=0.995):
    """古典吉他 — Karplus-Strong 拨弦, 更暖(初始更强低通)更短, 叠加琴体共振(~200Hz 带通)。"""
    N = max(2, int(sr / freq))
    buf = np.random.uniform(-1, 1, N)
    buf = (buf + np.roll(buf, 1)) / 2.0             # 暖(较多低通)
    ring = buf.copy()
    n = int(dur * sr)
    out = np.zeros(n)
    for i in range(n):
        out[i] = ring[0]
        new = decay * 0.5 * (ring[0] + ring[1])
        ring = np.roll(ring, -1)
        ring[-1] = new
    body = biquad_bandpass(out, sr, f0=200.0, Q=2.0) * 0.25   # 琴体暖意
    out = out + body
    env = amp_env(dur, sr, a=0.003, d=0.4, s=0.0, r=0.05)
    out = out * env
    return normalize(out)


def pipa(freq, dur=0.9, sr=SR):
    """琵琶 — 明亮拨弦(锯齿+高/低通) + 快攻击 + 轻软削波(金属"乒乓") + 拨弦噪声瞬态。
    中国弹拨代表, 颗粒感强、衰减快。"""
    ph, _ = phase_array(freq, dur, sr)
    out = saw_from_phase(ph, max_h=70)
    out = onepole_lp(out, sr, fc=6500.0)            # 明亮
    out = onepole_hp(out, sr, fc=120.0)             # 去 Mud, 颗粒感
    out = softclip(out, 1.2)                        # 略带金属感
    hn = np.random.uniform(-1, 1, int(0.008 * sr))
    hn = onepole_hp(hn, sr, fc=3000.0) * np.exp(-np.arange(len(hn)) / sr / 0.004)
    out[:len(hn)] = out[:len(hn)] + hn * 0.20
    env = amp_env(dur, sr, a=0.002, d=0.30, s=0.0, r=0.05)
    out = out * env
    return normalize(out)


# ---- 中国民乐 Chinese ----

def erhu(freq, dur=1.4, sr=SR, vib=50.0):
    """二胡 — 弓弦(锯齿, 富含谐波) + 鼻音共振峰带通(~1.5kHz) + 颤音(±50 cents,"如泣如诉")
    + 轻高通去 Mud + 轻饱和。中国拉弦代表, 带金属"亮"味。"""
    cents = [-3.0, 3.0]
    out = np.zeros(int(dur * sr))
    for c in cents:
        f = freq * 2 ** (c / 1200.0)
        ph, _ = phase_array(f, dur, sr, vib=vib, vib_rate=6.0)
        out = out + saw_from_phase(ph, max_h=60)
    out = out / len(cents)
    out = onepole_hp(out, sr, fc=150.0)             # 去 Mud
    formant = biquad_bandpass(out, sr, f0=1500.0, Q=4.0) * 1.6  # 鼻音"亮"味
    out = out + formant
    out = softclip(out, 1.15)
    env = amp_env(dur, sr, a=0.04, d=0.15, s=0.90, r=0.20, sustain_level=0.90)
    out = out * env
    return normalize(out)


def taiko_drum(dur=0.9, sr=SR, f_start=120.0, f_end=50.0, sweep=0.08):
    """中国大鼓 / 太鼓 — 低频俯冲(120->50Hz) + 下方八度 sub + 三次谐波 + 双层体共振
    (160/320Hz) + 鼓皮噪声拍击。深而长、宏大的"轰", 区别于 kick 的"thud"; 无基频。"""
    n = int(dur * sr)
    t = np.arange(n) / sr
    freq = f_end + (f_start - f_end) * np.exp(-t / sweep)
    phase = 2 * np.pi * np.cumsum(freq) / sr
    body = (np.sin(phase)
            + 0.8 * np.sin(2 * np.pi * f_end * t)               # 下方八度 sub 重量
            + 0.30 * np.sin(2 * np.pi * (3 * f_end) * t))       # 三次谐波厚度
    body = (biquad_bandpass(body, sr, f0=160.0, Q=2.5) * 1.8
            + biquad_bandpass(body, sr, f0=320.0, Q=2.5) * 1.0
            + body * 0.5)
    env = np.zeros(n)
    atk = max(1, int(0.003 * sr))
    env[:atk] = np.linspace(0, 1, atk)
    env[atk:] = np.exp(-t[atk:] / 0.6)              # 更长衰减，更"宏大"
    out = body * env
    slap = np.random.uniform(-1, 1, int(0.02 * sr))
    slap = onepole_hp(slap, sr, fc=700.0) * np.exp(-np.arange(int(0.02 * sr)) / sr / 0.01)
    out[:len(slap)] += slap * 0.7
    return normalize(out, peak=0.95)


# ---- 玻璃感 / 钟铃打击（C418 palette：三角铁 / 八音盒 / 钢鼓）----

def triangle(freq, dur=0.6, sr=SR):
    """三角铁 — 金属杆非谐分音(1:2.76:5.40:8.93) + 大量高次"闪光"分音 + 极快衰减 + 击打瞬态。
    高饱和、明亮、短促的 "ting"; 整体抬两个八度更"对味"。"""
    f0 = freq * 4.0
    partials = [1.0, 2.76, 5.40, 8.93, 13.34, 18.6]
    amps = [1.0, 0.70, 0.50, 0.35, 0.22, 0.14]
    taus_frac = [0.50, 0.35, 0.22, 0.14, 0.09, 0.06]
    taus = [dur * x for x in taus_frac]
    out = additive(f0, dur, sr, partials, amps, taus)
    hn = np.random.uniform(-1, 1, int(0.01 * sr))
    hn = onepole_hp(hn, sr, fc=4000.0) * np.exp(-np.arange(len(hn)) / sr / 0.004)
    out[:len(hn)] = out[:len(hn)] + hn * 0.25
    env = amp_env(dur, sr, a=0.001, d=0.40, s=0.0, r=0.05)
    out = out * env
    return normalize(out)


def music_box(freq, dur=1.2, sr=SR):
    """八音盒 — 金属梳齿拨击: 极快攻击(尖) + 非谐钟铃分音 + 较快衰减(叮叮) + 击打瞬态 tick。
    原版用近谐波分音+长余韵(sustain=0.5)偏"柔/闷"; 改为很"尖"悦耳的钟铃:
    非谐高次分音(1:2.76:4.07:5.43...) + 极快起音 + 明显击打 tick + 更快衰减余韵。"""
    partials = [1.0, 2.76, 4.07, 5.43, 6.80, 8.93]
    amps = [1.0, 0.55, 0.38, 0.26, 0.17, 0.11]
    taus = [0.55, 0.32, 0.20, 0.13, 0.09, 0.06]     # 绝对秒, 衰减更快 -> "叮"不拖泥
    out = additive(freq, dur, sr, partials, amps, taus)
    # 极尖的击打瞬态(高频 tick): 梳齿被拨击的"嗒"
    atk = max(1, int(0.003 * sr))
    tick = np.random.uniform(-1, 1, atk).astype(np.float64)
    tick = onepole_hp(tick, sr, fc=6000.0) * np.exp(-np.arange(atk) / sr / 0.0025)
    if len(out) >= atk:
        out[:atk] = out[:atk] + tick * 0.6
    # 极快攻击包络 -> "尖"
    env = amp_env(dur, sr, a=0.0004, d=0.16, s=0.0, r=0.05)
    out = out * env
    return normalize(out)


def steel_drum(freq, dur=1.6, sr=SR):
    """钢鼓 / 钢片琴(pan) — 加勒比特有音高金属音色。基频 + 强八度(2x) + 八度五度(3x) + 4x
    分音(略非谐) + 快攻击"哐" + 中长衰减余韵 + 轻微颤音 shimmer。明亮、高饱和。"""
    partials = [1.0, 2.0, 3.0, 4.0, 5.3]
    amps = [1.0, 0.80, 0.60, 0.42, 0.25]
    taus = [1.4, 1.1, 0.8, 0.6, 0.4]                # 绝对秒, 钢鼓余韵长
    out = additive(freq, dur, sr, partials, amps, taus, vib=4.0)
    out = softclip(out, 1.1)                        # 金属温热
    env = amp_env(dur, sr, a=0.003, d=0.25, s=0.70, r=0.15, sustain_level=0.70)
    out = out * env
    return normalize(out)


# ----------------------------------------------------------------------------
# 校验 / Demo
# ----------------------------------------------------------------------------
def dom_freq(x, sr=SR):
    x = x - np.mean(x)
    w = np.hanning(len(x))
    X = np.abs(np.fft.rfft(x * w))
    freqs = np.fft.rfftfreq(len(x), 1.0 / sr)
    mask = freqs > 30
    if not np.any(mask):
        return 0.0
    return freqs[mask][np.argmax(X[mask])]


def spectral_centroid(x, sr=SR):
    x = np.abs(x)
    X = np.abs(np.fft.rfft(x))
    freqs = np.fft.rfftfreq(len(x), 1.0 / sr)
    return np.sum(freqs * X) / (np.sum(X) + 1e-9)


def build_all(outdir='demo_wavs'):
    os.makedirs(outdir, exist_ok=True)
    A4 = note_freq('A4')   # 440
    C5 = note_freq('C5')   # 523.25
    items = [
        ('lead_supersaw', supersaw_lead(A4)),
        ('lead_pluck', pluck_lead(A4)),
        ('lead_bright', bright_lead(A4)),
        ('strings_pad', string_pad(A4)),
        ('strings_orchestral_stab', orchestral_stab(A4)),
        ('strings_pizzicato', pizzicato(A4)),
        ('brass_stab', brass_stab(A4)),
        ('flute_wind', flute_wind(A4)),
        ('vocal_ah', vocal_formant(A4, vowel='ah')),
        ('perc_kick', kick()),
        ('perc_snare', snare()),
        ('xylophone', xylophone(C5)),
        # ---- 本次新增 ----
        ('bass_sub', sub_bass(note_freq('A2'))),
        ('bass_saw', saw_bass(note_freq('A2'))),
        ('perc_hihat', hihat(dur=0.06)),
        ('keys_piano', piano(note_freq('C4'))),
        # ---- 本次新增（管弦乐 / 弹拨 / 中国民乐 / 玻璃感打击）----
        ('orch_violin', violin(note_freq('A4'))),
        ('orch_cello', cello(note_freq('C3'))),
        ('orch_french_horn', french_horn(note_freq('F3'))),
        ('pluck_harp', harp(note_freq('C5'))),
        ('pluck_nylon_guitar', nylon_guitar(note_freq('E3'))),
        ('pluck_pipa', pipa(note_freq('A3'))),
        ('cn_erhu', erhu(note_freq('A4'))),
        ('cn_taiko_drum', taiko_drum(dur=0.9)),
        ('glass_triangle', triangle(note_freq('C6'))),
        ('glass_music_box', music_box(note_freq('C5'))),
        ('glass_steel_drum', steel_drum(note_freq('C4'))),
    ]
    report = []
    for name, sig in items:
        path = os.path.join(outdir, name + '.wav')
        write_wav(path, sig)
        rms = float(np.sqrt(np.mean(sig ** 2)))
        df = dom_freq(sig)
        sc = spectral_centroid(sig)
        report.append((name, path, rms, df, sc))
    # medley
    gap = np.zeros(int(0.15 * SR))
    med = np.concatenate([np.concatenate([s, gap]) for (_, s) in items])
    write_wav(os.path.join(outdir, 'medley.wav'), med)
    return report


if __name__ == '__main__':
    here = os.path.dirname(os.path.abspath(__file__))
    out = os.path.join(here, 'demo_wavs')
    rep = build_all(out)
    print(f"{'name':28} {'rms':>7} {'domHz':>9} {'centroid':>9}")
    for name, path, rms, df, sc in rep:
        print(f"{name:28} {rms:7.4f} {df:9.1f} {sc:9.1f}")
    print(f"\nWAV 已写入: {out}")
