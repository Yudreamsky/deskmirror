"""生成 exe 的图标 packaging/deskmirror.ico：和托盘图标一样，蓝底白字“镜”。改了托盘图标的样子再跑一次。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import deskmirror  # noqa: E402,F401  预加载系统 DLL
from PIL import Image  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter  # noqa: E402

from deskmirror.config import StyleConfig  # noqa: E402

app = QGuiApplication([])
S = 256
img = QImage(S, S, QImage.Format.Format_ARGB32)
img.fill(QColor(0, 0, 0, 0))
p = QPainter(img)
p.setRenderHint(QPainter.RenderHint.Antialiasing)
p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
k = S / 64                                   # 按托盘图标（64×64）的比例放大
p.setBrush(QColor(StyleConfig().border_color))
p.setPen(QColor(255, 255, 255))
p.drawRoundedRect(4 * k, 4 * k, 56 * k, 56 * k, 12 * k, 12 * k)
f = QFont("Microsoft YaHei UI")
f.setPixelSize(int(36 * k))
f.setBold(True)
p.setFont(f)
p.drawText(img.rect(), Qt.AlignmentFlag.AlignCenter, "镜")
p.end()
png = ROOT / "build" / "icon_256.png"
png.parent.mkdir(exist_ok=True)
img.save(str(png))
out = ROOT / "packaging" / "deskmirror.ico"
Image.open(png).save(out, sizes=[(16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48), (64, 64), (128, 128),
                                 (256, 256)])
print(out)
