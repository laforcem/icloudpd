from bot.state import ChatState


def test_not_awaiting_by_default() -> None:
    state = ChatState()
    assert state.is_awaiting_code(1) is False


def test_start_and_stop_awaiting() -> None:
    state = ChatState()
    state.start_awaiting_code(1)
    assert state.is_awaiting_code(1) is True

    state.stop_awaiting_code(1)
    assert state.is_awaiting_code(1) is False


def test_tracks_chats_independently() -> None:
    state = ChatState()
    state.start_awaiting_code(1)
    assert state.is_awaiting_code(2) is False
