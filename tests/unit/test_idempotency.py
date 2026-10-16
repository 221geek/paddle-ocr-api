from ocr_service.application.use_cases.submit_job import make_work_key
from ocr_service.domain.models import JobInput


def test_work_key_changes_when_ocr_parameters_change() -> None:
    original = JobInput(archive_id="a", document_id="d", page_number=1)
    changed = JobInput(archive_id="a", document_id="d", page_number=1, include_boxes=False)
    assert make_work_key("hash", original, "model") != make_work_key("hash", changed, "model")
