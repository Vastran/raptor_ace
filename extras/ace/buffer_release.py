"""Open the ACE buffer on extruder retractions.

The buffer is a spring loop inside the ACE, closed by Hall sensors. Klipper
does not drive that loop. The only actuator is the slot feed gear, and
during a print that gear sits in feed assist: it tops the buffer up and
then holds the filament. An extruder retract therefore has nowhere to put
the filament, and nozzle pressure climbs on every retract.

This watches extruder moves. A retract larger than pressure-advance jitter
switches the active slot to rollback assist for just that distance, then
returns to feed assist so the buffer refills to its normal stop instead of
ratcheting tighter. Moves are timed to the toolhead print clock. Nothing
here waits on the ACE.
"""

import logging


def plan_buffer_actions(de, min_mm, max_mm, speed, restart_s=0.0):
    """Return the gear commands for one extruder delta.

    Each action is (name, length_mm, delay_s). ``delay_s`` is how long
    after the move's print_time to send it. A retract schedules a
    rollback at the move, then feed assist once that length has run.
    ``restart_s`` is extra wait before feed assist returns, used on ACE1
    so the stop-assist command is finished before the unwind, and the
    unwind is finished before assist starts pushing again.
    A forward move only restores feed assist.
    """
    if speed <= 0:
        speed = 20.0
    if restart_s < 0:
        restart_s = 0.0
    if de <= -min_mm:
        length = min(abs(de), max_mm)
        if length <= 0:
            return []
        return [
            ("rollback", length, 0.0),
            ("feed", 0.0, (length / speed) + restart_s),
        ]
    if de >= min_mm:
        return [("feed", 0.0, 0.0)]
    return []


class BufferRelease:
    def __init__(self, manager):
        self.manager = manager
        cfg = manager.ace_config
        self.enabled = bool(cfg.get("buffer_release", True))
        self.min_mm = float(cfg.get("buffer_release_min_mm", 0.4))
        self.max_mm = float(cfg.get("buffer_release_max_mm", 2.0))
        self.speed = float(cfg.get("buffer_release_speed", 20.0))
        # ACE1 will not unwind while feed assist still owns the gears.
        # This is how long to leave assist stopped before the unwind, and
        # it is also added before assist is started again.
        self.restart_s = float(cfg.get("buffer_release_restart_s", 0.25))
        self._installed = False
        self._gear = "feed"
        self._hold_feed_until = 0.0

    def install(self):
        """Wrap toolhead.move once Klipper is ready. Safe to call again."""
        if not self.enabled or self._installed:
            return
        toolhead = self.manager.printer.lookup_object("toolhead", None)
        if toolhead is None or not hasattr(toolhead, "move"):
            return
        orig_move = toolhead.move

        def move(newpos, speed):
            de = 0.0
            try:
                de = newpos[3] - toolhead.get_position()[3]
            except Exception:
                de = 0.0
            orig_move(newpos, speed)
            actions = plan_buffer_actions(
                de, self.min_mm, self.max_mm, self.speed,
                self._restart_delay(),
            )
            if not actions:
                return
            for name, length, delay in actions:
                toolhead.register_lookahead_callback(
                    lambda print_time, name=name, length=length, delay=delay:
                        self._schedule(print_time + delay, name, length)
                )

        toolhead.move = move
        self._installed = True
        self.manager.gcode.respond_info(
            "ACE: Buffer release on retractions of %.2fmm or more "
            "(max %.2fmm at %.0fmm/s)"
            % (self.min_mm, self.max_mm, self.speed)
        )

    def _schedule(self, print_time, name, length):
        printer = self.manager.printer
        reactor = printer.get_reactor()
        now = reactor.monotonic()
        delay = 0.0
        mcu = printer.lookup_object("mcu", None)
        if mcu is not None:
            try:
                delay = print_time - mcu.estimated_print_time(now)
            except Exception:
                delay = 0.0
        if delay < 0.0 or delay > 30.0:
            delay = 0.0
        reactor.register_timer(
            lambda eventtime, name=name, length=length: self._fire(name, length),
            now + delay,
        )

    def _fire(self, name, length):
        reactor = self.manager.printer.get_reactor()
        try:
            self._apply(name, length)
        except Exception:
            logging.exception("ACE buffer release failed")
        return reactor.NEVER

    def _restart_delay(self):
        """Extra time before feed assist is allowed back on.

        ACE2 mode 3 needs none. ACE1 needs a gap after stop-assist before
        the unwind is accepted, and the same gap after the unwind before
        assist starts pushing again. The unwind itself is scheduled at
        the first gap.
        """
        inst = self._active_instance()
        if inst is None:
            return 0.0
        if inst.protocol.supports_rollback_assist():
            return 0.0
        return self.restart_s * 2.0

    def _schedule_from_now(self, delay_s, name, length):
        reactor = self.manager.printer.get_reactor()
        now = reactor.monotonic()
        reactor.register_timer(
            lambda eventtime, name=name, length=length: self._fire(name, length),
            now + max(0.0, delay_s),
        )

    def _active_instance(self):
        if getattr(self.manager, "toolchange_in_progress", False) is True:
            return None
        for inst in self.manager.instances:
            if inst._feed_assist_index >= 0:
                return inst
        self._gear = "feed"
        return None

    def _apply(self, name, length):
        inst = self._active_instance()
        if inst is None:
            return
        if name == "rollback":
            if inst.protocol.supports_rollback_assist():
                ok = inst.queue_buffer_rollback(length, self.speed)
                window = length / self.speed if self.speed > 0 else 0.0
            else:
                # Stop assist first. The unwind is delayed so ACE1 can
                # drop the gears before the retract command arrives.
                ok = inst.queue_buffer_assist_stop()
                if ok:
                    self._schedule_from_now(self.restart_s, "unwind", length)
                window = self.restart_s + (
                    length / self.speed if self.speed > 0 else 0.0
                )
            if ok:
                self._gear = "rollback"
                now = self.manager.printer.get_reactor().monotonic()
                self._hold_feed_until = now + max(0.0, window - 0.02)
            return
        if name == "unwind":
            inst.queue_buffer_unwind(length, self.speed)
            return
        now = self.manager.printer.get_reactor().monotonic()
        if now < self._hold_feed_until:
            return
        if self._gear == "feed":
            return
        if inst.queue_buffer_feed():
            self._gear = "feed"
