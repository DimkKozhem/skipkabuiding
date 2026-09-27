"""Сравнение VLM через OpenRouter и локальный OpenAI-совместимый сервер.

Модуль не пишет наблюдения, WorkFact, сигналы и решения инспектора.
"""

from sitewatch.experiments.vlm_compare.runner import execute_run, plan_experiment

__all__ = ["execute_run", "plan_experiment"]
