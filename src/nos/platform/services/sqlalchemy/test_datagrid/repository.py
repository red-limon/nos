"""Test DataGrid DB read/write operations."""

from __future__ import annotations

from datetime import datetime

from ....extensions import db
from .model import TestDataGridDbModel


def _to_bool(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.lower() in ("true", "1", "yes", "on")
    return bool(v)


def _to_int_or_none(v):
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _to_float_or_none(v):
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def get_all() -> list[TestDataGridDbModel]:
    """Return all test_datagrid records."""
    return TestDataGridDbModel.query.all()


def get_by_id(record_id: int) -> TestDataGridDbModel | None:
    """Return record by id or None if not found."""
    return TestDataGridDbModel.query.get(record_id)


def create(data: dict) -> tuple[TestDataGridDbModel | None, str | None]:
    """
    Create a record from dict. Required keys: nome, cognome, email.
    Returns (model, None) on success, (None, "conflict") if email exists, (None, "bad_request") if validation fails.
    """
    if not data or not isinstance(data, dict):
        return None, "bad_request"
    required = ["nome", "cognome", "email"]
    missing = [f for f in required if f not in data or not data[f]]
    if missing:
        return None, "bad_request"
    existing = TestDataGridDbModel.query.filter_by(email=data["email"]).first()
    if existing:
        return None, "conflict"
    data_nascita = None
    if data.get("data_nascita"):
        try:
            data_nascita = datetime.fromisoformat(str(data["data_nascita"]).replace("Z", "+00:00")).date()
        except (ValueError, AttributeError, TypeError):
            pass
    data_registrazione = None
    if data.get("data_registrazione"):
        try:
            data_registrazione = datetime.fromisoformat(str(data["data_registrazione"]).replace("Z", "+00:00"))
        except (ValueError, AttributeError, TypeError):
            data_registrazione = datetime.utcnow()
    else:
        data_registrazione = datetime.utcnow()
    record = TestDataGridDbModel(
        nome=data["nome"],
        cognome=data["cognome"],
        codice_fiscale=data.get("codice_fiscale") or None,
        email=data["email"],
        eta=_to_int_or_none(data.get("eta")),
        reddito_annuo=_to_float_or_none(data.get("reddito_annuo")),
        telefono=data.get("telefono") or None,
        sito_web=data.get("sito_web") or None,
        data_nascita=data_nascita,
        data_registrazione=data_registrazione,
        stato_civile=data.get("stato_civile"),
        paese=data.get("paese"),
        genere=data.get("genere"),
        newsletter=_to_bool(data.get("newsletter", False)),
        privacy_accettata=_to_bool(data.get("privacy_accettata", False)),
        marketing=_to_bool(data.get("marketing", False)),
        note=data.get("note"),
        indirizzo=data.get("indirizzo"),
        colore_preferito=data.get("colore_preferito") or None,
        livello_soddisfazione=_to_int_or_none(data.get("livello_soddisfazione")),
        documento_identita=data.get("documento_identita") or None,
        codice_interno=data.get("codice_interno"),
    )
    db.session.add(record)
    db.session.commit()
    return record, None


def update(record_id: int, data: dict) -> tuple[TestDataGridDbModel | None, str | None]:
    """
    Update a record by id. Returns (model, None) on success, (None, "not_found") or (None, "conflict") or (None, "bad_request").
    """
    record = TestDataGridDbModel.query.get(record_id)
    if not record:
        return None, "not_found"
    if not data or not isinstance(data, dict):
        return None, "bad_request"
    if "nome" in data:
        record.nome = data["nome"]
    if "cognome" in data:
        record.cognome = data["cognome"]
    if "codice_fiscale" in data:
        record.codice_fiscale = data["codice_fiscale"]
    if "email" in data:
        if data["email"] != record.email:
            existing = TestDataGridDbModel.query.filter_by(email=data["email"]).first()
            if existing:
                return None, "conflict"
        record.email = data["email"]
    if "eta" in data:
        record.eta = _to_int_or_none(data["eta"])
    if "reddito_annuo" in data:
        record.reddito_annuo = _to_float_or_none(data["reddito_annuo"])
    if "telefono" in data:
        record.telefono = data["telefono"]
    if "sito_web" in data:
        record.sito_web = data["sito_web"]
    if "data_nascita" in data:
        if data["data_nascita"]:
            try:
                record.data_nascita = datetime.fromisoformat(str(data["data_nascita"]).replace("Z", "+00:00")).date()
            except (ValueError, AttributeError, TypeError):
                record.data_nascita = None
        else:
            record.data_nascita = None
    if "data_registrazione" in data and data["data_registrazione"]:
        try:
            record.data_registrazione = datetime.fromisoformat(str(data["data_registrazione"]).replace("Z", "+00:00"))
        except (ValueError, AttributeError, TypeError):
            pass
    if "stato_civile" in data:
        record.stato_civile = data["stato_civile"]
    if "paese" in data:
        record.paese = data["paese"]
    if "genere" in data:
        record.genere = data["genere"]
    if "newsletter" in data:
        record.newsletter = _to_bool(data["newsletter"])
    if "privacy_accettata" in data:
        record.privacy_accettata = _to_bool(data["privacy_accettata"])
    if "marketing" in data:
        record.marketing = _to_bool(data["marketing"])
    if "note" in data:
        record.note = data["note"]
    if "indirizzo" in data:
        record.indirizzo = data["indirizzo"]
    if "colore_preferito" in data:
        record.colore_preferito = data["colore_preferito"]
    if "livello_soddisfazione" in data:
        record.livello_soddisfazione = _to_int_or_none(data["livello_soddisfazione"])
    if "documento_identita" in data:
        record.documento_identita = data["documento_identita"]
    if "codice_interno" in data:
        record.codice_interno = data["codice_interno"]
    db.session.commit()
    return record, None


def delete_by_ids(record_ids: list[int]) -> tuple[list[int] | None, str | None]:
    """
    Delete records by ids. Returns (deleted_ids, None) on success, (None, "not_found") if no records, (None, "bad_request") if ids invalid.
    """
    if not record_ids or not isinstance(record_ids, list):
        return None, "bad_request"
    records = TestDataGridDbModel.query.filter(TestDataGridDbModel.id.in_(record_ids)).all()
    if not records:
        return None, "not_found"
    deleted = [r.id for r in records]
    for r in records:
        db.session.delete(r)
    db.session.commit()
    return deleted, None
