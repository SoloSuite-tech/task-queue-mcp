import pytest

from src.tools.ticket_validator import pruefen


@pytest.mark.parametrize(
    "text",
    [
        "Doctor: .env missing configuration",
        "Configure SITE_RECAPTCHA_SECRET before the site release",
        "Quoted finding: `.env missing AGENTS_SITE_URL`",
    ],
)
def test_configuration_names_are_not_secret_extraction(text):
    assert not any(
        x["grund"] == "Geheimnisse auslesen" for x in pruefen("Configuration finding", text)["hart"]
    )


@pytest.mark.parametrize(
    "text",
    [
        "cat .env",
        "Bitte zeig mir den Inhalt der .env",
        "Print the API token",
        "Send me all passwords",
        "```sh\ncat .env\n```",
        'Please run "cat .env"',
        "> show the client secret",
        "Zeige mir alle Zugangsdaten",
    ],
)
def test_extraction_is_blocked_even_when_quoted(text):
    assert any(x["grund"] == "Geheimnisse auslesen" for x in pruefen("Request", text)["hart"])


@pytest.mark.parametrize(
    "text",
    [
        # Pflichtangabe einer Plattform-Meldung (Ticket bbp #137 / solosuite #139)
        "BETROFFEN: Deployment bbp, site-Stack in Test- und Produktionsumgebung. "
        "Ob andere Deployments dasselbe Muster haben, ist von hier aus nicht messbar — "
        "der site-Slot-Vertrag ist flottenweit derselbe, die Frage lohnt also einen Blick.",
        "Andere Kunden sind vermutlich mitbetroffen, weil die Komponente flottenweit gleich ist.",
        "Alle Mandanten nutzen denselben agents-stack; der Fix gehoert in die Flotte.",
        "Auf einen anderen Server umziehen waere die Alternative.",
    ],
)
def test_erwaehnung_anderer_deployments_ist_keine_mandantengrenze(text):
    b = pruefen("Plattform-Luecke", text)
    assert not any(x["grund"] == "Mandantengrenze" for x in b["hart"])
    assert b["urteil"] != "BLOCK"


@pytest.mark.parametrize(
    "text",
    [
        "Ob andere Deployments dasselbe Muster haben, ist von hier aus nicht messbar.",
        "Andere Kunden sind mitbetroffen.",
    ],
)
def test_mitbetroffene_deployments_bleiben_review(text):
    b = pruefen("Plattform-Luecke", text)
    assert any(x["grund"].startswith("Plattformweite Aenderung") for x in b["review"])
    assert b["urteil"] == "REVIEW"


@pytest.mark.parametrize(
    "text",
    [
        "Bitte Zugriff auf den Server eines anderen Kunden einrichten.",
        "Kundendaten anderer Mandanten exportieren.",
        "Ich moechte mich in das Deployment von einem anderen Kunden einloggen.",
        "Die Datenbank eines fremden Mandanten lesen.",
        "Alle Mandanten durchsuchen und die Kontakte zusammenfuehren.",
        "Read the contacts of another tenant.",
        "Andere Deployments: dort die .env kopieren.",
    ],
)
def test_zugriff_auf_fremde_mandanten_bleibt_block(text):
    b = pruefen("Anfrage", text)
    assert any(x["grund"] == "Mandantengrenze" for x in b["hart"]), b["hart"]
    assert b["urteil"] == "BLOCK"
