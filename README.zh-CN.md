# Grain Splitter

[English](README.md) | 简体中文

[License](LICENSE)

Grain Splitter 是一个用于自动识别并分割大幅胶片扫描拼图的桌面工具，适合包括哈苏 `FFF` 在内的扫描工作流。项目基于 Python 和 Tkinter，重点面向超大分辨率扫描件的自动识别与手工修正。

## 主要特性

- 直接打开 `FFF`、`TIFF`、`TIF`、`JPG`、`PNG`、`BMP`、`WEBP` 文件。
- 对超大扫描件使用异步首开和低清预览路径，先显示内容，再继续完整加载。
- 自动识别条带、单张边界和扫描方向。
- 支持缩放、拖动、预览切换、手动调整辅助线，以及旋转后的框级编辑。
- 支持多图浏览、`导出当前` 和 `导出全部`。
- 支持调节 `JPEG`、`PNG`、`TIFF` 导出压缩参数。
- 内置英文、简体中文、德语界面。

## 支持的工作流

### 输入格式

- `FFF`
- `TIFF` / `TIF`
- `JPG` / `JPEG`
- `PNG`
- `BMP`
- `WEBP`

### 导出格式

- 尽可能保持原格式
- `JPG`
- `PNG`
- `TIFF`

## 文档

- [文档索引](docs/README.zh-CN.md)
- [安装指南](docs/INSTALLATION.zh-CN.md)
- [ART 用户命令指南](docs/ART_USERCOMMANDS.zh-CN.md)

## 环境要求

- 推荐使用 Python 3.10 及以上版本。
- 大多数 Windows 和 macOS 的 Python 安装包默认包含 `tkinter`。
- 在 Linux 上，可能需要先通过系统包管理器安装 Tk 相关组件，再运行程序。

## 仓库结构

```text
.
├── app/          # GUI、预览画布、设置与界面逻辑
├── core/         # 图像读取、检测、导出与共享常量
├── docs/         # 面向用户的说明文档
├── i18n/         # 界面语言文件
├── config/       # 默认设置与本地用户设置
├── main.py       # 主入口
└── neg_splitter.py
```
