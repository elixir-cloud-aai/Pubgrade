##### BASE IMAGE #####
## Pinned by digest, so that rebuilds use the same base image; the Python
## version of the app's image. Dependabot updates the tag and digest together
FROM python:3.15.0@sha256:4e324f579bdd7d0ce3cbae52e27bddeb316c9c23aa7563ac6a9811bbca55541b

##### METADATA #####
LABEL software="Pubgrade"
LABEL software.description="Pubgrade is a decoupled, publish-subscribe-based continuous integration (CI) and continuous delivery (CD) microservice that allows developers to notify deployments of available updates."
LABEL software.website="https://github.com/elixir-cloud-aai/Pubgrade"
LABEL software.license="https://spdx.org/licenses/Apache-2.0"
LABEL maintainer="akash2237778@gmail.com"
LABEL maintainer.organisation="ELIXIR Cloud & AAI"

##### SYSTEM USER #####
RUN groupadd -r pubgrade --gid 1000 && useradd -d /home/pubgrade -ms /bin/bash -r -g pubgrade pubgrade --uid 1000

##### WORKING DIRECTORY #####
WORKDIR /app

##### COPY SOURCE CODE #####
COPY --chown=1000:1000 ./ /app

##### INSTALL DEPENDENCIES #####
RUN pip install --upgrade pip \
  && pip install -r /app/build-complete-updater/requirements.txt

##### SWITCH TO NON-ROOT USER #####
USER 1000

##### ENTRYPOINT #####
CMD [ "python", "/app/build-complete-updater/updater.py" ]
