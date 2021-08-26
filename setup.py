from setuptools import (setup, find_packages)

with open('README.md', 'r') as fh:
    long_description = fh.read()

setup(
    name='pubgrade',
    # version=__version__,
    author='ELIXIR Cloud & AAI',
    author_email='akash2237778@gmail.com',
    description='Pubgrade is a decoupled, publish-subscribe-based continuous '
                'integration (CI) and continuous delivery (CD) microservice '
                'that allows developers to notify deployments of available '
                'updates, which can then autonomously decide what to do with '
                'them. ',
    long_description=long_description,
    long_description_content_type="text/markdown",
    license='Apache License 2.0',
    url='https://github.com/elixir-cloud-aai/Pubgrade.git',
    packages=find_packages(),
    keywords=(
        'ga4gh pubgrade elixir DevOps CI-CD api app server openapi '
        'swagger mongodb python flask docker'
    ),
    classifiers=[
        'License :: OSI Approved :: Apache Software License',
        'Development Status :: 3 - Alpha',
        'Intended Audience :: Science/Research',
        'Topic :: Scientific/Engineering :: Bio-Informatics',
        'Natural Language :: English',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
    ],
    install_requires=[],
)
