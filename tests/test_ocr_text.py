from snapanswer.ocr_text import (
    OcrLine,
    compact_text,
    is_new_question,
    lines_to_text,
    normalize_text,
    should_reanswer,
    similarity,
)


def test_normalize_text() -> None:
    raw = "  第一行\t内容 \r\n\r\n 第二行\u200b  \n"
    assert normalize_text(raw) == "第一行 内容\n第二行"


def test_lines_are_sorted_and_deduplicated() -> None:
    lines = [
        OcrLine("B. 选项二", 0.9, (10, 60, 150, 80)),
        OcrLine("A. 选项一", 0.9, (10, 30, 150, 50)),
        OcrLine("A. 选项一", 0.9, (10, 30, 150, 50)),
        OcrLine("题目：1+1=?", 0.95, (10, 0, 200, 20)),
    ]
    assert lines_to_text(lines) == "题目：1+1=?\nA. 选项一\nB. 选项二"


def test_low_confidence_is_filtered() -> None:
    lines = [
        OcrLine("噪声", 0.1, (0, 0, 10, 10)),
        OcrLine("真实题目", 0.9, (0, 20, 10, 30)),
    ]
    assert lines_to_text(lines, min_confidence=0.5) == "真实题目"


def test_similarity_and_new_question() -> None:
    assert similarity("1 + 1 = ?", "1+1=?") == 1.0
    assert similarity("", "") == 1.0
    assert similarity("abc", "") == 0.0
    assert is_new_question("第一道完全不同的题目", "另一道不相关的题干")
    assert not is_new_question("第一道完全不同的题目", "第一道完全不同的题日")
    assert not is_new_question("短", "")


def test_compact_text() -> None:
    assert compact_text(" A b\n C ") == "AbC"


def test_should_reanswer_detects_material_change() -> None:
    previous = "1. 下列关于 Python 的说法，哪一项是正确的？ A. 解释型 B. 编译型"
    assert not should_reanswer(previous, previous)
    assert not should_reanswer(previous, previous.replace("Python", "python"))
    assert should_reanswer(
        previous,
        "2. 请计算 7 // 2 的结果。 A. 3 B. 3.5 C. 4",
        threshold=0.9,
    )
    assert should_reanswer(previous, previous + " C. 两者都是", threshold=1.0)
    assert not should_reanswer(previous, "短", threshold=1.0)


def test_should_reanswer_empty_previous() -> None:
    assert should_reanswer("", "新的题目内容", threshold=0.95)
    assert not should_reanswer("旧题目内容", "", threshold=0.95)
