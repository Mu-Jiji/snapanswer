# 启动流程图可行性说明

对应脚本：[`bootstrap.ps1`](../bootstrap.ps1) 与 [`run.bat`](../run.bat)。

## 对原流程图的判断

原流程：

```text
定位至当前目录
  ↓
检测是否安装成功
  ├─ 是 → 运行
  └─ 否 → 判断 Python 是否加入环境变量
            ├─ 是 → 安装依赖 → 运行
            └─ 否 → 安装 Python 并加入环境 → 安装依赖 → 运行
```

结论：**整体方向可行，但不能直接照搬**。

主要问题：

1. **“检测是否安装成功”含义不明确**  
   应拆成两件事：Python 是否可用、项目依赖是否齐全。即使 Python 已安装，首次运行仍需安装依赖；原图“是 → 运行”会直接跳过依赖安装。

2. **“Python 是否加入环境变量”不能代表是否已安装**  
   Python 已安装但不在 PATH 时，不需要重新安装 Python；找到 `python.exe` 的绝对路径即可。原图“在 PATH → 安装依赖”与实际场景不符。

3. **自动安装 Python 不是无条件可行的**  
   需要网络、winget/安装包，部分环境还需要管理员权限。脚本只能“尽力自动安装”，失败时应给出官方下载入口。

4. **依赖安装应发生在虚拟环境中**  
   直接装到系统 Python 容易污染环境；应先创建 `.venv`。

5. **缺少安装后的验证步骤**  
   安装完成后应再次检查 Python 版本、依赖导入和配置，再启动。

## 修正后的流程

```text
定位脚本目录
  ↓
查找 Python 3.10–3.12
  ├─ 找到 → 创建/复用 .venv
  └─ 没找到 → winget 安装 Python 3.12
                 ├─ 成功 → 创建 .venv
                 └─ 失败 → 打开下载页并退出
  ↓
检查依赖
  ├─ 缺失 → pip install -e .
  └─ 完整 → 继续
  ↓
python -m snapanswer --check
  ├─ 失败 → 输出错误并退出
  └─ 通过 → 启动 GUI
```

## 脚本对应关系

| 流程图步骤 | 脚本实现 |
| --- | --- |
| 定位至当前目录 | `Set-Location $PSScriptRoot` |
| 检测 Python | `Find-Python`：py launcher → PATH → 常见路径 → 注册表 |
| Python 是否加入 PATH | 不强制要求；找到后使用绝对路径 |
| 安装 Python | `Install-Python`：winget 用户级安装 Python 3.12 |
| 安装依赖 | 创建 `.venv`，导入检查失败时 `pip install -e .` |
| 检测是否安装成功 | 依赖导入检查 + `snapanswer --check` |
| 运行 | `python -m snapanswer` |

## 使用

```powershell
.\run.bat
```

只检查环境、不启动 GUI：

```powershell
.\run.bat -CheckOnly
```
