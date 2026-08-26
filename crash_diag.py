# -*- coding: utf-8 -*-
"""崩溃 / 卡死 诊断引导模块（DouKunStudio）。

在主程序任何 import 之前调用 install()，即可在「异常退出 / 卡死 / 原生崩溃」时
把完整堆栈与上下文写入 %TEMP%/doukun_diag.log，便于真机精准定位。

捕获范围：
  1. 未捕获异常      sys.excepthook
  2. 线程内未捕获异常  threading.excepthook
  3. __del__ / 回调里的不可抛出异常  sys.unraisablehook
  4. 原生崩溃（段错误 / 访问越界等，含 Tk/SDL C 扩展）  faulthandler
  5. 主线程卡死      后台看门狗每 30s dump 全部线程堆栈（正常关闭时自动停止，避免误报）
  6. stdout / stderr  全部镜像到日志文件（含 pygame 等 C 扩展打印的内容）

使用方式（已在 main.py 顶部安装，无需手动调用）：
  - 源码：python main.py
  - exe ：直接运行 DouKunStudio.exe
复现卡死后，等待约 35 秒（看门狗会落一次主线程堆栈），再把
  %TEMP%/doukun_diag.log
回传即可。
"""
import os
import sys
import time
import faulthandler
import traceback
import threading

_LOG_PATH = os.path.join(os.environ.get('TEMP', os.path.expanduser('~')),
                         'doukun_diag.log')
_fp = None
_closing = False
_installed = False

# 主线程存活看门狗状态
_last_ping = 0.0
_guard_threshold = 4.0


def ping():
    """主线程心跳：由 main 的 after 循环每 ~0.5s 调用一次，证明主线程未被阻塞。"""
    global _last_ping
    _last_ping = time.time()
    if _fp is None:
        _open()


def start_hang_guard(threshold=4.0):
    """启动主线程存活看门狗（必须在 install() 之后、mainloop 之前调用）。

    主线程每 0.5s 通过 ping() 上报心跳。若超过 threshold 秒无心跳（说明主线程被
    死循环 / C 层事件重入 / 跨线程调 Tk 等冻结），看门狗线程立即把全部线程堆栈
    dump 到 doukun_diag.log 并干净 os._exit(0)，避免被系统判“未响应”强杀。
    """
    global _guard_threshold, _last_ping
    _guard_threshold = threshold
    _last_ping = time.time()

    def _guard():
        while True:
            time.sleep(1)
            if _closing:
                return
            if _last_ping > 0 and (time.time() - _last_ping) > _guard_threshold:
                try:
                    _fp.write('\n=== HANG GUARD: 主线程无响应 >%ss，'
                              'dump 全部线程堆栈并干净退出 ===\n' % _guard_threshold)
                    faulthandler.dump_traceback(file=_fp)
                    _fp.write('=== end hang dump (os._exit(0)) ===\n\n')
                    _fp.flush()
                except Exception:
                    pass
                os._exit(0)

    try:
        threading.Thread(target=_guard, daemon=True).start()
    except Exception:
        pass


def log_path():
    return _LOG_PATH


def log_event(msg):
    """记录一条带时间戳的普通事件。供 main.py 在关键节点调用。"""
    global _fp
    if _fp is None:
        _open()
    if _fp is None:
        return
    try:
        _fp.write('%s [event] %s\n' % (time.strftime('%H:%M:%S.%f'), msg))
        _fp.flush()
    except Exception:
        pass


def mark_closing():
    """标记程序正在正常关闭，停止卡死看门狗的周期性误报。"""
    global _closing
    _closing = True
    log_event('mark_closing -> NORMAL shutdown in progress')


def _open():
    global _fp
    try:
        # 行缓冲（buffering=1），确保崩溃瞬间也能落盘，不被缓冲区吞掉。
        _fp = open(_LOG_PATH, 'a', encoding='utf-8', buffering=1)
    except Exception:
        _fp = None
    return _fp


class _Tee:
    """把 sys.stdout / sys.stderr 同时写到原目标与诊断日志（控制台输出保留）。"""

    def __init__(self, real):
        self._real = real

    def write(self, s):
        try:
            if _fp is not None:
                _fp.write(s)
                _fp.flush()
        except Exception:
            pass
        try:
            if self._real is not None:
                self._real.write(s)
        except Exception:
            pass
        return len(s)

    def flush(self):
        try:
            if _fp is not None:
                _fp.flush()
        except Exception:
            pass
        try:
            if self._real is not None:
                self._real.flush()
        except Exception:
            pass

    def isatty(self):
        try:
            return self._real is not None and self._real.isatty()
        except Exception:
            return False


def install():
    """安装全部诊断钩子。必须在最早期（tkinter / pygame 之前）调用。"""
    global _installed, _fp
    if _installed:
        return
    _installed = True
    _open()
    try:
        _fp.write('\n========== DouKunStudio diag session %s ==========\n'
                  % time.strftime('%Y-%m-%d %H:%M:%S'))
        _fp.write('argv      = %s\n' % (sys.argv,))
        _fp.write('frozen    = %s\n' % getattr(sys, 'frozen', False))
        _fp.write('executable = %s\n' % sys.executable)
        _fp.write('python    = %s\n' % sys.version.replace('\n', ' '))
        _fp.write('cwd       = %s\n' % os.getcwd())
        _fp.write('log_path  = %s\n' % _LOG_PATH)
        _fp.flush()
    except Exception:
        pass

    # 1) faulthandler：原生崩溃捕获 + 可被看门狗调用 dump_traceback
    try:
        faulthandler.enable(file=_fp)
    except Exception:
        pass

    # 2) 未捕获异常
    _orig_exch = sys.excepthook

    def _exch(et, ev, tb):
        try:
            _fp.write('\n=== UNCAUGHT EXCEPTION %s ===\n'
                      % time.strftime('%H:%M:%S.%f'))
            traceback.print_exception(et, ev, tb, file=_fp)
            _fp.write('=== end uncaught exception ===\n\n')
            _fp.flush()
        except Exception:
            pass
        if _orig_exch is not None:
            try:
                _orig_exch(et, ev, tb)
            except Exception:
                pass

    sys.excepthook = _exch

    # 3) 线程异常
    _orig_texch = getattr(threading, 'excepthook', None)

    def _texch(args):
        try:
            _fp.write('\n=== THREAD EXCEPTION %s ===\n'
                      % time.strftime('%H:%M:%S.%f'))
            _fp.write('thread = %s\n' % getattr(args, 'thread', None))
            traceback.print_exception(args.exc_type, args.exc_value,
                                       args.exc_traceback, file=_fp)
            _fp.write('=== end thread exception ===\n\n')
            _fp.flush()
        except Exception:
            pass
        if _orig_texch is not None:
            try:
                _orig_texch(args)
            except Exception:
                pass

    if hasattr(threading, 'excepthook'):
        threading.excepthook = _texch

    # 4) 不可抛出异常（__del__ / 回调）
    _orig_unr = sys.unraisablehook

    def _unr(args):
        try:
            _fp.write('\n=== UNRAISABLE %s ===\n' % time.strftime('%H:%M:%S.%f'))
            _fp.write('what = %s\n' % getattr(args, 'what', None))
            traceback.print_exception(args.exc_type, args.exc_value,
                                       args.exc_traceback, file=_fp)
            _fp.write('=== end unraisable ===\n\n')
            _fp.flush()
        except Exception:
            pass
        if _orig_unr is not None:
            try:
                _orig_unr(args)
            except Exception:
                pass

    sys.unraisablehook = _unr

    # 5) 镜像 stdout / stderr
    try:
        sys.stdout = _Tee(sys.stdout)
    except Exception:
        pass
    try:
        sys.stderr = _Tee(sys.stderr)
    except Exception:
        pass

    # 6) 卡死看门狗：每 30s，若尚未处于正常关闭，dump 全部线程堆栈。
    #    窗口「未响应」通常是主线程被某处阻塞（死锁 / 跨线程调 Tk / 同步 I/O），
    #    此 dump 能精确指出卡在哪一行。
    def _watchdog():
        while True:
            time.sleep(30)
            if _closing:
                return
            try:
                _fp.write('\n=== HANG WATCHDOG %s (main thread may be blocked) ===\n'
                          % time.strftime('%H:%M:%S.%f'))
                faulthandler.dump_traceback(file=_fp)
                _fp.write('=== end hang dump ===\n\n')
                _fp.flush()
            except Exception:
                pass

    try:
        _wdt = threading.Thread(target=_watchdog, daemon=True)
        _wdt.start()
    except Exception:
        pass

    # 8) 正常退出记录
    import atexit
    atexit.register(lambda: log_event('atexit -> process exiting'))
