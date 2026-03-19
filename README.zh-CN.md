# Grain Splitter

[English](README.md) | 简体中文

[License](LICENSE) | [许可证说明](LICENSE.zh-CN.md)

Grain Splitter 是一个用于自动识别并分割大幅胶片扫描拼图的桌面工具，适合包括哈苏 `FFF` 在内的扫描工作流。项目基于 Python 和 Tkinter，重点面向超大分辨率扫描件的自动识别与手工修正。

## 主要特性

- 直接打开 `FFF`、`TIFF`、`TIF`、`JPG`、`PNG`、`BMP`、`WEBP` 文件。
- 对超大扫描件使用异步首开和低清预览路径，先显示内容，再继续完整加载。
- 自动识别条带、单张边界和扫描方向。
- 支持缩放、拖动、多图切换、手动调整辅助线，以及旋转后的框级编辑。
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

## 安装方法

### 1. 克隆仓库

```bash
git clone https://github.com/<your-name>/grain-splitter.git
cd grain-splitter
```

### 2. 创建并激活虚拟环境

#### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

#### Windows 命令提示符

```bat
python -m venv .venv
.\.venv\Scripts\activate.bat
```

#### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. 安装依赖

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 4. 安装增强 `FFF` / RAW 兼容性的可选依赖

```bash
python -m pip install -r requirements-optional.txt
```

`rawpy` 是可选项。程序本身已经会尝试 `tifffile`、`Pillow` 和 `OpenCV`，但对于某些更接近 RAW 结构的 `FFF` 文件，安装 `rawpy` 会更稳。

### 5. 运行程序

```bash
python main.py
```

下面这个兼容入口同样可用：

```bash
python neg_splitter.py
```

## 环境要求

- 推荐使用 Python 3.10 及以上版本。
- 大多数 Windows 和 macOS 的 Python 安装包默认包含 `tkinter`。
- Linux 上可能需要先通过系统包管理器安装 Tk 相关组件，再运行程序。

## 仓库结构

```text
.
├─ app/          # GUI、预览画布、设置与界面层逻辑
├─ core/         # 图像读取、检测、导出与共享常量
├─ i18n/         # 界面语言文件
├─ config/       # 默认设置与本地用户设置
├─ main.py       # 主入口
└─ neg_splitter.py
```

## 方便上传 GitHub 的项目文件

- [`requirements.txt`](requirements.txt)：核心运行依赖。
- [`requirements-optional.txt`](requirements-optional.txt)：增强 `FFF` 兼容性的可选依赖。
- [`.gitignore`](.gitignore)：忽略虚拟环境、缓存、本地设置、导出结果和本地大样本文件。
- [`README.md`](README.md)：GitHub 默认英文首页。
- [`LICENSE`](LICENSE)：英文许可证正文。
- [`LICENSE.zh-CN.md`](LICENSE.zh-CN.md)：中文许可证说明与阅读指引。

## 备注

- 项目的用户本地设置保存在 `config/user_settings.json`，该文件默认不会提交到 Git。
- 像 `001.fff` 这样的本地大样本默认会被忽略，以免仓库体积过大。
- 如果你准备公开发布这个项目，建议再补一份符合你使用意图的 `LICENSE` 文件。
