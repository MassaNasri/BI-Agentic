from preprocessing_high.schemas import HighPreprocessConfig, PreprocessHighResult

__all__ = [
    "preprocess_high_task",
    "run_preprocess_high",
    "HighPreprocessConfig",
    "PreprocessHighResult",
]


def __getattr__(name: str):
    if name in {"preprocess_high_task", "run_preprocess_high"}:
        from preprocessing_high.preprocess_high_task import preprocess_high_task, run_preprocess_high

        return {
            "preprocess_high_task": preprocess_high_task,
            "run_preprocess_high": run_preprocess_high,
        }[name]
    raise AttributeError(name)
