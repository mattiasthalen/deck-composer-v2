"""Deterministic tools behind the deck composer skill.

One CLI, one subcommand per module, JSON output (ADR-0001). Modules own
knowledge exclusively: ``ingest`` the ManaBox export format, ``collection``
the collection file format (ADR-0002).
"""
