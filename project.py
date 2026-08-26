"""数据模型：工程 / 音轨 / 音符，含 JSON 序列化（保存/打开）。"""
import json

BEATS_PER_BAR = 4  # 每小节拍数（4/4 拍，标准 FL Studio）；步→秒换算乘此因子

# 音轨配色预设（抖音主题 13 色）：新增音轨按顺序自增使用；
# 超出预设数量后改用最后的「天蓝色」作为后续音轨默认色。
TRACK_PALETTE = [
    ('抖音洋红', '#FE2C55'),
    ('蓝绿',     '#25F4EE'),
    ('白',       '#FFFFFF'),
    ('灰',       '#808080'),
    ('咖啡色',   '#6F4E37'),
    ('中黄',     '#FFD700'),
    ('橙色',     '#FFA500'),
    ('大红',     '#FF0000'),
    ('粉色',     '#FFC0CB'),
    ('紫色',     '#800080'),
    ('蓝紫色',   '#8A2BE2'),
    ('纯蓝色',   '#0000FF'),
    ('天蓝色',   '#87CEEB'),
]


class Note:
    def __init__(self, time, pitch, duration=4, velocity=0.85):
        self.time = int(time)            # 起始步（step）
        self.pitch = int(pitch)          # MIDI 音高
        self.duration = max(1, int(duration))  # 持续步数
        self.velocity = float(velocity)  # 音量 0..1

    def to_dict(self):
        return {'time': self.time, 'pitch': self.pitch,
                'duration': self.duration, 'velocity': self.velocity}

    @classmethod
    def from_dict(cls, d):
        return cls(d['time'], d['pitch'], d.get('duration', 4), d.get('velocity', 0.85))


class Track:
    def __init__(self, name, instrument, volume=0.85, muted=False, color=None):
        self.name = name
        self.instrument = instrument
        self.volume = float(volume)
        self.muted = bool(muted)
        # 默认色：未显式指定时取预设第一色（抖音洋红）；新增音轨由 add_track 按顺序分配。
        self.color = color if color else TRACK_PALETTE[0][1]
        self.notes = []

    def add_note(self, note):
        self.notes.append(note)

    def to_dict(self):
        return {'name': self.name, 'instrument': self.instrument,
                'volume': self.volume, 'muted': self.muted, 'color': self.color,
                'notes': [n.to_dict() for n in self.notes]}

    @classmethod
    def from_dict(cls, d):
        t = cls(d['name'], d['instrument'], d.get('volume', 0.85), d.get('muted', False),
                color=d.get('color', TRACK_PALETTE[0][1]))
        t.notes = [Note.from_dict(n) for n in d.get('notes', [])]
        return t


class Project:
    def __init__(self):
        self.bpm = 120
        self.steps_per_bar = 16      # 每小节 16 步（16 分音符网格）
        self.bars = 4
        self.master_volume = 0.9
        self.tracks = []

    @property
    def total_steps(self):
        return self.bars * self.steps_per_bar

    def add_track(self, instrument=None, color=None):
        idx = len(self.tracks) + 1
        if instrument is None:
            keys = synth_INSTRUMENTS()
            instrument = keys[len(self.tracks) % len(keys)]
        # 颜色自增：按顺序取预设色；超出预设范围后用最后的「天蓝色」作为默认。
        if color is None:
            color = TRACK_PALETTE[min(len(self.tracks), len(TRACK_PALETTE) - 1)][1]
        t = Track(f"音轨 {idx}", instrument, color=color)
        self.tracks.append(t)
        return t

    def to_dict(self):
        return {'bpm': self.bpm, 'steps_per_bar': self.steps_per_bar,
                'bars': self.bars, 'master_volume': self.master_volume,
                'tracks': [t.to_dict() for t in self.tracks]}

    def save(self, path):
        # .doukun 工作文件：在原有工程数据外包裹格式标记，便于识别与版本演进
        data = {'format': 'doukun', 'version': 1}
        data.update(self.to_dict())
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, path):
        with open(path, 'r', encoding='utf-8') as f:
            d = json.load(f)
        # 兼容旧版纯 .json 工程文件：去掉可能存在的格式标记
        d.pop('format', None)
        d.pop('version', None)
        p = cls()
        p.bpm = d.get('bpm', 120)
        p.steps_per_bar = d.get('steps_per_bar', 16)
        p.bars = d.get('bars', 4)
        p.master_volume = d.get('master_volume', 0.9)
        p.tracks = [Track.from_dict(t) for t in d.get('tracks', [])]
        return p


def synth_INSTRUMENTS():
    import synth
    return synth.INSTRUMENT_KEYS
