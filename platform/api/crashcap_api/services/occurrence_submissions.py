"""Upload annotations are evidence of a submission, never of a verified Build."""

from sqlalchemy.orm import Session

from ..models import Occurrence, OccurrenceSubmission, Upload, utcnow


def record_verified_submission(
    session: Session, upload: Upload, occurrence: Occurrence, *, include_unannotated: bool
) -> None:
    if upload.workspace_id != occurrence.workspace_id:
        raise ValueError("Submission and Occurrence Workspace differ")
    record = session.get(OccurrenceSubmission, upload.id)
    if record is None:
        if not include_unannotated:
            return
        record = OccurrenceSubmission(
            upload_id=upload.id,
            filename=upload.original_filename,
            source="upload-v1",
            submitted_at=upload.uploaded_at,
        )
        session.add(record)
    if record.occurrence_id is not None:
        if record.occurrence_id != occurrence.id:
            raise ValueError("Verified submission cannot be reassigned")
        return
    record.occurrence_id = occurrence.id
    record.verified_at = utcnow()
