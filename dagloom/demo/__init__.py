"""Dagloom demo module.

Provides a self-contained demo pipeline that exercises key features:
``@node``, ``>>``, ``|`` (branching), caching, scheduling, and
notification configuration.

Usage::

    dagloom demo          # Start server with demo pipeline
    dagloom demo --run    # Run demo pipeline directly (no server)
"""

from dagloom.demo.etl_pipeline import create_demo_pipeline

__all__ = ["create_demo_pipeline"]
