"""Regenerate data/systems_summary.json (planet count and flags per star) and print statistics.

Usage:  python tools/generate_systems.py [--seed N]

Simulated systems are deterministic for a given seed; a different seed gives a different
(equally plausible) galaxy. Confirmed systems (data/known_planets.json, data/solar_system.json)
are never changed by the seed - only their simulated moons are.
"""

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import systems as S  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=None, help="random seed (default: keep the current one)")
    args = parser.parse_args()

    stars = json.loads((ROOT / "data" / "stars.json").read_text(encoding="utf-8"))["stars"]
    start = time.time()
    summary = S.load_or_build_summary(ROOT / "data", stars, seed=args.seed, force=True)
    print(f"Generated {len(stars)} systems (seed {summary['seed']}) in {time.time() - start:.1f} s")

    total, with_planets, habitable, conservative, hab_moon, giant = (Counter() for _ in range(6))
    planets = 0
    for star, n, flags in zip(stars, summary["planets"], summary["flags"]):
        props = S.star_properties(star["spectral_class"], star.get("abs_mag"))
        group = props["group"] if props["category"] == "main_sequence" else S.CATEGORY_LABELS[props["category"]]
        total[group] += 1
        with_planets[group] += n > 0
        habitable[group] += bool(flags & S.FLAG_HABITABLE)
        conservative[group] += bool(flags & S.FLAG_CONSERVATIVE)
        hab_moon[group] += bool(flags & S.FLAG_HAB_MOON)
        giant[group] += bool(flags & S.FLAG_GIANT)
        planets += n

    confirmed = sum(1 for f in summary["flags"] if f & S.FLAG_CONFIRMED)
    print(f"{planets} planets in total; {confirmed} stars have confirmed (real) systems\n")
    print(f"{'Star type':<24}{'stars':>8}{'planets':>9}{'giant':>8}{'hab.':>8}{'cons.':>8}{'moon':>7}")
    order = list("OBAFGKM") + list(S.CATEGORY_LABELS.values())
    for group in sorted(total, key=lambda g: order.index(g) if g in order else 99):
        n = total[group]
        label = f"{group} dwarf" if len(group) == 1 else group
        print(f"{label:<24}{n:>8}{with_planets[group] / n:>9.1%}{giant[group] / n:>8.1%}"
              f"{habitable[group] / n:>8.1%}{conservative[group] / n:>8.1%}{hab_moon[group] / n:>7.2%}")
    print("\nColumns: share of stars with any planet, with a gas giant, with a potentially habitable "
          "rocky planet (optimistic / conservative habitable zone) and with a habitable-size moon.")


if __name__ == "__main__":
    main()
