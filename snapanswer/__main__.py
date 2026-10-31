"""Command-line entry point for SnapAnswer."""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import logging
import shutil
import sys
import traceback
from datetime import datetime
from pathlib import Path

from . import __version__
from .config import (
    Config,
    ConfigError,
    fallback_config_path,
    load_config,
    masked_api_key,
    resolve_config_path,
    save_config,
    validate_config,
)
from .logging_setup import install_qt_message_handler, log_dir, setup_logging

log = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="snapanswer",
        description="截图 OCR + AI 答题浮窗",
    )
    parser.add_argument("--config", help="指定配置文件路径")
    parser.add_argument("--version", action="version", version=f"SnapAnswer {__version__}")
    parser.add_argument("--debug", action="store_true", help="输出调试日志")
    parser.add_argument(
        "--check",
        action="store_true",
        help="检查配置与依赖，不启动图形界面",
    )
    parser.add_argument(
        "--ocr",
        metavar="IMAGE",
        help="对指定图片执行 OCR 并输出文字（用于测试）",
    )
    parser.add_argument(
        "--ask",
        metavar="QUESTION",
        help="直接把题目发送给模型并输出答案（用于测试 API）",
    )
    return parser


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def run_check(config_path: str | None) -> int:
    issues: list[str] = []
    cfg: Config
    try:
        cfg, path = load_config(config_path)
    except (ConfigError, OSError) as exc:
        print(f"配置错误：{exc}", file=sys.stderr)
        return 1
    print(f"SnapAnswer {__version__}")
    print(f"Python      : {sys.version.split()[0]}")
    print(f"平台        : {sys.platform}")
    print(f"配置文件    : {path}")
    print(f"日志目录    : {log_dir()}")
    print(f"模型地址    : {cfg.llm.base_url}")
    print(f"模型名称    : {cfg.llm.model}")
    print(f"API Key     : {masked_api_key(cfg)}")
    print(f"OCR 引擎    : {cfg.ocr.engine}")

    required = {
        "PyQt6": "PyQt6",
        "httpx": "httpx",
        "numpy": "numpy",
        "Pillow": "PIL",
        "rapidocr": "rapidocr_onnxruntime",
        "pynput": "pynput",
        "tomli_w": "tomli_w",
    }
    print("\n依赖：")
    for label, module in required.items():
        ok = _module_available(module)
        print(f"  {'OK ' if ok else 'MISS'}  {label}")
        if not ok:
            issues.append(f"缺少依赖 {label}（模块 {module}）")
    issues.extend(validate_config(cfg))
    if issues:
        print("\n发现问题：")
        for issue in issues:
            print(f"  - {issue}")
        return 1
    print("\n检查通过。")
    return 0


def run_ocr(config_path: str | None, image_path: str) -> int:
    from PIL import Image

    from .ocr import OcrError, RapidOcrEngine

    try:
        cfg, _ = load_config(config_path)
    except (ConfigError, OSError) as exc:
        print(f"配置错误：{exc}", file=sys.stderr)
        return 1
    try:
        image = Image.open(image_path)
        image.load()
    except OSError as exc:
        print(f"无法打开图片：{exc}", file=sys.stderr)
        return 1
    try:
        result = RapidOcrEngine(cfg.ocr).recognize(image)
    except OcrError as exc:
        print(f"OCR 失败：{exc}", file=sys.stderr)
        return 2
    print(result.text)
    return 0


def run_ask(config_path: str | None, question: str) -> int:
    from .config import resolve_api_key
    from .llm import LlmClient, LlmError

    try:
        cfg, _ = load_config(config_path)
    except (ConfigError, OSError) as exc:
        print(f"配置错误：{exc}", file=sys.stderr)
        return 1
    client = LlmClient(cfg.llm, resolve_api_key(cfg))
    try:
        result = client.complete(
            question,
            on_delta=lambda text: print(text, end="", flush=True),
        )
    except LlmError as exc:
        print(f"\n模型请求失败：{exc}", file=sys.stderr)
        return 2
    print()
    print(f"\n[{result.model} · {result.elapsed_sec:.1f}s]", file=sys.stderr)
    if result.usage is not None:
        from .usage import snapshot_from_usage

        usage = result.usage
        snapshot = snapshot_from_usage(
            usage,
            model=result.model,
            elapsed_sec=result.elapsed_sec,
            settings=cfg.usage,
        )
        source = "API" if usage.source == "api" else "估算"
        print(
            f"[{source} tokens: 输入 {usage.prompt_tokens:,} / 输出 "
            f"{usage.completion_tokens:,} / 合计 {usage.total_tokens:,} · "
            f"费用 {snapshot.formatted_cost()}]",
            file=sys.stderr,
        )
    return 0


def _recover_config(config_path: str | None, error: Exception) -> tuple[Config, Path]:
    """Back up a broken config, create defaults, and report through Qt."""
    from PyQt6.QtWidgets import QMessageBox

    path = resolve_config_path(config_path)
    backup: Path | None = None
    if path.exists():
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = path.with_name(f"{path.stem}.broken-{stamp}{path.suffix}")
        try:
            shutil.copy2(path, backup)
        except OSError:
            backup = None
    cfg = Config()
    try:
        save_config(cfg, path)
    except OSError:
        path = fallback_config_path()
        save_config(cfg, path)
    detail = f"\n\n原文件已备份到：\n{backup}" if backup else ""
    QMessageBox.warning(
        None,
        "配置文件损坏",
        f"读取配置失败：\n{error}{detail}\n\n已恢复为默认配置，请重新填写模型信息。",
    )
    return cfg, path


def run_gui(config_path: str | None) -> int:
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QGuiApplication
    from PyQt6.QtWidgets import QApplication, QMessageBox

    from .app import SnapAnswerApp

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication([sys.argv[0]])
    app.setApplicationName("SnapAnswer")
    app.setApplicationDisplayName("SnapAnswer")
    app.setOrganizationName("SnapAnswer")
    app.setDesktopFileName("snapanswer")
    app.setQuitOnLastWindowClosed(False)
    install_qt_message_handler()

    try:
        cfg, path = load_config(config_path)
    except ConfigError as exc:
        log.exception("Config load failed")
        try:
            cfg, path = _recover_config(config_path, exc)
        except Exception as recover_exc:  # pragma: no cover
            QMessageBox.critical(None, "无法启动", f"配置损坏且无法恢复：\n{recover_exc}")
            return 1
    except OSError as exc:
        QMessageBox.critical(None, "无法启动", f"读取或创建配置失败：\n{exc}")
        return 1

    issues = validate_config(cfg)
    if issues:
        log.warning("Config issues: %s", issues)

    try:
        controller = SnapAnswerApp(app, cfg, path)
        app.setWindowIcon(controller._make_icon())
        app.aboutToQuit.connect(controller.shutdown)
        controller.start()
    except Exception as exc:  # pragma: no cover - startup failure path
        log.exception("Startup failed")
        QMessageBox.critical(None, "SnapAnswer 启动失败", f"{exc}\n\n日志：{log_dir()}")
        return 1
    return app.exec()


def _install_exception_hook() -> None:
    def hook(exc_type, exc_value, exc_tb):  # noqa: ANN001
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        log.critical(
            "Unhandled exception:\n%s",
            "".join(traceback.format_exception(exc_type, exc_value, exc_tb)),
        )
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = hook


def _force_utf8_console() -> None:
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None or not hasattr(stream, "reconfigure"):
            continue
        with contextlib.suppress(OSError, ValueError):
            stream.reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _force_utf8_console()
    setup_logging(args.debug)
    _install_exception_hook()
    if args.check:
        return run_check(args.config)
    if args.ocr:
        return run_ocr(args.config, args.ocr)
    if args.ask:
        return run_ask(args.config, args.ask)
    return run_gui(args.config)


if __name__ == "__main__":
    raise SystemExit(main())
