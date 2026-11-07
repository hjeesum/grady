"""Read what a job advert says about visa sponsorship.

An employer on the sponsor register doesn't sponsor every job: in a week of real
adverts (Nov 2026), 22 of 41 said they wouldn't. This reads the advert's own
words with fixed phrases, so every decision can be tested and explained. (An AI
model would understand more wordings, but would cost money on every run.)

Only sentences about visas or the right to work are read, so "paid for the full
duration of the programme" elsewhere in an advert doesn't count.
"""

import re

# The notes saved in the database (jobs.visa_note). NULL there = not read yet.
SPONSORS = "sponsors"  # says it will sponsor a visa
VISA_MUST_LAST = "visa_must_last"  # no sponsorship, but your own visa is fine if it lasts the whole job
NO_SPONSORSHIP = "no_sponsorship"
SAYS_NOTHING = ""
# Shown next to the job in the email.
LABELS = {
    SPONSORS: "Advert says it sponsors visas",
    VISA_MUST_LAST: "No sponsorship: your own visa must last the whole job",
    NO_SPONSORSHIP: "Advert says no sponsorship",
}

ABOUT_VISAS = re.compile(r"sponsor|visa|right to work|work permit|immigration")

# "Not now, not later, not on a Graduate visa": nobody who needs a visa can apply.
HARD_NO = [
    r"now,? or (at any (point|time) )?in the (foreseeable )?future",
    r"(current|now) or future sponsorship",
    r"(now|currently),? (and|or) (later|going forward)",
    r"including (those |candidates |applicants )?(on|with|holding) (a )?graduate",
    r"graduate (route |visa )*(holders )?(are|is) not (eligible|accepted)",
]
# Only acceptable if your own permission to work lasts long enough.
MUST_LAST = [
    r"(full|entire|whole) (duration|length|term|period)",
    r"for the duration of",
    r"right to work[^.]{0,40} for (at least|more than|a minimum of|over) ",
    r"remaining on (their|your) [^.]{0,30}visa",
]
NO = [
    r"(unable|not able|cannot|can ?not|can't|won't|will not|do not|don't|does not|doesn't|"
    r"not in a position) to (offer|provide|support|sponsor|consider|accept|apply for)\b[^.]{0,60}(sponsor|visa)",
    r"(cannot|can ?not|can't|unable to|not able to|won't|will not|do not|don't|does not) sponsor\b",
    r"(does|do|will|can|is|are) not (offer|provide|support)[^.]{0,30}sponsor",
    r"sponsorship (is |will )?(not|n't) (be )?(available|offered|provided|possible)",
    r"\bno (visa )?sponsorship\b",
    r"without (the need for |requiring |needing |the need of )?[^.]{0,25}sponsorship",
    r"not (eligible|able to apply)[^.]{0,30}sponsor",
]
YES = [
    r"(will|can|are able to|is able to|happy to|able to) (offer|provide|consider) [^.]{0,30}sponsor",
    r"(provide|offer|sponsor) (a |an )?skilled worker visa",
    r"accept applications from (candidates|applicants) who (will )?require (visa )?sponsorship",
    r"sponsorship (is )?available",
    r"\bwe (can |do |will )?sponsor (work )?visas",
]


def visa_note(text: str) -> str:
    """One of SPONSORS, VISA_MUST_LAST, NO_SPONSORSHIP or SAYS_NOTHING."""
    sentences = visa_sentences(text)

    def says(patterns):
        return any(re.search(p, s) for p in patterns for s in sentences)

    # The order matters: a strict "no" beats a duration rule ("must have the
    # right to work for 2 years ... cannot sponsor now or in the future"), and
    # any "no" beats a "yes" ("sponsorship available" is inside "no sponsorship available").
    if says(HARD_NO):
        return NO_SPONSORSHIP
    if says(MUST_LAST):
        return VISA_MUST_LAST
    if says(NO):
        return NO_SPONSORSHIP
    if says(YES):
        return SPONSORS
    return SAYS_NOTHING


def visa_sentences(text: str) -> list[str]:
    """The advert's sentences that mention visas or the right to work, in lower case."""
    text = re.sub(r"\s+", " ", text.lower().replace("’", "'"))
    return [s for s in re.split(r"(?<=[.!?;])\s+|\s+[•·]\s+", text) if ABOUT_VISAS.search(s)]
