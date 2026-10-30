"""Measure sponsor matching against hand-labelled examples, across thresholds.

Run from the project root:  python -m scripts.evaluate_matching

Each row of the labels file is a company name from a real job advert and the
register name it should match (blank if it should match nothing).
"""

import csv

from grady.config import PROJECT_ROOT
from grady.matching import FUZZY_THRESHOLD, SponsorMatcher
from grady.sponsors import download_register, load_sponsor_names

LABELS_PATH = PROJECT_ROOT / "tests" / "data" / "sponsor_match_labels.csv"


def main() -> None:
    with open(LABELS_PATH, encoding="utf-8", newline="") as f:
        labels = list(csv.DictReader(f))

    # threshold=0 makes the matcher always return its best fuzzy guess with its
    # score, so we can test every threshold without re-running the search.
    matcher = SponsorMatcher(load_sponsor_names(download_register()), threshold=0)
    results = []
    for row in labels:
        match = matcher.match(row["advert_company"])
        expected = row["expected_register_name"] or None
        results.append((row["advert_company"], expected, match))

    print(f"{len(results)} labelled companies, "
          f"{sum(1 for _, e, _ in results if e)} of them should match.\n")
    print("threshold  correct  wrong  missed")
    for threshold in range(85, 101):
        correct = wrong = missed = 0
        for _, expected, match in results:
            accepted = match is not None and match.score >= threshold
            if accepted and match.register_name == expected:
                correct += 1
            elif accepted:
                wrong += 1
            if expected and not (accepted and match.register_name == expected):
                missed += 1
        marker = "  <- chosen" if threshold == FUZZY_THRESHOLD else ""
        print(f"{threshold:>9}  {correct:>7}  {wrong:>5}  {missed:>6}{marker}")

    print(f"\nDecisions at the chosen threshold ({FUZZY_THRESHOLD}) that aren't exact matches:")
    for company, expected, match in results:
        accepted = match is not None and match.score >= FUZZY_THRESHOLD
        if accepted and match.method == "exact":
            continue
        if accepted:
            verdict = "OK" if match.register_name == expected else "WRONG"
            print(f"  {verdict:6} {company!r} -> {match.register_name!r} "
                  f"({match.method}, {match.score:.1f})")
        elif expected:
            print(f"  MISSED {company!r} should be {expected!r}")


if __name__ == "__main__":
    main()
