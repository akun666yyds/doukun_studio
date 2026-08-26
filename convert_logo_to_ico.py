"""把用户提供的 logo PNG 转成 Windows 多尺寸 .ico，供 PyInstaller 打包使用。

用法：
    pip install pillow
    python convert_logo_to_ico.py
输出：
    assets/icon.ico

注意：
- 16/32/48 用 32 位 BMP（BGRA，未压缩）——这是 Windows 任务栏/资源管理器最兼容的格式；
  纯 PNG 小尺寸帧在部分 Windows 代码路径下会被忽略，导致任务栏回退到默认图标。
- 256 用 PNG 压缩（Windows 对 256 帧支持 PNG-in-ICO）。
"""
import io
import os
import struct
from PIL import Image

SRC = os.path.dirname(os.path.abspath(__file__))
logo_path = os.path.join(SRC, 'assets', 'icon_1024.png')
out_path = os.path.join(SRC, 'assets', 'icon.ico')


def _bmp_rgba(img):
    """生成 32 位 BGRA 未压缩 BMP 的像素数据（含 BITMAPINFOHEADER + XOR 行）。"""
    w, h = img.size
    # BITMAPINFOHEADER: 40 字节，32bpp，自下而上（负高度）
    header = struct.pack('<IiiHHIIiiII', 40, w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    px = img.load()
    rows = []
    for y in range(h):
        row = bytearray()
        for x in range(w):
            r, g, b, a = px[x, y]
            row += bytes((b, g, r, a))  # BGRA
        rows.append(bytes(row))
    return header + b''.join(reversed(rows))


def build_ico(png_path, out_path):
    img = Image.open(png_path).convert('RGBA')

    small = [(16, 16), (32, 32), (48, 48)]
    big = [(256, 256)]

    frames = []
    for s in small:
        bmp = _bmp_rgba(img.resize(s, Image.Resampling.LANCZOS))
        frames.append((s[0], s[1], bmp))
    buf = io.BytesIO()
    img.resize(big[0], Image.Resampling.LANCZOS).save(buf, format='PNG')
    frames.append((256, 256, buf.getvalue()))

    count = len(frames)
    data = struct.pack('<HHH', 0, 1, count)
    offset = 6 + 16 * count
    for w, h, payload in frames:
        bw = 0 if w == 256 else w
        bh = 0 if h == 256 else h
        is_png = payload[:4] == b'\x89PNG'
        bpp = 32
        data += struct.pack('<BBBBHHII', bw, bh, 0, 0, 1, bpp, len(payload), offset)
        offset += len(payload)
    for _, _, payload in frames:
        data += payload

    with open(out_path, 'wb') as f:
        f.write(data)
    print('saved:', out_path, 'frames:', [f[0] for f in frames])


if __name__ == '__main__':
    build_ico(logo_path, out_path)
