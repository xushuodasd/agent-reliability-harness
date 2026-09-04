"""Source-tree bootstrap package for running without installation."""

from pathlib import Path

_source_package = Path(__file__).resolve().parent.parent / "src" / "pilot_harness"
__path__.append(str(_source_package))

__all__ = ["ExperimentRunner", "EpisodeResult"]


def __getattr__(name):
    if name in __all__:
        from .runner import EpisodeResult, ExperimentRunner

        return {"ExperimentRunner": ExperimentRunner, "EpisodeResult": EpisodeResult}[name]
    raise AttributeError(name)
