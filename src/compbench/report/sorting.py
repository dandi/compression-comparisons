"""Render a sorting-fidelity sweep as a Markdown report.

The compression report answers "how small?"; this one answers the question
the study exists for: what does lossy compression do to the spike trains a
sorter recovers.

Two things this deliberately does NOT do:

* It does not lead with `accuracy`. Accuracy is pooled over matched units,
  so it can rise while the sorting gets worse -- the paper's own
  bit-truncation factor 5 reads 0.9268 accuracy alongside 1435 false
  positive units. Unit counts are the honest headline, and they are printed
  first.
* It does not treat a lossless arm as "should be 1.0". A sorter recovers
  ground truth imperfectly even on untouched data (the paper's lossless
  anchor is 0.9981 with 52 false positives), so the lossless arms are the
  BASELINE every lossy arm is measured against, not a target.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from compbench.report.render import align_markdown_tables


def _load(cell_dir: Path) -> dict[str, Any] | None:
    metrics = cell_dir / "sorting-metrics.json"
    if not metrics.is_file():
        return None
    out: dict[str, Any] = {"arm": cell_dir.name}
    m = json.loads(metrics.read_text())
    out.update(
        accuracy=m["pooled"]["accuracy"],
        recall=m["pooled"]["recall"],
        precision=m["pooled"]["precision"],
        **{k: m["unit_counts"][k] for k in m["unit_counts"]},
    )
    compress = cell_dir / "compress-metrics.json"
    if compress.is_file():
        c = json.loads(compress.read_text())
        out["cr"] = c.get("cr")
        out["rmse_uv"] = c.get("rmse_uv")
        # losslessness comes from the MEASUREMENT, not from the arm's name:
        # `blosc-zstd-level_9-shuffle_byte` is lossless and says so nowhere
        # in its directory name.
        out["lossless"] = bool(c.get("round_trip_exact"))
        codec = c.get("codec") or {}
        out["codec"] = codec.get("name", "")
        params = codec.get("params") or {}
        # the cell directory is a hash once params collide; the params
        # themselves are what a reader needs
        out["label"] = _label(codec.get("name", cell_dir.name), params)
    else:
        out["lossless"] = "lossless" in cell_dir.name or cell_dir.name.endswith("bits_0")
        out["label"] = cell_dir.name
    return out


def _label(codec: str, params: dict[str, Any]) -> str:
    """A human-readable arm label: the parameter that varies, not a hash."""
    for key, fmt in (
        ("step_size_for_qp", "QP {}"),
        ("bps", "{} bps"),
        ("bits", "{} bits"),
    ):
        if params.get(key) is not None:
            return f"{codec} {fmt.format(params[key])}"
    preset = str(params.get("preset", ""))
    if "lossless" in preset:
        return f"{codec} lossless"
    if params.get("level") is not None:
        return f"{codec} level {params['level']}"
    return codec


def render_sorting_markdown(
    results_dir: str | Path,
    title: str = "Sorting fidelity",
    baseline_arm: str | None = None,
    source_note: str = "",
) -> str:
    """Return the Markdown body for a sorting sweep.

    `baseline_arm` names the lossless arm every other row is compared
    against; when omitted, the first arm whose name marks it lossless is
    used.
    """
    root = Path(results_dir)
    rows = [r for r in (_load(d) for d in sorted(root.iterdir()) if d.is_dir()) if r]
    if not rows:
        return f"# {title}\n\nNo completed arms in `{root}`.\n"

    def _is_lossless(r: dict[str, Any]) -> bool:
        return bool(r.get("lossless"))

    base = None
    if baseline_arm:
        base = next((r for r in rows if r["arm"] == baseline_arm), None)
    if base is None:
        base = next((r for r in rows if _is_lossless(r)), None)

    head = [
        f"# {title}",
        "",
        f"**Arms:** {len(rows)} complete.",
    ]
    if source_note:
        head += ["", source_note]
    head += [
        "",
        "Unit counts first, deliberately: `accuracy` is pooled over matched "
        "units and can rise while the sorting degrades. The lossless arms are "
        "the baseline, not a target -- a sorter recovers ground truth "
        "imperfectly even on untouched data.",
        "",
        "| arm | CR | well detected | false positive | redundant | accuracy | vs baseline |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for r in sorted(rows, key=lambda r: (not _is_lossless(r), r.get("cr") or 0)):
        cr = f"{r['cr']:.3f}" if r.get("cr") else "—"
        if base is None or r["arm"] == base["arm"]:
            delta = "baseline" if base and r["arm"] == base["arm"] else "—"
        else:
            delta = (
                f"{r['num_well_detected'] - base['num_well_detected']:+d} well, "
                f"{r['num_false_positive'] - base['num_false_positive']:+d} FP"
            )
        head.append(
            f"| {r.get('label') or r['arm']} | {cr} | {r['num_well_detected']} | "
            f"{r['num_false_positive']} | {r['num_redundant']} | "
            f"{r['accuracy']:.4f} | {delta} |"
        )

    if base:
        losslessish = [r for r in rows if _is_lossless(r)]
        if len(losslessish) > 1:
            spread = max(r["accuracy"] for r in losslessish) - min(
                r["accuracy"] for r in losslessish
            )
            head += [
                "",
                "## Null control",
                "",
                f"{len(losslessish)} lossless arms, accuracy spread "
                f"**{spread:.6f}**. A spread of zero means the sorter is "
                "deterministic on this input, so any difference a lossy arm "
                "shows is attributable to the codec rather than to run-to-run "
                "variability.",
            ]
    return align_markdown_tables("\n".join(head)) + "\n"
