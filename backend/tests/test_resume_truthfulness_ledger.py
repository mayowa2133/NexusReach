"""Fail-closed artifact truthfulness ledger across generated field types."""

from types import SimpleNamespace

import pytest

from app.services.resume_artifact.truthfulness import (
    build_truthfulness_ledger,
    validate_truthfulness_ledger,
)


def _tailored(**overrides):
    values = {
        "skills_to_emphasize": [],
        "skills_to_add": [],
        "keywords_to_add": [],
        "bullet_rewrites": [],
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.parametrize("term", ["CPA", "RN license", "Security Clearance", "SAP", "Kubernetes"])
def test_unsupported_generated_term_fails_ledger(term):
    ledger = build_truthfulness_ledger(
        parsed={"skills": ["Excel"]},
        content=rf"\begin{{document}}\subsection*{{Skills}}Excel, {term}\end{{document}}",
        tailored=_tailored(skills_to_add=[term]),
    )

    assert ledger["status"] == "failed"
    with pytest.raises(ValueError, match="unsupported"):
        validate_truthfulness_ledger(ledger)


def test_source_supported_term_has_evidence_entry():
    ledger = build_truthfulness_ledger(
        parsed={"skills": ["SAP"]},
        content=r"\begin{document}\subsection*{Skills}SAP\end{document}",
        tailored=_tailored(skills_to_add=["SAP"]),
    )

    validate_truthfulness_ledger(ledger)
    generated = next(
        entry for entry in ledger["entries"]
        if entry["kind"] == "generated_term"
    )
    assert generated["source_supported"] is True


def test_unaccepted_inferred_rewrite_cannot_render():
    rewrite = {
        "id": "rw-1",
        "original": "Managed monthly reporting.",
        "rewritten": "Managed monthly reporting and held a CPA license.",
        "change_type": "inferred_claim",
        "requires_user_confirm": True,
    }
    ledger = build_truthfulness_ledger(
        parsed={
            "experience": [{
                "company": "Acme",
                "bullets": ["Managed monthly reporting."],
            }]
        },
        content=(
            r"\begin{document}Managed monthly reporting and held a CPA license."
            r"\end{document}"
        ),
        tailored=_tailored(bullet_rewrites=[rewrite]),
        rewrite_decisions={},
    )

    assert {item["type"] for item in ledger["violations"]} == {
        "unaccepted_inferred_rewrite",
        "unsupported_regulated_claim",
    }


def test_explicitly_accepted_inferred_rewrite_records_acceptance():
    rewrite = {
        "id": "rw-1",
        "original": "Managed monthly reporting.",
        "rewritten": "Managed monthly reporting and held a CPA license.",
        "change_type": "inferred_claim",
        "requires_user_confirm": True,
    }
    ledger = build_truthfulness_ledger(
        parsed={
            "experience": [{
                "company": "Acme",
                "bullets": ["Managed monthly reporting."],
            }]
        },
        content=(
            r"\begin{document}Managed monthly reporting and held a CPA license."
            r"\end{document}"
        ),
        tailored=_tailored(bullet_rewrites=[rewrite]),
        rewrite_decisions={"rw-1": "accepted"},
    )

    validate_truthfulness_ledger(ledger)
    accepted = next(
        entry for entry in ledger["entries"]
        if entry["kind"] == "rewrite"
    )
    assert accepted["explicit_acceptance"] is True


def test_regulated_claim_fails_even_if_llm_omits_it_from_structured_fields():
    ledger = build_truthfulness_ledger(
        parsed={"skills": ["Excel"]},
        content=r"\begin{document}Active security clearance\end{document}",
        tailored=_tailored(),
    )

    assert ledger["violations"] == [{
        "type": "unsupported_regulated_claim",
        "text": "security clearance",
    }]
