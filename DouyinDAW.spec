# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置（生成单文件 exe）。

用法：
    pyinstaller DouyinDAW.spec
生成位置： dist/DouKunStudio.exe

说明：
- console=False  -> 双击运行无黑色终端窗口（纯 GUI）。
- datas 把 instrument_dlc/（用户可编辑的 DLC 音色库）与 assets/（图标）一起打进 exe；
  首次运行会把示例 DLC 播种到可写目录（exe 同级或 LOCALAPPDATA），用户可生成/注册/编辑/删除。
- 静态 samples/ 音色库不打包（约 336MB，且实际播放已由即时合成兜底，samples 仅作可选加速），
  故冻结后跳过静态库重建，exe 体积更小、启动更快。
- upx=False：避免某些 Windows 杀软对 UPX 压缩体的误报，保证「双击即用、无依赖」。
"""
import os

try:
    SRC = os.path.dirname(os.path.abspath(__file__))
except NameError:
    # 某些 PyInstaller 版本在执行 .spec 时不注入 __file__，退回到当前工作目录
    SRC = os.getcwd()
APP_NAME = 'DouKunStudio'

a = Analysis(
    [os.path.join(SRC, 'main.py')],
    pathex=[SRC],
    binaries=[],
    datas=[
        (os.path.join(SRC, 'instrument_dlc'), 'instrument_dlc'),
        (os.path.join(SRC, 'assets', 'icon_1024.png'), 'assets'),
        (os.path.join(SRC, 'assets', 'icon.ico'), 'assets'),
    ],
    hiddenimports=['numpy', 'pygame', 'PIL', 'PIL.Image', 'PIL.ImageTk',
                   'synth', 'synth_factory', 'audio_engine', 'project', 'piano_roll', 'theme'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(SRC, 'assets', 'icon.ico'),
)
