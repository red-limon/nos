"""Form schema builder for test-datagrid. Shared by api.test_datagrid routes."""

from .form_wire import form_envelope


def get_test_datagrid_form_schema(record=None):
    """Build form_schema dict for test_datagrid (create or edit)."""
    stato_civile_options = [
        {"value": "celibe", "label": "Celibe/Nubile", "selected": bool(record and record.stato_civile == "celibe")},
        {"value": "sposato", "label": "Sposato/a", "selected": bool(record and record.stato_civile == "sposato")},
        {"value": "divorziato", "label": "Divorziato/a", "selected": bool(record and record.stato_civile == "divorziato")},
        {"value": "vedovo", "label": "Vedovo/a", "selected": bool(record and record.stato_civile == "vedovo")},
    ]
    paese_options = [
        {"value": "Italia", "label": "Italia", "selected": bool(record and record.paese == "Italia")},
        {"value": "Francia", "label": "Francia", "selected": bool(record and record.paese == "Francia")},
        {"value": "Germania", "label": "Germania", "selected": bool(record and record.paese == "Germania")},
        {"value": "Spagna", "label": "Spagna", "selected": bool(record and record.paese == "Spagna")},
        {"value": "Regno Unito", "label": "Regno Unito", "selected": bool(record and record.paese == "Regno Unito")},
        {"value": "Stati Uniti", "label": "Stati Uniti", "selected": bool(record and record.paese == "Stati Uniti")},
        {"value": "Canada", "label": "Canada", "selected": bool(record and record.paese == "Canada")},
        {"value": "Australia", "label": "Australia", "selected": bool(record and record.paese == "Australia")},
        {"value": "Brasile", "label": "Brasile", "selected": bool(record and record.paese == "Brasile")},
        {"value": "Argentina", "label": "Argentina", "selected": bool(record and record.paese == "Argentina")},
    ]
    genere_options = [
        {"value": "maschio", "label": "Maschio", "selected": bool(record and record.genere == "maschio")},
        {"value": "femmina", "label": "Femmina", "selected": bool(record and record.genere == "femmina")},
        {"value": "altro", "label": "Altro", "selected": bool(record and record.genere == "altro")},
    ]
    fields = [
        {"name": "id", "label": "ID", "type": "number", "placeholder": "", "required": False, "readonly": True, "value": record.id if record else None},
        {"name": "nome", "label": "Nome", "type": "text", "placeholder": "Inserisci nome", "required": True, "minLength": 2, "maxLength": 100},
        {"name": "cognome", "label": "Cognome", "type": "text", "placeholder": "Inserisci cognome", "required": True, "minLength": 2, "maxLength": 100},
        {
            "name": "codice_fiscale",
            "label": "Codice Fiscale",
            "type": "text",
            "placeholder": "ABCDEF12G34H567I",
            "required": False,
            "pattern": "^[A-Z]{6}[0-9]{2}[A-Z][0-9]{2}[A-Z][0-9]{3}[A-Z]$",
            "maxLength": 16,
            "description": "Formato: 6 lettere, 2 cifre, 1 lettera, 2 cifre, 1 lettera, 3 cifre, 1 lettera",
        },
        {"name": "email", "label": "Email", "type": "email", "placeholder": "cliente@example.com", "required": True, "maxLength": 200},
        {"name": "eta", "label": "Età", "type": "number", "placeholder": "Inserisci età", "required": False, "min": 18, "max": 120, "step": 1},
        {
            "name": "reddito_annuo",
            "label": "Reddito Annuo",
            "type": "number",
            "placeholder": "Inserisci reddito",
            "required": False,
            "min": 0,
            "step": 0.01,
            "description": "Importo in euro",
        },
        {"name": "telefono", "label": "Telefono", "type": "tel", "placeholder": "+39 123 456 7890", "required": False, "maxLength": 20},
        {"name": "sito_web", "label": "Sito Web", "type": "url", "placeholder": "https://www.example.com", "required": False, "maxLength": 500},
        {"name": "data_nascita", "label": "Data di Nascita", "type": "date", "required": False},
        {"name": "data_registrazione", "label": "Data Registrazione", "type": "datetime-local", "required": False},
        {"name": "stato_civile", "label": "Stato Civile", "type": "select", "required": False, "options": stato_civile_options},
        {"name": "paese", "label": "Paese", "type": "select", "required": False, "options": paese_options},
        {"name": "genere", "label": "Genere", "type": "radio", "required": False, "options": genere_options},
        {"name": "newsletter", "label": "Newsletter", "type": "checkbox", "value": record.newsletter if record else False, "required": False},
        {"name": "privacy_accettata", "label": "Privacy Accettata", "type": "checkbox", "value": record.privacy_accettata if record else False, "required": True},
        {"name": "marketing", "label": "Consenso Marketing", "type": "checkbox", "value": record.marketing if record else False, "required": False},
        {"name": "note", "label": "Note", "type": "textarea", "placeholder": "Inserisci note aggiuntive", "required": False, "maxLength": 2000},
        {"name": "indirizzo", "label": "Indirizzo", "type": "textarea", "placeholder": "Via, numero civico, CAP, città", "required": False, "maxLength": 500},
        {"name": "colore_preferito", "label": "Colore Preferito", "type": "color", "value": record.colore_preferito if record and record.colore_preferito else "#000000", "required": False},
        {
            "name": "livello_soddisfazione",
            "label": "Livello Soddisfazione",
            "type": "range",
            "value": record.livello_soddisfazione if record and record.livello_soddisfazione else 50,
            "required": False,
            "min": 0,
            "max": 100,
            "step": 1,
            "description": "Da 0 a 100",
        },
        {
            "name": "documento_identita",
            "label": "Documento Identità",
            "type": "file",
            "required": False,
            "accept": ".pdf,.jpg,.jpeg,.png",
            "description": "Carica documento (PDF, JPG, PNG)",
        },
        {"name": "codice_interno", "label": "Codice Interno", "type": "hidden", "value": record.codice_interno if record and record.codice_interno else "", "required": False},
    ]
    return form_envelope(
        form_id="test-datagrid-form",
        title="Anagrafica Cliente",
        description="Gestione anagrafica clienti - tutti i tipi di input",
        fields=fields,
        submit_label="Salva",
        cancel_label="Annulla",
        method="PUT" if record else "POST",
    )
