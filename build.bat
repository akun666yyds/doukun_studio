@echo off
REM 打包为单文件 exe（需先安装依赖： pip install -r requirements.txt）
python -m PyInstaller DouyinDAW.spec
echo.
echo 打包完成，exe 位于 dist\DouKunStudio.exe
pause
