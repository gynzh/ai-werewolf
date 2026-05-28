from __future__ import annotations

from ai_werewolf.models.schema import Faction, Role


ROLE_CN = {
    Role.WEREWOLF.value: "狼人",
    Role.SEER.value: "预言家",
    Role.WITCH.value: "女巫",
    Role.HUNTER.value: "猎人",
    Role.GUARD.value: "守卫",
    Role.VILLAGER.value: "平民",
}

FACTION_CN = {
    Faction.WOLVES.value: "狼人阵营",
    Faction.GOOD.value: "好人阵营",
}


def faction_of(role: str) -> str:
    return Faction.WOLVES.value if role == Role.WEREWOLF.value else Faction.GOOD.value


def role_name_cn(role: str) -> str:
    return ROLE_CN.get(role, role or "未知")


def faction_name_cn(faction: str) -> str:
    return FACTION_CN.get(faction, faction or "未知")


def is_god_role(role: str) -> bool:
    return role in {Role.SEER.value, Role.WITCH.value, Role.HUNTER.value, Role.GUARD.value}
