"""Offline reliability experiment harness for tool-using agents."""

__all__ = ["ExperimentRunner", "EpisodeResult"]


def __getattr__(name):
    if name in __all__:
        from .runner import EpisodeResult, ExperimentRunner

        return {"ExperimentRunner": ExperimentRunner, "EpisodeResult": EpisodeResult}[name]
    raise AttributeError(name)
