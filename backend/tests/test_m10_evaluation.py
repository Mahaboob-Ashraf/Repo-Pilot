from pathlib import Path

from app.evaluation.m10 import _load_suite, run_context_experiment


REPOSITORY_ROOT = Path(__file__).parents[2]
SUITE = REPOSITORY_ROOT / "evaluation" / "fixtures" / "m10" / "development.json"


def test_m10_development_suite_is_separate_and_bounded() -> None:
    suite = _load_suite(SUITE)

    assert suite["suite_id"] == "m10-development-v1"
    assert len(suite["planner_cases"]) == 3
    assert suite["patch_case"]["case_id"] == "exact-replacement-rounding"
    assert all("more-itertools" not in str(case) for case in suite["planner_cases"])
    assert all("toolz" not in str(case) for case in suite["planner_cases"])
    assert all("boltons" not in str(case) for case in suite["planner_cases"])


def test_context_depth_experiment_exposes_coverage_precision_tradeoff() -> None:
    artifact = run_context_experiment(_load_suite(SUITE))

    assert artifact["summary"]["10"]["coverage_rate"] == 1.0
    assert artifact["summary"]["5"]["coverage_rate"] == 1.0
    assert artifact["summary"]["3"]["coverage_rate"] < 1.0
    assert (
        artifact["summary"]["5"]["mean_precision"]
        > artifact["summary"]["10"]["mean_precision"]
    )
    assert (
        artifact["summary"]["5"]["mean_prompt_bytes"]
        < artifact["summary"]["10"]["mean_prompt_bytes"]
    )
