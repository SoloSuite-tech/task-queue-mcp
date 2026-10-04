"""
Code-Sperre fuer Agenten (v0.13): der Isolations-Marker gehoert dem Betreiber.

Ein Task, dessen Titel oder Beschreibung den Marker `workspace:agents` allein auf
einer Zeile traegt, laeuft nach der Freigabe in einem eigenen Container mit einem
schreibbaren Worktree des Agents-Stacks (Kontrollebene: app/src/isolation-marker.js).
Das ist der Weg, auf dem der BETREIBER Plattform-Code bauen laesst. Kein Agent darf
Agents-Code, Rollen-Vertraege, Systemprompts oder Leitplanken aendern — also darf
auch keine Rolle einen solchen Task einreichen. Anlass (27.09.2026): eine
Kundensitzung bot an, "das Verhalten der Plattform" per Marker-Task umzubauen.

Die Sperre sitzt am MCP-Werkzeug submit_task (Rollen-Token). Die Control-Route
POST /tasks/submit (Secret = Betreiber: Cockpit, Routinen, Ticket-Wachen) bleibt
unveraendert — dort kommen die legitimen Marker-Tasks her.

Das Muster ist eine Kopie von MARKER_LINE in app/src/isolation-marker.js. Beide
muessen dasselbe erkennen; die Tests beider Seiten nutzen dieselben Beispiele.
"""

import re

MARKER_LINE = re.compile(r"^\s*(?:[-*]\s*)?(?:marker\s*:\s*)?workspace:agents\s*$", re.IGNORECASE)

ABLEHNUNG = (
    "Abgelehnt: Aenderungen an Plattform-Code, Rollen-Vertraegen, Systemprompts und "
    "Leitplanken macht kein Agent — der Isolations-Marker ist dem Betreiber vorbehalten. "
    "Fehlt der Plattform eine Faehigkeit, melde sie als Ticket 'Plattform-Luecke' "
    "(ticket_create: Symptom und Wirkung in Kundensprache); gebaut wird zentral vom "
    "Betreiber. Den Nutzer nicht auf einen anderen Weg verweisen."
)


def has_isolation_marker(text) -> bool:
    return any(MARKER_LINE.match(line) for line in re.split(r"\r?\n", str(text or "")))


def role_submit_refusal(summary, description) -> str | None:
    """Fehlertext, wenn eine Rolle einen Marker-Task einreichen will, sonst None."""
    if has_isolation_marker(summary) or has_isolation_marker(description):
        return ABLEHNUNG
    return None
