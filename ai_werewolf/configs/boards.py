from __future__ import annotations

from ai_werewolf.models.schema import GameConfig, Role


BOARD_PRESETS: dict[str, list[str]] = {
    "6p": [
        Role.WEREWOLF.value,
        Role.WEREWOLF.value,
        Role.SEER.value,
        Role.WITCH.value,
        Role.VILLAGER.value,
        Role.VILLAGER.value,
    ],
    "8p-simple": [
        Role.WEREWOLF.value,
        Role.WEREWOLF.value,
        Role.WEREWOLF.value,
        Role.SEER.value,
        Role.WITCH.value,
        Role.VILLAGER.value,
        Role.VILLAGER.value,
        Role.VILLAGER.value,
    ],
    "10p-standard": [
        Role.WEREWOLF.value,
        Role.WEREWOLF.value,
        Role.WEREWOLF.value,
        Role.SEER.value,
        Role.WITCH.value,
        Role.HUNTER.value,
        Role.GUARD.value,
        Role.VILLAGER.value,
        Role.VILLAGER.value,
        Role.VILLAGER.value,
    ],
}


def available_presets() -> list[str]:
    return sorted(BOARD_PRESETS)


def parse_roles(raw: str) -> list[str]:
    roles = [item.strip().lower() for item in raw.split(",") if item.strip()]
    if not roles:
        raise ValueError("roles must not be empty")
    valid = {role.value for role in Role}
    invalid = [role for role in roles if role not in valid]
    if invalid:
        raise ValueError(f"unknown role(s): {', '.join(invalid)}; valid roles: {', '.join(sorted(valid))}")
    return roles


def parse_player_ids(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [item.strip().upper() for item in raw.split(",") if item.strip()]


def build_config(
    *,
    preset: str = "6p",
    roles: list[str] | None = None,
    seed: int | None = 42,
    max_days: int = 10,
    tie_policy: str = "no_exile",
    human_players: list[str] | None = None,
    reveal_death_role: bool = False,
    version_label: str = "rule_based_v2",
) -> GameConfig:
    if roles is None:
        try:
            roles = list(BOARD_PRESETS[preset])
        except KeyError as exc:
            raise ValueError(f"unknown board preset: {preset}; available: {', '.join(available_presets())}") from exc
    config = GameConfig(
        player_count=len(roles),
        roles=roles,
        random_seed=seed,
        max_days=max_days,
        tie_policy=tie_policy,
        human_players=human_players or [],
        reveal_death_role=reveal_death_role,
        version_label=version_label,
    )
    config.validate()
    return config
