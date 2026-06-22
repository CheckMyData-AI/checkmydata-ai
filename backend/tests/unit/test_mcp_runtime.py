from app.mcp_server import runtime


def test_current_principal_defaults_none():
    assert runtime.current_principal.get() is None


def test_principal_set_and_reset():
    token = runtime.current_principal.set({"user_id": "u1", "email": "a@b.c"})
    try:
        assert runtime.current_principal.get()["user_id"] == "u1"
    finally:
        runtime.current_principal.reset(token)
    assert runtime.current_principal.get() is None


def test_trace_service_holder():
    assert runtime.get_trace_service() is None
    sentinel = object()
    runtime.set_trace_service(sentinel)
    try:
        assert runtime.get_trace_service() is sentinel
    finally:
        runtime.set_trace_service(None)
