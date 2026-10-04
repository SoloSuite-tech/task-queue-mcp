"""Beglaubigte Herkunft eines submit_task-Aufrufs (src/origin.py) und die
Zustellbarkeits-Pruefung der context_refs (src/tools/refs.py).

Anlass: parker #157 — ein Verweis in den Arbeitsbereich einer anderen Rolle
wurde stillschweigend uebernommen und war im Lauf der Zielrolle unlesbar.
"""

import os
import tempfile

import pytest

from src.origin import origin_from_headers, origin_key, parse_origin, sign
from src.tools.queue import submit_task_handler
from src.tools.refs import ASSET, OTHER, WORK, classify_ref, refs_pruefen

SECRET = "ein-betreiber-secret-mit-laenge"
KEY = origin_key(SECRET)


def nachweis(konto="cevin-30bb4a", rolle="frontend-developer", key=KEY):
    return sign(konto, rolle, key)


# --------------------------------------------------------------- Signatur ---


def test_nachweis_ist_bitgenau_wie_in_der_kontrollebene():
    """Gegenstueck zu app/test/task-origin.test.mjs: beide Seiten bilden
    denselben Wert, sonst wird kein Anhang zugestellt und niemand sieht warum."""
    assert sign("cevin-30bb4a", "frontend-developer", origin_key(SECRET)) == (
        "v1.cevin-30bb4a.frontend-developer.c28f4d64725bf739e6bb5bc9e30c7633"
    )


def test_nachweis_wird_gelesen():
    assert parse_origin(nachweis(), KEY) == {
        "user": "cevin-30bb4a",
        "role": "frontend-developer",
    }


def test_fremder_schluessel_zaehlt_nicht():
    assert parse_origin(nachweis(), origin_key("ein-anderes-secret-ganz-anders")) is None


def test_gefaelschtes_konto_zaehlt_nicht():
    """Der Rumpf ist lesbar — wer ihn auf ein anderes Konto umschreibt, hat keine
    gueltige Signatur mehr. Genau das ist die Grenze zwischen den Konten."""
    echt = nachweis()
    gefaelscht = echt.replace("cevin-30bb4a", "admin-8c6976")
    assert parse_origin(gefaelscht, KEY) is None


@pytest.mark.parametrize(
    "wert",
    [
        None,
        "",
        "v1.cevin-30bb4a.frontend-developer",
        "v2.cevin-30bb4a.frontend-developer.0000000000000000000000000000beef",
        "v1.Cevin.frontend-developer.0000000000000000000000000000beef",
        "v1.../etc.passwd.0000000000000000000000000000beef",
    ],
)
def test_unbrauchbare_werte(wert):
    assert parse_origin(wert, KEY) is None


def test_ohne_secret_keine_herkunft():
    assert origin_key("") is None
    assert parse_origin(nachweis(), None) is None


def test_header_wird_unabhaengig_von_gross_klein_gelesen():
    assert origin_from_headers({"X-Agent-Origin": nachweis()}, SECRET) == {
        "user": "cevin-30bb4a",
        "role": "frontend-developer",
    }
    assert origin_from_headers({"andere": "egal"}, SECRET) is None


# ------------------------------------------------------- Klassifizierung ---


@pytest.mark.parametrize(
    "ref,klasse",
    [
        ("/home/agent/.cloudcli/assets/1790-x-IMG_4725.heic", ASSET),
        ("/work/administrator/small-dreams-preview/bild-1.jpg", WORK),
        ("/opt/parker/site/index.html", OTHER),
        ("/root/ai-efficiency-machine/deploy.sh", OTHER),
    ],
)
def test_klassen(ref, klasse):
    assert classify_ref(ref)[0] == klasse


@pytest.mark.parametrize(
    "ref",
    [
        "/work/../etc/passwd",
        "/work/rolle",
        "/work/rolle/a/b/c/d/e/f/g/tief.jpg",
        "/work/rolle/-start.jpg",
        "/home/agent/.cloudcli/assets/unter/ordner.jpg",
    ],
)
def test_unzustellbare_verweise_werden_abgewiesen(ref):
    fehler, _ = refs_pruefen([ref], herkunft_bekannt=True)
    assert fehler and ref in fehler


def test_work_verweis_wird_immer_abgewiesen():
    """Ein Uebergabeweg (agents-stack #128): auch beglaubigte Herkunft oeffnet
    keine fremden Rollen-Volumes; die Abweisung nennt den Asset-Weg."""
    for herkunft in (False, True):
        fehler, _ = refs_pruefen(["/work/administrator/bild-1.jpg"], herkunft_bekannt=herkunft)
        assert fehler and "~/.cloudcli/assets/<name>" in fehler


def test_fremder_pfad_nur_mit_hinweis():
    fehler, hinweise = refs_pruefen(["/opt/parker/site/x.html"], herkunft_bekannt=True)
    assert fehler is None
    assert len(hinweise) == 1 and "nur als Text" in hinweise[0]


def test_strict_weist_fremde_pfade_ab():
    fehler, _ = refs_pruefen(["/opt/parker/site/x.html"], herkunft_bekannt=True, strict=True)
    assert fehler and "STRICT" in fehler


# ------------------------------------------------------------- submit_task ---


def einreichen(**kw):
    with tempfile.TemporaryDirectory() as d:
        argumente = {
            "source_agent": "administrator",
            "target_agent": "crm-manager",
            "task_type": "build",
            "summary": "Newsletter bebildern",
            "description": "Fotos einsetzen",
            "queue_dir": d,
        }
        argumente.update(kw)
        ergebnis = submit_task_handler(**argumente)
        if ergebnis.get("ok"):
            import yaml

            with open(os.path.join(d, ergebnis["filename"])) as f:
                ergebnis["_task"] = yaml.safe_load(f)
        return ergebnis


def test_work_verweis_wird_nicht_eingereicht():
    for origin in (None, {"user": "cevin-30bb4a", "role": "frontend-developer"}):
        kw = {"origin": origin} if origin else {}
        ergebnis = einreichen(context_refs=["/work/administrator/small-dreams/bild-1.jpg"], **kw)
        assert ergebnis["ok"] is False
        assert "~/.cloudcli/assets/<name>" in ergebnis["error"]


def test_herkunft_wird_vermerkt():
    ergebnis = einreichen(
        context_refs=["/home/agent/.cloudcli/assets/bild-1.jpg"],
        origin={"user": "cevin-30bb4a", "role": "frontend-developer"},
    )
    assert ergebnis["ok"] is True
    assert ergebnis["_task"]["submitted_by"] == "cevin-30bb4a"
    assert ergebnis["_task"]["submitted_from_role"] == "frontend-developer"


def test_chat_anhang_bleibt_ohne_herkunft_moeglich():
    """Die Zustellung aus dem Chat-Anhang-Ordner gab es vor der Herkunft (#82)
    und bleibt erhalten — sonst waere die Verbesserung eine Verschlechterung."""
    ergebnis = einreichen(context_refs=["/home/agent/.cloudcli/assets/bild-1.jpg"])
    assert ergebnis["ok"] is True
    assert "submitted_by" not in ergebnis["_task"]


def test_fremder_pfad_kommt_mit_hinweis_durch():
    ergebnis = einreichen(context_refs=["/opt/parker/site/index.html"])
    assert ergebnis["ok"] is True
    assert ergebnis["hinweise"] and "nur als Text" in ergebnis["hinweise"][0]


def test_ohne_verweise_keine_hinweise():
    ergebnis = einreichen()
    assert ergebnis["ok"] is True and "hinweise" not in ergebnis
