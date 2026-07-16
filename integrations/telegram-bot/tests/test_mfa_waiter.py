import asyncio

from bot.mfa_waiter import MfaResultWaiter


async def test_resolve_delivers_result_to_waiting_future() -> None:
    waiter = MfaResultWaiter()
    future = waiter.start()

    waiter.resolve(success=True, error=None, username="jdoe@icloud.com")

    result = await asyncio.wait_for(future, timeout=1.0)
    assert result == (True, None, "jdoe@icloud.com")


async def test_resolve_with_failure_delivers_error() -> None:
    waiter = MfaResultWaiter()
    future = waiter.start()

    waiter.resolve(success=False, error="bad code", username="jdoe@icloud.com")

    result = await asyncio.wait_for(future, timeout=1.0)
    assert result == (False, "bad code", "jdoe@icloud.com")


async def test_resolve_without_a_pending_waiter_is_a_no_op() -> None:
    waiter = MfaResultWaiter()

    waiter.resolve(success=True, error=None, username="jdoe@icloud.com")  # must not raise


async def test_second_start_replaces_the_pending_future() -> None:
    waiter = MfaResultWaiter()
    first_future = waiter.start()
    second_future = waiter.start()

    waiter.resolve(success=True, error=None, username="jdoe@icloud.com")

    assert not first_future.done()
    result = await asyncio.wait_for(second_future, timeout=1.0)
    assert result == (True, None, "jdoe@icloud.com")


async def test_resolve_after_future_already_done_does_not_raise() -> None:
    waiter = MfaResultWaiter()
    future = waiter.start()
    waiter.resolve(success=True, error=None, username="jdoe@icloud.com")
    await asyncio.wait_for(future, timeout=1.0)

    waiter.resolve(success=False, error="late", username="jdoe@icloud.com")  # must not raise
