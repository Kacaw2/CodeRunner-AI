"""Phase 5 / Task 5: formalized eval dataset store.

Cases live under ``evals/datasets/<case_type>/`` as canonical JSON. The store
loads them into typed ``EvalCase`` objects and supports selectors like
``"all"``, ``"golden"`` and ``"golden:tutor"``.
"""


def test_dataset_store_loads_all_case_types():
    from evals.datasets.store import DatasetStore

    store = DatasetStore(root="evals/datasets")
    cases = store.load_cases(selector="all")
    case_types = {case.case_type for case in cases}

    assert {"golden", "hidden", "regression", "production_failure"} <= case_types
    assert all(case.id for case in cases)
    assert all(case.input.message for case in cases)


def test_selector_filters_by_type_and_suite():
    from evals.datasets.store import DatasetStore

    store = DatasetStore(root="evals/datasets")

    golden = store.load_cases(selector="golden")
    assert golden
    assert all(case.case_type == "golden" for case in golden)

    tutor_golden = store.load_cases(selector="golden:tutor")
    assert tutor_golden
    assert all(case.case_type == "golden" for case in tutor_golden)
    assert all(case.suite == "tutor" for case in tutor_golden)


def test_cases_carry_graders_and_budget():
    from evals.datasets.store import DatasetStore

    store = DatasetStore(root="evals/datasets")
    cases = store.load_cases(selector="golden:tutor")

    case = next(c for c in cases if c.graders)
    assert all(g.type.startswith("deterministic.") for g in case.graders)
    assert case.budget.get("max_tokens")
