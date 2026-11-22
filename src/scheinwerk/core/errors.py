"""Errors raised by the core. Messages are meant to be shown to the user as-is."""

from __future__ import annotations


class ScheinwerkError(Exception):
    """Base class for every error the core raises on purpose."""


class NotInProject(ScheinwerkError):
    """A path is not inside a Scheinwerk project."""


class InvalidName(ScheinwerkError):
    """A name breaks the naming rules (spec §5)."""


class ParseError(ScheinwerkError):
    """A path inside a project can't be read as a context (spec §6)."""
