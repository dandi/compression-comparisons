"""The Fig 14 verdict must judge a distribution, not its worst outlier."""

from compbench.waveform_errors import verdict


def _result(median, p90, mx):
    return {
        "cell": "x", "cr": 7.1,
        "summary": {"peak_to_valley@60um": {
            "median_relative_error": median,
            "p90_relative_error": p90,
            "max_relative_error": mx,
            "n": 20, "within_10_percent": mx < 0.10,
        }},
    }


def test_single_outlier_does_not_fail_a_passing_distribution():
    """WavPack 2.25 bps: medians <2%, p90 <5%, one unit at 32%.

    The paper states this codec passes; scoring on max said it failed.
    """
    v = verdict(_result(0.0000, 0.0499, 0.3246))
    assert v["within_tolerance"] is True
    assert v["max_over_all_features"] == 0.3246   # still reported


def test_a_genuinely_bad_distribution_still_fails():
    v = verdict(_result(0.42, 0.55, 0.61))
    assert v["within_tolerance"] is False


def test_statistic_is_recorded_so_a_number_is_never_ambiguous():
    assert verdict(_result(0.01, 0.02, 0.9))["statistic"] == "p90_relative_error"
