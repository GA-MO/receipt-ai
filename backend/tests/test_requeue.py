"""Work stranded by a restart must be picked back up.

Without a broker the thread pool is the only record that an extraction was in
flight, and it dies with the process. A redeploy mid-batch would otherwise
leave documents in ``processing`` with nothing to finish them — the database
row is the queue.
"""

import os

from app.models import Document
from app.routers import documents as docs_module


class _NoCloseSession:
    """Hands out the fixture's session but swallows close(), which the
    function calls on a session it believes it owns."""

    def __init__(self, session):
        self._session = session

    def __getattr__(self, name):
        return getattr(self._session, name)

    def close(self):
        pass


def _doc(db, tmp_path, doc_id, status, exists=True):
    path = tmp_path / f"{doc_id}.jpg"
    if exists:
        path.write_bytes(b"\xff\xd8\xff")
    db.add(Document(id=doc_id, filename=f"{doc_id}.jpg", file_path=str(path),
                    file_hash=doc_id, status=status))
    db.commit()
    return str(path)


def _capture(monkeypatch, db_session):
    """Point the function's own session factory at the test database.

    ``requeue_stuck_documents`` opens its own session — it runs at startup with
    no request to borrow one from — so the fixture's engine has to be injected
    the same way the background-task tests do it.
    """
    seen: list[str] = []
    monkeypatch.setattr(docs_module, "SessionLocal", lambda: _NoCloseSession(db_session))

    class _Pool:
        def submit(self, fn, doc_id, file_path):
            seen.append(doc_id)

    monkeypatch.setattr(docs_module, "_get_extraction_pool", lambda: _Pool())
    monkeypatch.setattr(docs_module.settings, "use_arq", False)
    return seen


def test_processing_documents_are_requeued(db_session, tmp_path, monkeypatch):
    _doc(db_session, tmp_path, "stuck-1", "processing")
    seen = _capture(monkeypatch, db_session)
    assert docs_module.requeue_stuck_documents() == 1
    assert seen == ["stuck-1"]


def test_finished_documents_are_left_alone(db_session, tmp_path, monkeypatch):
    for i, status in enumerate(("extracted", "reviewed", "error", "not_receipt")):
        _doc(db_session, tmp_path, f"done-{i}", status)
    seen = _capture(monkeypatch, db_session)
    assert docs_module.requeue_stuck_documents() == 0
    assert seen == []


def test_deleted_documents_are_not_resurrected(db_session, tmp_path, monkeypatch):
    from datetime import datetime

    _doc(db_session, tmp_path, "trashed", "processing")
    db_session.query(Document).filter(Document.id == "trashed").update(
        {"deleted_at": datetime.now()}
    )
    db_session.commit()
    seen = _capture(monkeypatch, db_session)
    assert docs_module.requeue_stuck_documents() == 0
    assert seen == []


def test_missing_file_is_skipped_not_submitted(db_session, tmp_path, monkeypatch):
    # The row survives a wiped uploads volume; resubmitting it would only fail
    # again on every boot.
    path = _doc(db_session, tmp_path, "gone", "processing")
    os.remove(path)
    seen = _capture(monkeypatch, db_session)
    docs_module.requeue_stuck_documents()
    assert seen == []
