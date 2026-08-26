"""抖音风格设计令牌 (douyin-theme) + Tkinter 暗色主题。

色板来自抖音官方品牌规范：纯黑画布 + 洋红(主)/青绿(辅)双电压霓虹。
"""
import os
import sys
import tkinter as tk
from tkinter import ttk

if sys.platform == 'win32':
    import ctypes
    from ctypes import wintypes
else:
    ctypes = None

# ---- 核心品牌色 ----
BLACK = '#000000'          # 纯黑画布
CYAN = '#25F4EE'           # 青绿 (辅强调)
MAGENTA = '#FE2C55'        # 洋红 (主行动)
WHITE = '#FFFFFF'

# ---- 功能色 ----
SURFACE = '#161823'        # 卡片 / 容器
INPUT = '#23262F'          # 输入框 / 分隔线：偏冷的深蓝灰，与 SURFACE / 霓虹更和谐
TEXT_PRIMARY = '#FFFFFF'
TEXT_SECONDARY = '#E5E5E5'
TEXT_MUTED = '#8A8A8A'

# ---- 衍生态 ----
MAGENTA_HOVER = '#FF4775'
MAGENTA_PRESS = '#E0244A'
CYAN_DIM = '#1BBFBA'
GRID_LINE = '#1c1c22'
BAR_LINE = '#252530'     # 小节分割线：比黑底稍亮的深灰，低调不抢
KEY_LINE = '#16161c'
INPUT_DISABLED = '#1A1C24'   # 冻结（播放中）的输入框底色
SEP_LINE = '#3A3D47'         # 圆角数字框内 数字区/箭头区 分隔线

# ---- 字体（抖音风泛黑体）----
# 抖音官方字体（抖音美好体）为商用闭源，无法随包分发；在 Windows 上最贴近其观感的
# 「泛黑体 / 类黑体」即微软雅黑（Microsoft YaHei），全平台稳定可用、无需安装。
# 若日后要 100% 还原抖音体，可在此统一替换为打包的 TTF 家族名。
FONT_FAMILY = 'Microsoft YaHei'
FONT_UI = (FONT_FAMILY, 10)
FONT_UI_BOLD = (FONT_FAMILY, 10, 'bold')
FONT_DISPLAY = (FONT_FAMILY, 14, 'bold')

# 多音轨配色（按轨道序号轮换，均为高饱和霓虹，黑底上清晰）
NOTE_COLORS = [CYAN, MAGENTA, '#7C5CFF', '#FFB020', '#3DDC84', '#FF6B9D', '#4CC9F0']


def invert_color(hex_color):
    """返回给定 #RRGGBB 颜色的反色（各 RGB 分量取 255-原值）。

    用于「选中高亮音符 = 所在音轨颜色的反色」：让选中态与未选中态在任意音轨色下都形成强对比。
    """
    h = (hex_color or '#000000').lstrip('#')
    if len(h) == 3:
        h = ''.join(c * 2 for c in h)
    if len(h) != 6:
        return '#000000'
    try:
        r = 255 - int(h[0:2], 16)
        g = 255 - int(h[2:4], 16)
        b = 255 - int(h[4:6], 16)
    except ValueError:
        return '#000000'
    return '#%02X%02X%02X' % (r, g, b)


def contrast_text(hex_color):
    """根据背景色亮度返回可读的文字色（亮底用黑、暗底用白）。

    用于把文字画在任意音轨色块上时保证清晰（如「取色」按钮：白底上用黑字、暗底上用白字）。
    """
    h = (hex_color or '#000000').lstrip('#')
    if len(h) == 3:
        h = ''.join(c * 2 for c in h)
    if len(h) != 6:
        return '#FFFFFF'
    try:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        return '#FFFFFF'
    # 感知亮度（ITU-R BT.601）
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    return '#000000' if lum > 140 else '#FFFFFF'


def setup_theme(root):
    """配置全局 ttk 暗色主题。"""
    style = ttk.Style()
    try:
        style.theme_use('clam')
    except Exception:
        pass
    style.configure('.', background=BLACK, foreground=TEXT_SECONDARY,
                     font=FONT_UI, borderwidth=0)
    style.configure('TFrame', background=BLACK)
    style.configure('Surface.TFrame', background=SURFACE)
    style.configure('TLabel', background=BLACK, foreground=TEXT_SECONDARY)
    style.configure('Muted.TLabel', background=BLACK, foreground=TEXT_MUTED)
    style.configure('TButton', background=INPUT, foreground=WHITE, relief='flat',
                    borderwidth=0, padding=(10, 5))
    style.map('TButton', background=[('active', '#3A3A3A'), ('pressed', '#252525')])
    style.configure('Primary.TButton', background=MAGENTA, foreground=WHITE, relief='flat',
                    borderwidth=0, padding=(14, 6), font=FONT_UI_BOLD)
    style.map('Primary.TButton',
              background=[('active', MAGENTA_HOVER), ('pressed', MAGENTA_PRESS)])
    style.configure('Cyan.TButton', background=INPUT, foreground=CYAN, relief='flat',
                    borderwidth=0, padding=(10, 5))
    style.map('Cyan.TButton', background=[('active', '#26303A')])
    style.configure('TCombobox', fieldbackground=INPUT, background=INPUT,
                    foreground=WHITE, selectbackground=INPUT, selectforeground=WHITE,
                    borderwidth=0, arrowcolor=CYAN)
    style.map('TCombobox', fieldbackground=[('readonly', INPUT)],
              foreground=[('readonly', WHITE)])
    style.configure('TCheckbutton', background=SURFACE, foreground=TEXT_SECONDARY,
                    indicatorcolor=INPUT)
    style.map('TCheckbutton', indicatorcolor=[('selected', MAGENTA)])
    style.configure('TSpinbox', fieldbackground=INPUT, background=INPUT,
                    foreground=WHITE, borderwidth=0)
    style.configure('TScale', background=BLACK, troughcolor=INPUT, borderwidth=0)
    style.configure('TNotebook', background=BLACK, borderwidth=0)
    style.configure('TNotebook.Tab', background=SURFACE, foreground=TEXT_MUTED,
                    padding=(10, 4))
    style.map('TNotebook.Tab', background=[('selected', MAGENTA)],
              foreground=[('selected', WHITE)])
    style.configure('TSeparator', background=INPUT)
    style.configure('TScrollbar', background=INPUT, troughcolor=BLACK,
                    borderwidth=0, width=16)
    style.map('TScrollbar', background=[('active', CYAN_DIM)])
    root.configure(bg=BLACK)
    try:
        root.option_add('*TCombobox*Listbox.background', INPUT)
        root.option_add('*TCombobox*Listbox.foreground', WHITE)
        root.option_add('*TCombobox*Listbox.selectBackground', MAGENTA)
        root.option_add('*TCombobox*Listbox.font', FONT_UI)
    except Exception:
        pass


def set_dark_titlebar(root):
    """将 Windows 窗口标题栏/边框设为深色，匹配抖音纯黑主题。

    兼容 Win10 1809+（沉浸式深色模式）和 Win11（标题栏/边框自定义颜色）。
    Tkinter 本身无法控制非客户区，这里通过 dwmapi 调用实现。
    """
    if sys.platform != 'win32' or ctypes is None:
        return
    try:
        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        if not hwnd:
            return
        dwmapi = ctypes.windll.dwmapi

        # Win10 1809+ / Win11: 启用沉浸式深色模式
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        value = ctypes.c_int(1)
        dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE,
                                     ctypes.byref(value), ctypes.sizeof(value))

        # Win11 独有：直接指定标题栏和边框颜色为纯黑
        if sys.getwindowsversion().build >= 22000:
            DWMWA_CAPTION_COLOR = 35
            DWMWA_BORDER_COLOR = 36
            black = ctypes.c_int(0x000000)
            dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_CAPTION_COLOR,
                                         ctypes.byref(black), ctypes.sizeof(black))
            dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_BORDER_COLOR,
                                         ctypes.byref(black), ctypes.sizeof(black))
    except Exception:
        pass


class RoundedButton(tk.Canvas):
    """自绘圆角按钮，适配抖音主题。

    用法与 ttk.Button 类似：
        RoundedButton(parent, text='播放', style='primary', command=on_play)
    style: 'primary'(洋红) / 'cyan'(青绿描边) / 'default'(深灰)
    """
    HEIGHT = 32
    RADIUS = 8

    def __init__(self, parent, text='', style='default', command=None,
                 width=None, height=HEIGHT, radius=RADIUS, font=None, **kw):
        self._style = style
        self._command = command
        self._text = text
        self._radius = radius
        self._font = font
        self._hover = False
        self._pressed = False

        pad_x = max(72, len(text) * 12 + 24) if width is None else width
        super().__init__(parent, width=pad_x, height=height,
                         bg=kw.pop('bg', BLACK), highlightthickness=0, **kw)

        self.bind('<Enter>', lambda e: self._set_hover(True))
        self.bind('<Leave>', lambda e: self._set_hover(False))
        self.bind('<Button-1>', lambda e: self._set_pressed(True))
        self.bind('<ButtonRelease-1>', self._on_release)
        self._draw()

    def _palette(self):
        if self._style == 'primary':
            base = MAGENTA
            hover = MAGENTA_HOVER
            press = MAGENTA_PRESS
            fg = WHITE
        elif self._style == 'cyan':
            base = INPUT
            hover = '#26303A'
            press = '#1C242C'
            fg = CYAN
        else:
            base = INPUT
            hover = '#3A3A3A'
            press = '#252525'
            fg = WHITE
        return base, hover, press, fg

    def _set_hover(self, value):
        self._hover = value
        self._draw()

    def _set_pressed(self, value):
        self._pressed = value
        self._draw()

    def _on_release(self, _):
        self._set_pressed(False)
        if self._command:
            self._command()

    def set_text(self, text):
        self._text = text
        self._draw()

    def _draw(self):
        self.delete('all')
        w, h = int(self['width']), int(self['height'])
        r = self._radius
        base, hover, press, fg = self._palette()
        fill = press if self._pressed else (hover if self._hover else base)

        self._round_rect(0, 0, w, h, r, fill=fill, outline='')
        _f = self._font or (FONT_UI_BOLD if self._style == 'primary' else FONT_UI)
        self.create_text(w // 2, h // 2, text=self._text, fill=fg, font=_f)

    def _round_rect(self, x1, y1, x2, y2, radius, **kwargs):
        points = [
            x1 + radius, y1,
            x2 - radius, y1,
            x2, y1,
            x2, y1 + radius,
            x2, y2 - radius,
            x2, y2,
            x2 - radius, y2,
            x1 + radius, y2,
            x1, y2,
            x1, y2 - radius,
            x1, y1 + radius,
            x1, y1,
        ]
        return self.create_polygon(points, smooth=True, **kwargs)


class RoundedFrame(tk.Canvas):
    """自绘圆角容器，作为 Surface 卡片的背景。

    内部放置子控件时，建议用 inner 作为实际 parent：
        rf = RoundedFrame(parent)
        rf.pack(...)
        ttk.Label(rf.inner, ...).pack(...)
    """
    RADIUS = 12

    def __init__(self, parent, bg=SURFACE, radius=RADIUS, padding=8, **kw):
        self._radius = radius
        self._padding = padding
        self._bg = bg
        super().__init__(parent, bg=kw.pop('canvas_bg', BLACK),
                         highlightthickness=0, **kw)
        self.inner = tk.Frame(self, bg=bg)
        self._lw = None
        self._lh = None
        self.bind('<Configure>', lambda e: self._draw())
        self._draw()

    def _draw(self):
        w = self.winfo_width()
        h = self.winfo_height()
        if w == self._lw and h == self._lh:
            return
        self._lw, self._lh = w, h
        self.delete('all')
        r = self._radius
        if w < 2 * r or h < 2 * r:
            return
        self._round_rect(0, 0, w, h, r, fill=self._bg, outline='')
        p = self._padding
        self.inner.place(x=p, y=p, width=max(1, w - 2 * p), height=max(1, h - 2 * p))

    def _round_rect(self, x1, y1, x2, y2, radius, **kwargs):
        points = [
            x1 + radius, y1, x2 - radius, y1, x2, y1,
            x2, y1 + radius, x2, y2 - radius, x2, y2,
            x2 - radius, y2, x1 + radius, y2, x1, y2,
            x1, y2 - radius, x1, y1 + radius, x1, y1,
        ]
        return self.create_polygon(points, smooth=True, **kwargs)


class RoundedSpinbox(tk.Canvas):
    """自绘圆角数字输入框（抖音风），替代 ttk.Spinbox。

    与 RoundedButton / RoundedFrame 同语言（圆角矩形 + 霓虹点缀）：
    - 右侧上/下箭头增减；editable=True 时点数字区可直接键入（回车/失焦提交，Esc 取消）；
    - 绑定 textvariable，外部 .set() 自动同步显示；
    - set_state('disabled'/'normal') 用于播放时冻结；configure(to=...) 兼容旧调用；
    - 改动只更新数值变量并回调 command，**不触发任何网格/音符重绘**，故快速、无卡顿、鲁棒。
    """
    HEIGHT = 36
    RADIUS = 10

    def __init__(self, parent, from_=0, to=100, textvariable=None, command=None,
                 editable=True, width_chars=5, step=1, font=None, **kw):
        self._from = from_
        self._to = to
        self._textvariable = textvariable
        self._command = command
        self._editable = editable
        self._step = step
        self._font = font or FONT_UI
        self._width_chars = max(2, int(width_chars))
        self._state = 'normal'
        self._hover_up = False
        self._hover_down = False
        self._entry = None

        try:
            _sz = int(self._font[1]) if isinstance(self._font, (tuple, list)) and len(self._font) > 1 else 10
        except Exception:
            _sz = 10
        _char_w = max(8, int(_sz * 0.62))
        self._arrow_w = 24
        self._num_w = self._width_chars * _char_w
        _w = self._num_w + self._arrow_w + 14

        super().__init__(parent, width=_w, height=self.HEIGHT,
                         bg=kw.pop('bg', BLACK), highlightthickness=0, **kw)
        if self._textvariable is not None:
            self._textvariable.trace_add('write', lambda *a: self._draw())
        self.bind('<Button-1>', self._on_press)
        self.bind('<Motion>', self._on_motion)
        self.bind('<Leave>', self._on_leave)
        self._draw()

    # ---- 取值 / 赋值 ----
    def _get_value(self):
        if self._textvariable is not None:
            try:
                return int(self._textvariable.get())
            except (ValueError, TypeError, tk.TclError):
                return self._from
        return self._from

    def _set_value(self, v):
        if self._textvariable is not None:
            self._textvariable.set(int(v))

    # ---- 交互 ----
    def _on_press(self, event):
        if self._state == 'disabled':
            return
        w = int(self['width'])
        ax = w - self._arrow_w
        if event.x >= ax:
            if event.y < int(self['height']) // 2:
                self._step_by(self._step)
            else:
                self._step_by(-self._step)
        elif self._editable and self._entry is None:
            self._begin_edit()

    def _on_motion(self, event):
        if self._state == 'disabled' or self._entry is not None:
            return
        w = int(self['width'])
        ax = w - self._arrow_w
        if event.x >= ax:
            up = event.y < int(self['height']) // 2
            down = not up
            if self._hover_up != up or self._hover_down != down:
                self._hover_up, self._hover_down = up, down
                self._draw()
        else:
            if self._hover_up or self._hover_down:
                self._hover_up = self._hover_down = False
                self._draw()

    def _on_leave(self, _=None):
        if self._hover_up or self._hover_down:
            self._hover_up = self._hover_down = False
            self._draw()

    def _step_by(self, delta):
        if self._state == 'disabled':
            return
        cur = self._get_value()
        new = max(self._from, min(self._to, cur + delta))
        if new == cur:
            return
        self._set_value(new)          # trace -> _draw
        if self._command:
            self._command()

    # ---- 编辑（点数字区键入）----
    def _begin_edit(self):
        if self._entry is not None:
            return
        self._entry = tk.Entry(self, font=self._font, bg=INPUT, fg=WHITE,
                               bd=0, justify='center', highlightthickness=0,
                               insertbackground=CYAN)
        self._entry.insert(0, str(self._get_value()))
        self._entry.place(x=6, y=4, width=self._num_w + 6, height=self.HEIGHT - 8)
        self._entry.focus_set()
        self._entry.select_range(0, 'end')
        self._entry.bind('<Return>', self._commit_edit)
        self._entry.bind('<FocusOut>', self._commit_edit)
        self._entry.bind('<Escape>', self._cancel_edit)

    def _commit_edit(self, _=None):
        if self._entry is None:
            return
        try:
            v = int(self._entry.get())
        except ValueError:
            v = self._get_value()
        v = max(self._from, min(self._to, v))
        self._destroy_entry()
        if v != self._get_value():
            self._set_value(v)
        if self._command:
            self._command()

    def _cancel_edit(self, _=None):
        self._destroy_entry()

    def _destroy_entry(self):
        if self._entry is not None:
            try:
                self._entry.destroy()
            except Exception:
                pass
            self._entry = None
        self._draw()

    # ---- 状态 / 兼容 ----
    def set_state(self, state):
        if state == self._state:
            return
        self._state = state
        if state == 'disabled' and self._entry is not None:
            self._destroy_entry()
        else:
            self._draw()

    def configure(self, **kw):
        redraw = False
        if 'to' in kw:
            self._to = kw.pop('to')
            redraw = True
        if 'from' in kw:
            self._from = kw.pop('from')
            redraw = True
        if 'state' in kw:
            self.set_state(kw.pop('state'))
        if kw:
            super().configure(**kw)
        elif redraw:
            self._draw()

    # ---- 绘制 ----
    def _draw(self):
        self.delete('all')
        w, h = int(self['width']), int(self['height'])
        r = self.RADIUS
        disabled = (self._state == 'disabled')
        fill = INPUT_DISABLED if disabled else INPUT
        self._round_rect(0, 0, w, h, r, fill=fill, outline='')
        if self._entry is None:
            fg = TEXT_MUTED if disabled else WHITE
            self.create_text(9, h // 2, text=str(self._get_value()), anchor='w',
                             fill=fg, font=self._font)
        ax = w - self._arrow_w
        self.create_line(ax, 7, ax, h - 7, fill=('#000000' if disabled else SEP_LINE), width=1)
        cx = (ax + w) // 2
        up_col = TEXT_MUTED if disabled else (CYAN if self._hover_up else TEXT_SECONDARY)
        down_col = TEXT_MUTED if disabled else (CYAN if self._hover_down else TEXT_SECONDARY)
        self.create_polygon(ax + 5, int(h * 0.44), w - 5, int(h * 0.44), cx, int(h * 0.28),
                            fill=up_col, outline='')
        self.create_polygon(ax + 5, int(h * 0.56), w - 5, int(h * 0.56), cx, int(h * 0.72),
                            fill=down_col, outline='')

    def _round_rect(self, x1, y1, x2, y2, radius, **kwargs):
        points = [
            x1 + radius, y1, x2 - radius, y1, x2, y1,
            x2, y1 + radius, x2, y2 - radius, x2, y2,
            x2 - radius, y2, x1 + radius, y2, x1, y2,
            x1, y2 - radius, x1, y1 + radius, x1, y1,
        ]
        return self.create_polygon(points, smooth=True, **kwargs)



def setup_custom_titlebar(root, app_ref=None, title='DouKunStudio'):
    """隐藏原生标题栏，替换为抖音故障风自定义标题栏。

    标题栏左侧显示白色“DouKunStudio”文字 + 青色/洋红色偏移重影，
    右侧提供最小化、最大化/还原、关闭按钮，并支持拖拽移动窗口。
    该函数同时负责把窗口图标重新设置到 HWND，尽量修复任务栏图标空白。
    """
    if sys.platform != 'win32':
        return None
    try:
        root.overrideredirect(True)
    except Exception:
        return None

    titlebar = tk.Frame(root, bg=BLACK, height=34)
    titlebar.pack(side=tk.TOP, fill=tk.X)
    titlebar.pack_propagate(False)

    # ---- 左侧抖音故障风 Logo ----
    logo_w = 260
    canvas = tk.Canvas(titlebar, width=logo_w, height=34, bg=BLACK,
                       highlightthickness=0, cursor='size')
    canvas.pack(side=tk.LEFT, padx=(10, 0))

    font = (FONT_FAMILY, 15, 'bold')
    x = 0
    y = 18
    # 先画两层偏移重影，再画白色主体
    canvas.create_text(x - 2, y, text=title, font=font, fill=CYAN,
                       anchor='w', tags='title')
    canvas.create_text(x + 2, y, text=title, font=font, fill=MAGENTA,
                       anchor='w', tags='title')
    canvas.create_text(x, y, text=title, font=font, fill=WHITE,
                       anchor='w', tags='title')

    # ---- 右侧窗口控制按钮 ----
    btn_frame = tk.Frame(titlebar, bg=BLACK)
    btn_frame.pack(side=tk.RIGHT, fill=tk.Y)

    def _make_btn(text, hover_bg, cmd):
        c = tk.Canvas(btn_frame, width=44, height=34, bg=BLACK,
                      highlightthickness=0)
        c.pack(side=tk.LEFT)
        c.create_text(22, 17, text=text, font=(FONT_FAMILY, 12, 'bold'),
                      fill=WHITE, anchor='c')

        def _on_enter(e, c=c, bg=hover_bg):
            c.configure(bg=bg)

        def _on_leave(e, c=c):
            c.configure(bg=BLACK)

        c.bind('<Enter>', _on_enter)
        c.bind('<Leave>', _on_leave)
        c.bind('<Button-1>', lambda e: cmd())
        return c

    def _minimize():
        try:
            root.iconify()
        except Exception:
            pass

    def _toggle_maximize():
        try:
            if root.state() == 'zoomed':
                root.state('normal')
            else:
                root.state('zoomed')
        except Exception:
            pass

    def _close():
        if app_ref is not None and hasattr(app_ref, '_on_close'):
            try:
                app_ref._on_close()
            except Exception:
                root.destroy()
        else:
            root.destroy()

    _make_btn('_', '#2A2D35', _minimize)
    _make_btn('□', '#2A2D35', _toggle_maximize)
    _make_btn('×', '#E81123', _close)

    # ---- 拖拽移动 ----
    drag = {'x': 0, 'y': 0, 'ox': 0, 'oy': 0, 'active': False}

    def _start_drag(event):
        drag['x'] = event.x_root
        drag['y'] = event.y_root
        drag['ox'] = root.winfo_x()
        drag['oy'] = root.winfo_y()
        drag['active'] = True

    def _do_drag(event):
        if not drag['active']:
            return
        dx = event.x_root - drag['x']
        dy = event.y_root - drag['y']
        root.geometry(f'+{drag["ox"] + dx}+{drag["oy"] + dy}')

    def _stop_drag(event=None):
        drag['active'] = False

    def _on_double(event):
        _toggle_maximize()

    for w in (titlebar, canvas):
        w.bind('<Button-1>', _start_drag)
        w.bind('<B1-Motion>', _do_drag)
        w.bind('<ButtonRelease-1>', _stop_drag)
        w.bind('<Double-Button-1>', _on_double)

    # ---- 任务栏图标兜底：再次通过 HWND 设置 exe 图标 ----
    try:
        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        if hwnd:
            # WM_SETICON: ICON_BIG=1, ICON_SMALL=0
            WM_SETICON = 0x0080
            ICON_BIG = 1
            ICON_SMALL = 0
            # 尝试从 assets/icon.ico 加载图标句柄
            ico_path = getattr(sys, '_MEIPASS', '')
            if not ico_path:
                ico_path = os.path.dirname(os.path.abspath(__file__))
            ico_file = os.path.join(ico_path, 'assets', 'icon.ico')
            if os.path.exists(ico_file):
                hicon = ctypes.windll.user32.LoadImageW(
                    None, ico_file, 1,  # IMAGE_ICON=1
                    0, 0, 0x00000010 | 0x00002000)  # LR_LOADFROMFILE | LR_DEFAULTSIZE
                if hicon:
                    ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, hicon)
                    ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hicon)
    except Exception:
        pass

    return titlebar
