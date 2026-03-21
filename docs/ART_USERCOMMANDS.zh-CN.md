# ART 用户命令指南

[English](ART_USERCOMMANDS.md) | 简体中文

本文档说明如何在 Windows 上把 Grain Splitter 的用户命令安装到 ART 中。

## 参考链接

- [ART 仓库](https://github.com/artpixls/ART)
- [ART User Commands 官方文档](https://artraweditor.github.io/Usercommands)

## 这个集成会做什么

安装完成后，ART 的用户命令菜单中会出现两条 Grain Splitter 命令：

- `Open in Grain Splitter`
- `Open Folder in Grain Splitter`

这两条命令会把 ART 当前选中的文件或整个文件夹传给 Grain Splitter，让你可以从 ART 里直接打开。

## 开始之前

请先确认下面几项已经准备好：

1. 你的 Windows 系统里已经安装了 ART。
2. Grain Splitter 仓库已经克隆到本地。
3. Grain Splitter 的依赖已经安装到虚拟环境中。
4. 项目目录中存在以下文件：
   `main.py`
   `install_art_usercommands.ps1`

如果你还没有安装 Grain Splitter，请先阅读 [安装指南](INSTALLATION.zh-CN.md)。

## 安装步骤

### 1. 完全关闭 ART

ART 在运行时可能会缓存用户命令，所以安装或更新 Grain Splitter 命令前，先把 ART 完全退出。

### 2. 在项目目录中打开 PowerShell

例如：

```powershell
cd D:\neg_splitter_gui
```

### 3. 运行 ART 安装脚本

```powershell
powershell -ExecutionPolicy Bypass -File .\install_art_usercommands.ps1
```

## 安装脚本会做什么

安装脚本会把用户命令文件写入：

```text
%LOCALAPPDATA%\ART\usercommands
```

它会安装这些文件：

- `grain_splitter_files.txt`
- `grain_splitter_files.cmd`
- `grain_splitter_folder.txt`
- `grain_splitter_folder.cmd`

它还会自动检测项目脚本路径和可用的 Python 解释器，然后让 ART 最终调用：

```text
pythonw.exe main.py
```

ART 的 `.txt` 文件会使用官方文档里的用户命令格式，例如：

```text
Command=cmd.exe /c .\grain_splitter_files.cmd
Command=cmd.exe /c .\grain_splitter_folder.cmd
```

## 4. 重新启动 ART

安装完成后，再重新打开 ART。

## 5. 在 ART 中使用这些命令

### 打开选中的文件

1. 在 ART 中选中一个或多个文件。
2. 打开 ART 的用户命令菜单。
3. 运行 `Open in Grain Splitter`。

### 打开整个文件夹

1. 在 ART 中选择对应的文件夹工作流入口。
2. 打开 ART 的用户命令菜单。
3. 运行 `Open Folder in Grain Splitter`。

## 故障排查

### ART 能启动 Grain Splitter，但没有自动读入文件

1. 完全关闭 ART。
2. 重新运行安装脚本。
3. 再重新打开 ART。

### 路径里有空格或特殊字符

当前安装脚本已经针对 Windows 下通过 ART 用户命令层传入的空格路径和常见特殊字符做了兼容处理。

### ART 里看不到用户命令

请检查下面这个目录里是否已经生成了相关文件：

```text
%LOCALAPPDATA%\ART\usercommands
```

如果没有，请回到 Grain Splitter 项目目录，再运行一次安装脚本。
