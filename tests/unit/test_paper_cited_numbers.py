"""The transcribed paper numbers must stay consistent with the profiles.

`.specify/specs/paper-cited-numbers.yaml` is hand-transcribed from the
article, and the profiles hand-write each recording's LSB. A typo in
either produces a plausible number computed on wrongly-scaled data, which
is exactly the class of error that is invisible in a results table.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
CITED = REPO / ".specify/specs/paper-cited-numbers.yaml"
REFERENCE = REPO / ".specify/specs/paper-reference-lossless.csv"
PROFILES = [
    REPO / "configs/profiles/paper-real-np1-8.yaml",
    REPO / "configs/profiles/paper-real-16.yaml",
]


@pytest.fixture(scope="module")
def cited():
    return yaml.safe_load(CITED.read_text())


def test_cited_numbers_file_parses(cited):
    assert cited["meta"]["doi"] == "10.1088/1741-2552/acf5a4"
    # The paper reports median, not mean — see plan §4.6b. Our gate compares
    # a median against it, so this must not silently change.
    assert cited["meta"]["statistic"] == "median_plus_minus_sd"
    assert cited["meta"]["n_per_distribution"] == 8


def test_every_quoted_number_carries_its_quote(cited):
    for section in ("lossless_raw", "lossless_bandpass_300_6000"):
        for entry in cited[section]:
            assert entry.get("quote"), f"{section}/{entry['codec']} has no source quote"
            assert isinstance(entry["cr"], (int, float))


def test_derived_numbers_are_flagged_as_derived(cited):
    """Values back-computed from a file-size percentage are not quotes."""
    for entry in cited["lossless_raw_derived"]:
        assert entry["derived"] is True
        assert "from_file_size_percent" in entry


def test_conditions_are_recorded(cited):
    """A CR is meaningless without the conditions it was measured under."""
    cond = cited["meta"]["conditions"]
    assert cond["lsb_correction"] is True
    assert cond["chunk_duration_s"] == 1.0


def test_all_16_experimental_recordings_plus_2_simulated(cited):
    recs = cited["recordings"]
    assert len(recs) == 18
    exp = [r for r in recs if r["source"] in {"IBL", "AIND"}]
    assert len(exp) == 16
    assert sum(1 for r in exp if r["probe"] == "NP1") == 8
    assert sum(1 for r in exp if r["probe"] == "NP2") == 8


def test_lsb_follows_acquisition_software(cited):
    """SpikeGLX writes raw ADC values (LSB 1); Open Ephys rescales (12/3)."""
    for r in cited["recordings"]:
        if r["acquisition"] == "SpikeGLX":
            assert r["lsb"] == 1, r["session"]
        elif r["acquisition"] == "OpenEphys":
            assert r["lsb"] == (12 if r["probe"] == "NP1" else 3), r["session"]


@pytest.mark.parametrize("profile_path", PROFILES, ids=lambda p: p.name)
def test_profile_lsb_vars_match_the_paper(profile_path, cited):
    """The check that stops a silent mis-scaling of a whole recording."""
    by_session = {r["session"]: r["lsb"] for r in cited["recordings"]}
    profile = yaml.safe_load(profile_path.read_text())
    recordings = profile["datasets_matrix"]["recordings"]
    assert recordings, f"{profile_path.name} has no recordings"
    for rec in recordings:
        session = rec["params"]["path"].rstrip("/").split("/")[-1]
        assert session in by_session, f"{session} not in paper table 1"
        assert "vars" in rec and "lsb" in rec["vars"], (
            f"{rec['label']} declares no lsb; the lsb_correction step needs it"
        )
        assert rec["vars"]["lsb"] == by_session[session], (
            f"{rec['label']}: profile says lsb={rec['vars']['lsb']}, "
            f"paper table 1 says {by_session[session]}"
        )


# ---- the transcription vs the capsule's own data -----------------------


@pytest.fixture(scope="module")
def reference():
    """Per-condition table derived from the capsule's benchmark-lossless.csv."""
    import csv

    with REFERENCE.open() as f:
        rows = list(csv.DictReader(line for line in f if not line.startswith("#")))
    assert rows, "reference table is empty"
    return rows


def _lookup(reference, probe, compressor, level, shuffle=None, ccs=None):
    """Headline conditions: LSB-corrected, 1 s chunks (plan §4.6b)."""
    hits = [
        r
        for r in reference
        if r["probe"] == probe
        and r["compressor"] == compressor
        and r["level"] == level
        and r["chunk_duration"] == "1s"
        and r["lsb_mode"] == "corrected"
        and (shuffle is None or r["shuffle"] == shuffle)
        and (ccs is None or r["channel_chunk_size"] == str(ccs))
    ]
    assert hits, f"no reference row for {probe}/{compressor}/{level}"
    return hits


@pytest.mark.parametrize(
    ("probe", "compressor", "level", "shuffle", "ccs", "expected"),
    [
        ("NP1", "wavpack", "medium", None, -1, 3.59),
        ("NP2", "wavpack", "medium", None, -1, 2.26),
        # FLAC compresses channel PAIRS; at the default -1 its NP1 CR is 2.94.
        ("NP1", "flac", "medium", None, 2, 3.58),
        ("NP2", "flac", "medium", None, 2, 2.27),
        ("NP1", "blosc-zstd", "high", "bit", -1, 2.79),
        ("NP2", "blosc-zstd", "high", "bit", -1, 1.90),
        ("NP1", "lzma", "high", "no", -1, 2.82),
        ("NP2", "lzma", "high", "byte", -1, 1.91),
    ],
)
def test_transcribed_numbers_match_the_capsule_data(
    reference, probe, compressor, level, shuffle, ccs, expected
):
    """Guards the hand-transcription against the authors' own results."""
    rows = _lookup(reference, probe, compressor, level, shuffle, ccs)
    assert len(rows) == 1, f"conditions under-specified: {len(rows)} rows matched"
    assert float(rows[0]["cr_median"]) == pytest.approx(expected, abs=0.005)
    assert int(rows[0]["n_sessions"]) == 8


def test_flac_channel_chunk_size_is_recorded_as_a_condition(cited):
    """It changes NP1 CR by 22% and the article's prose never states it."""
    flac = [e for e in cited["lossless_raw"] if e["codec"] == "flac"]
    assert flac
    for entry in flac:
        assert entry["channel_chunk_size"] == 2


def test_reference_table_covers_every_paper_codec(reference):
    codecs = {r["compressor"] for r in reference}
    assert {
        "blosc-lz4",
        "blosc-lz4hc",
        "blosc-zlib",
        "blosc-zstd",
        "gzip",
        "lz4",
        "lzma",
        "zlib",
        "zstd",
        "flac",
        "wavpack",
    } <= codecs
