"""Release gates for the frozen 23-occupation evaluation corpus."""

import json
from pathlib import Path

from app.services.cross_category_evaluation import evaluate_cross_category_cases


FIXTURE = Path(__file__).parent / "fixtures" / "cross_category_eval.json"


def test_cross_category_corpus_covers_the_complete_taxonomy():
    result = evaluate_cross_category_cases(json.loads(FIXTURE.read_text()))

    assert result["category_count"] == 23
    assert result["taxonomy_coverage"] == 1.0
    assert result["missing_categories"] == []
    assert result["unknown_categories"] == []


def test_cross_category_correctness_release_gates():
    result = evaluate_cross_category_cases(json.loads(FIXTURE.read_text()))

    assert result["jobs"]["occupation_recall"] == 1.0
    assert result["jobs"]["occupation_precision"] >= 0.95
    assert result["jobs"]["critical_term_recall"] >= 0.90
    assert result["people"]["context_accuracy"] == 1.0
    assert result["people"]["peer_preference_accuracy"] == 1.0
    assert result["people"]["manager_seed_coverage"] == 1.0
    assert result["resumes"]["supported_term_retention"] == 1.0
    assert result["resumes"]["unsupported_term_block_rate"] == 1.0
