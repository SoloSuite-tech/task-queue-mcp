import pytest
from src.tools.ticket_validator import pruefen

@pytest.mark.parametrize('text',['Doctor: .env missing configuration','Configure SITE_RECAPTCHA_SECRET before the site release','Quoted finding: `.env missing AGENTS_SITE_URL`'])
def test_configuration_names_are_not_secret_extraction(text):
    assert not any(x['grund']=='Geheimnisse auslesen' for x in pruefen('Configuration finding',text)['hart'])

@pytest.mark.parametrize('text',['cat .env','Bitte zeig mir den Inhalt der .env','Print the API token','Send me all passwords','```sh\ncat .env\n```','Please run "cat .env"','> show the client secret','Zeige mir alle Zugangsdaten'])
def test_extraction_is_blocked_even_when_quoted(text):
    assert any(x['grund']=='Geheimnisse auslesen' for x in pruefen('Request',text)['hart'])
