"""Bakes the window background: cover art, darkened, with flat panels behind the UI."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

W, H = 1000, 680
PANEL = (18, 22, 30)
HERE = Path(__file__).resolve().parent


def build():
    src = Image.open(HERE / 'assets' / 'background.png').convert('RGB')

    # Fill the window, biased downwards so the box-art logo sits below the
    # title bar instead of fighting with it.
    scale = max(W / src.width, H / src.height) * 1.25
    img = src.resize((int(src.width * scale), int(src.height * scale)), Image.LANCZOS)
    left = (img.width - W) // 2
    top = int((img.height - H) * 0.62)
    img = img.crop((left, top, left + W, top + H))

    img = ImageEnhance.Brightness(img).enhance(0.62)
    img = ImageEnhance.Color(img).enhance(0.9)
    img = Image.blend(img, Image.new('RGB', (W, H), (8, 12, 20)), 0.28)

    # A dark band under the header so the title always reads cleanly.
    band = Image.new('L', (W, H), 0)
    d = ImageDraw.Draw(band)
    for y in range(120):
        d.line([(0, y), (W, y)], fill=int(210 * (1 - y / 120.0)))
    img = Image.composite(Image.new('RGB', (W, H), (6, 9, 16)), img, band)

    blurred = img.filter(ImageFilter.GaussianBlur(9))
    out = img.copy()

    def panel(box, alpha):
        region = blurred.crop(box)
        flat = Image.new('RGB', region.size, PANEL)
        out.paste(Image.blend(region, flat, alpha), box)

    panel((16, 96, 376, 664), 0.86)      # list panel
    panel((388, 96, 984, 664), 0.86)     # detail panel

    edge = ImageDraw.Draw(out)
    for box in ((16, 96, 375, 663), (388, 96, 983, 663)):
        edge.rectangle(box, outline=(38, 48, 68))

    out.save(HERE / 'assets' / 'bg.png')
    print('wrote assets/bg.png', out.size)


if __name__ == '__main__':
    build()
