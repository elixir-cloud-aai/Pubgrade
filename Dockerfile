##### BASE IMAGE #####
FROM elixircloud/foca:v0.7.0-py3.9


##### METADATA ##### 

LABEL software="Pubgrade"
LABEL software.description="Pubgrade is a decoupled, publish-subscribe-based continuous integration (CI) and continuous delivery (CD) microservice that allows developers to notify deploments of available updates."
LABEL software.website="https://github.com/elixir-cloud-aai/Pubgrade"
LABEL software.license="https://spdx.org/licenses/Apache-2.0"
LABEL maintainer="akash2237778@gmail.com"
LABEL maintainer.organisation="ELIXIR Cloud & AAI"


## Copy remaining app files
COPY ./ /app

## Install app
RUN cd /app \
  && python setup.py develop \
  && chmod g+w /app/pubgrade/api/ \
  && pip install -r requirements.txt

CMD ["bash", "-c", "cd /app/pubgrade; python app.py"]
