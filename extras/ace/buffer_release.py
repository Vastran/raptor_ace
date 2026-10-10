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


def plan_buffer_actions(de, min_mm, max_mm, speed):
    """Return the gear commands for one extruder delta.

    Each action is (name, length_mm, delay_s). ``delay_s`` is how long
    after the move's print_time to send it. A retract schedules a
    rollback at the move, then feed assist once that length has run.
    A forward move only restores feed assist.
    """
    if speed <= 0:
        speed = 20.0
    if de <= -min_mm:
        length = min(abs(de), max_mm)
        if length <= 0:
            return []
        return [
            ("rollback", length, 0.0),
            ("feed", 0.0, length / speed),
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
        self._installed = False
        self._gear = "feed"

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
                de, self.min_mm, self.max_mm, self.speed
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
            if inst.queue_buffer_rollback(length, self.speed):
                self._gear = "rollback"
            return
        if self._gear == "feed":
            return
        if inst.queue_buffer_feed():
            self._gear = "feed"
