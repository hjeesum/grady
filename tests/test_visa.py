import pytest

from grady.adverts import plain
from grady.visa import NO_SPONSORSHIP, SAYS_NOTHING, SPONSORS, VISA_MUST_LAST, visa_note


# Real sentences from adverts at sponsor employers (Nov 2026).
@pytest.mark.parametrize("text, expected", [
    # Graphcore: both sentences together. Your own visa is fine if it lasts.
    ("Applicants must already have the right to work in the UK for the full duration of the "
     "programme, without requiring visa sponsorship. We are unable to sponsor work visas for "
     "our Early Careers opportunities.", VISA_MUST_LAST),
    ("We can only consider applicants with at least one year remaining on their Graduate or "
     "Post-Study Work visa. We cannot currently offer visa sponsorship.", VISA_MUST_LAST),
    # A strict "no" beats the duration rule.
    ("Must have own right to work in the UK for more than 2 years. Unfortunately, we cannot "
     "consider applications requiring visa sponsorship now, or in the future.", NO_SPONSORSHIP),
    ("We are unable to offer sponsorship for this position at this time, including to those on "
     "Graduate Visas.", NO_SPONSORSHIP),
    ("Applicants must have the right to work without the need for current or future sponsorship.",
     NO_SPONSORSHIP),
    ("Please note that visa sponsorship is not available for this position.", NO_SPONSORSHIP),
    ("Veeva does not provide sponsorship for employment visa status for this position.", NO_SPONSORSHIP),
    ("We are not able to offer visa sponsorship for this position.", NO_SPONSORSHIP),
    ("You will need the right to work in the UK - we can't sponsor work permits.", NO_SPONSORSHIP),
    ("We are unable to accept applications from candidates who require a visa to work in the UK.",
     NO_SPONSORSHIP),
    ("Barclays will accept applications from candidates who require visa sponsorship to work in "
     "the UK and will provide a Skilled Worker visa for successful applicants.", SPONSORS),
    ("We sponsor visas and encourage underrepresented groups to apply.", SPONSORS),
    ("Applicants must be authorised to work in the UK.", SAYS_NOTHING),
    ("", SAYS_NOTHING),
])
def test_visa_note(text, expected):
    assert visa_note(text) == expected


def test_only_sentences_about_visas_count():
    # "Full duration" here is about pay, not visas.
    assert visa_note("You'll be paid for the full duration of the programme.") == SAYS_NOTHING
    # A sponsor of an event isn't a visa sponsor.
    assert visa_note("Help develop the events business, including sponsor research.") == SAYS_NOTHING


def test_no_sponsorship_available_is_not_a_yes():
    # "sponsorship available" is inside "no sponsorship available".
    assert visa_note("There is no sponsorship available for this role.") == NO_SPONSORSHIP


def test_plain_text_from_html():
    # Escaped twice, as some systems send it; list items become separate sentences.
    html = "&lt;ul&gt;&lt;li&gt;Full duration of the programme&lt;/li&gt;&lt;li&gt;No visa sponsorship&lt;/li&gt;&lt;/ul&gt;"
    assert plain(html) == "Full duration of the programme. No visa sponsorship."
    assert visa_note(plain(html)) == NO_SPONSORSHIP  # the duration line isn't about visas
