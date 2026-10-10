"""Buffer release planning and the ACE2 rollback-assist command."""

from ace.buffer_release import BufferRelease, plan_buffer_actions
from ace.protocol import create_protocol_adapter
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


def test_ace1_waits_for_assist_to_stop_before_restoring():
    actions = plan_buffer_actions(-0.8, 0.4, 2.0, 20.0, restart_s=0.25)
    assert actions[0] == ("rollback", 0.8, 0.0)
    assert actions[1][2] == (0.8 / 20.0) + 0.25


def test_ace1_has_no_rollback_assist_mode():
    ace1 = create_protocol_adapter("ace1_json")
    assert ace1.supports_rollback_assist() is False
    assert ace1.build_stop_feed_assist_request(1)["method"] == "stop_feed_assist"
    unwind = ace1.build_unwind_filament_request(1, 0.8, 20)
    assert unwind["method"] == "unwind_filament"
    assert unwind["params"]["length"] == 0.8


def test_ace1_retract_stops_assist_then_unwinds_after_the_gap():
    class Protocol:
        def supports_rollback_assist(self):
            return False

    class Instance:
        def __init__(self):
            self.protocol = Protocol()
            self._feed_assist_index = 1
            self.sent = []

        def queue_buffer_assist_stop(self):
            self.sent.append("stop")
            return True

        def queue_buffer_unwind(self, length, speed):
            self.sent.append(("unwind", length, speed))
            return True

        def queue_buffer_feed(self):
            self.sent.append("feed")
            return True

        def queue_buffer_rollback(self, length, speed):
            self.sent.append(("rollback", length))
            return True

    class Reactor:
        NEVER = object()

        def __init__(self):
            self.now = 10.0
            self.timers = []

        def monotonic(self):
            return self.now

        def register_timer(self, callback, when):
            self.timers.append((when, callback))

    class Printer:
        def __init__(self, reactor):
            self._reactor = reactor

        def get_reactor(self):
            return self._reactor

    class Manager:
        def __init__(self, reactor):
            self.ace_config = {}
            self.toolchange_in_progress = False
            self.printer = Printer(reactor)
            self.instances = []

    reactor = Reactor()
    manager = Manager(reactor)
    inst = Instance()
    manager.instances = [inst]
    release = BufferRelease(manager)

    assert release._restart_delay() == 0.5
    release._apply("rollback", 0.8)
    assert inst.sent == ["stop"]
    assert inst._feed_assist_index == 1
    assert len(reactor.timers) == 1
    when, callback = reactor.timers[0]
    assert when == 10.25

    # An unretract before the window ends must not restart assist.
    release._apply("feed", 0.0)
    assert inst.sent == ["stop"]

    callback(when)
    assert inst.sent[-1] == ("unwind", 0.8, 20.0)

    reactor.now = 10.0 + 0.5 + (0.8 / 20.0)
    release._apply("feed", 0.0)
    assert inst.sent[-1] == "feed"


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
