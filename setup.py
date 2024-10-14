"""Kept for partial compatibility with old pip versions."""

from setuptools import setup

setup(
    use_scm_version={"local_scheme": "no-local-version"},
    setup_requires=["setuptools_scm[toml]>=3.5.0"],
)
