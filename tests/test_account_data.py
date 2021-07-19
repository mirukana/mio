# Copyright mio authors & contributors <https://github.com/mirukana/mio>
# SPDX-License-Identifier: LGPL-3.0-or-later

from dataclasses import dataclass

from pytest import mark

from mio.account_data.contents import (
    PushCondition, PushContainsDisplayName, PushEventMatch,
    PushRoomMemberCount, PushRule, PushSenderNotificationPermission,
)
from mio.account_data.events import AccountDataEvent
from mio.client import Client
from mio.core.callbacks import CallbackGroup
from mio.core.contents import EventContent
from mio.rooms.contents.messages import Text
from mio.rooms.contents.settings import Creation
from mio.rooms.room import Room

from .conftest import read_json

pytestmark = mark.asyncio


async def test_sending_receiving(alice: Client):
    @dataclass
    class Test(EventContent):
        type = "mio.test"
        foo: int

    got       = []
    group_got = []

    class TestCbGroup(CallbackGroup):
        def on_test(self, _, event: AccountDataEvent[Test]) -> None:
            group_got.append(event)

    alice.account_data.callbacks[Test].append(lambda self, ev: got.append(ev))
    alice.account_data.callback_groups.append(TestCbGroup())

    assert Test not in alice.account_data
    assert "mio.test" not in alice.account_data

    await alice.account_data.send(Test(1))
    await alice.sync.once()

    assert len(got) == len(group_got) == 1
    assert got[0].content == group_got[0].content == Test(1)
    assert alice.account_data[Test].content == Test(1)
    assert alice.account_data["mio.test"].content == Test(1)


async def test_parsing_saving(alice: Client):
    sync = await alice.sync.once()
    saved = read_json(alice.account_data.path)["_data"]
    assert sync and list(saved.values()) == sync["account_data"]["events"]


async def test_push_rules_actions_parsing():
    rule = PushRule.from_dict({
        "rule_id": "test",
        "actions": ["custom_str", "dont_notify", "coalesce", "notify"],
    }, parent=None)
    assert rule.notify
    assert not rule.highlight
    assert rule.sound is None
    assert rule.bubble
    assert not rule.urgency_hint
    assert rule.other_actions == ["custom_str"]

    rule = PushRule.from_dict({
        "rule_id": "test2",
        "actions": [
            {"set_tweak": "highlight", "value": None},
            {"set_tweak": "sound", "value": "xyz"},
            {"abc": 123},
        ],
    }, parent=None)
    assert not rule.notify
    assert rule.highlight
    assert rule.sound == "xyz"
    assert not rule.bubble
    assert rule.urgency_hint
    assert rule.other_actions == [{"abc": 123}]

    rule = PushRule.from_dict({
        "rule_id": "test3",
        "actions": [
            {"set_tweak": "sound", "value": None},
            {"set_tweak": "bubble", "value": None},
            {"set_tweak": "urgency_hint", "value": False},
        ],
    }, parent=None)
    assert not rule.notify
    assert not rule.highlight
    assert rule.sound == "default"
    assert rule.bubble
    assert not rule.urgency_hint
    assert not rule.other_actions


async def test_push_rules_unknown_condition():
    rule = PushCondition.from_dict({"abc": "123"}, parent=None)
    assert type(rule) is PushCondition
    assert rule.source["abc"] == "123"
    assert not rule.triggered_by(None)


async def test_push_rules_triggering(alice: Client, bob: Client, room: Room):
    await room.timeline.send(Text.from_html("<b>abc</b>, def"))
    await room.timeline.send(Text(f"...{alice.profile.name}..."))
    await alice.sync.once()

    assert isinstance(room.timeline[0].content, Creation)
    creation = room.timeline[0]
    abc      = room.timeline[-2]
    mention  = room.timeline[-1]

    # Individual conditions

    assert PushEventMatch({}, "content.format", "org.*.hTmL").triggered_by(abc)
    assert not PushEventMatch({}, "content.format", "html").triggered_by(abc)
    assert not PushEventMatch({}, "bad field", "blah").triggered_by(abc)

    assert PushEventMatch({}, "content.body", "abc").triggered_by(abc)
    assert PushEventMatch({}, "content.body", "Ab[cd]").triggered_by(abc)
    assert not PushEventMatch({}, "content.body", "ab").triggered_by(abc)

    assert PushContainsDisplayName({}).triggered_by(mention)
    assert not PushContainsDisplayName({}).triggered_by(abc)
    assert not PushContainsDisplayName({}).triggered_by(creation)

    ops = PushRoomMemberCount.Operator
    assert PushRoomMemberCount({}, 1).triggered_by(creation)
    assert PushRoomMemberCount({}, 2, ops.lt).triggered_by(abc)
    assert PushRoomMemberCount({}, 0, ops.gt).triggered_by(abc)
    assert PushRoomMemberCount({}, 1, ops.le).triggered_by(abc)
    assert PushRoomMemberCount({}, 1, ops.ge).triggered_by(abc)
    assert not PushRoomMemberCount({}, 1, ops.gt).triggered_by(abc)
    assert not PushRoomMemberCount({}, 1, ops.lt).triggered_by(abc)
    assert not PushRoomMemberCount({}, 2, ops.eq).triggered_by(abc)

    assert PushSenderNotificationPermission({}, "room").triggered_by(abc)
    assert PushSenderNotificationPermission({}, "unknown").triggered_by(abc)
    users = {alice.user_id: 49}
    await room.state.send(room.state.power_levels.but(users=users))
    await alice.sync.once()
    assert not PushSenderNotificationPermission({}, "room").triggered_by(abc)
    assert not PushSenderNotificationPermission({}, "xyz").triggered_by(abc)

    # PushRule

    kinds = PushRule.Kind
    assert PushRule("test").triggered_by(abc)
    assert not PushRule("test", enabled=False).triggered_by(abc)
    mention_1 = PushRule("test", conditions=[
        PushContainsDisplayName({}), PushRoomMemberCount({}, 1),
    ])
    assert mention_1.triggered_by(mention)
    assert not mention_1.triggered_by(abc)

    assert PushRule("c", kind=kinds.content, pattern="abc").triggered_by(abc)
    assert not PushRule("c", kind=kinds.content, pattern="a").triggered_by(abc)

    assert PushRule(room.id, kind=kinds.room).triggered_by(abc)
    assert not PushRule(room.id + "a", kind=kinds.room).triggered_by(abc)

    assert PushRule(alice.user_id, kind=kinds.sender).triggered_by(abc)
    assert not PushRule(bob.user_id, kind=kinds.sender).triggered_by(abc)

    # PushRuleset

    rule = alice.account_data.push_rules.main.triggered(abc)
    assert rule and rule.id == ".m.rule.message"
