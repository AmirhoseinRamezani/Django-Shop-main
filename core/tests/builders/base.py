from __future__ import annotations

from typing import Any


class BaseBuilder:
    """
    Base Builder.
    Every Builder in tests inherits from this class.

    Features
    --------
    • fluent API
    • immutable style
    • default values
    • override values
    • reset()
    • build()

    """

    factory = None

    def __init__(self, **defaults):

        self._attrs = {}

        self._attrs.update(defaults)

    # ---------------------------------------------------------
    # generic attribute setter
    # ---------------------------------------------------------

    def with_attrs(self, **kwargs):

        self._attrs.update(kwargs)

        return self

    # ---------------------------------------------------------

    def reset(self):

        self._attrs.clear()

        return self

    # ---------------------------------------------------------

    def clone(self):

        builder = self.__class__()

        builder._attrs = self._attrs.copy()

        return builder

    # ---------------------------------------------------------

    def build(self, **override):

        if self.factory is None:
            raise RuntimeError(
                f"{self.__class__.__name__} has no factory"
            )

        attrs = self._attrs.copy()

        attrs.update(override)

        return self.factory(**attrs)

    # ---------------------------------------------------------

    def create(self, **override):
        """
        alias
        """

        return self.build(**override)

    # ---------------------------------------------------------

    def __call__(self, **override):

        return self.build(**override)