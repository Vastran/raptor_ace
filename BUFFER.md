# Buffer

The ACE buffer is a spring loop inside the unit. Hall sensors tell the firmware when it is open or shut. Klipper cannot move that loop: there is no buffer stepper on the host. The only actuator the host can command is the slot feed gear.

Feed assist (ACE2 `FEED_OR_ROLLBACK` mode 2) fills the buffer and then holds the filament. It does not run the gears backward when the extruder retracts, so each retract shoves filament into a buffer that is already shut and nozzle pressure climbs. Pressure-advance moves are too small to treat as retractions.

`buffer_release` (on by default) watches extruder moves. A retract of at least `buffer_release_min_mm` (default 0.4), capped at `buffer_release_max_mm` (default 2), opens the buffer and then returns to feed assist. The commands are queued to the move's print time and do not wait on the ACE. Pressure-advance moves are ignored.

ACE2 switches the active slot to rollback assist (`FEED_OR_ROLLBACK` mode 3) for that distance, then back to feed assist.

ACE1 has no rollback-assist mode, and an unwind sent while feed assist is still running does not open the buffer: assist owns the gears and either ignores the unwind or pushes the loop shut again. On a retract the host stops feed assist without forgetting the slot, waits `buffer_release_restart_s` (default 0.25s), unwinds that retract length, waits the unwind time plus the same gap, then starts feed assist again. A forward move inside that window does not restart assist early. If `klippy.log` reports `buffer unwind rejected`, raise `buffer_release_restart_s`. The driver's 1s assist-stop wait is for toolchanges; using it on every retract would leave the extruder pulling against a stopped buffer.

Set `buffer_release: False` under `[ace]` to turn this off.

## Unload

The same limit shows up at the end of a toolchange unload.

Two cases are fixed here.

The RDM overshoot used to `reactor.pause` after the sensor went clear. That only extends an unwind that is still running. On a long bowden the commanded retract has often already ended by the time the sensor opens, so the pause added no motion and the tip stayed at the RDM. If the command cannot cover `rdm_overshoot_length`, the host now sends a real follow-up retract of the missing distance.

The coordinated unload also fired one extruder retract and then required both sensors to be clear. That retract mostly takes up slack above the gears, so the toolhead sensor can stay covered after the bowden path is already clear. When the nozzle is hot enough to extrude and the RDM is clear, the host now retracts the extruder in short steps, up to one more `toolhead_retraction_length`, until the toolhead sensor opens.

Install by copying `extras/ace/` over `klipper/klippy/extras/ace/` and restarting Klipper. This repository is the ACE host library only.
