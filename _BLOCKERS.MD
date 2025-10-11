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
