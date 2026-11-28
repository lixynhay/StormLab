"""Hypothesis profiles: deterministic in CI, broad nightly.

Select with HYPOTHESIS_PROFILE=ci|nightly; default is ci.
"""

import os

from hypothesis import HealthCheck, settings

_PROFILE = os.getenv("HYPOTHESIS_PROFILE", "ci")

settings.register_profile(
    "ci",
    derandomize=True,
    max_examples=50,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.register_profile(
    "nightly",
    derandomize=False,
    max_examples=1000,
    suppress_health_check=[HealthCheck.too_slow],
)

settings.load_profile(_PROFILE)
