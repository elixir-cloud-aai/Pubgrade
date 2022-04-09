##### BASE IMAGE #####
FROM python:3

##### METADATA ##### 

LABEL software="Pubgrade"
LABEL software.description="Pubgrade is a decoupled, publish-subscribe-based continuous integration (CI) and continuous delivery (CD) microservice that allows developers to notify deploments of available updates."
LABEL software.website="https://github.com/elixir-cloud-aai/Pubgrade"
LABEL software.license="https://spdx.org/licenses/Apache-2.0"
LABEL maintainer="akash2237778@gmail.com"
LABEL maintainer.organisation="ELIXIR Cloud & AAI"


RUN groupadd -r pubgrade --gid 1000 && useradd -d /home/pubgrade -ms /bin/bash -r -g pubgrade pubgrade --uid 1000

COPY --chown=1000:1000 ./ /app

RUN cd /app \
  && pip install -r requirements.txt


USER 1000

CMD [ "python", "/app/updater.py" ]