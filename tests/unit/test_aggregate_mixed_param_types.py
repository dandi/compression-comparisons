"""One codec's int parameter must not sink another codec's report row.

`lzma` takes `preset: 9`; `t261` takes `preset: "combinedPresetEEG_..."`.
Both flatten to `codec_param_preset`, and an untyped mix kills the whole
parquet write -- which is how a completed 96-cell sweep ended up with no
aggregate at all.
"""

import json
from pathlib import Path

from compbench.report.aggregate import aggregate_directory


def _cell(root: Path, name: str, codec: str, params: dict) -> None:
    d = root / name
    d.mkdir(parents=True)
    (d / "metrics.json").write_text(json.dumps({"cr": 2.0, "round_trip_ok": True}))
    (d / "manifest.json").write_text(json.dumps({
        "codec": {"name": codec, "params": params},
        "input": {"provenance": {}},
    }))


def test_int_and_str_params_share_a_column_without_exploding(tmp_path: Path) -> None:
    _cell(tmp_path, "a__lzma", "lzma", {"preset": 9})
    _cell(tmp_path, "b__t261", "t261", {"preset": "combinedPresetEEG_IndepChannel"})
    rows = aggregate_directory(tmp_path)
    vals = {r.get("codec_param_preset") for r in rows}
    assert vals == {"9", "combinedPresetEEG_IndepChannel"}
    assert all(isinstance(v, str) for v in vals), "mixed types would break parquet"


def test_none_stays_none(tmp_path: Path) -> None:
    _cell(tmp_path, "c__wavpack", "wavpack", {"bps": None})
    rows = aggregate_directory(tmp_path)
    assert rows[0]["codec_param_bps"] is None
