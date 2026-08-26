# DouKunStudio（抖坤音乐工坊）

一个基于 **Python + Tkinter** 的本地音乐 DAW（数字音频工作站）。采用**即时合成（instant synthesis）**，不依赖任何采样库，所有音色与用户 DLC 都在播放/导出时实时计算。

## 功能特性

- 多轨钢琴卷帘编曲（支持 13 个半音音阶、和弦、BPM/拍号）
- 14 种合成音色：基础波 `sine/saw/square/triangle/pulse`、合成类 `fm/additive/noise`、真实乐器建模 `pluck/piano/bell/flute/bowed/brass`（基于 Karplus-Strong、钢琴非谐性、钟体模态比等物理/模态合成）
- **用户 DLC 系统**：可视化生成 / 注册 / 编辑 / 删除自定义合成音色（写入 Python 文件，零运行时第三方依赖，可热插拔）
- 工程保存 / 加载（`.doukun`），混音并导出 WAV
- 抖音故障风自定义标题栏（白色「DouKunStudio」+ 青/红偏移重影），深色主题
- 单文件 exe 打包（PyInstaller），**零第三方依赖即可运行**

## 项目结构

```
DouyinDAW/
├── main.py              # 主程序：UI、事件、DLC 编辑器、工程、导出
├── audio_engine.py      # 音频引擎（pygame 混音/播放/回调）
├── synth.py             # 合成内核：音色注册、渲染、DLC 加载/删除
├── synth_factory.py     # 14 种合成类型实现 + DLC 源码生成
├── theme.py             # 深色主题配色 + 自定义故障风标题栏
├── piano_roll.py        # 钢琴卷帘组件（轨道/琴键/网格）
├── project.py           # 工程数据模型（拍号/轨道/BPM）
├── edm_synth.py         # EDM 风格合成辅助
├── ingest_samples.py    # 采样入库脚本（采样库可选，非运行必需）
├── convert_logo_to_ico.py / make_icon.py  # 图标生成辅助
├── regression_test.py   # 全量回归测试（14 类型/DLC 生命周期）
├── DouyinDAW.spec       # PyInstaller 单文件打包配置
├── build.bat            # 一键构建脚本
├── requirements.txt     # 运行依赖
├── assets/              # icon.ico（运行用）、icon_1024.png（图标源）
└── instrument_dlc/      # 内置 DLC 种子（Caesar.py / 我的音色.py / 蔡徐坤.py）
```

## 环境要求

| 项 | 说明 |
| --- | --- |
| 系统 | Windows 10 / 11（GUI 基于 Tkinter，已验证 Win11） |
| Python | 3.13+（推荐 3.14；需系统提供 `tkinter` / Tcl-Tk，受管精简环境可能缺 Tcl/Tk） |
| 运行依赖 | `numpy`、`pygame`、`Pillow` |
| 可选 | `scipy`（更好的低通滤波，缺失时自动回退到内置实现） |
| 打包 | `PyInstaller`（仅构建时需要） |

## 安装与运行（源码）

```bash
# 1) 安装依赖
pip install -r requirements.txt

# 2) 启动
python main.py
```

> 说明：Tkinter 在 Windows / macOS 随 Python 自带；Linux 需 `apt install python3-tk`。
> 若仅想听音/编曲，`numpy` + `pygame` 即可；`Pillow` 用于问题报告里的图片缩略图。

## 依赖说明（保证可复现）

`requirements.txt` 内容：

```
numpy>=1.24
pygame>=2.5
Pillow>=10.0
```

- **运行必需**：`numpy`（信号处理）、`pygame`（音频输出）、`Pillow`（报告缩略图，已在 `try/except` 内，缺失仅降级该功能）
- **可选增强**：`scipy`（低通滤波，缺失自动回退，不影响任何音色）
- **仅打包**：`PyInstaller`（见下方「构建独立 exe」）

程序**不依赖任何采样库**（336MB 采样数据不入库、也不参与运行），内置与 DLC 音色均为实时计算。

## 构建独立 exe（零依赖分发）

```bash
# 使用系统 Python（需含 Tcl/Tk）与 PyInstaller
pyinstaller DouyinDAW.spec --clean
# 或直接：
build.bat
```

打包结果位于 `dist/DouKunStudio.exe`，已内嵌 `assets/` 与 `instrument_dlc/`，**不打包采样库**，在干净 Win10/11 上无需 Python 环境即可运行。

## 自带的冒烟 / 回归测试

```bash
# 无界面冒烟测试（覆盖资源打包、DLC 生命周期、全 14 类型合成等），结果写 stdout 与 %TEMP%/doukun_smoke_result.txt
set DOUKUN_SMOKE_TEST=1
python main.py

# 全量回归（14 合成类型 默认/极端参数/DLC/和弦）
python regression_test.py
```

## 仓库不含的内容（已在 .gitignore 忽略）

`dist/`（构建产物）、`samples/`（采样数据）、`wheels/`（离线 wheel）、`__pycache__/`、`.workbuddy/`（本地工作记忆）、`%TMPD%/`（构建临时残留）、`*.wav` 演示文件、设计稿候选 PNG。

## License

MIT（如需其他协议请自行添加 LICENSE 文件）。
