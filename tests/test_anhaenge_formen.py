"""Anhaenge in jeder Eingangsform (Befund 05.10.: context_refs als JSON-String)."""

import yaml

from src.tools.queue import amend_task_handler, get_task_handler, submit_task_handler
from src.tools.refs import anhaenge_im_text, refs_normalisieren

BILD = "/home/agent/.cloudcli/assets/1759700000000-ab12-room-redesign-base.png"
PDF = "/home/agent/.cloudcli/assets/grundriss.pdf"


def _submit(tmp_path, **kw):
    args = dict(
        source_agent="a",
        target_agent="ai-engineer",
        task_type="build",
        summary="Zimmer neu gestalten",
        description="Drei Stile",
        queue_dir=str(tmp_path),
    )
    args.update(kw)
    return submit_task_handler(**args)


def _refs(tmp_path, result):
    return get_task_handler(task_id=result["task_id"], queue_dir=str(tmp_path))["payload"][
        "context_refs"
    ]


def test_normalisieren_formen():
    assert refs_normalisieren(f'["{BILD}"]') == [BILD]
    assert refs_normalisieren(f"{BILD}, {PDF}") == [BILD, PDF]
    assert refs_normalisieren(f"{BILD}\n{PDF}\n") == [BILD, PDF]
    assert refs_normalisieren(BILD) == [BILD]
    assert refs_normalisieren([BILD], [BILD, PDF]) == [BILD, PDF]
    assert refs_normalisieren("~/.cloudcli/assets/x.png") == ["/home/agent/.cloudcli/assets/x.png"]
    assert refs_normalisieren(None, "", []) == []


def test_submit_json_string(tmp_path):
    r = _submit(tmp_path, context_refs=f'["{BILD}"]')
    assert r["ok"] is True, r
    assert _refs(tmp_path, r) == [BILD]


def test_submit_attachments_mit_context_refs_zusammengefuehrt(tmp_path):
    r = _submit(tmp_path, context_refs=[BILD], attachments=f"{PDF}, {BILD}")
    assert r["ok"] is True, r
    assert _refs(tmp_path, r) == [BILD, PDF]


def test_submit_relativ_bleibt_abgewiesen(tmp_path):
    r = _submit(tmp_path, attachments='["relativ/datei.png"]')
    assert r["ok"] is False
    assert "context_ref" in r["error"]


def test_submit_work_bleibt_abgewiesen(tmp_path):
    r = _submit(tmp_path, attachments="/work/frontend/bild.png")
    assert r["ok"] is False
    assert "cloudcli/assets" in r["error"]


def test_submit_nicht_string_eintrag_abgewiesen(tmp_path):
    r = _submit(tmp_path, attachments=[42])
    assert r["ok"] is False


def test_anhang_nur_in_beschreibung_wird_uebernommen(tmp_path):
    r = _submit(tmp_path, description=f"Referenzbild: {BILD}. Bitte drei Stile.")
    assert r["ok"] is True, r
    assert _refs(tmp_path, r) == [BILD]
    assert any("Aus dem Text" in h for h in r.get("hinweise", []))


def test_anhaenge_im_text_tilde_und_satzende():
    text = "Siehe ~/.cloudcli/assets/a.png und (/home/agent/.cloudcli/assets/b.pdf)."
    assert anhaenge_im_text(text) == [
        "/home/agent/.cloudcli/assets/a.png",
        "/home/agent/.cloudcli/assets/b.pdf",
    ]
    assert anhaenge_im_text("/x/home/agent/.cloudcli/assets/c.png") == []


def test_amend_reicht_anhang_nach(tmp_path):
    r = _submit(tmp_path)
    a = amend_task_handler(
        task_id=r["task_id"],
        amendment="",
        actor="a",
        attachments=f'["{PDF}"]',
        queue_dir=str(tmp_path),
    )
    assert a["ok"] is True, a
    task = get_task_handler(task_id=r["task_id"], queue_dir=str(tmp_path))
    assert task["payload"]["context_refs"] == [PDF]
    assert task["payload"]["amendments"][0]["context_refs"] == [PDF]
    assert "nachgereicht" in task["payload"]["amendments"][0]["text"]


def test_amend_work_pfad_abgewiesen(tmp_path):
    r = _submit(tmp_path)
    a = amend_task_handler(
        task_id=r["task_id"],
        amendment="x",
        actor="a",
        attachments="/work/a/b.png",
        queue_dir=str(tmp_path),
    )
    assert a["ok"] is False


def test_task_yaml_bleibt_liste(tmp_path):
    r = _submit(tmp_path, context_refs=BILD)
    with open(tmp_path / r["filename"]) as f:
        assert yaml.safe_load(f)["payload"]["context_refs"] == [BILD]
