"""Generated Markdown tables must be readable as plain text.

These reports are read in terminals and diffs far more often than they are
rendered; a ragged table is unreadable there (see CLAUDE.md).
"""

from compbench.report.render import align_markdown_tables


def _cols(line):
    return [c for c in line.strip().strip("|").split("|")]


def test_columns_are_padded_to_equal_width():
    src = (
        "| dataset | codec | CR |\n"
        "| --- | --- | ---: |\n"
        "| ibl-CSHZAD029-raw | blosc-zstd | 2.484 |\n"
        "| a | b | 7.12 |\n"
    )
    lines = [l for l in align_markdown_tables(src).split("\n") if l.startswith("|")]
    widths = {tuple(len(c) for c in _cols(l)) for l in lines}
    assert len(widths) == 1, f"ragged table: {widths}"


def test_alignment_colons_survive_and_drive_padding():
    src = (
        "| a | b | c |\n"
        "| --- | ---: | :---: |\n"
        "| xxxxx | 1 | y |\n"
    )
    out = align_markdown_tables(src).split("\n")
    sep, row = out[1], out[2]
    assert sep.count(":") == 3, sep
    left, right, centre = _cols(row)
    assert left.startswith(" x") and left.endswith(" ")      # left-aligned
    assert right.endswith("1 ") and right.startswith("  ")   # right-aligned
    assert centre.strip() == "y"


def test_non_table_text_is_untouched():
    src = "# Title\n\nsome | pipe in prose\n\n- bullet\n"
    assert align_markdown_tables(src) == src


def test_handles_multiple_tables_in_one_document():
    src = (
        "| a | b |\n| --- | --- |\n| 1 | 2 |\n"
        "\ntext\n\n"
        "| ccc | d |\n| --- | --- |\n| 1 | 22222 |\n"
    )
    out = align_markdown_tables(src)
    assert out.count("\ntext\n") == 1
    for block in out.split("\ntext\n"):
        lines = [l for l in block.split("\n") if l.startswith("|")]
        widths = {tuple(len(c) for c in _cols(l)) for l in lines}
        assert len(widths) == 1, f"ragged: {widths}"
