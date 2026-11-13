#!/usr/bin/env bash
# Starts an image of Pubgrade with MongoDB in Docker, under an arbitrary user
# ID as on OpenShift, on port 8080 of the host, and waits until it responds;
# for CI's smoke test and the test of the notify action. The container's name
# `mongodb` is the host in `pubgrade/config.yaml`.
# Usage: tests/start.sh <image>

set -euo pipefail

image="$1"

docker network create pubgrade
docker run --detach --name mongodb --network pubgrade mongo:7.0
for _ in $(seq 1 30); do
  if docker exec mongodb mongosh --quiet --eval 'db.adminCommand({ping: 1}).ok' > /dev/null 2>&1; then
    break
  fi
  sleep 2
done
docker run --detach --name pubgrade --network pubgrade \
  --user 12345:0 --publish 8080:8080 "${image}"
for _ in $(seq 1 60); do
  if curl --fail --silent --output /dev/null "http://localhost:8080/ui/"; then
    exit 0
  fi
  sleep 2
done
echo "::error::App did not respond"
exit 1
