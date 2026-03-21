# 安装指南

[English](INSTALLATION.md) | 简体中文

本文档介绍 Grain Splitter 的标准本地安装步骤。

## 1. 克隆仓库

```bash
git clone https://github.com/Zwiengli/grain-splitter.git
cd grain-splitter
```

## 2. 创建并激活虚拟环境

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### Windows 命令提示符

```bat
python -m venv .venv
.\.venv\Scripts\activate.bat
```

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
```

## 3. 安装依赖

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## 4. 安装可选运行时依赖

```bash
python -m pip install -r requirements-optional.txt
```

当前没有额外需要安装的运行时读图依赖。Grain Splitter 现在会默认用 `tifffile` 打开 `FFF` / `TIFF` / `TIF`，只有在没有安装 `tifffile` 时才回退到 `OpenCV`；其他格式则直接使用 `OpenCV`。

## 5. 运行程序

```bash
python main.py
```

下面这个兼容入口同样可用：

```bash
python neg_splitter.py
```
