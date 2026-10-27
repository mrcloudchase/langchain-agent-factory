"""Registered tool implementations.

These are deliberately small and deterministic so the factory is testable end to end.
Each one is shaped like the real integration it stands in for (helpdesk, search, repo),
and the registry entry, not the code, decides who may use it and whether it needs approval.
"""
