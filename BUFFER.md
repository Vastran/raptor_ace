# Buffer

The ACE buffer is a spring loop inside the unit. Hall sensors tell the firmware when it is open or shut. Klipper cannot move that loop: there is no buffer stepper on the host. The only actuator the host can command is the slot feed gear.

Feed assist (ACE2 `FEED_OR_ROLLBACK` mode 2) fills the buffer and then holds the filament. It does not run the gears backward when the extruder retracts, so each retract shoves filament into a buffer that is already shut and nozzle pressure climbs. Pressure-advance moves are too small to treat as retractions.

`buffer_release` (on by default) watches extruder moves. A retract of at least `buffer_release_min_mm` (default 0.4) switches the active assist slot to rollback assist (ACE2 mode 3) for that distance, capped at `buffer_release_max_mm` (default 2). It then sends feed assist again so the buffer returns to its normal stop instead of staying open or ratcheting tighter. The commands are queued to the move's print time and do not wait on the ACE. ACE1 has no rollback-assist mode, so the same window sends a finite unwind of that length and then re-enables feed assist.

Set `buffer_release: False` under `[ace]` to turn this off.

## Unload

The same limit shows up at the end of a toolchange unload.

Two cases are fixed here.

The RDM overshoot used to `reactor.pause` after the sensor went clear. That only extends an unwind that is still running. On a long bowden the commanded retract has often already ended by the time the sensor opens, so the pause added no motion and the tip stayed at the RDM. If the command cannot cover `rdm_overshoot_length`, the host now sends a real follow-up retract of the missing distance.

The coordinated unload also fired one extruder retract and then required both sensors to be clear. That retract mostly takes up slack above the gears, so the toolhead sensor can stay covered after the bowden path is already clear. When the nozzle is hot enough to extrude and the RDM is clear, the host now retracts the extruder in short steps, up to one more `toolhead_retraction_length`, until the toolhead sensor opens.

Install by copying `extras/ace/` over `klipper/klippy/extras/ace/` and restarting Klipper. This repository is the ACE host library only.
