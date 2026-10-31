# Contributing

感谢你对 SnapAnswer 的兴趣。这个项目优先保证：

1. **离线 OCR**：截图不出本机，只有识别出的文字可以发送给模型。
2. **可替换模型**：通过 OpenAI Chat Completions 兼容接口接入云端或本地模型，不把某一家服务写死。
3. **可测试的核心逻辑**：OCR 文本处理、配置、SSE 解析、DPI 裁剪都应与 GUI 解耦。

## 开发环境

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
python -m pip install -e ".[dev]"
```

## 提交前检查

```powershell
ruff check .
pytest -q
```

真实 OCR 模型测试默认跳过，修改 OCR 相关代码时请运行：

```powershell
$env:SNAPANSWER_RUN_OCR_TESTS="1"
pytest -q tests/test_ocr_integration.py
```

## 代码约定

- 不在日志、异常或测试中写入真实 API Key、截图或题目原文。
- GUI 线程不做 OCR 或网络请求；耗时任务放在 `QThread` worker 中。
- 新增配置项时同时更新 `config.example.toml`、默认值、设置界面和 README。
- 修复 bug 时尽量补一个不依赖真实屏幕/真实模型的测试。
- 不要提交 `config.toml`、日志、`.venv` 或构建产物。

## Pull Request

请说明改动目的、验证方式，以及是否涉及隐私（截图、OCR 文本、API Key）或平台差异（高 DPI、多显示器、全局热键）。
