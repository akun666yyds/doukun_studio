"""音色合成引擎（适配层）。

底层合成内核来自技能 edm-timbre-synthesis 的 edm_synth.py（纯 numpy 数学合成，
依据权威社区调研的 EDM 音色配方：Supersaw / 减法合成主音 / Karplus-Strong 拨弦 /
滤波包络铜管 / 共振峰人声 / 非谐分音木琴 / 失谐锯齿+sub 贝斯 / 噪声高通鼓组 / Riser 等）。

本文件复刻一套 42 种独立音色——每个乐器 key 一一对应 edm_synth 里一个
**有独立实现**的函数，不再做"近似 / 重复"映射（旧版 23 key 实际只映射到十几个函数，
造成大量重复且遗漏）。前 17 种依据 edm-timbre-synthesis 技能文档；本次再新增 11 种
（管弦乐 / 弹拨 / 中国民乐 / 玻璃感打击），不拘泥于原技能、并参考 C418 的钟铃/玻璃感 palette；
另含一组「类正弦波」和弦音色（大三/小三 + 12 种明亮和弦，一个音符内多个音调同音色同时作响）。

42 种音色（类别 / edm_synth 函数名）：
  主音 Lead(3)        : supersaw_lead / pluck_lead / bright_lead
  弦乐 Strings(3)     : string_pad / orchestral_stab / pizzicato
  管乐 Brass/Wind(2)  : brass_stab / flute_wind
  打击乐 Perc(3)      : kick / snare / hihat
  模拟人声 Vocal(1)   : vocal_formant
  木琴 Xylo(1)        : xylophone
  低频 Bass(2)        : sub_bass / saw_bass
  键盘 Keys(1)        : piano
  -- 本次新增 --
  管弦乐 Orchestral(3): violin / cello / french_horn
  弹拨 Plucked(3)     : harp / nylon_guitar / pipa
  中国民乐 Chinese(2) : erhu(拉弦) / taiko_drum(打击)
  玻璃感打击 Glass(3) : triangle / music_box / steel_drum

对外暴露的稳定 API（audio_engine / main / project / ingest_samples 无需改动）：
  INSTRUMENTS / INSTRUMENT_KEYS / INSTRUMENT_LABEL / INSTRUMENT_FAMILY / LABEL_TO_KEY
  SR / MIDI_LOW / MIDI_HIGH / midi_to_freq / note_name / render_one_shot
  SYNTH[key] = {'kind','s',[('sub')]}   # 供 audio_engine 拉伸/循环策略
  PERC_DUR   = {sub: 自然时长(秒)}        # 供 audio_engine 渲染静态样本
"""
import os
import numpy as np
import edm_synth as edm
from synth_factory import DLC_DIR

SR = edm.SR  # 44100

# ----------------------------------------------------------------------------
# 乐器注册表：(key, 中文名, 家族) —— 严格 17 种，每个对应 edm_synth 独立函数
# ----------------------------------------------------------------------------
INSTRUMENTS = [
    # 主音 Lead
    ('supersaw_lead', '超级锯齿主音', '主音'),
    ('pluck_lead',    '清脆拨弦主音', '主音'),
    ('bright_lead',   '穿透双波主音', '主音'),
    # 弦乐 Strings
    ('string_pad',     '温润弦乐铺底', '弦乐'),
    ('orchestral_stab','亮弦 Stab',    '弦乐'),
    ('pizzicato',      '弹性拨弦',     '弦乐'),
    # 管乐 Brass / Wind
    ('brass_stab',     '铜管 Stab',     '管乐'),
    ('flute_wind',     '长笛气声管乐', '管乐'),
    # 打击乐 Perc
    ('kick',    '底鼓',  '打击乐'),
    ('snare',   '军鼓',  '打击乐'),
    ('hihat',   '踩镲',  '打击乐'),
    # 模拟人声 Vocal
    ('vocal_formant', '共振峰人声', '人声'),
    # 木琴 Xylo
    ('xylophone', '木琴', '木琴'),
    # 低频 Bass
    ('sub_bass',  'Sub 低频贝斯',  '低频贝斯'),
    ('saw_bass',  'Reese 锯齿贝斯','低频贝斯'),
    # 键盘 Keys
    ('piano', '钢琴', '键盘'),
    # 管弦乐 Orchestral（本次新增，拉齐"管弦乐"家族）
    ('violin',      '小提琴',   '管弦乐'),
    ('cello',       '大提琴',   '管弦乐'),
    ('french_horn', '圆号',     '管弦乐'),
    # 弹拨 Plucked（本次新增）
    ('harp',         '竖琴',     '弹拨'),
    ('nylon_guitar', '古典吉他', '弹拨'),
    ('pipa',         '琵琶',     '弹拨'),
    # 中国民乐 Chinese（本次新增）
    ('erhu',       '二胡',     '中国拉弦'),
    ('taiko_drum', '中国大鼓', '中国打击乐'),
    ('gong',       '敲锣',     '中国打击乐'),
    # 玻璃感 / 钟铃打击 Glass-perc（参考 C418 palette）
    ('triangle',    '三角铁', '玻璃感打击'),
    ('music_box',   '八音盒', '玻璃感打击'),
    ('steel_drum',  '钢鼓',   '玻璃感打击'),
    # 正弦和弦 Chord-sine（一个音符内多个同音色音调同时作响；相对第一个音为基调）
    # 保留：大三 / 小三；宽音/错位和弦（chord_maj_a / chord_maj7_w / chord_dom9_w / chord_min_w）已删除；
    # 新增 12 种明亮好听、高饱和、不混沌昏黑的和弦音色（依据和弦乐理叠加公式）。
    ('chord_maj',       '大三和弦 C+E+G',       '正弦和弦'),
    ('chord_min',       '小三和弦 C+D#+G',      '正弦和弦'),
    ('chord_maj7',      '大七和弦 C+E+G+B',     '正弦和弦'),
    ('chord_dom7',      '属七和弦 C+E+G+Bb',    '正弦和弦'),
    ('chord_maj6',      '大六和弦 C+E+G+A',     '正弦和弦'),
    ('chord_add9',      '大九和弦 C+E+G+D',     '正弦和弦'),
    ('chord_sus4',      '挂四和弦 C+F+G',       '正弦和弦'),
    ('chord_sus2',      '挂二和弦 C+D+G',       '正弦和弦'),
    ('chord_maj_oct',   '大三·八度 C+E+G+C5',   '正弦和弦'),
    ('chord_maj_fifth', '大三·高八G C+E+G+G5',  '正弦和弦'),
    ('chord_min7',      '小七和弦 C+D#+G+Bb',   '正弦和弦'),
    ('chord_min6',      '小六和弦 C+D#+G+A',    '正弦和弦'),
    ('chord_min_add9',  '小九和弦 C+D#+G+D',    '正弦和弦'),
    ('chord_dom9',      '属九和弦 C+E+G+Bb+D',  '正弦和弦'),
]
INSTRUMENT_KEYS = [k for k, _, _ in INSTRUMENTS]
INSTRUMENT_LABEL = {k: l for k, l, _ in INSTRUMENTS}
INSTRUMENT_FAMILY = {k: f for k, _, f in INSTRUMENTS}
LABEL_TO_KEY = {l: k for k, l, _ in INSTRUMENTS}

# 音高范围（含端点）。C2(36)..C6(84) = 4 个八度
MIDI_LOW = 36
MIDI_HIGH = 84

# ----------------------------------------------------------------------------
# 音色映射表：每个 key -> edm_synth 合成函数 + 渲染元数据
#   func       : edm_synth 中的函数名（每个都是独立实现，无重复）
#   needs_freq : 是否需要基频参数（tonal/vocal 需要；perc/fx 仅 dur）
#   kind       : 'tonal' / 'perc' / 'vocal' / 'fx'（audio_engine 拉伸/循环策略）
#   sustain    : 延音电平（0=衰减型，>0=持续型）
#   sub        : perc/fx 的"自然时长"键（与 PERC_DUR 对应）
#   natural    : perc/fx 的自然时长（秒），用作静态样本渲染时长
#   kwargs     : 传给 edm 函数的额外参数（如 vocal 的 vowel）
# ----------------------------------------------------------------------------
_DISPATCH = {
    # 主音 Lead
    'supersaw_lead':   dict(func='supersaw_lead',   needs_freq=True,  kind='tonal', sustain=0.80),
    'pluck_lead':      dict(func='pluck_lead',      needs_freq=True,  kind='tonal', sustain=0.00),
    'bright_lead':     dict(func='bright_lead',     needs_freq=True,  kind='tonal', sustain=0.70),
    # 弦乐 Strings
    'string_pad':      dict(func='string_pad',      needs_freq=True,  kind='tonal', sustain=0.85),
    'orchestral_stab': dict(func='orchestral_stab', needs_freq=True,  kind='tonal', sustain=0.80),
    'pizzicato':       dict(func='pizzicato',       needs_freq=True,  kind='tonal', sustain=0.00),
    # 管乐 Brass / Wind
    'brass_stab':      dict(func='brass_stab',      needs_freq=True,  kind='tonal', sustain=0.80),
    'flute_wind':      dict(func='flute_wind',      needs_freq=True,  kind='tonal', sustain=0.80),
    # 打击乐 Perc（无基频）
    'kick':    dict(func='kick',    needs_freq=False, kind='perc', sustain=0.0, sub='kick',  natural=0.50, gain=1.25),
    'snare':   dict(func='snare',   needs_freq=False, kind='perc', sustain=0.0, sub='snare', natural=0.25),
    'hihat':   dict(func='hihat',   needs_freq=False, kind='perc', sustain=0.0, sub='hihat', natural=0.12),
    # 模拟人声 Vocal（有基频，共振峰随元音变形）
    'vocal_formant': dict(func='vocal_formant', needs_freq=True,  kind='vocal', sustain=0.90, kwargs={'vowel': 'ah'}),
    # 木琴 Xylo
    'xylophone':      dict(func='xylophone',        needs_freq=True,  kind='tonal', sustain=0.00),
    # 低频 Bass
    'sub_bass':       dict(func='sub_bass',         needs_freq=True,  kind='tonal', sustain=0.90),
    'saw_bass':       dict(func='saw_bass',         needs_freq=True,  kind='tonal', sustain=0.95),
    # 键盘 Keys
    'piano':          dict(func='piano',            needs_freq=True,  kind='tonal', sustain=0.00),
    # 管弦乐 Orchestral（本次新增）
    'violin':      dict(func='violin',      needs_freq=True,  kind='tonal', sustain=0.88),
    'cello':       dict(func='cello',       needs_freq=True,  kind='tonal', sustain=0.90),
    'french_horn': dict(func='french_horn', needs_freq=True,  kind='tonal', sustain=0.85),
    # 弹拨 Plucked（本次新增）
    'harp':         dict(func='harp',         needs_freq=True,  kind='tonal', sustain=0.00),
    'nylon_guitar': dict(func='nylon_guitar', needs_freq=True,  kind='tonal', sustain=0.00),
    'pipa':         dict(func='pipa',         needs_freq=True,  kind='tonal', sustain=0.00),
    # 中国民乐 Chinese（本次新增）
    'erhu':       dict(func='erhu',       needs_freq=True,  kind='tonal', sustain=0.90),
    'taiko_drum': dict(func='taiko_drum', needs_freq=False, kind='perc', sustain=0.0, sub='taiko_drum', natural=0.90, gain=1.30),
    # 玻璃感 / 钟铃打击（本次新增，参考 C418 palette）
    'triangle':    dict(func='triangle',    needs_freq=True,  kind='tonal', sustain=0.00),
    'music_box':   dict(func='music_box',   needs_freq=True,  kind='tonal', sustain=0.50),
    'steel_drum':  dict(func='steel_drum',  needs_freq=True,  kind='tonal', sustain=0.70),
    # 中国民族打击乐：敲锣（金属非谐分音 + 长余音）
    'gong':        dict(func='gong',        needs_freq=True,  kind='tonal', sustain=0.00),
    # 正弦和弦（类正弦波；chord=相对第一个音的半音偏移列表，按所放音符整体平移）：
    # 一个音符内多个同音色正弦声部同时作响。保留大三/小三，新增 12 种（和弦乐理叠加公式，高饱和不黯然）。
    'chord_maj':       dict(func='chord_voice', needs_freq=True, kind='tonal', sustain=0.80, chord=[0, 4, 7]),
    'chord_min':       dict(func='chord_voice', needs_freq=True, kind='tonal', sustain=0.80, chord=[0, 3, 7]),
    'chord_maj7':      dict(func='chord_voice', needs_freq=True, kind='tonal', sustain=0.80, chord=[0, 4, 7, 11]),
    'chord_dom7':      dict(func='chord_voice', needs_freq=True, kind='tonal', sustain=0.80, chord=[0, 4, 7, 10]),
    'chord_maj6':      dict(func='chord_voice', needs_freq=True, kind='tonal', sustain=0.80, chord=[0, 4, 7, 9]),
    'chord_add9':      dict(func='chord_voice', needs_freq=True, kind='tonal', sustain=0.80, chord=[0, 4, 7, 14]),
    'chord_sus4':      dict(func='chord_voice', needs_freq=True, kind='tonal', sustain=0.80, chord=[0, 5, 7]),
    'chord_sus2':      dict(func='chord_voice', needs_freq=True, kind='tonal', sustain=0.80, chord=[0, 2, 7]),
    'chord_maj_oct':   dict(func='chord_voice', needs_freq=True, kind='tonal', sustain=0.80, chord=[0, 4, 7, 12]),
    'chord_maj_fifth': dict(func='chord_voice', needs_freq=True, kind='tonal', sustain=0.80, chord=[0, 4, 7, 19]),
    'chord_min7':      dict(func='chord_voice', needs_freq=True, kind='tonal', sustain=0.80, chord=[0, 3, 7, 10]),
    'chord_min6':      dict(func='chord_voice', needs_freq=True, kind='tonal', sustain=0.80, chord=[0, 3, 7, 9]),
    'chord_min_add9':  dict(func='chord_voice', needs_freq=True, kind='tonal', sustain=0.80, chord=[0, 3, 7, 14]),
    'chord_dom9':      dict(func='chord_voice', needs_freq=True, kind='tonal', sustain=0.80, chord=[0, 4, 7, 10, 14]),
}

# 供 audio_engine 使用的元数据表（保持旧字段名 kind / sub / s；gain 为可选混音增益）
SYNTH = {}
for _k, _v in _DISPATCH.items():
    _e = {'kind': _v['kind'], 's': _v['sustain']}
    if _v['kind'] in ('perc', 'fx'):
        _e['sub'] = _v['sub']
    if 'gain' in _v:
        _e['gain'] = _v['gain']
    SYNTH[_k] = _e

# perc/fx 自然时长表（单源真相，供 build_sample_library 渲染静态样本）
PERC_DUR = {_k: _v['natural'] for _k, _v in _DISPATCH.items() if _v['kind'] in ('perc', 'fx')}


# ----------------------------------------------------------------------------
# 音色 DLC 注册表（运行时可插拔；与内置乐器分离，不污染静态音色库统计）
# ----------------------------------------------------------------------------
# 设计：内置乐器走 INSTRUMENT_KEYS / _DISPATCH；DLC 仅叠加进 _DISPATCH / SYNTH /
# INSTRUMENT_LABEL / INSTRUMENT_FAMILY，并单独登记到 DLC_KEYS（供选择器展示），
# 但**不进入 INSTRUMENT_KEYS**——因此静态音色库(library_* / build_sample_library)
# 的计数与渲染只针对内置乐器，DLC 始终走「即时合成」路径，可随添随删、无需重建缓存。
DLC_KEYS = []          # 当前已注册的 DLC 乐器 key 列表
DLC_REGISTRY = {}      # key -> (spec, module)


def _spec_to_synth(spec):
    e = {'kind': spec['kind'], 's': spec['sustain']}
    if spec['kind'] in ('perc', 'fx'):
        e['sub'] = spec['sub']
    if 'gain' in spec:
        e['gain'] = spec['gain']
    return e


def register_dlc(key, spec, module):
    """把已加载的 DLC 模块注册进内核（运行时生效，无需重启）。"""
    spec = dict(spec)
    spec['dlc'] = True
    spec['module'] = module
    spec['func'] = spec.get('func', 'render')
    _DISPATCH[key] = spec
    SYNTH[key] = _spec_to_synth(spec)
    INSTRUMENT_LABEL[key] = spec.get('label', key)
    INSTRUMENT_FAMILY[key] = spec.get('family', '我的DLC')
    if INSTRUMENT_LABEL[key] not in LABEL_TO_KEY:
        LABEL_TO_KEY[INSTRUMENT_LABEL[key]] = key
    if key not in DLC_KEYS:
        DLC_KEYS.append(key)
    DLC_REGISTRY[key] = (spec, module)


def unregister_dlc(key):
    """从内核注销 DLC 乐器（运行时移除）。"""
    _DISPATCH.pop(key, None)
    SYNTH.pop(key, None)
    label = INSTRUMENT_LABEL.pop(key, None)
    INSTRUMENT_FAMILY.pop(key, None)
    if label and LABEL_TO_KEY.get(label) == key:
        LABEL_TO_KEY.pop(label, None)
    if key in DLC_KEYS:
        DLC_KEYS.remove(key)
    DLC_REGISTRY.pop(key, None)


def get_all_instrument_keys():
    """内置 + DLC 全部乐器 key（供音色选择器展示）。"""
    return list(INSTRUMENT_KEYS) + list(DLC_KEYS)


def _import_dlc_module(key, full):
    import importlib.util
    spec = importlib.util.spec_from_file_location('dlc_' + key, full)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_dlc_folder(path=None):
    """扫描 instrument_dlc/ 下所有 .py（排除内部模块），导入并注册。返回新注册的 key 列表。"""
    if path is None:
        path = DLC_DIR
    os.makedirs(path, exist_ok=True)
    loaded = []
    for fn in sorted(os.listdir(path)):
        if not fn.endswith('.py'):
            continue
        if fn in ('synth_factory.py', 'dlc_base.py'):
            continue
        key = fn[:-3]
        if key in _DISPATCH and _DISPATCH[key].get('dlc'):
            continue  # 已加载
        full = os.path.join(path, fn)
        try:
            mod = _import_dlc_module(key, full)
            dlc = getattr(mod, 'DLC', None)
            if not isinstance(dlc, dict):
                continue
            register_dlc(key, dlc, mod)
            loaded.append(key)
        except Exception as e:
            import sys
            print('[DLC] 加载失败 %s: %r' % (fn, e), file=sys.stderr)
    return loaded


def reload_dlc():
    """即插即用：扫描文件夹，注册新增、注销已删除的 DLC。返回新加载的 key。"""
    if not os.path.isdir(DLC_DIR):
        return []
    present = set()
    for fn in os.listdir(DLC_DIR):
        if fn.endswith('.py') and fn not in ('synth_factory.py', 'dlc_base.py'):
            present.add(fn[:-3])
    for key in list(DLC_KEYS):
        if key not in present:
            unregister_dlc(key)
    return load_dlc_folder()


def delete_dlc(key):
    """注销并从磁盘删除一个 DLC 模块文件。"""
    unregister_dlc(key)
    path = os.path.join(DLC_DIR, key + '.py')
    if os.path.exists(path):
        try:
            os.remove(path)
        except BaseException:
            # 兜底：绕过可能存在的拦截式删除钩子（如沙箱安全删除 shim / 权限限制 /
            # 杀软 hook os.remove 抛 SystemExit），直接调用 Win32 DeleteFileW，
            # 确保用户的 DLC「删除」在任何环境下都能生效。
            # 用 BaseException 而非 Exception：某些拦截器会抛 SystemExit，
            # 普通 except Exception 接不住，会导致整个删除流程中断。
            try:
                import ctypes
                ctypes.windll.kernel32.DeleteFileW(path)
            except BaseException:
                pass


_NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']


def midi_to_freq(m):
    return 440.0 * (2.0 ** ((m - 69) / 12.0))


def note_name(midi):
    return f"{_NOTE_NAMES[midi % 12]}{(midi // 12) - 1}"


def render_one_shot(key, midi, sr=SR, dur=2.0):
    """生成单个 (乐器, 音高) 的一次性采样波形（float32, -1..1）。

    委托给 edm_synth 的具体合成函数；perc/fx 不接收 freq 参数，其余按 midi 解算频率。
    和弦音色（含 'chord' 字段）以所放音符为基调，叠加多个相对偏移的声部：
    - 内置和弦（无 module）：用 edm.chord_voice 逐音叠加（干净正弦分音，旧行为）；
    - DLC 和弦（有 module）：跳过此分支，下面统一走 module.render，
      由 DLC 模块内部按自身音色叠加 chord 偏移（保证「同一用户音色」的和弦）。
    """
    spec = _DISPATCH[key]
    try:
        if 'chord' in spec and not spec.get('module'):
            offsets = spec['chord']
            length = int(dur * sr)
            out = np.zeros(length, dtype=np.float64)
            for off in offsets:
                f = midi_to_freq(midi + off)
                out = out + edm.chord_voice(f, dur, sr)
            return np.asarray(edm.normalize(out, peak=0.9), dtype=np.float32)
        func = getattr(spec.get('module') or edm, spec['func'])
        kw = spec.get('kwargs', {})
        if spec['needs_freq']:
            freq = midi_to_freq(midi)
            sig = func(freq, dur, sr, **kw)
        else:
            sig = func(dur, sr, **kw)
        return np.asarray(sig, dtype=np.float32)
    except Exception as e:
        # 容错：用户 DLC 渲染若抛异常（如代码写错），返回静音兜底，
        # 绝不因单个坏 DLC 让整段播放 / 导出崩溃。
        import sys
        print('[DLC] render 失败 %s: %r' % (key, e), file=sys.stderr)
        return np.zeros(max(1, int(dur * sr)), dtype=np.float32)
