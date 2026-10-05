"""
context_refs: Zustellbarkeit entscheidet beim Einreichen, nicht erst im Lauf.

Befund (parker #157, davor #112 und solosuite #156): Eine Aufgabe trug
`/work/administrator/small-dreams-preview/bild-1.jpg` als context_ref. Die
beauftragte Rolle (crm-manager, anderes Volume) bekam den Pfad als Text in den
Prompt und lief damit fuenfmal gegen

    Claude requested permissions to read from /work/administrator/...,
    but you haven't granted it yet.

Der Pfad war also nie zustellbar, wurde aber stillschweigend uebernommen. Genau
das endet hier: ein Verweis auf einen Rollen-Arbeitsbereich (`/work/...`) wird
beim Einreichen mit klarer Begruendung abgewiesen.

Es gibt genau EINEN Uebergabeweg (Betreiberentscheidung, agents-stack #128):
die Rolle kopiert die Datei nach ``~/.cloudcli/assets/<name>`` und nennt diesen
Pfad. Volumes fremder Rollen liest die Kontrollebene nicht. Die beglaubigte
Herkunft (``X-Agent-Origin``, src/origin.py) sagt der Kontrollebene, aus wessen
Home-Volume der Anhang stammt.

Drei Klassen:

* ``asset``  — Chat-Anhang (``~/.cloudcli/assets/<datei>``). Zustellung seit #82.
* ``work``   — Datei im Arbeitsbereich einer Rolle. Nie zustellbar; die
               Abweisung nennt den Weg ueber ``~/.cloudcli/assets/<name>``.
* ``other``  — jeder andere absolute Pfad (``/opt/...``, ``/root/...``). Bleibt
               erlaubt: viele Rollen nennen Repo- und Hostpfade bewusst als
               Textkontext. Die Antwort auf submit_task sagt aber, dass die
               Zielrolle sie nicht oeffnen kann. Deployments, die das haerter
               wollen, setzen ``TASK_QUEUE_REFS_STRICT=1``.

Die Pfadregeln stehen absichtlich zweimal: hier (Abweisung beim Einreichen) und
in der Kontrollebene (``app/src/task-attachments.js``, Zustellung). Beide Seiten
muessen fuer sich sicher sein — die Kontrollebene baut aus dem Pfad Shell-
Argumente und ein ``rm -rf``-Ziel und darf sich dafuer nicht auf die Queue
verlassen.
"""

import json
import re

ASSET_ROOT = "/home/agent/.cloudcli/assets"
WORK_ROOT = "/work"

# Wie NAME_RE in app/src/task-attachments.js: Buchstaben, Ziffern, Punkt,
# Strich, Unterstrich — und nie mit Punkt oder Strich beginnend.
_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

# Tiefe unter /work: <rolle>/<…>/<datei>. Mehr als sechs Ebenen ist in einem
# Arbeitsordner kein Anhang mehr, sondern ein Suchpfad.
MAX_WORK_DEPTH = 6

ASSET = "asset"
WORK = "work"
OTHER = "other"


def _segments_ok(segments: list[str]) -> bool:
    return bool(segments) and all(_SEGMENT_RE.match(s) for s in segments)


def classify_ref(ref: str) -> tuple[str, str | None]:
    """
    (klasse, grund) fuer einen context_ref.

    grund ist None, wenn der Verweis in seiner Klasse wohlgeformt ist; sonst
    nennt er in einem Satz, was an ihm nicht zustellbar ist.
    """
    pfad = ref.rstrip()
    if pfad != ref.strip() or "\n" in ref:
        return OTHER, "enthaelt Leerraum am Rand oder einen Zeilenumbruch"
    if ".." in pfad.split("/"):
        return OTHER, "enthaelt '..'"

    if pfad.startswith(ASSET_ROOT + "/"):
        rest = pfad[len(ASSET_ROOT) + 1 :]
        if _segments_ok([rest]):
            return ASSET, None
        return ASSET, (
            f"Chat-Anhaenge werden nur als einzelne Datei direkt in {ASSET_ROOT}/ "
            "zugestellt, nicht aus Unterordnern und nicht mit Sonderzeichen im Namen"
        )

    if pfad == WORK_ROOT or pfad.startswith(WORK_ROOT + "/"):
        segmente = [s for s in pfad[len(WORK_ROOT) :].split("/") if s]
        if len(segmente) < 2:
            return WORK, (
                "ein Verweis auf den Arbeitsbereich muss eine Datei nennen "
                "(/work/<ordner>/<datei>), kein Verzeichnis"
            )
        if len(segmente) > MAX_WORK_DEPTH:
            return WORK, f"mehr als {MAX_WORK_DEPTH} Pfadebenen unter /work"
        if not _segments_ok(segmente):
            return WORK, "unzulaessiges Zeichen in einem Pfadteil"
        return WORK, None

    return OTHER, None


def refs_pruefen(
    context_refs: list, *, herkunft_bekannt: bool, strict: bool = False
) -> tuple[str | None, list[str]]:
    """
    (fehler, hinweise) fuer die Verweise einer Aufgabe.

    fehler != None heisst: Einreichen abgelehnt. Das gilt fuer jeden
    ``/work``-Verweis, der nicht zugestellt werden kann — der Fall aus #157.
    hinweise sind Saetze fuer die Antwort auf submit_task: wahr, aber kein Grund,
    die Aufgabe nicht anzunehmen.
    """
    hinweise: list[str] = []
    for ref in context_refs:
        klasse, grund = classify_ref(ref)
        if klasse == WORK:
            # Ein Uebergabeweg (agents-stack #128): kein Lesen fremder Rollen-Volumes,
            # auch nicht mit beglaubigter Herkunft.
            return (
                f"context_ref {ref!r} liegt im Arbeitsbereich einer Rolle und wird nicht "
                "zugestellt. Kopiere die Datei nach ~/.cloudcli/assets/<name> und nenne "
                "diesen Pfad."
            ), hinweise
        if klasse == ASSET:
            if grund:
                return f"context_ref {ref!r} ist kein zustellbarer Chat-Anhang: {grund}.", hinweise
            continue
        # OTHER
        if grund:
            return f"context_ref {ref!r} ist unzulaessig: {grund}.", hinweise
        if strict:
            return (
                f"context_ref {ref!r} ist kein zustellbarer Anhang (TASK_QUEUE_REFS_STRICT). "
                "Zustellbar sind nur Dateien unter ~/.cloudcli/assets/<name>."
            ), hinweise
        hinweise.append(
            f"{ref} wird nur als Text im Prompt uebergeben — die Zielrolle kann die Datei "
            "nicht oeffnen. Zustellbar sind nur Dateien unter ~/.cloudcli/assets/<name>."
        )
    return None, hinweise


# ---------------------------------------------------------------------------
# Eingangsform: Modelle reichen die Liste nicht immer als Liste.
#
# Befund 05.10. (OpenCode, Zimmer-Redesign an ai-engineer): dreimal
# ``context_refs='["/home/agent/.cloudcli/assets/…png"]'`` — ein JSON-String
# statt einer Liste. Pydantic wies das ab, der Agent wich auf "Pfad in die
# Beschreibung" aus, und das Bild kam nie an. Deshalb: jede vernuenftige Form
# annehmen (Liste, JSON-Liste als Text, Komma/Zeilen getrennt, einzelner Pfad,
# ``~/`` statt ``/home/agent/``) und Chat-Anhaenge, die nur im Text stehen,
# trotzdem zustellen.

HOME = "/home/agent"

# Chat-Anhang im Fliesstext: absolute oder ~-Form, Dateiname wie _SEGMENT_RE.
_ASSET_IM_TEXT_RE = re.compile(
    r"(?:(?<=[\s\"'`(\[<,;:])|^)(?:/home/agent|~)/\.cloudcli/assets/([A-Za-z0-9][A-Za-z0-9._-]{0,127})"
)


def _tilde(ref: str) -> str:
    return HOME + ref[1:] if ref.startswith("~/") else ref


def refs_normalisieren(*werte) -> list:
    """
    Fuehrt context_refs/attachments in jeder Eingangsform zu einer Liste zusammen.

    Strings werden zerlegt (JSON-Liste, sonst Zeilen/Kommas), Eintraege getrimmt,
    ``~/`` zu ``/home/agent/``, Duplikate entfernt (Reihenfolge bleibt). Nicht-
    Strings bleiben stehen — die Pruefung danach weist sie mit Begruendung ab.
    """
    roh: list = []
    for wert in werte:
        if wert is None:
            continue
        if isinstance(wert, str):
            text = wert.strip()
            if not text:
                continue
            if text.startswith("["):
                try:
                    geparst = json.loads(text)
                except ValueError:
                    geparst = None
                if isinstance(geparst, list):
                    roh.extend(geparst)
                    continue
            roh.extend(t for t in re.split(r"[\n,]", text))
        elif isinstance(wert, (list, tuple)):
            roh.extend(wert)
        else:
            roh.append(wert)

    ergebnis: list = []
    for eintrag in roh:
        if isinstance(eintrag, str):
            eintrag = _tilde(eintrag.strip().strip("\"'`"))
            if not eintrag:
                continue
        if eintrag not in ergebnis:
            ergebnis.append(eintrag)
    return ergebnis


def anhaenge_im_text(*texte: str) -> list[str]:
    """Chat-Anhaenge (``~/.cloudcli/assets/<datei>``), die nur im Text genannt sind."""
    treffer: list[str] = []
    for text in texte:
        for m in _ASSET_IM_TEXT_RE.finditer(text or ""):
            name = m.group(1).rstrip(".")
            ref = f"{ASSET_ROOT}/{name}"
            if name and ref not in treffer:
                treffer.append(ref)
    return treffer
