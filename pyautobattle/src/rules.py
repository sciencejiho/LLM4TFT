"""Versioned economy and timing profiles for the simplified autobattler."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Rules:
    """Describe one reproducible economy and combat pacing profile."""

    name: str
    starting_hp: int
    starting_level: int
    starting_gold: int
    preparation_seconds: int
    combat_seconds: int
    early_income: tuple[int, ...]
    max_rounds: int = 200

    def base_income(self, turn: int) -> int:
        """Return income for a zero-based completed combat round."""
        return self.early_income[min(max(turn, 0), len(self.early_income) - 1)]

    def streak_income(self, streak: int) -> int:
        """Return the bounded bonus for consecutive wins or losses."""
        length = abs(streak)
        if self.name == "legacy":
            return min(length, 6) if length >= 2 else 0
        if length >= 5:
            return 3
        if length >= 4:
            return 2
        return 1 if length >= 2 else 0

    def round_damage(self, turn: int) -> int:
        """Return base player damage, increasing every five research rounds."""
        if self.name == "legacy":
            return 3
        return (0, 2, 3, 5, 8, 12, 16)[min(max(turn, 0) // 5, 6)]


RESEARCH = Rules("research", 100, 2, 3, 45, 30, (2, 2, 3, 4, 5))
LEGACY = Rules("legacy", 30, 1, 0, 10, 5, (10,))


def resolve_rules(rules: object = None) -> Rules:
    """Resolve a profile name or Rules instance, rejecting unknown names."""
    if isinstance(rules, Rules):
        return rules
    if rules is None or rules == "research":
        return RESEARCH
    if rules == "legacy":
        return LEGACY
    raise ValueError(f"Unknown ruleset: {rules!r}")
