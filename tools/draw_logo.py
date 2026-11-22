# Genera il logo (fulmine + fiamma). Uso: python tools/draw_logo.py > logo.png  (richiede Pillow)
import io, sys
from PIL import Image, ImageDraw
K = 8; W = 256 * K
BG = (21, 101, 192); FG = (255, 255, 255)

def cubic(p0, p1, p2, p3, n=48):
    return [tuple((1-t)**3*a + 3*(1-t)**2*t*b + 3*(1-t)*t*t*c + t**3*e for a, b, c, e in zip(p0, p1, p2, p3))
            for t in (i/n for i in range(n+1))]

def path(start, segs):
    pts, cur = [], start
    for c1, c2, end in segs:
        pts += cubic(cur, c1, c2, end); cur = end
    return [(x*K, y*K) for x, y in pts]

img = Image.new("RGB", (W, W), BG); d = ImageDraw.Draw(img)
dx = int(sys.argv[1]) if len(sys.argv) > 1 else 0
bolt = [(102, 36), (44, 144), (86, 144), (68, 224), (132, 112), (92, 112), (120, 36)]
d.polygon([(x*K, y*K) for x, y in bolt], fill=FG)
outer = path((176, 224), [
    ((148, 224), (130, 205), (130, 180)),
    ((130, 152), (152, 134), (158, 108)),
    ((161, 92), (158, 74), (150, 52)),
    ((186, 68), (222, 110), (222, 172)),
    ((222, 202), (202, 224), (176, 224)),
])
inner = path((178, 214), [
    ((162, 214), (152, 203), (152, 190)),
    ((152, 176), (162, 168), (166, 156)),
    ((168, 148), (167, 140), (163, 128)),
    ((186, 140), (204, 162), (204, 188)),
    ((204, 204), (193, 214), (178, 214)),
])
d.polygon(outer, fill=FG); d.polygon(inner, fill=BG)
out = img.resize((256, 256), Image.LANCZOS)
buf = io.BytesIO(); out.save(buf, "PNG", optimize=True); sys.stdout.buffer.write(buf.getvalue())
