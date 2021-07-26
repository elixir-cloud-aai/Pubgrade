##### BASE IMAGE #####
FROM elixircloud/foca:latest


##### METADATA ##### 

LABEL software="Broker"
LABEL software.description="Broker is a decoupled, publish-subscribe-based continuous integration (CI) and continuous delivery (CD) microservice that allows developers to notify deploments of available updates."
LABEL software.website="https://github.com/elixir-cloud-aai/Broker"
LABEL software.license="https://spdx.org/licenses/Apache-2.0"
LABEL maintainer="akash2237778@gmail.com"
LABEL maintainer.organisation="ELIXIR Cloud & AAI"


## Copy remaining app files
COPY ./ /app

## Install app
RUN cd /app \
  && python setup.py develop \
  && cd / \
  && chmod g+w /app/broker/api/ \
  && pip install yq \
  && pip install kubernetes \
  && pip install gitpython

CMD ["bash", "-c", "cd /app/broker; python app.py"]
