import sys
import os
import subprocess
import json
import re
import argparse
import math
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PIL import Image, ImageOps, ImageEnhance
from PyQt6.QtWidgets import QApplication
from PyQt6.QtQuick import QQuickView
from PyQt6.QtCore import QUrl, QTimer, QRectF, Qt
from PyQt6.QtGui import QImage, QPainter, QColor, QPen

def strip_ansi(text):
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)

def get_scheme_colors():
    colors = {
        "primary_paletteKeyColor": "#7171ac", "secondary_paletteKeyColor": "#76758e", "tertiary_paletteKeyColor": "#9e648e",
        "background": "#131317", "surface": "#131317", "surfaceContainerHigh": "#2a292e", "surfaceContainerHighest": "#353438",
        "surfaceContainer": "#201f23", "primary": "#c2c1ff", "primaryContainer": "#7171ac", "text": "#e5e1e7", "textDark": "#918f9a"
    }
    meta = {
        "Name": "catppuccin", "Flavour": "mocha", "Mode": "dark", "Variant": "tonalspot"
    }
    try:
        output = subprocess.check_output(["caelestia", "scheme", "get"], text=True)
        output = strip_ansi(output)
        in_colours = False
        parsed_colors = {}
        parsed_meta = {}
        for line in output.split('\n'):
            line = line.strip()
            if line.startswith("Colours:"):
                in_colours = True
                continue
            if in_colours and ":" in line:
                key, val = line.split(":", 1)
                parsed_colors[key.strip()] = "#" + val.strip()
            elif ":" in line:
                key, val = line.split(":", 1)
                parsed_meta[key.strip()] = val.strip()
        if parsed_colors:
            colors = parsed_colors
        if parsed_meta:
            meta = parsed_meta
    except Exception as e:
        print("Failed to get scheme, falling back to default Catppuccin Mocha:", e)
        
    if "textDark" not in colors and "subtext0" in colors:
        colors["textDark"] = colors["subtext0"]
    return colors, meta

def get_shell_config():
    config = {
        "transparency_base": 0.75,
        "transparency_layers": 0.4,
        "rounding_scale": 1.0,
        "rounding_window": 16, # Default smaller than before
        "rounding_item": 12,
        "wallpaperRecolor": True,
        "wallpaperRecolorStrength": 1.0,
        "item_height": 48,
        "item_padding": 4,
        "item_spacing": 16,
        "timeout_height": 12
    }
    
    shell_json_path = os.path.expanduser("~/.config/caelestia/shell.json")
    if os.path.exists(shell_json_path):
        try:
            with open(shell_json_path) as f:
                data = json.load(f)
                app = data.get("appearance", {})
                transp = app.get("transparency", {})
                if "base" in transp:
                    config["transparency_base"] = transp["base"]
                if "layers" in transp:
                    config["transparency_layers"] = transp["layers"]
                bg = data.get("background", {})
                if "wallpaperRecolor" in bg:
                    config["wallpaperRecolor"] = bg["wallpaperRecolor"]
                if "wallpaperRecolorStrength" in bg:
                    config["wallpaperRecolorStrength"] = bg["wallpaperRecolorStrength"]
                rounding = app.get("rounding", {})
                if "scale" in rounding:
                    config["rounding_scale"] = rounding["scale"]
        except:
            pass

    tokens_json_path = os.path.expanduser("~/.config/caelestia/shell-tokens.json")
    if os.path.exists(tokens_json_path):
        try:
            with open(tokens_json_path) as f:
                data = json.load(f)
                rounding = data.get("appearance", {}).get("rounding", {})
                if "extraExtraLarge" in rounding:
                    config["rounding_window"] = rounding["extraExtraLarge"]
                if "large" in rounding:
                    config["rounding_item"] = rounding["large"]
                    
                padding = data.get("appearance", {}).get("padding", {})
                if "extraExtraLarge" in padding:
                    config["item_height"] = padding["extraExtraLarge"]
                if "large" in padding:
                    config["item_padding"] = padding["large"]
                    config["timeout_height"] = padding["large"]
                    
                config["item_spacing"] = config.get("item_height", 36) + config.get("item_padding", 12) // 2
        except:
            pass
            
    return config

def get_active_wallpaper():
    path = os.path.expanduser("~/.local/state/caelestia/wallpaper/current")
    if os.path.exists(path):
        return os.path.realpath(path)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "background.png")

def get_luminance(hex_color):
    hex_color = hex_color.lstrip('#')
    if len(hex_color) == 6:
        r, g, b = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
    else:
        return 0
    return (0.299 * r + 0.587 * g + 0.114 * b)

def process_icons(scheme_colors):
    import shutil
    src_dir = "icons"
    dst_dir = "../theme/icons"
    if not os.path.exists(src_dir):
        return
    
    os.makedirs(dst_dir, exist_ok=True)
    text_hex = scheme_colors.get("text", "#ffffff")
    # If text is dark (luminance < 128), we must invert the white icons to black
    invert = get_luminance(text_hex) < 128
    
    for filename in os.listdir(src_dir):
        if not filename.endswith(".png"):
            continue
        src_path = os.path.join(src_dir, filename)
        dst_path = os.path.join(dst_dir, filename)
        
        if invert:
            try:
                img = Image.open(src_path).convert("RGBA")
                r, g, b, a = img.split()
                rgb = Image.merge("RGB", (r, g, b))
                rgb = ImageOps.invert(rgb)
                r2, g2, b2 = rgb.split()
                img = Image.merge("RGBA", (r2, g2, b2, a))
                img.save(dst_path)
            except Exception as e:
                print(f"Failed to process icon {filename}:", e)
        else:
            shutil.copy2(src_path, dst_path)
    print(f"Processed {len(os.listdir(src_dir))} icons (Inverted: {invert})")

def parse_resolution(value):
    match = re.fullmatch(r"(\d+)[xX](\d+)", value or "")
    if not match:
        raise argparse.ArgumentTypeError("Resolution must be WIDTHxHEIGHT, for example 3440x1440")
    width, height = map(int, match.groups())
    if not (640 <= width <= 16384 and 480 <= height <= 16384):
        raise argparse.ArgumentTypeError("Resolution must be between 640x480 and 16384x16384")
    return width, height


def detect_resolution():
    """Prefer an explicit GRUB mode, then the focused Hyprland output's physical pixels."""
    try:
        with open("/etc/default/grub") as f:
            match = re.search(r'^GRUB_GFXMODE=["\']?([^"\'\n#]+)', f.read(), re.M)
        if match:
            first_mode = re.split(r"[,;]", match[1])[0].strip()
            match = re.fullmatch(r"(\d+x\d+)(?:x\d+)?", first_mode)
            if match:
                return parse_resolution(match[1])
    except (OSError, argparse.ArgumentTypeError):
        pass

    try:
        monitors = json.loads(subprocess.check_output(
            ["hyprctl", "-j", "monitors"], text=True, stderr=subprocess.DEVNULL, timeout=5
        ))
        active = [m for m in monitors if isinstance(m, dict) and not m.get("disabled", False)]
        monitor = next((m for m in active if m.get("focused")), next(iter(active), {}))
        width, height = monitor.get("width"), monitor.get("height")
        if monitor.get("transform", 0) in (1, 3, 5, 7):
            width, height = height, width
        return parse_resolution(f"{width}x{height}")
    except (OSError, subprocess.SubprocessError, ValueError, TypeError, argparse.ArgumentTypeError):
        pass

    # Installation may run without a compositor session. Read enabled DRM outputs
    # and use dimensions that fit every active output, including mixed orientations.
    resolutions = []
    for connector in Path("/sys/class/drm").glob("card*-*"):
        try:
            if (connector / "status").read_text().strip() != "connected":
                continue
            if (connector / "enabled").read_text().strip() != "enabled":
                continue
            modes = (connector / "modes").read_text().splitlines()
            if modes:
                resolutions.append(parse_resolution(modes[0]))
        except (OSError, argparse.ArgumentTypeError):
            continue
    if resolutions:
        return min(size[0] for size in resolutions), min(size[1] for size in resolutions)

    # A conservative fallback also fits older firmware using a 4:3 video mode.
    print("Could not detect the boot resolution; using 1024x768. Override with --resolution WIDTHxHEIGHT.")
    return 1024, 768


def get_layout(resolution, timeout_height):
    """Keep the 3:2 panel intact and fit the panel/bar group inside both screen axes."""
    width, height = resolution
    margin = 40
    # One unit is 1/400 of the original 1200x800 panel; integral units preserve its ratio.
    unit = max(1, math.floor(min(400, (width - 2 * margin) / 3,
                                (height - 2 * margin) / (2 + (20 + timeout_height) / 400))))
    scale = unit / 400
    panel_width, panel_height = 3 * unit, 2 * unit
    gap = max(1, round(20 * scale))
    bar_height = max(3, round(timeout_height * scale))
    group_height = panel_height + gap + bar_height
    panel_top = -(group_height // 2)
    padding = max(1, math.ceil(10 * scale))
    menu_width = round(1160 * scale)
    return {
        "scale": scale,
        "panelWidth": panel_width,
        "panelHeight": panel_height,
        "panelTop": panel_top,
        "padding": padding,
        "imageWidth": panel_width + 2 * padding,
        "imageHeight": panel_height + 2 * padding,
        "menuWidth": menu_width,
        "menuHeight": round(620 * scale),
        "menuTop": panel_top + round(90 * scale),
        "barTop": panel_top + panel_height + gap,
        "barHeight": bar_height,
    }


def centered(offset):
    return f"50%{offset:+d}" if offset else "50%"


def update_theme_txt(scheme_colors, shell_cfg, layout):
    theme_txt_path = "../theme/theme.txt"
    with open(theme_txt_path, "r") as f:
        content = f.read()

    geometry = {
        "image": {
            "left": centered(-(layout["imageWidth"] // 2)),
            "top": centered(layout["panelTop"] - layout["padding"]),
            "width": layout["imageWidth"], "height": layout["imageHeight"],
        },
        "boot_menu": {
            "left": centered(-(layout["menuWidth"] // 2)),
            "top": centered(layout["menuTop"]),
            "width": layout["menuWidth"], "height": layout["menuHeight"],
            "item_color": '"' + scheme_colors.get("textDark", "#a2adac") + '"',
            "selected_item_color": '"' + scheme_colors.get("text", "#dce8e6") + '"',
            "item_height": shell_cfg["item_height"],
            "item_padding": shell_cfg["item_padding"],
            "item_spacing": shell_cfg["item_spacing"],
        },
        "progress_bar": {
            "left": centered(-(layout["menuWidth"] // 2)),
            "top": centered(layout["barTop"]),
            "width": layout["menuWidth"], "height": layout["barHeight"],
        },
    }
    for component, properties in geometry.items():
        def update(match):
            block = match.group(0)
            for name, value in properties.items():
                block = re.sub(rf'(?m)^(\s*{name}\s*=\s*)[^\n]+',
                               lambda m: m[1] + str(value), block)
            return block
        content = re.sub(rf'\+ {component} \{{[^}}]*\}}', update, content)

    with open(theme_txt_path, "w") as f:
        f.write(content)


def create_wallpaper(scheme_colors, scheme_meta, shell_cfg):
    """Keep the source aspect ratio so GRUB can crop it for the actual boot viewport."""
    import tempfile
    wp_path = get_active_wallpaper()
    with tempfile.TemporaryDirectory(prefix="caelestia-grub-") as directory:
        if wp_path.lower().endswith(('.mp4', '.mkv', '.webm', '.avi', '.gif', '.mov')):
            frame = os.path.join(directory, "frame.png")
            subprocess.run(
                ["ffmpeg", "-i", wp_path, "-vframes", "1", "-q:v", "2", frame, "-y"],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True
            )
            wp_path = frame
        with Image.open(wp_path) as source:
            img = ImageOps.exif_transpose(source).convert("RGB")
        should_recolor = shell_cfg.get("wallpaperRecolor", True)
        is_dynamic = scheme_meta.get("Name") == "dynamic"
        is_monochrome = scheme_meta.get("Variant") == "monochrome"
        should_recolor_active = should_recolor and (not is_dynamic or is_monochrome)
        if should_recolor and is_dynamic and is_monochrome:
            img = ImageOps.grayscale(img).convert("RGB")
        if should_recolor_active and scheme_meta.get("Flavour") == "hard":
            img = ImageEnhance.Contrast(img).enhance(1.45)
        sharp_path = os.path.join(directory, "sharp.png")
        img.save(sharp_path)
        qimg = QImage(sharp_path)
        if should_recolor_active and not is_monochrome:
            strength = shell_cfg.get("wallpaperRecolorStrength", 1.0)
            if strength > 0:
                painter = QPainter(qimg)
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Overlay)
                painter.setOpacity(strength)
                painter.fillRect(qimg.rect(), QColor(scheme_colors.get("primary", "#9bd0cc")))
                painter.end()
        out_path = os.path.abspath("../theme/background.png")
        if not qimg.save(out_path):
            raise OSError(f"Could not save wallpaper to {out_path}")
    return out_path


def create_panel_bg(scheme_colors, shell_cfg, layout):
    """Render a transparent panel independently of the wallpaper and its crop."""
    img = QImage(layout["imageWidth"], layout["imageHeight"], QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    painter = QPainter(img)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.translate(layout["padding"], layout["padding"])
    painter.scale(layout["scale"], layout["scale"])
    rect = QRectF(0, 0, 1200, 800)
    radius = int(shell_cfg["rounding_window"] * shell_cfg["rounding_scale"])
    primary_color = QColor(scheme_colors.get("primary", "#9bd0cc"))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    for i in range(1, 6):
        glow_color = QColor(primary_color)
        glow_color.setAlpha(int(30 / i))
        painter.setPen(QPen(glow_color, i * 3))
        painter.drawRoundedRect(rect, radius, radius)
    tint = QColor(scheme_colors.get("surfaceContainer", "#131b1a"))
    tint.setAlpha(int(shell_cfg["transparency_base"] * 255))
    painter.setBrush(tint)
    painter.setPen(QPen(primary_color, 1.5))
    painter.drawRoundedRect(rect, radius, radius)
    painter.end()
    out_path = os.path.abspath("../theme/panel_base.png")
    if not img.save(out_path):
        raise OSError(f"Could not save panel to {out_path}")
    return out_path

def generate_9slice(name, bg_color_hex, shell_cfg, border_color_hex=None, radius=None, alpha_override=None, exact_height=None, max_height=None):
    if exact_height is not None:
        h = exact_height
    else:
        if max_height is not None:
            h = max_height
        else:
            h = 42
            
    if radius is None:
        r = int(shell_cfg.get("rounding_item", 12) * shell_cfg.get("rounding_scale", 1.0))
    else:
        r = radius
        
    r = min(r, h // 2)
            
    c_w = max(r, 2)
    
    # Crucial Fix: Make the middle slice (e) as large as possible to contain the whole chevron (if used).
    # This ensures GRUB scales the middle uniformly.
    # We MUST ensure c_h * 2 < h so the middle slice has at least 1px height.
    c_h = r + 2
    if c_h * 2 >= h:
        c_h = max((h - 1) // 2, 1)
    
    mid_w = 20
    w = c_w * 2 + mid_w
    
    img = QImage(w, h, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    painter = QPainter(img)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    
    bg_color = QColor(bg_color_hex)
    if alpha_override is not None:
        bg_color.setAlphaF(alpha_override)
    else:
        bg_color.setAlphaF(shell_cfg.get("transparency_layers", 0.4))
    painter.setBrush(bg_color)
    
    if border_color_hex:
        border_color = QColor(border_color_hex)
        border_color.setAlphaF(0.8)
        painter.setPen(QPen(border_color, 2))
    else:
        painter.setPen(Qt.PenStyle.NoPen)
        
    painter.drawRoundedRect(QRectF(0, 0, w, h), r, r)
        
    painter.end()
    
    parts = {
        "nw": (0, 0, c_w, c_h), 
        "n":  (c_w, 0, mid_w, c_h), 
        "ne": (w - c_w, 0, c_w, c_h),
        "w":  (0, c_h, c_w, h - 2 * c_h), 
        "c":  (c_w, c_h, mid_w, h - 2 * c_h), 
        "e":  (w - c_w, c_h, c_w, h - 2 * c_h),
        "sw": (0, h - c_h, c_w, c_h),
        "s":  (c_w, h - c_h, mid_w, c_h),
        "se": (w - c_w, h - c_h, c_w, c_h)
    }
    
    for suffix, rect in parts.items():
        comp_path = f"../theme/{name}_{suffix}.png"
        part_img = img.copy(rect[0], rect[1], rect[2], rect[3])
        part_img.save(comp_path)

def save_image():
    try:
        img = view.grabWindow().scaled(layout["imageWidth"], layout["imageHeight"],
                                       Qt.AspectRatioMode.IgnoreAspectRatio,
                                       Qt.TransformationMode.SmoothTransformation)
        out_path = os.path.abspath("../theme/panel.png")
        if not img.save(out_path):
            raise OSError(f"Could not save panel to {out_path}")
        print(f"Saved {out_path}")

        grub_rendered_height = max(30 + 2 * shell_cfg.get("item_padding", 12), shell_cfg.get("item_height", 36))
        generate_9slice("item", scheme_colors.get("surfaceContainerHigh", "#192120"), shell_cfg,
                        exact_height=grub_rendered_height)
        generate_9slice("select", scheme_colors.get("surfaceContainerHighest", "#1d2827"), shell_cfg,
                        exact_height=grub_rendered_height)
        generate_9slice("timeout_bg", scheme_colors.get("surfaceContainerHigh", "#192120"), shell_cfg,
                        exact_height=layout["barHeight"], alpha_override=1.0)
        generate_9slice("timeout_hl", scheme_colors.get("primary", "#9bd0cc"), shell_cfg,
                        exact_height=layout["barHeight"], alpha_override=1.0)
        process_icons(scheme_colors)
        update_theme_txt(scheme_colors, shell_cfg, layout)
        app.exit(0)
    except Exception as e:
        print("Error saving:", e, file=sys.stderr)
        app.exit(1)


def main():
    global app, view, scheme_colors, shell_cfg, layout
    parser = argparse.ArgumentParser(description="Generate a centered, aspect-preserving GRUB theme.")
    parser.add_argument("--resolution", type=parse_resolution,
                        help="GRUB viewport WIDTHxHEIGHT; otherwise detect the configured mode or focused monitor")
    parser.add_argument("--preview", action="store_true", help="Render a preview at the target resolution")
    args = parser.parse_args()
    resolution = args.resolution or detect_resolution()
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    os.makedirs("../theme", exist_ok=True)
    app = QApplication([sys.argv[0]])
    scheme_colors, scheme_meta = get_scheme_colors()
    shell_cfg = get_shell_config()
    layout = get_layout(resolution, shell_cfg["timeout_height"])
    print(f"Target: {resolution[0]}x{resolution[1]}; panel: {layout['panelWidth']}x{layout['panelHeight']}")
    try:
        wallpaper_path = create_wallpaper(scheme_colors, scheme_meta, shell_cfg)
        panel_path = create_panel_bg(scheme_colors, shell_cfg, layout)
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        print(f"Could not generate theme: {e}", file=sys.stderr)
        return 1

    with open("theme_config.js", "w") as f:
        f.write(".pragma library\n")
        config = {
            "scheme": scheme_colors,
            "layersTransparency": shell_cfg["transparency_layers"],
            "bgPath": panel_path,
            "wallpaperPath": wallpaper_path,
            "previewMode": args.preview,
            "screenWidth": resolution[0], "screenHeight": resolution[1],
            "layout": layout,
            "itemHeight": shell_cfg["item_height"],
            "itemPadding": shell_cfg["item_padding"],
            "itemSpacing": shell_cfg["item_spacing"],
        }
        for key, value in config.items():
            f.write(f"var {key} = {json.dumps(value)};\n")

    view = QQuickView()
    view.setColor(Qt.GlobalColor.transparent)
    view.setResizeMode(QQuickView.ResizeMode.SizeRootObjectToView)
    view.setSource(QUrl.fromLocalFile(os.path.abspath("theme.qml")))
    if view.status() == QQuickView.Status.Error:
        return 1
    if args.preview:
        view.setGeometry(0, 0, *resolution)
    else:
        view.setGeometry(0, 0, layout["imageWidth"], layout["imageHeight"])
    view.show()
    if args.preview:
        def save_preview():
            path = os.path.abspath("../theme/preview.png")
            saved = view.grabWindow().scaled(*resolution, Qt.AspectRatioMode.IgnoreAspectRatio,
                                            Qt.TransformationMode.SmoothTransformation).save(path)
            print(f"{'Saved' if saved else 'Could not save'} preview to {path}")
            app.exit(0 if saved else 1)
        QTimer.singleShot(1000, save_preview)
    else:
        QTimer.singleShot(1000, save_image)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
