from io import BytesIO

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


async def test_retry_seekable(alice: Client, mock_responses):
    got  = b"nothing"
    data = BytesIO(b"abc")

    # Make sure the retry process will seek back to whatever the stream's
    # position initially was, and not just blindly seek to 0
    data.read(1)

    async def cb(url, **kwargs):
        nonlocal got
        got = b"".join([chunk async for chunk in kwargs["data"]])

    mock_responses.post(alice.net.api  / "test", status=429)
    mock_responses.post(alice.net.api  / "test", status=200, callback=cb)

    await alice.net.post(alice.net.api / "test", data)
    assert alice.net.last_replies[1].status == 429
    assert alice.net.last_replies[0].status == 200
    assert got == b"bc"


async def test_pings(alice: Client):
    await alice.auth.logout()
    assert 0 < alice.net.last_replies[0].ping.total_seconds() < 10
