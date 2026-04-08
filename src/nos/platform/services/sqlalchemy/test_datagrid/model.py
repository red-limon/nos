"""TestDataGrid DB model (table: test_datagrid)."""

from datetime import datetime
from ....extensions import db


class TestDataGridDbModel(db.Model):
    """Test table for data grid with all form field types (table: test_datagrid)."""

    __tablename__ = "test_datagrid"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    cognome = db.Column(db.String(100), nullable=False)
    codice_fiscale = db.Column(db.String(16), nullable=True, unique=True)
    email = db.Column(db.String(200), nullable=False, unique=True)
    eta = db.Column(db.Integer, nullable=True)
    reddito_annuo = db.Column(db.Numeric(12, 2), nullable=True)
    telefono = db.Column(db.String(20), nullable=True)
    sito_web = db.Column(db.String(500), nullable=True)
    data_nascita = db.Column(db.Date, nullable=True)
    data_registrazione = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    stato_civile = db.Column(db.String(20), nullable=True)
    paese = db.Column(db.String(100), nullable=True)
    genere = db.Column(db.String(10), nullable=True)
    newsletter = db.Column(db.Boolean, default=False, nullable=False)
    privacy_accettata = db.Column(db.Boolean, default=False, nullable=False)
    marketing = db.Column(db.Boolean, default=False, nullable=False)
    note = db.Column(db.Text, nullable=True)
    indirizzo = db.Column(db.Text, nullable=True)
    colore_preferito = db.Column(db.String(7), nullable=True)
    livello_soddisfazione = db.Column(db.Integer, nullable=True)
    documento_identita = db.Column(db.String(500), nullable=True)
    codice_interno = db.Column(db.String(50), nullable=True)
    data_creazione = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    data_aggiornamento = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def to_dict(self):
        """Convert model to dictionary."""
        return {
            "id": self.id,
            "nome": self.nome,
            "cognome": self.cognome,
            "codice_fiscale": self.codice_fiscale,
            "email": self.email,
            "eta": self.eta,
            "reddito_annuo": float(self.reddito_annuo) if self.reddito_annuo else None,
            "telefono": self.telefono,
            "sito_web": self.sito_web,
            "data_nascita": self.data_nascita.isoformat() if self.data_nascita else None,
            "data_registrazione": self.data_registrazione.isoformat() if self.data_registrazione else None,
            "stato_civile": self.stato_civile,
            "paese": self.paese,
            "genere": self.genere,
            "newsletter": self.newsletter,
            "privacy_accettata": self.privacy_accettata,
            "marketing": self.marketing,
            "note": self.note,
            "indirizzo": self.indirizzo,
            "colore_preferito": self.colore_preferito,
            "livello_soddisfazione": self.livello_soddisfazione,
            "documento_identita": self.documento_identita,
            "codice_interno": self.codice_interno,
            "data_creazione": self.data_creazione.isoformat() if self.data_creazione else None,
            "data_aggiornamento": self.data_aggiornamento.isoformat() if self.data_aggiornamento else None,
        }

    def __repr__(self):
        return f"<TestDataGridDbModel {self.nome} {self.cognome}>"
