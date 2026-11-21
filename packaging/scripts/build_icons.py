#!/usr/bin/env python3
"""从 Floe 双款彩色设计原图与黑白菜单栏原图构建全平台图标资产：

1. 双款彩色主应用图标 (bull: 红涨瞭望款 / bear: 绿跌闭眼款)：
   - static/icons/floe_icon_bull.png & floe_icon_bear.png (512x512)
   - static/icons/favicon_bull.png & favicon_bear.png (64x64)
   - static/icons/floe_icon.png & favicon.png (默认指向 bull 款)
   - packaging/icons/floe_bull.icns & floe_bear.icns & floe.icns (macOS Apple HIG 824/1024 比例)
   - packaging/icons/floe_bull.ico & floe_bear.ico & floe.ico (Windows 多尺寸透明图标)

2. 黑白极简系统菜单栏图标：
   - packaging/icons/menubar_template.png (18x18) & menubar_template@2x.png (36x36 Retina)
   - packaging/icons/tray_icon_white.png (64x64)
"""
import os
import shutil
import subprocess
import sys
import tempfile
import numpy as np
from PIL import Image, ImageDraw


def _apply_rounded_alpha_mask(rgb_crop: Image.Image, target_px: int = 1024, radius_ratio: float = 0.225) -> Image.Image:
    """将裁切出的图标框缩放至 target_px 正方形并施加 4x 超采样平滑圆角透明遮罩。"""
    upscaled = rgb_crop.resize((target_px, target_px), Image.Resampling.LANCZOS).convert('RGBA')
    ss = 4
    mask_hi = Image.new('L', (target_px * ss, target_px * ss), 0)
    draw = ImageDraw.Draw(mask_hi)
    radius_hi = int(target_px * ss * radius_ratio)
    draw.rounded_rectangle([(0, 0), (target_px * ss - 1, target_px * ss - 1)], radius=radius_hi, fill=255)
    mask = mask_hi.resize((target_px, target_px), Image.Resampling.LANCZOS)

    out = Image.new('RGBA', (target_px, target_px), (0, 0, 0, 0))
    out.paste(upscaled, (0, 0), mask=mask)
    return out


def extract_dual_color_icons(dual_img: Image.Image):
    """从左右双拼原图中自动检测左（红涨瞭望款 bull）与右（绿跌闭眼款 bear）两枚发光圆角图标框。"""
    rgb = dual_img.convert('RGB')
    w, h = rgb.size
    arr = np.array(rgb)
    cy = h // 2
    row_mid = arr[cy, :, :].mean(axis=1)

    lx = np.where((np.arange(w) > 30) & (np.arange(w) < w // 2 - 10) & (row_mid > 80))[0]
    rx = np.where((np.arange(w) > w // 2 + 10) & (np.arange(w) < w - 30) & (row_mid > 80))[0]
    if len(lx) < 10 or len(rx) < 10:
        raise RuntimeError('Failed to detect left and right icon frames in dual source image')

    def _crop_half(xs_arr):
        x0, x1 = int(xs_arr.min()), int(xs_arr.max())
        cx = (x0 + x1) // 2
        ys_arr = np.where((np.arange(h) > 30) & (np.arange(h) < h - 30) & (arr[:, cx, :].mean(axis=1) > 80))[0]
        y0, y1 = int(ys_arr.min()), int(ys_arr.max())
        # 向内收缩 8px 彻底切除四条直边外框及内发光余辉，配合圆角遮罩同时切净四角弧形光边
        inset = 8
        return rgb.crop((
            max(0, x0 + inset),
            max(0, y0 + inset),
            min(w, x1 + 1 - inset),
            min(h, y1 + 1 - inset),
        ))

    bull_crop = _crop_half(lx)
    bear_crop = _crop_half(rx)
    return _apply_rounded_alpha_mask(bull_crop, 1024, radius_ratio=0.228), _apply_rounded_alpha_mask(bear_crop, 1024, radius_ratio=0.228)


def make_macos_hig_canvas(fullbleed_icon: Image.Image, canvas_size: int) -> Image.Image:
    """按 Apple macOS Big Sur+ HIG 规范将圆角图标按 824/1024 比例居中于透明画布，对齐系统原生 Dock 尺寸。"""
    inner = max(1, int(round(canvas_size * (824.0 / 1024.0))))
    scaled = fullbleed_icon.resize((inner, inner), Image.Resampling.LANCZOS)
    canvas = Image.new('RGBA', (canvas_size, canvas_size), (0, 0, 0, 0))
    offset = (canvas_size - inner) // 2
    canvas.paste(scaled, (offset, offset), scaled)
    return canvas


def _save_icns(fullbleed_1024: Image.Image, icns_path: str):
    if sys.platform == 'darwin' and shutil.which('iconutil'):
        with tempfile.TemporaryDirectory() as tmp:
            iconset_dir = os.path.join(tmp, 'Floe.iconset')
            os.makedirs(iconset_dir, exist_ok=True)
            spec_sizes = [
                (16, 'icon_16x16.png'),
                (32, 'icon_16x16@2x.png'),
                (32, 'icon_32x32.png'),
                (64, 'icon_32x32@2x.png'),
                (128, 'icon_128x128.png'),
                (256, 'icon_128x128@2x.png'),
                (256, 'icon_256x256.png'),
                (512, 'icon_256x256@2x.png'),
                (512, 'icon_512x512.png'),
                (1024, 'icon_512x512@2x.png'),
            ]
            for px, filename in spec_sizes:
                make_macos_hig_canvas(fullbleed_1024, px).save(os.path.join(iconset_dir, filename), format='PNG')
            subprocess.run(['iconutil', '-c', 'icns', iconset_dir, '-o', icns_path], check=True)
    else:
        make_macos_hig_canvas(fullbleed_1024, 1024).save(icns_path, format='ICNS')


def extract_menubar_penguin(mono_img: Image.Image):
    """提取黑白企鹅剪影并转为透明背景抗锯齿 Alpha 模板图像。"""
    arr = np.array(mono_img.convert('RGB'), dtype=np.float32)
    h, w, _ = arr.shape
    top_cut = int(h * 0.08)
    gray = arr.mean(axis=2)
    valid_mask = gray.copy()
    valid_mask[:top_cut, :] = 0.0

    ys, xs = np.where(valid_mask > 130.0)
    if len(xs) == 0 or len(ys) == 0:
        raise RuntimeError('Failed to locate monochrome penguin silhouette')

    x0, x1 = int(xs.min()), int(xs.max())
    y0, y1 = int(ys.min()), int(ys.max())
    pw, ph = x1 - x0 + 1, y1 - y0 + 1
    side = int(round(max(pw, ph) * 1.12))
    cx = (x0 + x1) / 2.0
    cy = (y0 + y1) / 2.0
    left = max(0, int(round(cx - side / 2.0)))
    top = max(top_cut, int(round(cy - side / 2.0)))
    crop_gray = gray[top:min(h, top + side), left:min(w, left + side)]

    alpha_f = np.clip((crop_gray - 58.0) / (220.0 - 58.0), 0.0, 1.0)
    alpha_u8 = (alpha_f * 255.0).astype(np.uint8)

    ch, cw = alpha_u8.shape
    sq = max(ch, cw)
    alpha_sq = np.zeros((sq, sq), dtype=np.uint8)
    oy = (sq - ch) // 2
    ox = (sq - cw) // 2
    alpha_sq[oy:oy + ch, ox:ox + cw] = alpha_u8

    black_rgba = np.zeros((sq, sq, 4), dtype=np.uint8)
    black_rgba[:, :, 3] = alpha_sq

    white_rgba = np.full((sq, sq, 4), 255, dtype=np.uint8)
    white_rgba[:, :, 3] = alpha_sq

    return Image.fromarray(black_rgba), Image.fromarray(white_rgba)


def build_all_icons(dual_source_path: str, mono_source_path: str, project_root: str):
    static_icons = os.path.join(project_root, 'static', 'icons')
    pkg_icons = os.path.join(project_root, 'packaging', 'icons')
    os.makedirs(static_icons, exist_ok=True)
    os.makedirs(pkg_icons, exist_ok=True)

    bull_1024, bear_1024 = extract_dual_color_icons(Image.open(dual_source_path))

    for variant, img_1024 in (('bull', bull_1024), ('bear', bear_1024)):
        img_1024.resize((512, 512), Image.Resampling.LANCZOS).save(
            os.path.join(static_icons, f'floe_icon_{variant}.png'), format='PNG'
        )
        img_1024.resize((64, 64), Image.Resampling.LANCZOS).save(
            os.path.join(static_icons, f'favicon_{variant}.png'), format='PNG'
        )
        img_1024.save(
            os.path.join(pkg_icons, f'floe_{variant}.ico'),
            format='ICO',
            sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
        )
        _save_icns(img_1024, os.path.join(pkg_icons, f'floe_{variant}.icns'))

    # 默认图标指向红涨瞭望款 (bull)
    shutil.copyfile(os.path.join(static_icons, 'floe_icon_bull.png'), os.path.join(static_icons, 'floe_icon.png'))
    shutil.copyfile(os.path.join(static_icons, 'favicon_bull.png'), os.path.join(static_icons, 'favicon.png'))
    shutil.copyfile(os.path.join(pkg_icons, 'floe_bull.ico'), os.path.join(pkg_icons, 'floe.ico'))
    shutil.copyfile(os.path.join(pkg_icons, 'floe_bull.icns'), os.path.join(pkg_icons, 'floe.icns'))

    if mono_source_path and os.path.isfile(mono_source_path):
        tmpl_black, tray_white = extract_menubar_penguin(Image.open(mono_source_path))
        tmpl_black.resize((18, 18), Image.Resampling.LANCZOS).save(
            os.path.join(pkg_icons, 'menubar_template.png'), format='PNG'
        )
        tmpl_black.resize((36, 36), Image.Resampling.LANCZOS).save(
            os.path.join(pkg_icons, 'menubar_template@2x.png'), format='PNG'
        )
        tmpl_black.resize((64, 64), Image.Resampling.LANCZOS).save(
            os.path.join(static_icons, 'menubar_template.png'), format='PNG'
        )
        tray_white.resize((64, 64), Image.Resampling.LANCZOS).save(
            os.path.join(pkg_icons, 'tray_icon_white.png'), format='PNG'
        )
        tray_white.resize((64, 64), Image.Resampling.LANCZOS).save(
            os.path.join(static_icons, 'menubar_icon_white.png'), format='PNG'
        )

    print('Built dual Floe icons (bull & bear) + menubar icons successfully!')


if __name__ == '__main__':
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    default_dual = os.path.join(root, 'packaging', 'icons', 'source_dual_icons.jpg')
    default_mono = os.path.join(root, 'packaging', 'icons', 'source_menubar.jpg')
    dual_arg = sys.argv[1] if len(sys.argv) >= 2 else default_dual
    mono_arg = sys.argv[2] if len(sys.argv) >= 3 else default_mono
    build_all_icons(dual_arg, mono_arg, root)
