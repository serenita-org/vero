# TODO fix
### Known blockers

- PEP-649 incompatibilities - deferred evaluation of annotations
  - msgspec
    - https://github.com/jcrist/msgspec/issues/651
    - https://github.com/jcrist/msgspec/pull/852
    - => workaround deployed: from __future__ import annotations
  - remerkleable
    - accesses __annotations__ of classes internally
    - works as is, as long as we don't change the annotations (move them under TYPE_CHECKING)
    - => exception added to ruff

- Free-threading
  - aiohttp > 3.13.0 ✅
  - msgspec
    - not supported yet, someone ( kumaraditya303 ) is working on it
      - see https://github.com/kumaraditya303/msgspec/tree/thread-safe
    - https://github.com/jcrist/msgspec/issues/744
  - tip: when checking if no-GIL works, remove the uv .venv, then change the Python version to 3.14t
    in .python-version and then run uv sync. That currently fails to build msgspec.
  - TODO ensure we're using the free-threading build of Python everywhere (!) (e.g. Dockerfile but also in tests, CI workflows, hooks, ...)
