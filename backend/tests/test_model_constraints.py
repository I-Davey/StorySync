from __future__ import annotations

from app.models import Audiobook, ProcessingJob


def _constraint_names(model) -> set[str]:
    return {constraint.name for constraint in model.__table__.constraints if constraint.name}


def test_processing_job_model_has_basic_integrity_constraints() -> None:
    names = _constraint_names(ProcessingJob)

    assert "ck_processing_jobs_state" in names
    assert "ck_processing_jobs_attempt_nonnegative" in names
    assert "ck_processing_jobs_processing_has_lease" in names
    assert "ck_processing_jobs_terminal_fields_clear" in names


def test_audiobook_model_has_basic_integrity_constraints() -> None:
    names = _constraint_names(Audiobook)

    assert "ck_audiobooks_file_size_nonnegative" in names
    assert "ck_audiobooks_checksum_length" in names
