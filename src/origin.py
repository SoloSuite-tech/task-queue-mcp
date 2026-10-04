"""
Beglaubigte Herkunft eines submit_task-Aufrufs: welches Konto, welche Sandbox.

Warum ueberhaupt. Soll die Kontrollebene einen Anhang der EINREICHENDEN Sandbox
(``~/.cloudcli/assets/<name>``, agents-stack #82/#128) in den Aufgaben-Ordner der
Zielrolle kopieren (parker #157), muss sie wissen, aus wessen Home-Volume.
Das Bearer-Token der Queue sagt das nicht: es gibt genau eines je Rolle, fuer
alle Konten gemeinsam. Deshalb trug kein Task bisher ein ``submitted_by``, und
die Zustellung konnte das Konto nur raten.

Warum ein Header und kein zweiter Token. Ein Header, den der Agent selbst setzen
koennte, waere eine schwaechere zweite Identitaetsquelle — genau das, was
src/auth.py ablehnt. Dieser hier ist signiert: die Kontrollebene legt ihn beim
Einrichten der Sandbox in die ``.mcp.json`` der Rolle, der Schluessel dafuer
steht nur in der Kontrollebene und hier. Ein Agent kann den Wert seiner eigenen
Sandbox lesen und weiterreichen — aber keinen fuer ein anderes Konto bilden. Und
genau das ist die Grenze, die zaehlt: zugestellt wird nur aus dem Home des
Einreichenden, in dem er ohnehin schon lesen darf.

Form:  ``v1.<konto>.<rolle>.<mac>``   — mac = HMAC-SHA256 ueber ``v1.<konto>.<rolle>``,
                                        128 Bit hex, Schluessel s. u.

Der Schluessel ist aus ``TASK_QUEUE_API_SECRET`` abgeleitet (eigene Domain, damit
die Herkunfts-Signatur und das Betreiber-Secret nicht derselbe Wert sind) — kein
neues Vertragsfeld in ``.env``, kein neues Geheimnis, das je Host verteilt werden
muesste. Fehlt das Secret, gibt es keine beglaubigte Herkunft; die Zustellung
faellt dann auf den bisherigen Rueckfall (#82) zurueck.
"""

import hmac
import logging
import os
import re
from hashlib import sha256

logger = logging.getLogger(__name__)

HEADER = "x-agent-origin"
VERSION = "v1"
DOMAIN = b"agents-task-origin-v1"
MAC_HEX_LEN = 32

# Konto- und Rollen-Ids wie in app/src/sandbox.js (ID_RE): klein, ohne Punkt.
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")


def origin_key(secret: str | None = None) -> bytes | None:
    """Abgeleiteter Signaturschluessel, oder None wenn kein Secret gesetzt ist."""
    roh = os.environ.get("TASK_QUEUE_API_SECRET", "") if secret is None else secret
    roh = (roh or "").strip()
    if not roh:
        return None
    return hmac.new(roh.encode(), DOMAIN, sha256).digest()


def sign(konto: str, rolle: str, key: bytes) -> str:
    """Herkunfts-Nachweis bilden (die Kontrollebene tut das in JS, gleiche Form)."""
    rumpf = f"{VERSION}.{konto}.{rolle}"
    mac = hmac.new(key, rumpf.encode(), sha256).hexdigest()[:MAC_HEX_LEN]
    return f"{rumpf}.{mac}"


def parse_origin(wert: str | None, key: bytes | None) -> dict | None:
    """
    Geprueften Herkunfts-Nachweis als {"user", "role"} — oder None.

    None heisst immer "keine Herkunft bekannt", nie "egal": der Aufrufer weist
    ``/work``-Verweise dann ab. Ein falsch signierter Wert wird protokolliert,
    aber nicht zum Fehler des Einreichens: ohne Herkunft greift ohnehin die
    Abweisung mit verstaendlicher Begruendung.
    """
    if not wert or not key:
        return None
    teile = str(wert).strip().split(".")
    if len(teile) != 4 or teile[0] != VERSION:
        logger.warning("origin: unbekannte Form des Herkunfts-Nachweises")
        return None
    _, konto, rolle, mac = teile
    if not ID_RE.match(konto) or not ID_RE.match(rolle):
        logger.warning("origin: unzulaessige Konto- oder Rollen-Id im Herkunfts-Nachweis")
        return None
    if not hmac.compare_digest(mac, sign(konto, rolle, key).rsplit(".", 1)[1]):
        logger.warning("origin: Herkunfts-Nachweis fuer Konto %s nicht gueltig signiert", konto)
        return None
    return {"user": konto, "role": rolle}


def origin_from_headers(headers: dict | None, secret: str | None = None) -> dict | None:
    """Herkunft aus den HTTP-Headern des laufenden Aufrufs (Namen klein gelesen)."""
    if not headers:
        return None
    wert = None
    for name, inhalt in headers.items():
        if str(name).lower() == HEADER:
            wert = inhalt
            break
    return parse_origin(wert, origin_key(secret))
