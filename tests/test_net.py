from mio.client import Client
from mio.net.errors import (
    RETRIABLE_STATUS, NonStandardRetriableStatus, ServerError,
)
from pytest import mark, raises

pytestmark = mark.asyncio


async def test_retry_errors(alice: Client, mock_responses):
    assert 429 in RETRIABLE_STATUS
    mock_responses.post(alice.net.api / "logout", status=429)

    assert 520 in RETRIABLE_STATUS and 520 in set(NonStandardRetriableStatus)
    mock_responses.post(alice.net.api / "logout", status=520)

    assert 403 not in RETRIABLE_STATUS
    mock_responses.post(alice.net.api / "logout", status=403)

    replies = alice.net.last_replies
    replies.clear()

    with raises(ServerError):
        await alice.auth.logout()

    assert len(replies) == 3
    assert replies[2].error and replies[2].status == 429
    assert replies[1].error and replies[1].status == 520
    assert replies[0].error and replies[0].status == 403


async def test_pings(alice: Client):
    await alice.auth.logout()
    assert 0 < alice.net.last_replies[0].ping.total_seconds() < 10
