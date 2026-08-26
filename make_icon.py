"""生成 抖坤音乐工坊 · DouKunStudio 应用图标。

设计语义：
- 黑色圆角方底（抖音风格）
- 白色主标：小写 d 的圆碗 + 竖 stem，同时这个 stem 也是小写 k 的竖 stem，
  从中部分出右上 / 右下两条斜线，形成 dk 共 stem 的融合。
- 洋红/青绿错位阴影，模拟抖音 chromatic aberration。

输出：
  assets/icon_1024.png   高清主图标
  assets/icon.ico        Windows 多尺寸图标（16/32/48/256）
"""
import os
from PIL import Image, ImageDraw

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets')
os.makedirs(OUT_DIR, exist_ok=True)

# 抖音令牌
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
CYAN = (37, 244, 238)      # #25F4EE
MAGENTA = (254, 44, 85)  # #FE2C55

SIZE = 1024
CORNER = 220
LINE = 90           # 主笔画粗细
GHOST = 14          # 色散偏移量


def rounded_rect(draw, xy, radius, fill):
    """画实心圆角矩形。"""
    x1, y1, x2, y2 = xy
    draw.rounded_rectangle(xy, radius=radius, fill=fill)


def draw_symbol(draw, color, offset=(0, 0)):
    """绘制 dk 融合符号。

    坐标系基于 1024x1024 画布中心。
    - d 的圆碗：圆心偏左，作为音符头
    - d 的竖 stem：圆碗右侧向上延伸
    - k 的两条腿：从 stem 中部向右上、右下分叉
      这样 stem 被 d 和 k 共享。
    """
    ox, oy = offset

    # 几何中心
    cx, cy = SIZE // 2, SIZE // 2

    # d 的圆碗（音符头）：圆心稍偏左下
    bowl_cx = cx - 100 + ox
    bowl_cy = cy + 90 + oy
    bowl_r = 130

    # stem：从圆碗右侧边缘向上
    stem_x = bowl_cx + bowl_r + ox
    stem_top = cy - 160 + oy
    stem_bottom = bowl_cy + oy  # 与圆碗底部平齐
    k_branch_y = cy - 10 + oy   # k 分叉点（stem 中部偏上）

    # k 的两条腿端点
    k_top_x = cx + 170 + ox
    k_top_y = cy - 170 + oy
    k_bottom_x = cx + 170 + ox
    k_bottom_y = cy + 150 + oy

    # 画圆碗（实心圆，直径≈ 2*bowl_r，与 LINE 粗细匹配）
    draw.ellipse(
        [bowl_cx - bowl_r, bowl_cy - bowl_r,
         bowl_cx + bowl_r, bowl_cy + bowl_r],
        fill=color
    )

    # 画 stem（共享竖线）
    draw.line([(stem_x, stem_bottom), (stem_x, stem_top)], fill=color, width=LINE, joint="curve")

    # 画 k 的右上斜线
    draw.line([(stem_x, k_branch_y), (k_top_x, k_top_y)], fill=color, width=LINE, joint="curve")
    # 画 k 的右下斜线
    draw.line([(stem_x, k_branch_y), (k_bottom_x, k_bottom_y)], fill=color, width=LINE, joint="curve")


def make_icon():
    img = Image.new('RGBA', (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 黑色圆角方底
    rounded_rect(draw, (0, 0, SIZE - 1, SIZE - 1), CORNER, BLACK)

    # 青/洋红错位阴影（模拟抖音 chromatic aberration）
    draw_symbol(draw, CYAN, offset=(-GHOST, -GHOST))
    draw_symbol(draw, MAGENTA, offset=(GHOST, GHOST))

    # 白色主标
    draw_symbol(draw, WHITE, offset=(0, 0))

    png_path = os.path.join(OUT_DIR, 'icon_1024.png')
    img.save(png_path, 'PNG')

    # 生成 Windows 多尺寸 ico
    ico_path = os.path.join(OUT_DIR, 'icon.ico')
    sizes = [(16, 16), (32, 32), (48, 48), (256, 256)]
    imgs = [img.resize(s, Image.Resampling.LANCZOS) for s in sizes]
    imgs[0].save(ico_path, format='ICO', sizes=sizes, append_images=imgs[1:])

    print('saved:', png_path)
    print('saved:', ico_path)
    return png_path, ico_path


if __name__ == '__main__':
    make_icon()
