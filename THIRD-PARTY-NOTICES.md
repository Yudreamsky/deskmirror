# 第三方组件 / Third-party components

## 源码 / Source code

本仓库不包含下列组件：运行 `setup.bat` 时由 pip 从 PyPI 安装。文字识别模型随 RapidOCR 的安装包一起安装；
韩文识别模型在第一次选“原文：韩文”时由 RapidOCR 从 ModelScope 下载。

These components are not included in this repository. They are installed from PyPI by `setup.bat`. The OCR models
come with the RapidOCR package; the Korean model is downloaded by RapidOCR from ModelScope when Korean is first selected.

| 组件 Component | 用途 Used for | 许可证 License | 主页 Homepage |
|---|---|---|---|
| Qt for Python (PySide6) | 界面 / user interface | LGPL-3.0 | https://www.qt.io/qt-for-python |
| RapidOCR | 文字识别 / OCR | Apache-2.0 | https://github.com/RapidAI/RapidOCR |
| PaddleOCR 模型 (PP-OCR) / models | 文字识别模型 / OCR models | Apache-2.0 | https://github.com/PaddlePaddle/PaddleOCR |
| ONNX Runtime (DirectML) | 运行识别模型 / model inference | MIT | https://github.com/microsoft/onnxruntime |
| OpenCV | 图像处理 / image processing | Apache-2.0 | https://opencv.org |
| NumPy | 数值计算 / arrays | BSD-3-Clause | https://numpy.org |
| HTTPX | 调用翻译服务 / HTTP client | BSD-3-Clause | https://www.python-httpx.org |
| python-mss | 截屏 / screen capture | MIT | https://github.com/BoboTiG/python-mss |

PySide6 以未修改的动态库形式使用，可以换成你自己编译的版本。
PySide6 is used unmodified as dynamically linked libraries and can be replaced with your own build.

## Windows 发行包 / Windows release (zip)

GitHub Releases 上的 zip 是用 PyInstaller 打包的：上面这些组件（含韩文识别模型）都在里面，另外还有：

The zip on GitHub Releases is built with PyInstaller. It contains all of the components above (including the Korean
OCR model) and also:

| 组件 Component | 许可证 License | 主页 Homepage |
|---|---|---|
| Python 3.12 运行时 / runtime（含 OpenSSL、libffi、zlib、bzip2、xz、expat） | PSF-2.0（各库见各自许可证） | https://www.python.org |
| PyInstaller 启动器 / bootloader | GPL-2.0-or-later，带启动器例外条款 / with the bootloader exception | https://pyinstaller.org |
| Microsoft Visual C++ 运行库 / runtime | Microsoft Visual C++ Redistributable 许可 | https://learn.microsoft.com/cpp/windows/latest-supported-vc-redist |
| DirectML（随 ONNX Runtime） | Microsoft DirectML 许可 / license | https://github.com/microsoft/DirectML |
| Pillow、Shapely（含 GEOS，LGPL-2.1）、pyclipper、OmegaConf、ANTLR 运行库、PyYAML、requests、urllib3、certifi、charset-normalizer、idna、anyio、h11、httpcore、tqdm、colorlog、colorama、typing_extensions、packaging、setuptools | 各自的许可证 / see each license | — |

所有许可证原文在发行包的 `licenses` 文件夹里（每个组件一个子文件夹）。Qt、shiboken6 和 GEOS 都是单独的 DLL，
可以换成你自己编译的版本。桌面魔镜本身的源代码就是本仓库（对应的版本标签，如 `v1.0.0`）。

The full license texts are in the `licenses` folder of the release (one subfolder per component). Qt, shiboken6 and
GEOS are separate DLLs and can be replaced with your own builds. The corresponding source code of DeskMirror is this
repository at the matching tag (e.g. `v1.0.0`).
