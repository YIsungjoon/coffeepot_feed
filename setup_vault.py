"""Prepare the target vault and copy default dashboards that are missing."""

from feed_settings import ROOT, vault_path
from save_feed import write_new_note


def setup() -> None:
    vault = vault_path()
    for folder in (".obsidian", "10_Feeds/Articles", "10_Feeds/Daily_Digest", "20_Notes"):
        (vault / folder).mkdir(parents=True, exist_ok=True)
    for template in sorted((ROOT / "vault-templates").glob("*.md")):
        destination = vault / template.name
        if not destination.exists():
            write_new_note(destination, template.read_text(encoding="utf-8"))
    print(vault)


if __name__ == "__main__":
    setup()
