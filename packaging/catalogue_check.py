"""Read-only installed catalogue check using the runtime's visibility gates."""
import sys
from pathlib import Path


def main(home, release):
    # Use the serving release's registry, including when control is newer.
    sys.path.insert(0, str(release))
    from ai_router import availability, catalogue, model_policy
    available = availability.effective_ids(
        home, availability.current_key(home), availability.current_region(home))
    return 0 if catalogue.check(
        home / 'mixed-models.json', allowed=model_policy.load(home)[2],
        available=available) else 1


if __name__ == '__main__':
    raise SystemExit(main(Path(sys.argv[1]), Path(sys.argv[2])))
