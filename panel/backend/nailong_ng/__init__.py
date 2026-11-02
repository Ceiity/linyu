"""奶龙 Next Generation 2.0 backend modules.

The legacy panel lives in ``panel/backend/app.py``.  Everything that is new in
2.0 – the protocol adapter layer (NapCat / SnowLuma), protocol switching with
rollback, the unified login state machine, error-code normalisation,
diagnostics and SSH remote deployment – lives in this package so it can be
unit-tested without a Docker daemon.  ``app.py`` wires the real Docker / HTTP
helpers in through :class:`nailong_ng.host.Host`.
"""

NG_VERSION = "2.0.0"
