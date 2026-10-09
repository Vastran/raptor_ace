# Buffer unload

ACE feed assist is bang-bang inside the unit. The host protocol can start or stop it, but it cannot set assist speed or read the buffer Hall position. The failures that look like a buffer problem during a toolchange are the host unload finishing in the wrong place.

Two cases are fixed here.

The RDM overshoot used to `reactor.pause` after the sensor went clear. That only extends an unwind that is still running. On a long bowden the commanded retract has often already ended by the time the sensor opens, so the pause added no motion and the tip stayed at the RDM. If the command cannot cover `rdm_overshoot_length`, the host now sends a real follow-up retract of the missing distance.

The coordinated unload also fired one extruder retract and then required both sensors to be clear. That retract mostly takes up slack above the gears, so the toolhead sensor can stay covered after the bowden path is already clear. When the nozzle is hot enough to extrude and the RDM is clear, the host now retracts the extruder in short steps, up to one more `toolhead_retraction_length`, until the toolhead sensor opens.

Install by copying `extras/ace/` over `klipper/klippy/extras/ace/` and restarting Klipper. This repository is the ACE host library only.
