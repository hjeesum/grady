"""Match a job advert's company name to a name on the Register of Licensed Sponsors.

Three checks, from safest to riskiest:
1. Exact: the normalised names are identical ("Capgemini" = "Capgemini UK PLC").
2. Unique prefix: the advert name is the start of exactly ONE register name
   ("Tarmac" -> "Tarmac Trading Limited"). If several register names start that
   way, we don't guess.
3. Fuzzy: whole-name similarity (rapidfuzz ratio) above a high threshold, for
   small typos and spacing differences.
"""

from collections import defaultdict
from dataclasses import dataclass

from rapidfuzz import fuzz, process

from grady.normalise import normalise_company

# Chosen with `python -m scripts.evaluate_matching` on tests/data/sponsor_match_labels.csv.
# 93 scored perfectly, but its closest correct match (93.6) sat just above a wrong
# one (92.9). 95 keeps a safety margin, at the cost of one missed match: we'd
# rather miss a sponsor than show a job from a company that can't sponsor.
FUZZY_THRESHOLD = 95


@dataclass(frozen=True)
class SponsorMatch:
    register_name: str  # the name as written in the register
    method: str  # "exact", "prefix" or "fuzzy"
    score: float  # 100 for exact and prefix matches


class SponsorMatcher:
    def __init__(self, sponsors: dict[str, str], threshold: float = FUZZY_THRESHOLD):
        """sponsors maps normalised name -> register name (from sponsors.load_sponsor_names)."""
        self.sponsors = sponsors
        self.threshold = threshold
        self._names = list(sponsors)

        # Index every leading run of words: "tarmac trading" is stored under "tarmac".
        # Built once, so each prefix lookup is an instant dict lookup.
        self._by_prefix = defaultdict(set)
        for name in self._names:
            words = name.split()
            for i in range(1, len(words)):
                self._by_prefix[" ".join(words[:i])].add(name)

        # The same company appears in many adverts; remember answers we've worked out.
        self._cache = {}

    def match(self, company: str) -> SponsorMatch | None:
        name = normalise_company(company)
        if not name:
            return None
        if name not in self._cache:
            self._cache[name] = self._match_normalised(name)
        return self._cache[name]

    def _match_normalised(self, name: str) -> SponsorMatch | None:
        if name in self.sponsors:
            return SponsorMatch(self.sponsors[name], "exact", 100)

        candidates = self._by_prefix.get(name, set())
        if len(candidates) == 1:
            (candidate,) = candidates
            return SponsorMatch(self.sponsors[candidate], "prefix", 100)

        # score_cutoff lets rapidfuzz skip names that can't reach the threshold,
        # which makes searching 128,000 names much faster.
        best = process.extractOne(
            name, self._names, scorer=fuzz.ratio, score_cutoff=self.threshold
        )
        if best is None:
            return None
        matched_name, score, _ = best
        return SponsorMatch(self.sponsors[matched_name], "fuzzy", score)
