"""Buffer release planning and the ACE2 rollback-assist command."""

from ace.buffer_release import plan_buffer_actions
from ace.protocol_ace2 import AceProtoProtocolAdapter, _pb_decode, _pb_first


def test_pressure_advance_jitter_is_ignored():
    assert plan_buffer_actions(0.15, 0.4, 2.0, 20.0) == []
    assert plan_buffer_actions(-0.2, 0.4, 2.0, 20.0) == []


def test_retract_opens_buffer_then_restores_feed():
    actions = plan_buffer_actions(-0.8, 0.4, 2.0, 20.0)
    assert actions[0] == ("rollback", 0.8, 0.0)
    assert actions[1][0] == "feed"
    assert actions[1][2] == 0.8 / 20.0


def test_large_retract_is_capped():
    actions = plan_buffer_actions(-40.0, 0.4, 2.0, 20.0)
    assert actions[0] == ("rollback", 2.0, 0.0)


def test_forward_move_only_restores_feed():
    assert plan_buffer_actions(0.8, 0.4, 2.0, 20.0) == [("feed", 0.0, 0.0)]


def test_ace2_rollback_assist_is_mode_3():
    adapter = AceProtoProtocolAdapter()
    request = adapter.build_rollback_assist_request(2, 20)
    assert request["params"]["mode"] == 3
    assert request["params"]["length"] == 0
    payload = adapter._encode_request_payload(
        request["command"], request["params"]
    )
    fields = _pb_decode(payload)
    assert _pb_first(fields, 1) == 2
    assert _pb_first(fields, 2) == 20
    assert _pb_first(fields, 4) == 3
