##### BASE IMAGE #####
FROM elixircloud/foca:v0.7.0-py3.9


##### METADATA ##### 

LABEL software="Pubgrade"
LABEL software.description="Pubgrade is a decoupled, publish-subscribe-based continuous integration (CI) and continuous delivery (CD) microservice that allows developers to notify deploments of available updates."
LABEL software.website="https://github.com/elixir-cloud-aai/Pubgrade"
LABEL software.license="https://spdx.org/licenses/Apache-2.0"
LABEL maintainer="akash2237778@gmail.com"
LABEL maintainer.organisation="ELIXIR Cloud & AAI"

RUN groupadd -r pubgrade --gid 1000 && useradd -d /home/pubgrade -ms /bin/bash -r -g pubgrade pubgrade --uid 1000

## Copy remaining app files
COPY --chown=1000:1000 ./ /app

## Install app
## FOCA 0.7 pins pymongo 3.10, which fails at startup on current MongoDB versions
## (dropping the indexes of a collection that doesn't exist yet): 3.13 fixes that.
## Remove this with the move to a newer FOCA
RUN cd /app \
  && python setup.py develop \
  && chmod g+w /app/pubgrade/api/ \
  && pip install -r requirements.txt \
  && pip install --no-deps pymongo==3.13.0


RUN mkdir /pubgrade_temp_files && chown 1000 /pubgrade_temp_files

USER 1000

CMD ["bash", "-c", "cd /app/pubgrade; python app.py"]
