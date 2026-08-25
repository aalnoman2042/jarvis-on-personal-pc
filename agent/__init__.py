"""The PC agent — the only VONDO process on Rohan's machine.

Deliberately small: a websocket, an allow-list, and psutil. No AI, no models,
no speech, no window. If something here starts needing a heavyweight dependency,
that is a sign the work belongs in the cloud instead.
"""
