"""音频引擎：音色静态库 / 工程混音 / 播放 / 导出 WAV。

- build_sample_library(): 把每种乐器的每个音高预合成为 samples/*.wav 静态文件。
  这正对应需求「音色调用 AI 自行合成、作为静态文件」——此处用程序化合成充当
  音色生成器，将来可直接替换为 AI 生成的采样文件（同名即可被加载）。
- render_note(): 优先加载静态文件并按音符时长 fit；缺文件时即时合成。
- mix_project(): 把所有音轨/音符按时间轴混合成单声道缓冲。
- play()/stop(): 基于 pygame 的播放控制。
"""
import os
import wave
import time
import threading
import numpy as np
import synth
from project import BEATS_PER_BAR

SR = synth.SR
SAMPLE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'samples')
USE_STATIC_SAMPLES = True

_player = {
    'channel': None,
    'sound': None,
    'full_pcm': None,
    'playing': False,
    'paused': False,
    'start_time': 0.0,
    'paused_at': 0.0,
    'playhead_step': 0.0,
    'step_dur': 0.0,
    'total_steps': 0,
    'project_hash': None,
    'preparing': False,
    'want_play': False,
}

# 保护 _player 中 full_pcm / project_hash / preparing 等状态，避免后台预渲染与前台播放竞争。
_render_lock = threading.Lock()
_render_thread = None


def _project_hash(project):
    """工程数据摘要，用于判断是否需要重新渲染整曲。"""
    return hash((
        project.bpm, project.bars, project.steps_per_bar, project.master_volume,
        tuple((t.instrument, round(t.volume, 4), t.muted,
               tuple((n.time, n.pitch, n.duration, round(n.velocity, 4))
                     for n in sorted(t.notes, key=lambda x: (x.time, x.pitch))))
              for t in project.tracks)
    ))

def _sample_path(key, midi):
    return os.path.join(SAMPLE_DIR, f"{key}_{midi}.wav")


def _write_wav(path, data, sr):
    data = np.clip(data, -1.0, 1.0)
    pcm = (data * 32767.0).astype('<i2')
    with wave.open(path, 'w') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


def _read_wav(path):
    with wave.open(path, 'r') as w:
        n = w.getnframes()
        sr = w.getframerate()
        raw = w.readframes(n)
    data = np.frombuffer(raw, dtype='<i2').astype(np.float32) / 32767.0
    return data, sr


def _library_signature():
    """随乐器集与合成内核变化的指纹；用于检测「静态缓存是否过时/损坏」。

    - 含 synth.py / edm_synth.py 的 sha256：任一音色数学改动都会使指纹变化
      -> 自动作废旧缓存并重生（杜绝「旧缓存掩盖代码修复」类问题）。
    - 含乐器 key 列表：新增/删除乐器也会触发重生。
    """
    import hashlib
    parts = []
    base = os.path.dirname(os.path.abspath(__file__))
    for fn in ('synth.py', 'edm_synth.py'):
        p = os.path.join(base, fn)
        try:
            with open(p, 'rb') as f:
                parts.append(hashlib.sha256(f.read()).hexdigest())
        except Exception:
            parts.append('missing:' + fn)
    parts.append(list(synth.INSTRUMENT_KEYS))
    return parts


def _manifest_path():
    return os.path.join(SAMPLE_DIR, '.library_manifest.json')


def _write_manifest():
    import json
    try:
        os.makedirs(SAMPLE_DIR, exist_ok=True)
        with open(_manifest_path(), 'w', encoding='utf-8') as f:
            json.dump({'signature': _library_signature(),
                       'built_at': time.time()}, f)
    except Exception:
        pass


def _safe_delete_file(p):
    """删除单个文件，绕过 Windows 只读锁与 safe-delete shim；非 Windows 走 os.remove。"""
    p = os.path.abspath(p)
    if os.name == 'nt':
        try:
            ctypes.windll.kernel32.SetFileAttributesW(p, 0x80)  # 清只读位
            if ctypes.windll.kernel32.DeleteFileW(p):
                return
        except Exception:
            pass
    try:
        os.chmod(p, 0o777)
    except Exception:
        pass
    try:
        os.remove(p)
    except Exception:
        pass


def clear_sample_library():
    """清空整个 samples 目录（含指纹）。用于「不完整则清空重载」。"""
    if os.path.isdir(SAMPLE_DIR):
        for f in os.listdir(SAMPLE_DIR):
            fp = os.path.join(SAMPLE_DIR, f)
            try:
                if os.path.isfile(fp) or os.path.islink(fp):
                    _safe_delete_file(fp)
            except Exception:
                pass
    if os.path.isdir(SAMPLE_DIR):
        if os.name == 'nt':
            try:
                ctypes.windll.kernel32.SetFileAttributesW(SAMPLE_DIR, 0x80)
                if ctypes.windll.kernel32.RemoveDirectoryW(SAMPLE_DIR):
                    return
            except Exception:
                pass
        try:
            import shutil
            shutil.rmtree(SAMPLE_DIR, ignore_errors=True)
        except Exception:
            pass


def library_fast_ok():
    """快速前置检查：指纹(manifest)吻合 且 .wav 文件数齐全 -> 信任缓存。

    仅用于「是否弹加载蒙版」的判定，不做逐文件解码（避免每次启动都慢）。
    """
    import json
    mp = _manifest_path()
    if not os.path.exists(mp):
        return False
    try:
        with open(mp, 'r', encoding='utf-8') as f:
            cur = json.load(f).get('signature')
    except Exception:
        return False
    if cur != _library_signature():
        return False
    expected = len(synth.INSTRUMENT_KEYS) * (synth.MIDI_HIGH - synth.MIDI_LOW + 1)
    try:
        actual = sum(1 for f in os.listdir(SAMPLE_DIR) if f.endswith('.wav'))
    except Exception:
        return False
    return actual == expected


def library_integrity_ok():
    """详尽校验：指纹 + 逐个 .wav 可打开 / 格式正确(单声道16bit) / 非空。

    任一缺失、损坏或指纹不符 -> 返回 False（调用方应清空重载）。
    """
    import json
    sig = _library_signature()
    mp = _manifest_path()
    if not os.path.exists(mp):
        return False
    try:
        with open(mp, 'r', encoding='utf-8') as f:
            if json.load(f).get('signature') != sig:
                return False
    except Exception:
        return False
    for key in synth.INSTRUMENT_KEYS:
        for midi in range(synth.MIDI_LOW, synth.MIDI_HIGH + 1):
            path = _sample_path(key, midi)
            if not os.path.exists(path):
                return False
            try:
                with wave.open(path, 'r') as w:
                    if w.getnchannels() != 1 or w.getsampwidth() != 2:
                        return False
                    if w.getnframes() < int(SR * 0.02):   # 短于 ~20ms 视为损坏
                        return False
            except Exception:
                return False
    return True


def build_sample_library(on_done=None, force=False, progress=None):
    """后台生成全部静态音色文件。

    force=True 时先清空整个 samples 目录（用于「不完整则清空重载」）。
    progress(done, total) 每渲染一个音高回调一次（用于 UI 进度条）。
    完成后写入 .library_manifest.json 指纹，供下次快速校验。
    """
    def _work():
        if force:
            clear_sample_library()
        os.makedirs(SAMPLE_DIR, exist_ok=True)
        total = len(synth.INSTRUMENT_KEYS) * (synth.MIDI_HIGH - synth.MIDI_LOW + 1)
        done = 0
        for key in synth.INSTRUMENT_KEYS:
            for midi in range(synth.MIDI_LOW, synth.MIDI_HIGH + 1):
                path = _sample_path(key, midi)
                if os.path.exists(path) and not force:
                    done += 1
                    if progress and (done % 20 == 0 or done == total):
                        progress(done, total)
                    continue
                p = synth.SYNTH[key]
                dur = 2.0
                if p['kind'] in ('perc', 'fx'):
                    dur = synth.PERC_DUR.get(p['sub'], 2.0)
                data = synth.render_one_shot(key, midi, SR, dur)
                _write_wav(path, data, SR)
                done += 1
                if progress and (done % 20 == 0 or done == total):
                    progress(done, total)
        _write_manifest()
        if on_done:
            on_done()
    threading.Thread(target=_work, daemon=True).start()


def build_sample_library_sync(force=False, progress=None):
    """同步版 build_sample_library：供启动线程在冻结界面时顺序执行（含进度回调）。"""
    if force:
        clear_sample_library()
    os.makedirs(SAMPLE_DIR, exist_ok=True)
    total = len(synth.INSTRUMENT_KEYS) * (synth.MIDI_HIGH - synth.MIDI_LOW + 1)
    done = 0
    for key in synth.INSTRUMENT_KEYS:
        for midi in range(synth.MIDI_LOW, synth.MIDI_HIGH + 1):
            path = _sample_path(key, midi)
            if os.path.exists(path) and not force:
                done += 1
                if progress and (done % 20 == 0 or done == total):
                    progress(done, total)
                continue
            p = synth.SYNTH[key]
            dur = 2.0
            if p['kind'] in ('perc', 'fx'):
                dur = synth.PERC_DUR.get(p['sub'], 2.0)
            data = synth.render_one_shot(key, midi, SR, dur)
            _write_wav(path, data, SR)
            done += 1
            if progress and (done % 20 == 0 or done == total):
                progress(done, total)
    _write_manifest()


def _fit_to_duration(data, dur, kind, sustain=0.8):
    n = int(dur * SR)
    if n <= 0:
        return np.zeros(1, dtype=np.float32)
    if kind in ('perc', 'fx'):
        # 打击乐不拉伸：按自然长度，尾部轻微淡出
        if len(data) >= n:
            out = data[:n].copy()
        else:
            out = np.pad(data, (0, n - len(data)))
        rel = int(min(0.03 * SR, n * 0.3))
        if rel > 0:
            out[-rel:] *= np.linspace(1, 0, rel)
        return out.astype(np.float32)
    # tonal / vocal：拼接 [起音][持续段循环][释音]，使声音长度 == 显示长度
    a_len = min(int(0.12 * SR), max(1, len(data) // 4))
    if sustain > 0.02:
        # 持续型（主音/铺底/弦乐/铜管/人声）：循环稳段，整段保持电平
        s0, s1 = int(0.4 * SR), int(0.9 * SR)
        if s1 > len(data):
            s1 = len(data)
        body = data[s0:s1]
        if len(body) < 1:
            body = data[a_len:max(a_len + 1, len(data))]
    else:
        # 衰减型（拨弦/钢琴）：循环早期波形 + 整体缓慢衰减，保证整段可闻
        s0, s1 = a_len, min(len(data), a_len + int(0.2 * SR))
        body = data[s0:s1]
        if len(body) < 1:
            body = data[:max(1, len(data) // 2)]
    reps = int(np.ceil((n - a_len) / max(1, len(body))))
    out = np.concatenate([data[:a_len], np.tile(body, reps)])[:n]
    if sustain <= 0.02:
        t = np.arange(n) / SR
        out = out * np.exp(-t * (1.5 / max(0.2, dur)))
    rel = int(min(0.12 * SR, n * 0.3))
    if rel > 0:
        out[-rel:] *= np.linspace(1, 0, rel)
    # 统一电平：无论源采样强弱，渲染后的每个音符都拉到一致可闻电平，
    # 避免钢琴/拨弦/主音等快速衰减音色在「起音+循环拼接」后偏轻、
    # 听起来像“没声音”。打击乐/riser 原本就接近满幅，此步基本不改变它们。
    pk = float(np.max(np.abs(out)))
    if pk > 1e-6:
        out = out / pk * 0.9
    return out.astype(np.float32)


def render_note(key, midi, dur, velocity):
    # 防御：若音色（如已卸载的 DLC）已从内核注销，回退到内置钢琴，避免播放崩溃
    if key not in synth.SYNTH:
        key = 'piano'
    p = synth.SYNTH[key]
    kind = p['kind']
    sustain = p.get('s', 0.0)
    if kind == 'vocal':
        sustain = 0.85
    # 旋律类（tonal / vocal）：按音符真实时长即时合成，彻底消除「静态样本循环拼接」
    # 造成的音节分节 / 抖动 / 杂乱问题——每个音都是一次连续、无接缝的发声。
    if kind in ('tonal', 'vocal'):
        data = synth.render_one_shot(key, midi, SR, max(0.05, float(dur)))
        pk = float(np.max(np.abs(data)))
        if pk > 1e-6:
            data = data / pk * 0.9
        return (data * float(velocity)).astype(np.float32)
    # 打击乐 / FX：使用静态样本（短促、无需拉伸），可按需施加混音增益
    data = None
    if USE_STATIC_SAMPLES:
        path = _sample_path(key, midi)
        if os.path.exists(path):
            try:
                data, _ = _read_wav(path)
            except Exception:
                data = None   # 静态文件损坏 -> 退回即时合成，不让播放崩溃
    if data is None:
        data = synth.render_one_shot(key, midi, SR, dur)
    data = _fit_to_duration(data, dur, kind, sustain)
    gain = p.get('gain', 1.0)
    return (data * gain * float(velocity)).astype(np.float32)


def mix_project(project, sr=SR):
    step_dur = (60.0 / project.bpm) * BEATS_PER_BAR / project.steps_per_bar
    total_steps = project.bars * project.steps_per_bar
    length = int(total_steps * step_dur * sr) + int(0.5 * sr)
    buf = np.zeros(length, dtype=np.float32)
    for track in project.tracks:
        if track.muted:
            continue
        for note in track.notes:
            if note.duration <= 0:
                continue
            t0 = int(note.time * step_dur * sr)
            dur = note.duration * step_dur
            if t0 >= length:
                continue
            samples = render_note(track.instrument, note.pitch, dur, note.velocity)
            # 三层音量独立乘区：音符 velocity（单音） × 音轨 volume × 工程 master_volume
            samples = samples * track.volume
            end = t0 + len(samples)
            if end > length:
                samples = samples[:length - t0]
                end = length
            if len(samples) == 0:
                continue
            buf[t0:end] += samples
    # 总音量（master）作为最后一级乘区作用于混音总线
    buf *= project.master_volume
    peak = float(np.max(np.abs(buf))) if buf.size else 0.0
    if peak > 0.999:
        buf = buf / peak * 0.99
    return buf, sr


def export_wav(project, path):
    buf, sr = mix_project(project, sr=SR)
    _write_wav(path, buf, sr)
    return path


# ---------------- pygame 播放（确定性状态机：停止 / 播放 / 暂停） ----------------
# 设计原则：无论暂停还是从任意位置拖动，再次发声都「按 step 重新切片」full_pcm，
# 绝不依赖 pygame 的 channel.unpause() 恢复旧声道段（那会在拖动后错位/失声）。
# 这样保证「从中间播放」在任何控制路径下都 100% 有声、且与红/蓝播放头严格对齐。
#
# 2026-08-26 改进：
# - _ensure_mixer 在启动时尽早调用，避免首次点击播放时才初始化音频设备造成数秒卡顿。
# - 新增 prepare_project：后台预渲染整曲，播放时只要缓存命中即可立即切片发声。
# - start/resume/seek 在缓存未命中时会后台渲染，并通过 root.after 回到主线程自动播放。
def _ensure_mixer():
    import pygame
    try:
        if not pygame.mixer.get_init():
            # 注意：pygame 实际强制立体声（2 通道），单声道字节会被当双声道 -> 速度翻倍。
            # 这里显式请求 2 通道，并在播放时按实际通道数构造 buffer。
            pygame.mixer.init(frequency=SR, size=-16, channels=2, buffer=2048)
    except Exception:
        # 极少数无音频设备的环境：静默降级，不阻塞启动；播放不可用但 UI 正常。
        pass


def _pcm_from_buf(buf):
    """把单声道 float 缓冲转换为 pygame 可直接播放的 int16（按实际通道数扩成多声道）。"""
    import pygame
    pcm = (np.clip(buf, -1, 1) * 32767.0).astype('<i2')
    init = pygame.mixer.get_init()
    if not init:
        # 无音频设备时单声道降级，避免 get_init() 返回 None 导致的崩溃
        return pcm.tobytes()
    _, _, ch = init
    if ch == 2:
        pcm = np.column_stack([pcm, pcm]).ravel()
    return pcm


def _render(project):
    """混音整曲（带哈希缓存），得到立体声 int16 的 full_pcm；始终刷新 step_dur/total_steps。

    注意：本函数主要在主线程调用；涉及 _player 写操作加锁，避免与后台 prepare_project 竞争。
    """
    import pygame
    _ensure_mixer()
    h = _project_hash(project)
    with _render_lock:
        if _player['project_hash'] == h and _player['full_pcm'] is not None:
            _player['step_dur'] = (60.0 / project.bpm) * BEATS_PER_BAR / project.steps_per_bar
            _player['total_steps'] = project.total_steps
            return
        buf, sr = mix_project(project, sr=SR)
        _player['full_pcm'] = _pcm_from_buf(buf)
        _player['step_dur'] = (60.0 / project.bpm) * BEATS_PER_BAR / project.steps_per_bar
        _player['total_steps'] = project.total_steps
        _player['project_hash'] = h


def prepare_project(project, root=None, on_ready=None):
    """后台预渲染工程。缓存命中则立即回调；否则启动后台线程，完成后回调。

    若提供 root，则 on_ready 通过 root.after(0, ...) 回到主线程，确保 pygame Sound.play
    等操作在主线程执行，避免多线程音频初始化/播放的潜在问题。
    """
    _ensure_mixer()
    h = _project_hash(project)
    with _render_lock:
        if _player['project_hash'] == h and _player['full_pcm'] is not None:
            if on_ready:
                if root is not None:
                    root.after(0, on_ready)
                else:
                    on_ready()
            return
        if _player.get('preparing'):
            return
        _player['preparing'] = True

    def work():
        try:
            buf, sr = mix_project(project, sr=SR)
            h2 = _project_hash(project)
            with _render_lock:
                _player['full_pcm'] = _pcm_from_buf(buf)
                _player['step_dur'] = (60.0 / project.bpm) * BEATS_PER_BAR / project.steps_per_bar
                _player['total_steps'] = project.total_steps
                _player['project_hash'] = h2
                _player['preparing'] = False
        except Exception:
            with _render_lock:
                _player['preparing'] = False
            raise
        if on_ready:
            if root is not None:
                root.after(0, on_ready)
            else:
                on_ready()

    global _render_thread
    _render_thread = threading.Thread(target=work, daemon=True)
    _render_thread.start()


def is_preparing():
    return bool(_player.get('preparing'))


def _start_from(step):
    """从 step（含）开始播放：对 full_pcm 重新切片尾部并播放，保证任意位置都有声。"""
    import pygame
    pcm = _player['full_pcm']
    if pcm is None or len(pcm) < 2:
        _player['playing'] = False
        _player['paused'] = False
        return
    sr = SR
    start_frame = int(max(0.0, step) * _player['step_dur'] * sr)
    idx = start_frame * 2  # 立体声交织，每帧 2 个 int16
    tail = pcm[idx:]
    if len(tail) < 2:
        # 已到曲尾，没有可播放内容
        _player['playing'] = False
        _player['paused'] = False
        return
    if _player['channel']:
        try:
            _player['channel'].stop()
        except Exception:
            pass
    _player['sound'] = pygame.mixer.Sound(tail.tobytes())
    _player['channel'] = _player['sound'].play()
    _player['start_time'] = time.time()
    _player['playhead_step'] = float(step)
    _player['playing'] = True
    _player['paused'] = False


def start(project, root=None, start_step=None):
    """停止态 -> 从 start_step（默认当前 playhead）开始播放。

    若缓存命中则立即播放并返回 True；否则后台渲染，就绪后自动播放并返回 False。
    """
    _ensure_mixer()
    h = _project_hash(project)
    with _render_lock:
        ready = (_player['project_hash'] == h and _player['full_pcm'] is not None)
    if ready:
        step = start_step if start_step is not None else _player.get('playhead_step', 0.0)
        step = max(0.0, min(step, _player['total_steps']))
        _start_from(step)
        return True

    # 缓存未命中：后台准备，完成后自动从指定位置播放
    _player['want_play'] = True

    def on_ready():
        if _player.get('want_play'):
            _player['want_play'] = False
            step = start_step if start_step is not None else _player.get('playhead_step', 0.0)
            step = max(0.0, min(step, _player['total_steps']))
            _start_from(step)

    prepare_project(project, root=root, on_ready=on_ready)
    return False


def resume(project, root=None):
    """暂停态 -> 从记录位置继续（重新切片，确保声音正确且对齐播放头）。"""
    _ensure_mixer()
    h = _project_hash(project)
    with _render_lock:
        ready = (_player['project_hash'] == h and _player['full_pcm'] is not None)
    if ready:
        _start_from(_player.get('playhead_step', 0.0))
        return True

    _player['want_play'] = True

    def on_ready():
        if _player.get('want_play'):
            _player['want_play'] = False
            _start_from(_player.get('playhead_step', 0.0))

    prepare_project(project, root=root, on_ready=on_ready)
    return False


def pause(project):
    """播放 -> 暂停（停声并记录当前精确位置）。"""
    if _player.get('playing'):
        _player['playhead_step'] = get_playhead_step()
        if _player['channel']:
            try:
                _player['channel'].stop()
            except Exception:
                pass
    _player['playing'] = False
    _player['paused'] = True
    _player['channel'] = None
    _player['want_play'] = False


def stop():
    """停止并回到开头。"""
    try:
        if _player.get('channel'):
            _player['channel'].stop()
    except Exception:
        pass
    _player['playing'] = False
    _player['paused'] = False
    _player['playhead_step'] = 0.0
    _player['channel'] = None
    _player['sound'] = None
    _player['want_play'] = False


def seek(project, step, root=None):
    """跳转：播放中则无缝从新位置重播；暂停/停止则仅记忆位置（下次必然从该位置发声）。"""
    step = max(0.0, min(float(step), project.total_steps))
    _player['playhead_step'] = step
    if _player.get('playing'):
        h = _project_hash(project)
        with _render_lock:
            ready = (_player['project_hash'] == h and _player['full_pcm'] is not None)
        if ready:
            _start_from(step)
        else:
            _player['want_play'] = True

            def on_ready():
                if _player.get('want_play'):
                    _player['want_play'] = False
                    _start_from(step)

            prepare_project(project, root=root, on_ready=on_ready)


def is_playing():
    return _player['playing']


def is_paused():
    return _player['paused']


def get_playhead_step():
    if _player.get('playing'):
        elapsed = time.time() - _player['start_time']
        return _player.get('playhead_step', 0.0) + elapsed / _player['step_dur']
    return _player.get('playhead_step', 0.0)


# ---------------- 试听 / 音标发声（鼠标按住发声，松开停止） ----------------
# 独立于整曲播放（_player），独占一条声道；用于钢琴卷帘「点音标/点音符发声、
# 拖拽变调连续发声」等交互（参考 FL Studio 的琴键试听）。
_preview = {'channel': None, 'sound': None, 'key': None, 'midi': None, 'velocity': None}

# ---- 试听缓冲缓存：原 preview_note 每次都在 UI 线程全量重合成 2.5s 缓冲（单次 ~500ms），
#      是「点击/拖拽音符卡顿」的根因。改为按 (乐器, 音高, 量化响度) 缓存合成结果，
#      并用「稳态尾段短循环」消除卡顿且不引入循环重音头。----
_preview_cache = {}                 # (key, midi, vq) -> MONO int16 pcm bytes（与声道数无关）
_preview_cache_lock = threading.Lock()
_preview_warming = set()            # 正在后台预热的乐器 key，避免重复预热

# 预览用：合成稍长缓冲以越过起音(attack)，再截取稳态尾段作为无缝短循环，
# 既消除「每跨一行重合成 ~500ms」的卡顿，又避免短循环反复重触发音头。
PREVIEW_RENDER_DUR = 0.7           # 渲染长度（秒），需 > 起音时长以保证尾段处于稳态
PREVIEW_LOOP_DUR = 0.35            # 实际循环段长度（秒，取自稳态尾段）


def _preview_pcm_bytes(key, midi, velocity):
    """返回 MONO int16 pcm bytes（tonal/vocal 为稳态尾段短循环；perc/fx 为短促整段）。

    命中缓存直接返回；未命中则合成并按 (乐器, 音高, 量化响度) 缓存。
    缓存与声道数无关——声道复制在播放时（main 线程、mixer 已初始化）完成，
    因此本函数可在后台线程安全调用（无需初始化 pygame）。
    """
    p = synth.SYNTH.get(key)
    if p is None:
        return None
    kind = p['kind']
    vq = round(float(velocity) * 10) / 10   # 响度量化到 10% 步进，缩小缓存规模
    cache_key = (key, int(midi), vq)
    with _preview_cache_lock:
        hit = _preview_cache.get(cache_key)
    if hit is not None:
        return hit
    if kind in ('tonal', 'vocal'):
        dur = PREVIEW_RENDER_DUR
    else:
        dur = synth.PERC_DUR.get(p.get('sub'), 0.5)
    data = render_note(key, int(midi), float(dur), float(velocity))
    pcm = (np.clip(data, -1.0, 1.0) * 32767.0).astype('<i2')
    if kind in ('tonal', 'vocal'):
        # 取一段稳态窗做无缝短循环。持续音（pad/弦乐/lead）尾段≈稳态 -> 直接取尾段无缝；
        # 但衰减快的「打击感 tonal」（八音盒/钢琴/拨弦）在 0.35s 后已近静音，若仍取尾段
        # 则循环段几乎无声（拖拽/试听听不到）。此时改用整段 RMS 最大的窗，落在起音段，
        # 循环即有可听的「重击/叮」声。
        loop_n = int(PREVIEW_LOOP_DUR * SR)
        if len(pcm) > loop_n:
            total = len(pcm)
            tail = pcm[total - loop_n:]
            tail_rms = float(np.sqrt(np.mean(tail.astype('float64') ** 2)))
            full_rms = float(np.sqrt(np.mean(pcm.astype('float64') ** 2)))
            if full_rms > 1e-6 and tail_rms < 0.30 * full_rms:
                best_rms, best_i = 0.0, 0
                hop = max(1, loop_n // 4)
                for i in range(0, total - loop_n + 1, hop):
                    seg = pcm[i:i + loop_n].astype('float64')
                    r = np.sqrt(np.mean(seg * seg))
                    if r > best_rms:
                        best_rms, best_i = r, i
                pcm = pcm[best_i:best_i + loop_n]
            else:
                pcm = tail
    b = pcm.tobytes()
    with _preview_cache_lock:
        _preview_cache[cache_key] = b
    return b


def preview_note(key, midi, velocity=1.0, dur=None):
    """开始试听一个音：用当前乐器 key 合成 midi 音高的声音并独占声道播放。
    - tonal / vocal：循环播放直到 preview_stop()（实现「按多久响多久」）。
    - perc / fx：仅播放一次（短促，本就不适合持续发声）。
    音色 == 当前音轨乐器，音调 == midi，响度 == velocity（音标调用时传 1.0 即 100%）。
    合成结果按 (乐器, 音高, 响度) 缓存，杜绝每次点击/拖拽的重复重合成卡顿。
    """
    import pygame
    _ensure_mixer()
    p = synth.SYNTH.get(key)
    if p is None:
        return
    kind = p['kind']
    mono = _preview_pcm_bytes(key, int(midi), float(velocity))
    if mono is None:
        return
    # 声道复制在播放时（main 线程、mixer 已初始化）完成；缓存只存 mono
    _, _, ch = pygame.mixer.get_init()
    if ch == 2:
        arr = np.frombuffer(mono, dtype='<i2')
        stereo = np.column_stack([arr, arr]).ravel().tobytes()
    else:
        stereo = mono
    preview_stop()  # 先停掉上一次，避免叠音
    sound = pygame.mixer.Sound(stereo)
    loops = -1 if kind in ('tonal', 'vocal') else 0
    _preview['channel'] = sound.play(loops=loops)
    _preview['sound'] = sound
    _preview['key'] = key
    _preview['midi'] = int(midi)
    _preview['velocity'] = float(velocity)


def preview_set_pitch(key, midi, velocity=1.0):
    """拖拽变调时调用：若正在试听且音高/乐器变化则重新触发（FL 风滑音试听），
    否则（音高没变）保持当前发声持续。命中缓存时几乎零开销。"""
    if _preview.get('key') is None:
        return
    if _preview.get('midi') == int(midi) and _preview.get('key') == key:
        return
    preview_note(key, midi, velocity)


def preview_stop():
    """停止试听发声（左键松开时调用）。"""
    if _preview.get('channel'):
        try:
            _preview['channel'].stop()
        except Exception:
            pass
    for k in ('channel', 'sound', 'key', 'midi', 'velocity'):
        _preview[k] = None


def preview_raw(wave, loops=-1):
    """试听任意一段生成好的单声道波形（float32/float64, -1..1）。

    主要用于「音色合成工坊」实时预览：用 synth_factory 即时合成 -> 直接播放，
    不经过 (乐器, 音高) 缓存。 tonal 传 loops=-1 持续循环直到 preview_stop()。
    """
    import pygame
    _ensure_mixer()
    wave = np.asarray(wave, dtype=np.float64)
    wave = np.clip(wave, -1.0, 1.0)
    pcm = (wave * 32767.0).astype('<i2')
    _, _, ch = pygame.mixer.get_init()
    if ch == 2:
        arr = pcm
        stereo = np.column_stack([arr, arr]).ravel().tobytes()
    else:
        stereo = pcm.tobytes()
    preview_stop()
    sound = pygame.mixer.Sound(stereo)
    _preview['channel'] = sound.play(loops=loops)
    _preview['sound'] = sound
    _preview['key'] = None
    _preview['midi'] = None
    _preview['velocity'] = None


def warm_preview_cache(key, midis):
    """后台预热某乐器的试听缓存（整条音域）。独立线程执行，不阻塞 UI；
    预热完成后该乐器任意音高的点击/拖拽均为缓存命中，零音频合成开销。
    预热覆盖常用响度（1.0=音标/试听、0.85=默认音符），其余响度按需即时合成并缓存。"""
    with _preview_cache_lock:
        if key in _preview_warming:
            return
        _preview_warming.add(key)

    def _run():
        try:
            for m in midis:
                for v in (1.0, 0.85):
                    _preview_pcm_bytes(key, m, v)
        finally:
            with _preview_cache_lock:
                _preview_warming.discard(key)

    threading.Thread(target=_run, daemon=True).start()


def clear_preview_cache(key=None):
    """清除试听缓存（换乐器/卸载音色时调用，避免陈旧缓冲）。key=None 清空全部。"""
    with _preview_cache_lock:
        if key is None:
            _preview_cache.clear()
        else:
            for k in list(_preview_cache.keys()):
                if k[0] == key:
                    _preview_cache.pop(k, None)

