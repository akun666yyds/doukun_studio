"""钢琴卷帘编辑器 + 多音轨并行概览。

PianoRoll: 选中音轨的逐音符编辑（点击空白处加音符、拖动移动、右边缘拖拽改音长、
            右键删除、选中后滚轮调音量）。3 个八度音高 × 时间步网格。
TrackLanes: 顶部概览，所有音轨并行显示，点击切换选中（满足「多行音轨可以并行」）。
"""
import tkinter as tk
import synth
import project
import audio_engine as ae
from theme import (BLACK, CYAN, MAGENTA, WHITE, SURFACE, INPUT, TEXT_SECONDARY,
                   TEXT_MUTED, GRID_LINE, BAR_LINE, invert_color)

KEY_W = 56
KEY_H = 16
BEAT_W = 26          # 100% 缩放时的每拍像素宽（基准）
RULER_H = 22

# 横向缩放档位：0~100% 用 10% 分度，100~500% 用 50% 分度
_ZOOM_LEVELS = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100,
                150, 200, 250, 300, 350, 400, 450, 500]


def _next_zoom(current, direction):
    """按档位表取下一档。direction>0 放大(更大百分比)，<0 缩小。"""
    if direction > 0:
        for z in _ZOOM_LEVELS:
            if z > current + 1e-6:
                return z
        return _ZOOM_LEVELS[-1]
    for z in reversed(_ZOOM_LEVELS):
        if z < current - 1e-6:
            return z
    return _ZOOM_LEVELS[0]


_BLACK_SET = {1, 3, 6, 8, 10}


def is_black(midi):
    return (midi % 12) in _BLACK_SET


class KeyColumn(tk.Canvas):
    """冻结的音高列（不随横向时间轴滚动）。

    始终固定在钢琴卷帘最左侧：白键浅底深字、黑键深底**白字**，便于左右浏览时序时
    随时读到一个音高的位置。纵向滚动与 PianoRoll 同步（共用相同 scrollregion 高度）。
    """

    def __init__(self, parent, project, app, **kw):
        super().__init__(parent, bg=BLACK, width=KEY_W, highlightthickness=0, **kw)
        self.app = app
        self.project = project
        self.bind('<Button-1>', self.on_press)
        self.bind('<B1-Motion>', self.on_drag)
        self.bind('<ButtonRelease-1>', self.on_release)
        self.redraw()

    def y_to_midi(self, y):
        """画布 y -> MIDI 音高（点中键条区域才返回，否则 None）。"""
        idx = int((y - RULER_H) // KEY_H)
        midi = synth.MIDI_HIGH - idx
        if midi < synth.MIDI_LOW or midi > synth.MIDI_HIGH:
            return None
        return midi

    def on_press(self, ev):
        if self.app is None:
            return
        midi = self.y_to_midi(self.canvasy(ev.y))
        if midi is None:
            return
        track = getattr(self.app, 'selected_track', None)
        if track is None:
            return
        # 音标发声：音色 = 当前音轨乐器，音调 = 所点音高，响度恒为 100%
        ae.preview_note(track.instrument, midi, 1.0)

    def on_drag(self, ev):
        midi = self.y_to_midi(self.canvasy(ev.y))
        if midi is None:
            return
        track = getattr(self.app, 'selected_track', None)
        if track is None:
            return
        # 按住拖动：音高变了就重新触发，形成滑音试听（FL 风）
        ae.preview_set_pitch(track.instrument, midi, 1.0)

    def on_release(self, ev):
        ae.preview_stop()

    def redraw(self):
        self.delete('all')
        h = (synth.MIDI_HIGH - synth.MIDI_LOW + 1) * KEY_H + RULER_H + 40
        self.configure(scrollregion=(0, 0, KEY_W, h))
        # 顶部标尺条（与 PianoRoll 的 RULER_H 对齐）
        self.create_rectangle(0, 0, KEY_W, RULER_H, fill=SURFACE, outline='')
        for midi in range(synth.MIDI_LOW, synth.MIDI_HIGH + 1):
            y = RULER_H + (synth.MIDI_HIGH - midi) * KEY_H
            black = is_black(midi)
            key_color = '#0d0d12' if black else '#f2f2f5'
            self.create_rectangle(0, y, KEY_W, y + KEY_H, fill=key_color, outline='#000')
            # 黑键用白色字母符号标出，白键用深色字
            self.create_text(6, y + KEY_H / 2, text=synth.note_name(midi), anchor='w',
                             fill=(WHITE if black else '#222'),
                             font=('Microsoft YaHei', 8))
        # 右侧分隔线
        self.create_line(KEY_W - 1, 0, KEY_W - 1, h, fill=INPUT, width=1)

    def set_yview(self, fraction):
        self.yview_moveto(float(fraction))

    def set_project(self, project):
        """打开/新建工作文件后同步底层工程引用（本类仅存储，并不依赖其绘制）。"""
        self.project = project



class PianoRoll(tk.Canvas):
    def __init__(self, parent, project, app, **kw):
        super().__init__(parent, bg=BLACK, highlightthickness=0, **kw)
        self.project = project
        self.app = app
        self.track = None
        self.selected_note = None        # 主选中音符（供编辑器面板显示/编辑）
        self.selected_notes = set()      # 全部选中音符（框选/同步移动用）
        self.drag = None
        self._last_preview_midi = None   # 拖拽变调时记录上次试听音高，避免每像素重触发
        self.playhead_step = 0
        self.zoom = 100.0                 # 当前横向缩放百分比（默认 100%）
        self.beat_w = BEAT_W              # 当前每拍像素宽 = BEAT_W * zoom / 100
        self.hscroll = None               # 由 main.py 注入，用于缩放后同步滚条
        self._content_w = 0               # 静态层尺寸缓存（供 update_playhead 复用）
        self._content_h = 0
        self._note_items = {}              # note -> [画布item id(s)]，拖拽时只移动单个音符(O(1))
        self._sx = None                    # 鼠标相对画布控件的屏幕像素 x（用于准心，缩放/滚动后仍精确）
        self._sy = None
        self._drag_undone = False          # 本次拖拽是否已压入撤销快照（避免每像素重复压栈）
        self._box_start = None             # 右键框选起点（画布坐标）
        self._box_rect = None
        self._grid_drawn = False           # 静态网格是否已绘制（用于切换音轨时跳过重画）
        self.bind('<Button-1>', self.on_down)
        self.bind('<B1-Motion>', self.on_drag)
        self.bind('<ButtonRelease-1>', self.on_up)
        self.bind('<Button-3>', self.on_right_down)
        self.bind('<B3-Motion>', self.on_right_drag)
        self.bind('<ButtonRelease-3>', self.on_right_up)
        self.bind('<Motion>', self.on_motion)
        self.bind('<Leave>', self.on_leave)
        self.bind('<MouseWheel>', self.on_wheel)
        self.bind('<Shift-MouseWheel>', self._on_hscroll)
        # 编辑区光标变为十字准心（系统指针永远精确位于鼠标，零偏移）
        self.configure(cursor='cross', xscrollincrement=self.beat_w, yscrollincrement=KEY_H)

    # --- 坐标换算 ---
    def grid_width(self):
        return self.project.total_steps * self.beat_w

    def grid_height(self):
        return (synth.MIDI_HIGH - synth.MIDI_LOW + 1) * KEY_H

    def time_to_x(self, step):
        return step * self.beat_w

    def x_to_time(self, x):
        return max(0, int(round(x / self.beat_w)))

    def y_to_pitch(self, y):
        idx = int((y - RULER_H) / KEY_H)
        return max(synth.MIDI_LOW, min(synth.MIDI_HIGH, synth.MIDI_HIGH - idx))

    def pitch_to_y(self, midi):
        return RULER_H + (synth.MIDI_HIGH - midi) * KEY_H

    # --- 公共接口 ---
    def set_track(self, track):
        self.track = track
        self.selected_note = None
        self.selected_notes = set()
        # 切换音轨：网格仅取决于工程几何（小节/步数/缩放），与所选音轨无关，
        # 因此复用已绘制的静态网格，只重建音符层 + 播放头 + 同步滚条/准心，
        # 避免每次点击切换音轨都重画全部网格线（密集操作下的卡顿根因之一）。
        if getattr(self, '_grid_drawn', False):
            self.redraw_notes()
            self.update_playhead()
            self._sync_hscroll()
            self._update_crosshair()
        else:
            self.redraw()   # 首次：网格尚未绘制，完整绘制

    def set_project(self, project):
        """切换底层工程对象（打开/新建工作文件后必须调用）。

        PianoRoll 在构造时捕获了 project 的引用；主程序若替换了 self.project，
        这里必须把视图也指到新对象，并清空与旧工程绑定的视图状态（选中、拖拽、
        音符缓存、框选），否则网格/音符/小节数会永远停留在旧工程（「死了」）。
        """
        self.project = project
        self.track = None
        self.selected_note = None
        self.selected_notes = set()
        self.drag = None
        self._note_items = {}
        self._box_start = None
        self._box_rect = None
        self._last_preview_midi = None
        self.playhead_step = 0
        self.redraw()

    def redraw(self):
        """完整重绘（仅缩放 / 切换音轨 / 加载时调用）：重建静态网格 + 音符 + 播放头。

        高频操作请勿调用本方法：
        - 拖拽 / 增删 / 选中变化 -> 调用 redraw_notes()（只重建单轨音符层）
        - 播放头逐帧移动 / seek -> 调用 update_playhead()（只重画一条蓝线）
        这样可避免每次鼠标移动或每帧播放都重建几百条网格线并连带重绘头部概览。
        """
        self._draw_grid()
        self.redraw_notes()
        self.update_playhead()
        # 缩放/换轨改变了 scrollregion 与视图：同步横向滚条 + 镜像头部概览
        self._sync_hscroll()
        # 准心随缩放/滚动重算（基于屏幕坐标 _sx/_sy，自动跟随视图变化，零偏移）
        self._update_crosshair()

    def _draw_grid(self):
        """静态层：时间竖线 + 音高横线 + 拍号标尺。仅在缩放/换轨/步数变化时重建。"""
        self.delete('grid')
        if self.track is None:
            self.create_text(220, 60, text='← 在左侧选择一条音轨以编辑', fill=TEXT_MUTED,
                             font=('Microsoft YaHei', 12), tags=('grid',))
            self.configure(scrollregion=(0, 0, 1, 1))
            self._content_w = self._content_h = 0
            return
        w = self.grid_width() + 60
        h = self.grid_height() + RULER_H + 40
        total = self.project.total_steps
        # 时间竖线（小节线用淡灰，节拍线用更暗网格线）
        for step in range(total + 1):
            x = self.time_to_x(step)
            bar = step % self.project.steps_per_bar == 0
            self.create_line(x, RULER_H, x, h,
                             fill=(BAR_LINE if bar else GRID_LINE),
                             width=(2 if bar else 1), tags=('grid',))
        # 音高横线（首列音标由左侧冻结 KeyColumn 负责，这里只画网格）
        for midi in range(synth.MIDI_LOW, synth.MIDI_HIGH + 1):
            y = self.pitch_to_y(midi)
            black = is_black(midi)
            self.create_line(0, y, w, y, fill=('#101015' if black else '#1a1a20'), tags=('grid',))
        # 拍号标尺
        for step in range(total + 1):
            if step % self.project.steps_per_bar == 0:
                x = self.time_to_x(step)
                self.create_rectangle(0, 0, x, RULER_H, fill=SURFACE, outline='', tags=('grid',))
                self.create_text(x + 4, RULER_H / 2, text=f"{step // self.project.steps_per_bar + 1}",
                                 anchor='w', fill=TEXT_SECONDARY, font=('Microsoft YaHei', 9), tags=('grid',))
        self._content_w, self._content_h = w, h
        self.configure(scrollregion=(0, 0, w, h))
        self._grid_drawn = True            # 静态层已绘制，后续切换音轨可复用

    def redraw_notes(self):
        """动态层：音符（含选中高亮）。拖拽 / 增删 / 选中变化时调用，不触碰网格与播放头。"""
        self.delete('notes')
        self._note_items = {}
        if self.track is None:
            return
        color = self.track.color
        for note in self.track.notes:
            self._note_items[note] = self._draw_note(note, color)
        # 重画音符后，确保蓝色播放头仍位于最上层（否则会被新音符覆盖）
        self.tag_raise('playhead')

    def update_playhead(self):
        """仅重绘蓝色播放头。逐帧播放 / seek 时调用，开销极小（删一条线、画一条线）。"""
        self.delete('playhead')
        if self.track is None or not self._content_h:
            return
        step = max(0, min(self.playhead_step, self.project.total_steps))
        px = self.time_to_x(step)
        self.create_line(px, 0, px, self._content_h, fill=CYAN, width=2, tags=('playhead',))

    def _draw_note(self, note, color):
        x = self.time_to_x(note.time)
        y = self.pitch_to_y(note.pitch)
        w = note.duration * self.beat_w
        selected = note in self.selected_notes
        # 选中态：填充为「音轨色反色」形成强对比；未选中：直接用音轨色。
        fill = invert_color(color) if selected else color
        ids = [self.create_rectangle(x, y + 1, x + w, y + KEY_H - 1, fill=fill, outline=BLACK, width=1, tags=('notes',))]
        if selected:
            ids.append(self.create_rectangle(x, y + 1, x + w, y + KEY_H - 1, outline=WHITE, width=2, tags=('notes',)))
        return ids

    def _move_note_item(self, note):
        """拖拽中只移动单个音符的画布 item（O(1)），不重建全部音符层，消除实体吞吐卡顿。

        注意：不再对每个被移动音符调用 tag_raise('playhead')（整组逐个 raise 是卡顿根因），
        改为一次拖拽只在末尾统一 raise 一次（见 on_drag 收尾）。
        """
        ids = self._note_items.get(note)
        if not ids:
            self.redraw_notes()   # 兜底：无缓存 id 时退回整层重绘
            return
        x = self.time_to_x(note.time)
        y = self.pitch_to_y(note.pitch)
        w = note.duration * self.beat_w
        self.coords(ids[0], x, y + 1, x + w, y + KEY_H - 1)
        if len(ids) > 1:
            self.coords(ids[1], x, y + 1, x + w, y + KEY_H - 1)

    # --- 交互 ---
    def _hit_note(self, x, y):
        for note in self.track.notes:
            nx = self.time_to_x(note.time)
            ny = self.pitch_to_y(note.pitch)
            nw = note.duration * self.beat_w
            if nx <= x <= nx + nw and ny <= y <= ny + KEY_H:
                return note
        return None

    def on_down(self, ev):
        self.focus_set()
        self.delete('crosshair')    # 拖动开始时收起准心，避免拖动期间残留/重复重绘
        self._drag_undone = False
        x, y = self.canvasx(ev.x), self.canvasy(ev.y)
        # 拍号标尺区（时间轴头部）按住拖动：控制播放头，不与音符编辑冲突
        if y < RULER_H:
            self.drag = ('seek',)
            self._seek(x)
            return
        hit = self._hit_note(x, y)
        if hit:
            nx = self.time_to_x(hit.time) + hit.duration * self.beat_w
            if x > nx - 6:
                # 右边缘拖拽改音长：对该音符单独操作
                self._select_single(hit)
                self.drag = ('resize', hit)
            elif hit in self.selected_notes and len(self.selected_notes) > 1:
                # 命中已选中的音符（且处于多选集合）→ 同步移动整个选区
                self._begin_movemulti(x, y, hit)
            else:
                # 命中未选中的音符 → 单选它并移动
                self._select_single(hit)
                self.drag = ('move', hit, x - self.time_to_x(hit.time), y - self.pitch_to_y(hit.pitch))
            # 现有音符：左键按住即发声（音色=当前音轨、音调/响度=该音符），松开停止
            ae.preview_note(self.track.instrument, hit.pitch, hit.velocity)
            self._last_preview_midi = hit.pitch
            self.redraw_notes()
            return
        # 空白处：进入框选（marquee）。拖动=框选音符；纯点击=取消选择（有选区时）
        # 或新建一个音符（无选区时，保留原创建能力）。
        self.drag = ('marquee',)
        self._marquee_start = (x, y)
        self._marquee_moved = False
        self._marquee_rect = None

    # --- 选择 / 移动辅助 ---
    def _select_single(self, note):
        self.selected_note = note
        self.selected_notes = {note}
        self.app.on_note_selected(note)

    def _begin_movemulti(self, x, y, lead):
        self._drag_notes = [(n, n.time, n.pitch) for n in self.selected_notes]
        self._drag_start = (x, y)
        self.drag = ('movemulti', lead)

    def _clear_selection(self):
        self.selected_note = None
        self.selected_notes = set()
        self.redraw_notes()
        self.app.on_note_selected(None)

    def _create_note_at(self, x, y):
        """空白单击（且无选区）时新建一个音符，保留原创建能力。

        注意：新置音符【不自动选中】，避免每次新置都要多点两次才能继续放置下一个音符。
        """
        step = self.x_to_time(x)
        pitch = self.y_to_pitch(y)
        dur = max(1, self.project.steps_per_bar // 4)
        self.app.push_undo()
        note = project.Note(step, pitch, dur, 0.85)
        self.track.add_note(note)
        self.redraw_notes()
        self.app._schedule_prepare()
        self.app.set_status(f"已添加音符 {synth.note_name(pitch)} @ 第 {step + 1} 步")

    def _draw_marquee(self, box):
        self.delete('marquee')
        x1, y1, x2, y2 = box
        # 左键框选：蓝绿实心 + 半透明（stipple 模拟 alpha），实色边框，去掉空心虚线。
        self.create_rectangle(x1, y1, x2, y2, outline=CYAN, width=2,
                              fill=CYAN, stipple='gray50', tags=('marquee',))

    def on_drag(self, ev):
        if not self.drag:
            return
        x, y = self.canvasx(ev.x), self.canvasy(ev.y)
        mode = self.drag[0]
        if mode == 'seek':
            if y < RULER_H * 2:
                self._seek(x)
            return
        if mode == 'box':
            # 右键框选由 on_right_drag 处理；按住右键同时又触发左键拖动(<B1-Motion>)时
            # self.drag 仍为 ('box',) 单元素元组，此处直接忽略，避免 drag[1] 越界。
            return
        if mode == 'marquee':
            sx, sy = self._marquee_start
            if abs(x - sx) > 3 or abs(y - sy) > 3:
                self._marquee_moved = True
                self._marquee_rect = (min(sx, x), min(sy, y), max(sx, x), max(sy, y))
                self._draw_marquee(self._marquee_rect)
            return
        if mode == 'movemulti':
            if not self._drag_undone:
                self.app.push_undo()      # 拖拽首次实际位移前快照一次
                self._drag_undone = True
            dx_steps = self.x_to_time(x) - self.x_to_time(self._drag_start[0])
            dy_pitch = self.y_to_pitch(y) - self.y_to_pitch(self._drag_start[1])
            lead = self.drag[1]
            for (n, ot, op) in self._drag_notes:
                n.time = max(0, ot + round(dx_steps))
                n.pitch = max(synth.MIDI_LOW, min(synth.MIDI_HIGH, op + dy_pitch))
                self._move_note_item(n)   # O(1)：逐个移动被拖拽的音符，不重建全部
            # 拖拽变调：以主音符音高驱动试听（FL 风滑音）
            if lead.pitch != self._last_preview_midi:
                ae.preview_set_pitch(self.track.instrument, lead.pitch, lead.velocity)
                self._last_preview_midi = lead.pitch
            # 整组移动结束后统一把蓝色播放头提到最上层（一次 raise，杜绝逐个 raise 的卡顿）
            self.tag_raise('playhead')
            return
        note = self.drag[1]
        if mode == 'move':
            if not self._drag_undone:
                self.app.push_undo()      # 拖拽首次实际位移前快照一次
                self._drag_undone = True
            dx, dy = self.drag[2], self.drag[3]
            note.time = max(0, self.x_to_time(x - dx))
            note.pitch = self.y_to_pitch(y - dy)
            # 拖拽变调：保持发声持续，音高跟随当前位置（FL 风滑音试听）
            if note.pitch != self._last_preview_midi:
                ae.preview_set_pitch(self.track.instrument, note.pitch, note.velocity)
                self._last_preview_midi = note.pitch
        elif mode == 'resize':
            if not self._drag_undone:
                self.app.push_undo()
                self._drag_undone = True
            nx = self.time_to_x(note.time)
            note.duration = max(1, round((x - nx) / self.beat_w))
        self._move_note_item(note)   # O(1)：只移动被拖拽的单个音符，不重建全部
        self.tag_raise('playhead')   # 本次拖拽结束统一提到最上层（仅一次）

    def on_up(self, ev):
        drag = self.drag
        self.drag = None
        self._last_preview_midi = None
        ae.preview_stop()   # 左键松开 -> 停止试听发声
        if not drag:
            return
        mode = drag[0]
        if mode in ('move', 'resize', 'movemulti'):
            # 拖拽移动/改长结束，工程已修改，触发后台预渲染
            self.app._schedule_prepare()
            return
        if mode == 'marquee':
            self.delete('marquee')
            if not self._marquee_moved:
                # 纯点击空白：有选区则取消选择（不放置新音符）；无选区则新建一个音符
                if self.selected_notes:
                    self._clear_selection()
                else:
                    self._create_note_at(self._marquee_start[0], self._marquee_start[1])
            else:
                # 拖动框选：选中框内所有音符（替换当前选区）
                box = self._marquee_rect
                sel = [n for n in self.track.notes if self._note_intersects(n, box)]
                self.selected_notes = set(sel)
                self.selected_note = sel[0] if sel else None
                self.redraw_notes()
                self.app.on_note_selected(self.selected_note)
                self.app.set_status(
                    f'已框选 {len(sel)} 个音符' if sel else '框选区域无音符')

    # --- 十字准心（解决"显示光标与实际操作点偏差"）---
    # 设计：系统光标设为 cross（指针永远精确位于鼠标，零偏移）；同时绘制一条「吸附到网格」
    # 的虚线准心，其位置用与音符放置/控制完全相同的 x_to_time / y_to_pitch 计算，
    # 因此准心交点 = 音符实际落点，绝无偏差。基于屏幕坐标 _sx/_sy 重算，缩放/滚动后依然精确。
    def on_motion(self, ev):
        self._sx, self._sy = ev.x, ev.y
        # 拖动中（self.drag 非 None）跳过准心重绘：每像素 delete+2×create_line 是卡顿来源之一；
        # 拖动结束（on_up 置 None）后的下一次移动再重绘，零视觉损失。
        if self.drag:
            return
        self._update_crosshair()

    def on_leave(self, ev):
        self._sx = self._sy = None
        self._update_crosshair()

    def _update_crosshair(self):
        self.delete('crosshair')
        if self.track is None or self._sx is None or self._sy is None:
            return
        mx, my = self.canvasx(self._sx), self.canvasy(self._sy)
        if my < RULER_H:          # 顶部标尺区为 seek，不显示音符准心
            return
        step = self.x_to_time(mx)   # 与 on_down 放置音符、on_drag 移动音符同一套换算 -> 零偏移
        pitch = self.y_to_pitch(my)
        cx = self.time_to_x(step)
        cy = self.pitch_to_y(pitch)
        h = self._content_h or (self.grid_height() + RULER_H + 40)
        w = self._content_w or (self.grid_width() + 60)
        self.create_line(cx, RULER_H, cx, h, fill=MAGENTA, width=1, dash=(3, 3), tags=('crosshair',))
        self.create_line(0, cy, w, cy, fill=MAGENTA, width=1, dash=(3, 3), tags=('crosshair',))

    # --- 右键拖框：框内音符全删除 ---
    def on_right_down(self, ev):
        x, y = self.canvasx(ev.x), self.canvasy(ev.y)
        if self.track is None or y < RULER_H:
            return
        self.delete('crosshair')    # 右键框删拖动时同样收起准心
        self.drag = ('box',)
        self._box_start = (x, y)
        self._box_rect = None

    def on_right_drag(self, ev):
        if not self.drag or self.drag[0] != 'box':
            return
        x2, y2 = self.canvasx(ev.x), self.canvasy(ev.y)
        x1, y1 = self._box_start
        self._box_rect = (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))
        self._draw_box()

    def on_right_up(self, ev):
        if not self.drag or self.drag[0] != 'box':
            self.drag = None
            return
        x2, y2 = self.canvasx(ev.x), self.canvasy(ev.y)
        x1, y1 = self._box_start
        self.drag = None
        self.delete('selbox')
        self._box_rect = None
        # 单击未拖动（框极小）-> 退化为单音符删除（保留旧行为）
        if abs(x2 - x1) < 4 and abs(y2 - y1) < 4:
            hit = self._hit_note(x1, y1)
            if hit:
                self.app.push_undo()
                self.track.notes.remove(hit)
                if self.selected_note is hit:
                    self.selected_note = None
                self.selected_notes.discard(hit)
                self.redraw_notes()
                self.app.on_note_selected(None)
                self.app._schedule_prepare()
            return
        box = (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))
        removed = [n for n in self.track.notes if self._note_intersects(n, box)]
        if not removed:
            return
        self.app.push_undo()
        for n in removed:
            self.track.notes.remove(n)
        if self.selected_note in removed:
            self.selected_note = None
        self.selected_notes.difference_update(removed)
        self.redraw_notes()
        self.app.on_note_selected(None)
        self.app._schedule_prepare()
        self.app.set_status(f'已框选删除 {len(removed)} 个音符')

    def _note_intersects(self, note, box):
        nx = self.time_to_x(note.time)
        ny = self.pitch_to_y(note.pitch)
        nw = note.duration * self.beat_w
        nh = KEY_H
        x1, y1, x2, y2 = box
        return nx < x2 and nx + nw > x1 and ny < y2 and ny + nh > y1

    def _draw_box(self):
        self.delete('selbox')
        if not self._box_rect:
            return
        x1, y1, x2, y2 = self._box_rect
        # 右键删除框：洋红实心 + 半透明（stipple 模拟 alpha），与左键蓝绿框选对照，去掉空心虚线。
        self.create_rectangle(x1, y1, x2, y2, outline=MAGENTA, width=2,
                              fill=MAGENTA, stipple='gray50', tags=('selbox',))

    def _seek(self, x):
        # 连续化拖动：直接按像素换算为小数 step，不再量子化到整数步
        step = max(0.0, min(x / self.beat_w, self.project.total_steps))
        self.app.seek_playhead(step)

    def set_playhead(self, step):
        # 连续化：保留小数 step（像素级精度），与音频引擎的浮点播放头对齐
        self.playhead_step = max(0.0, min(float(step), self.project.total_steps))
        # 仅重绘播放头线，不重建网格/音符（否则逐帧卡顿）
        self.update_playhead()

    def on_wheel(self, ev):
        # Ctrl+滚轮：横向视图缩放（以音轨起点为中心向右展开）
        if ev.state & 0x4:
            direction = 1 if ev.delta > 0 else -1
            nz = _next_zoom(self.zoom, direction)
            self.set_zoom(nz)
            return
        if self.selected_notes:
            d = 0.05 if ev.delta > 0 else -0.05
            for n in self.selected_notes:
                n.velocity = max(0.05, min(1.0, n.velocity + d))
            self.app.on_note_selected(self.selected_note)

    def set_zoom(self, z, anchor_canvas_x=None):
        """设置横向缩放百分比（10~500），并同步缩放后的视图。

        - 缩放后每拍像素宽 beat_w = BEAT_W * z / 100，所有音符/网格/蓝色播放头、
          横向滚条都基于 beat_w 重新计算，因此播放头位置与移动速度、滚条始终一致。
        - 缩放中心固定为**音轨起点（step 0 / 画布 x=0）**，向右侧展开：缩放前后起点
          在屏幕上的位置保持不变，时间轴随缩放比例向右拉伸/收缩。
          （anchor_canvas_x 仅保留为接口兼容参数，不再用于定点锚定。）
        """
        z = max(10.0, min(500.0, float(z)))
        # 锚定音轨起点：缩放前记录起点(画布x=0)当前的屏幕偏移，缩放后使其回到原位
        first, _ = self.xview()
        old_sr_w = self.grid_width() + 60
        screen = -first * old_sr_w          # 起点(画布x=0)当前的屏幕偏移
        self.zoom = z
        self.beat_w = BEAT_W * z / 100.0
        self.xscrollincrement = self.beat_w
        self.redraw()
        new_sr_w = self.grid_width() + 60
        if new_sr_w > 0:
            first_new = -screen / new_sr_w  # 使起点仍停在同一屏幕偏移
            self.xview_moveto(max(0.0, min(first_new, 1.0)))
        if self.app:
            self.app.set_status(f"横向缩放 {int(z)}%  （Ctrl+滚轮，以音轨起点为中心向右展开）")

    def _sync_hscroll(self):
        """缩放/重绘改变了 scrollregion 或视图：同步横向滚条 + 镜像头部概览。
        交给 main 的 _on_pr_xview 统一处理（两只横向滚条 + 头部重绘），保证一致。"""
        app = self.app
        if app is not None and hasattr(app, '_on_pr_xview'):
            try:
                app._on_pr_xview(*self.xview())
            except Exception:
                pass
        elif self.hscroll is not None:
            try:
                self.hscroll.set(*self.xview())
            except Exception:
                pass

    def _on_hscroll(self, ev):
        units = 3 if ev.delta > 0 else -3
        self.xview('scroll', units, 'units')


class TrackLanes(tk.Canvas):
    """顶部并行音轨概览（压缩为缩略时间轴）。

    交互：
    - 左侧标签区（x <= KEY_W）点击选择音轨；
    - 右侧时间轴区（x > KEY_W）按住左键拖动控制红线播放头位置，与钢琴卷帘蓝线同步。
    """

    def __init__(self, parent, project, app, **kw):
        super().__init__(parent, bg=SURFACE, highlightthickness=0, height=40, **kw)
        self.project = project
        self.app = app
        self.playhead_step = 0
        self._drag = False
        self._last_sync_off = None         # 上次 sync_view 使用的视图左边缘偏移（去重用）
        self.bind('<Button-1>', self.on_down)
        self.bind('<B1-Motion>', self.on_drag)
        self.bind('<ButtonRelease-1>', self.on_up)
        self.bind('<MouseWheel>', self.on_wheel)
        self._last_tl_w = -1
        self._redraw_timer = None
        self.bind('<Configure>', self._on_configure)

    def _on_configure(self, _ev):
        # 窗口缩放时 <Configure> 会高频触发；防抖合并，且尺寸未实质变化则跳过，
        # 避免拖动边框时每帧都完整重绘头部概览（主界面 resize 卡顿根因）。
        w = self.winfo_width()
        if abs(w - self._last_tl_w) < 2:
            return
        self._last_tl_w = w
        if self._redraw_timer is not None:
            self.after_cancel(self._redraw_timer)
        self._redraw_timer = self.after(90, self.redraw)

    def set_project(self, project):
        """同 PianoRoll：打开/新建工作文件后同步底层工程引用，并复位视图状态。"""
        self.project = project
        self.playhead_step = 0
        self._drag = False
        self.redraw()

    def _bw(self):
        """当前每拍像素宽：跟随主钢琴卷帘的缩放（默认 100% 时为 BEAT_W）。"""
        pr = getattr(self.app, 'pr', None)
        return getattr(pr, 'beat_w', BEAT_W)

    def _view_offset(self):
        """编辑区当前横向视图的左边缘画布 x（与编辑区共享缩放/视图）。"""
        pr = getattr(self.app, 'pr', None)
        if pr is None:
            return 0.0
        try:
            return pr.xview()[0] * (pr.grid_width() + 60)
        except Exception:
            return 0.0

    def redraw(self):
        """完整重绘（仅音轨增删 / 换乐器 / 选中变化时调用）：重建静态层 + 镜像音符 + 红线。"""
        self._draw_lanes()
        self.redraw_notes()
        self.update_playhead()
        self._last_sync_off = self._view_offset()   # 重置去重基准，确保下次滚动必重绘

    def _draw_lanes(self):
        """静态层：各音轨底色 + 分隔线 + 左侧冻结音轨名标签。仅音轨结构变化时重建。"""
        self.delete('lanes')
        lanes = self.project.tracks
        if not lanes:
            return
        w = max(200, self.winfo_width())
        lane_h = 28
        total = max(40, lane_h * len(lanes))
        self.configure(height=total)
        # 各音轨底色 + 分隔线
        for i, track in enumerate(lanes):
            y = i * lane_h
            sel = (track is self.app.selected_track)
            self.create_rectangle(0, y, w, y + lane_h - 2,
                                  fill=('#1d1d2b' if sel else '#101018'), outline=INPUT, tags=('lanes',))
            self.create_line(0, y + lane_h - 2, w, y + lane_h - 2, fill=INPUT, tags=('lanes',))
        # 左侧音轨名标签列（冻结，覆盖溢出）
        self.create_rectangle(0, 0, KEY_W, total, fill=SURFACE, outline='', tags=('lanes',))
        for i, track in enumerate(lanes):
            y = i * lane_h
            sel = (track is self.app.selected_track)
            self.create_text(8, y + lane_h / 2,
                             text=f"{track.name} · {synth.INSTRUMENT_LABEL.get(track.instrument, track.instrument)}",
                             anchor='w', fill=(CYAN if sel else TEXT_SECONDARY),
                             font=('Microsoft YaHei', 9), tags=('lanes',))

    def redraw_notes(self):
        """动态层：镜像音符（依赖缩放 beat_w 与视图偏移 off）。滚动 / 缩放 / 音符变化时调用。"""
        self.delete('notes')
        lanes = self.project.tracks
        if not lanes:
            return
        bw = self._bw()
        off = self._view_offset()           # 编辑区左边缘画布 x
        w = max(200, self.winfo_width())
        lane_h = 28
        for i, track in enumerate(lanes):
            y = i * lane_h
            c = track.color
            for note in track.notes:
                nx = KEY_W + note.time * bw - off
                nw = max(2, note.duration * bw)
                if nx + nw < 0 or nx > w:
                    continue
                self.create_rectangle(max(KEY_W, nx), y + 6, nx + nw, y + lane_h - 8,
                                      fill=c, outline='', tags=('notes',))
        # 重画镜像音符后，确保红线播放头仍位于最上层
        self.tag_raise('playhead')

    def update_playhead(self):
        """仅重绘红线播放头（与编辑区蓝线像素级对齐）。逐帧播放 / seek 时调用。"""
        self.delete('playhead')
        lanes = self.project.tracks
        if not lanes:
            return
        lane_h = 28
        total = max(40, lane_h * len(lanes))
        bw = self._bw()
        off = self._view_offset()
        w = max(200, self.winfo_width())
        step = max(0, min(self.playhead_step, self.project.total_steps))
        px = KEY_W + step * bw - off
        if 0 <= px <= w:
            self.create_line(px, 0, px, total, fill=MAGENTA, width=2, tags=('playhead',))

    def sync_view(self):
        """编辑区横向视图变化（滚动 / 缩放）：只重绘镜像音符与红线，不动静态层。

        去重：若本次视图左边缘偏移与上次完全相同（重复/微小滚动事件），
        镜像音符与红线位置均未变，直接跳过重建，避免每个滚动事件都重画全部音符矩形。
        """
        off = self._view_offset()
        if off == self._last_sync_off:
            return
        self._last_sync_off = off
        self.redraw_notes()
        self.update_playhead()

    def set_playhead(self, step):
        # 连续化：保留小数 step（像素级精度），与音频引擎的浮点播放头对齐
        self.playhead_step = max(0.0, min(float(step), self.project.total_steps))
        # 仅重绘红线，不重建静态层/镜像音符（否则逐帧卡顿）
        self.update_playhead()

    def on_down(self, ev):
        self._drag = False
        x = self.canvasx(ev.x)
        if x > KEY_W:
            self._drag = True
            self._seek(x)
        else:
            lane_h = 28
            i = int(self.canvasy(ev.y) // lane_h)
            if 0 <= i < len(self.project.tracks):
                self.app.select_track(self.project.tracks[i])

    def on_drag(self, ev):
        if self._drag and self.canvasx(ev.x) > KEY_W:
            self._seek(self.canvasx(ev.x))

    def on_up(self, ev):
        self._drag = False

    def _seek(self, x):
        # 镜像：屏幕 x 对应 step = (x - KEY_W + 视图偏移) / beat_w
        bw = self._bw()
        off = self._view_offset()
        step = (x - KEY_W + off) / bw if bw > 0 else 0
        self.app.seek_playhead(step)

    def on_wheel(self, ev):
        # Ctrl+滚轮：与编辑区共享同一缩放倍率（头部为镜像，自动跟随；以音轨起点为中心）
        if ev.state & 0x4:
            pr = getattr(self.app, 'pr', None)
            if pr is not None:
                direction = 1 if ev.delta > 0 else -1
                nz = _next_zoom(pr.zoom, direction)
                pr.set_zoom(nz)
            return
