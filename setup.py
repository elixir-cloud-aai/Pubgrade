from setuptools import find_packages, setup

from pubgrade import __version__

setup(
    name="pubgrade",
    version=__version__,
    author="ELIXIR Cloud & AAI",
    author_email="akash2237778@gmail.com",
    description=(
        "Pubgrade is a decoupled, publish-subscribe-based continuous "
        "integration (CI) and continuous delivery (CD) microservice "
        "that allows developers to notify deployments of available "
        "updates, which can then autonomously decide what to do with "
        "them. "
    ),
    license="Apache License 2.0",
    url="https://github.com/elixir-cloud-aai/Pubgrade.git",
    packages=find_packages(),
    keywords=(
        "api app ci-cd devops docker elixir flask ga4gh mongodb openapi "
        "pubgrade pubsub python server subscription swagger upgrade "
    ),
    classifiers=[
        "License :: OSI Approved :: Apache Software License",
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Information Technology",
        "Topic :: Scientific/Engineering :: Bio-Informatics",
        "Natural Language :: English",
        "Programming Language :: Python :: 3.13",
    ],
    python_requires=">=3.13",
    install_requires=[],
    extras_require={
        "test": [
            "coverage==7.17.2",
            "mongomock==4.3.0",
            "pytest==9.2.0",
        ],
        # The documentation (`mkdocs.yml`), built with Python 3.13 on Read
        # the Docs (`.readthedocs.yaml`) and in CI
        "docs": [
            "griffelib>=2.4,<3",
            "mkdocs>=1.6.1,<2",
            "mkdocs-autorefs>=1.4.4,<2",
            "mkdocs-material>=9.7.7,<10",
            "mkdocstrings>=1.0.8,<2",
            "mkdocstrings-python>=2.0.10,<3",
            "pymdown-extensions>=12.3,<13",
        ],
    },
)
