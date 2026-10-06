# 第三方组件 / Third-party components

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
