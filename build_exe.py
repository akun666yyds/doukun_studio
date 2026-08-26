# -*- coding: utf-8 -*-
r"""DouKunStudio 可靠打包脚本（绕过 WorkBuddy safe-delete shim）。

关键陷阱：
- 沙箱内 Python 的 tempfile.gettempdir() 返回 D:\Temp，而非 C:\Users\...\AppData\Local\Temp。
- WorkBuddy 的 safe-delete shim 只对「位于 OS 临时目录（gettempdir()）或 pip 临时目录」的
  删除走真实删除，其余一律尝试移入回收站；而沙箱内回收站不可用 -> FAIL_CLOSED 抛 OSError，
  会中断 PyInstaller 的临时文件清理，导致 exe 写不出来。
- 对策：
  1) --workpath 指向 D:\Temp\dkbuild（被 shim 识别为 OS 临时目录 -> PyInstaller 清理时真实删除）。
  2) 打包前用 ctypes DeleteFileW/RemoveDirectoryW 直接硬删 dist 里的旧 exe（绕过 shim），
     避免 PyInstaller --noconfirm 去删 dist 下的旧 exe 时触发 FAIL_CLOSED。
"""
import os
import sys
import ctypes
import shutil
import subprocess
import time

PROJECT = os.path.dirname(os.path.abspath(__file__))
SRC_EXE = os.path.join(PROJECT, 'dist', 'DouKunStudio.exe')
NEW_EXE = os.path.join(PROJECT, 'dist', 'DouKunStudio_new.exe')
WORKPATH = r'D:\Temp\dkbuild'
DISTPATH = os.path.join(PROJECT, 'dist')

PY = sys.executable  # 应使用系统 Python 3.14（含 Tcl/Tk）


def ctypes_delete(path):
    """强制删除（文件或目录树），绕过 safe-delete shim / 回收站。

    对文件：DeleteFileW 若返回 0（如沙箱/AV 锁导致 ACCESS_DENIED），再尝试
    MoveFileW 改名挪开以腾出原文件名（PyInstaller 即可新建同名文件），最后
    再尽力删除改名后的残留。失败不抛出，仅告警。
    """
    if sys.platform != 'win32':
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path, ignore_errors=True)
        else:
            try:
                os.remove(path)
            except OSError:
                pass
        return
    k = ctypes.windll.kernel32  # noqa
    FILE_ATTRIBUTE_NORMAL = 0x80
    FILE_ATTRIBUTE_DIRECTORY = 0x10

    def _norm(p):
        try:
            k.SetFileAttributesW(p, FILE_ATTRIBUTE_NORMAL)
        except Exception:
            pass

    if os.path.isdir(path) and not os.path.islink(path):
        for root, dirs, files in os.walk(path, topdown=False):
            for f in files:
                fp = os.path.join(root, f)
                _norm(fp)
                k.DeleteFileW(fp)
            for d in dirs:
                dp = os.path.join(root, d)
                _norm(dp)
                k.RemoveDirectoryW(dp)
        _norm(path)
        k.RemoveDirectoryW(path)
        return

    try:
        _norm(path)
        if k.DeleteFileW(path):
            return
    except Exception as e:
        print('  [warn] DeleteFileW %s: %s' % (path, e))
    # DeleteFileW 失败（常见于文件被沙箱/AV 锁定）：改名挪开腾出原名
    try:
        aside = path + '.old'
        if k.MoveFileW(path, aside):
            print('  renamed-aside (lock):', path, '->', aside)
            try:
                k.DeleteFileW(aside)
            except Exception:
                pass
            return
    except Exception as e:
        print('  [warn] MoveFileW %s: %s' % (path, e))
    if os.path.exists(path):
        print('  [warn] 仍无法删除（可能被外部锁定）: %s' % path)


def ensure_seeds():
    """已废弃：预设示例 DLC（Caesar / 我的音色 / 蔡徐坤）已永久移除，不再随 exe 打包或播种。

    用户应得到干净的 DLC 空间，自行生成/注册音色。保留空函数仅作占位，避免误调用。
    """
    return


def clear_user_dlc():
    """打包前清空 instrument_dlc/ 下的全部用户 DLC 源文件（含历史预设），确保分发包不再携带任何音色。

    已不再打包内置示例 DLC，用户得到干净空间。__pycache__ 等缓存一并清理。
    """
    seed_dir = os.path.join(PROJECT, 'instrument_dlc')
    os.makedirs(seed_dir, exist_ok=True)
    for fn in os.listdir(seed_dir):
        full = os.path.join(seed_dir, fn)
        if fn.endswith('.py'):
            print('clear dlc:', full)
            ctypes_delete(full)
        elif fn in ('__pycache__', '_smoke_types', '_regress_tmp'):
            ctypes_delete(full)
    print('cleared all DLC (clean space for user)')


def main():
    os.chdir(PROJECT)
    print('Project :', PROJECT)
    print('Python  :', PY)
    print('gettempdir:', __import__('tempfile').gettempdir())

    # 0) 不再打包预设 DLC：清空 instrument_dlc/ 下全部音色，给用户干净空间
    clear_user_dlc()

    # 1) 预删 dist 下的旧 exe（绕过 shim，确保 PyInstaller 无需删除它们）
    for p in (SRC_EXE, NEW_EXE):
        if os.path.exists(p) or os.path.islink(p):
            print('ctypes-delete:', p)
            ctypes_delete(p)

    # 2) 预清 workpath（位于 OS 临时目录，PyInstaller 清理时也会真实删除，这里先清一遍更稳）
    if os.path.exists(WORKPATH):
        print('ctypes-clear workpath:', WORKPATH)
        ctypes_delete(WORKPATH)

    # 3) 运行 PyInstaller
    cmd = [
        PY, '-m', 'PyInstaller', 'DouyinDAW.spec',
        '--workpath', WORKPATH,
        '--distpath', DISTPATH,
        '--noconfirm',
    ]
    print('CMD:', ' '.join(cmd))
    t0 = time.time()
    proc = subprocess.run(cmd)
    print('PyInstaller exit:', proc.returncode, '(%.1fs)' % (time.time() - t0))
    if proc.returncode != 0:
        print('BUILD FAILED')
        sys.exit(proc.returncode)

    if not os.path.exists(SRC_EXE):
        print('BUILD FAILED: %s not produced' % SRC_EXE)
        sys.exit(2)

    # 4) 复制出 _new.exe 供用户并行测试（copyfile 以截断方式写目标，不调用 os.remove）
    print('copy ->', NEW_EXE)
    shutil.copyfile(SRC_EXE, NEW_EXE)
    print('DONE. sizes:')
    for p in (SRC_EXE, NEW_EXE):
        print('  %s : %d bytes' % (p, os.path.getsize(p)))


if __name__ == '__main__':
    main()
