# Copyright mio authors & contributors <https://github.com/mirukana/mio>
# SPDX-License-Identifier: LGPL-3.0-or-later

import operator
import re
from contextlib import suppress
from dataclasses import dataclass, field
from enum import Enum, auto
from fnmatch import fnmatchcase
from typing import ClassVar, Dict, List, Optional, Tuple, Type, TypeVar, Union

from ..core.contents import EventContent
from ..core.data import (
    JSON, AutoStrEnum, DictS, IndexableMap, JSONLoadError, Runtime,
)
from ..core.ids import UserId
from ..core.utils import deep_find_subclasses, dot_flatten_dict
from ..rooms.events import TimelineEvent

PushCondT = TypeVar("PushCondT", bound="PushCondition")


@dataclass
class PushCondition(JSON):
    kind: ClassVar[Optional[str]] = None

    source: Runtime[DictS] = field(repr=False)


    @classmethod
    def from_dict(cls: Type[PushCondT], data: DictS, parent) -> PushCondT:
        data["source"] = data

        if cls is not PushCondition:
            return super().from_dict(data, parent)

        for subcls in deep_find_subclasses(cls):
            if subcls.kind == data.get("kind"):
                with suppress(JSONLoadError):
                    return subcls.from_dict(data, parent)

        return super().from_dict(data, parent)


    def triggered_by(self, event: TimelineEvent) -> bool:
        return False


@dataclass
class PushEventMatch(PushCondition):
    kind    = "event_match"
    aliases = {"field": "key"}

    field:   str
    pattern: str


    def triggered_by(self, event: TimelineEvent) -> bool:
        value = str(dot_flatten_dict(event.dict).get(self.field))

        if self.field == "content.body":
            pattern = f"*[!a-z0-9]{self.pattern.lower()}[!a-z0-9]*"
            return fnmatchcase(f" {value.lower()} ", pattern)

        return fnmatchcase(value.lower(), self.pattern.lower())


@dataclass
class PushContainsDisplayName(PushCondition):
    kind = "contains_display_name"


    def triggered_by(self, event: TimelineEvent) -> bool:
        body = event.source.get("content", {}).get("body", "")
        name = event.room.client.profile.name

        if not body or not name:
            return False

        pattern = rf".*(^|\W){re.escape(name)}(\W|$).*"
        return bool(re.match(pattern, body, re.IGNORECASE))


@dataclass
class PushRoomMemberCount(PushCondition):
    class Operator(Enum):
        eq = "=="
        lt = "<"
        gt = ">"
        le = "<="
        ge = ">="

    kind = "room_member_count"

    count:    Runtime[int]
    operator: Runtime[Operator] = Operator.eq


    @classmethod
    def from_dict(cls, data: DictS, parent) -> "PushRoomMemberCount":
        regex             = r"(==|<|>|<=|>=)?([0-9.-]+)"
        op, data["count"] = re.findall(regex, data["is"])[0]
        data["operator"]  = op or cls.Operator.eq
        return super().from_dict(data, parent)


    @property
    def dict(self) -> DictS:
        return {**super().dict, "is": f"{self.operator.value}{self.count}"}


    def triggered_by(self, event: TimelineEvent) -> bool:
        members = event.room.state.total_members
        return getattr(operator, self.operator.name)(members, self.count)


@dataclass
class PushSenderNotificationPermission(PushCondition):
    kind = "sender_notification_permission"

    key: str


    def triggered_by(self, event: TimelineEvent) -> bool:
        user = event.room.state.users.get(event.sender)
        return bool(user and user.can_trigger_notification(self.key))


@dataclass
class PushRule(JSON):
    class Kind(AutoStrEnum):
        override  = auto()
        content   = auto()
        room      = auto()
        sender    = auto()
        underride = auto()

    aliases = {"id": "rule_id", "server_made": "default"}

    id:          str
    kind:        Kind = Kind.override  # Will be set in parent ruleset init
    enabled:     bool = True
    server_made: bool = False

    pattern:    str                 = ""
    conditions: List[PushCondition] = field(default_factory=list)

    notify:        Runtime[bool]                    = False
    highlight:     Runtime[bool]                    = False
    sound:         Runtime[Optional[str]]           = None
    bubble:        Runtime[bool]                    = False
    urgency_hint:  Runtime[bool]                    = False
    other_actions: Runtime[List[Union[str, DictS]]] = field(
        default_factory=list,
    )


    @classmethod
    def from_dict(cls, data: DictS, parent) -> "PushRule":
        obj                   = super().from_dict(data, parent)
        explicit_bubble_tweak = False
        explicit_hint_tweak   = False

        for action in data.get("actions", []):
            # `tweak` will be False if the action isn't a tweak dict
            tweak = isinstance(action, dict) and action.get("set_tweak")
            value = isinstance(action, dict) and action.get("value")

            if action in ("notify", "coalesce"):
                obj.notify = True
                continue

            if tweak is False:
                if action not in ("dont_notify", "coalesce"):
                    obj.other_actions.append(action)
                continue

            if tweak == "bubble":
                explicit_bubble_tweak = True
            elif tweak == "urgency_hint":
                explicit_hint_tweak = True
            elif tweak not in ("highlight", "sound"):
                obj.other_actions.append(action)
                continue

            if tweak == "highlight" and value is not False:
                obj.highlight = True
            elif tweak == "sound" and value and isinstance(value, str):
                obj.sound = value
            elif tweak == "sound" and (value or value is None):  # like js-sdk
                obj.sound = "default"
            elif tweak == "bubble" and value is not False:
                obj.bubble = True
            elif tweak == "urgency_hint" and value is not False:
                obj.urgency_hint = True

        if not explicit_bubble_tweak:
            obj.bubble = obj.notify

        if not explicit_hint_tweak:
            obj.urgency_hint = obj.sound is not None

        return obj


    @property
    def dict(self) -> DictS:
        data:    DictS                   = super().dict
        actions: List[Union[str, DictS]] = []

        if self.notify:
            actions.append("notify")

        if self.highlight:
            actions.append({"set_tweak": "highlight", "value": True})

        if self.sound:
            actions.append({"set_tweak": "sound", "value": self.sound})

        if self.bubble:
            actions.append({"set_tweak": "bubble", "value": self.bubble})

        if self.urgency_hint:
            value = self.urgency_hint
            actions.append({"set_tweak": "urgency_hint", "value": value})

        data["actions"] = actions + list(self.other_actions)
        return data


    def triggered_by(self, event: TimelineEvent) -> bool:
        if not self.enabled:
            return False

        if self.kind == self.Kind.content:
            matcher = PushEventMatch({}, "content.body", self.pattern)
            return matcher.triggered_by(event)

        if self.kind == self.Kind.room:
            return event.room.id == self.id

        if self.kind == self.Kind.sender:
            return event.sender == self.id

        return all(c.triggered_by(event) for c in self.conditions)


@dataclass
class PushRuleset(JSON, IndexableMap[Tuple[PushRule.Kind, str], PushRule]):
    override:  List[PushRule] = field(default_factory=list)
    content:   List[PushRule] = field(default_factory=list)
    room:      List[PushRule] = field(default_factory=list)
    sender:    List[PushRule] = field(default_factory=list)
    underride: List[PushRule] = field(default_factory=list)


    def __post_init__(self) -> None:
        for attr in ("override", "content", "room", "sender", "underride"):
            for rule in getattr(self, attr):
                rule.kind = PushRule.Kind[attr]


    def triggered(self, event: TimelineEvent) -> Optional[PushRule]:
        return next((r for r in self.values() if r.triggered_by(event)), None)


    @property
    def _data(self) -> Dict[Tuple[PushRule.Kind, str], PushRule]:
        attrs = (
            self.override, self.content, self.room, self.sender,
            self.underride,
        )

        return {(r.kind, r.id): r for rules in attrs for r in rules}


@dataclass
class PushRules(EventContent):
    type     = "m.push_rules"
    aliases  = {"main": "global"}  # global is a reserved python keyword
    rich_fix = False

    main: PushRuleset = field(default_factory=PushRuleset)


@dataclass
class IgnoredUsers(EventContent):
    type    = "m.ignored_user_list"
    aliases = {"users": "ignored_users"}

    users: Dict[UserId, dict]
