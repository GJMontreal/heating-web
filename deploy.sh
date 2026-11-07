#!/bin/bash
set -e

REMOTE_USER=$1
REMOTE_HOST=$2

if [ -z "${REMOTE_USER}" ] || [ -z "${REMOTE_HOST}" ]; then
    echo "usage: ./deploy.sh <user> <host>"
    exit 1
fi

SERVICE_NAME=heating_web
SERVICE_USER="${SERVICE_USER:-heating}"
INSTALL_DIR="/var/lib/${SERVICE_NAME}"
OTHER_DIRS=(/var/lib/boiler_relay /var/lib/boiler_relay_v2 /var/lib/mqtt_bridge /var/lib/mqtt_bridge_v2)

for OTHER_DIR in "${OTHER_DIRS[@]}"; do
    if [ "${INSTALL_DIR%/}" = "${OTHER_DIR}" ]; then
        echo "refusing to deploy to ${OTHER_DIR}, which belongs to another service"
        exit 1
    fi
done

TEMPLATES=(
    "deploy/setup_python.sh.template"
    "deploy/${SERVICE_NAME}.service.template"
)

echo "Creating files from templates"
for INPUT_FILE in "${TEMPLATES[@]}"; do
    OUTPUT_FILE=${INPUT_FILE%.*}
    sed -e "s/<service_name>/${SERVICE_NAME}/g" -e "s/<service_user>/${SERVICE_USER}/g" "${INPUT_FILE}" > "${OUTPUT_FILE}"
done

STAGE=$(mktemp -d)
trap 'rm -rf "${STAGE}"' EXIT

mkdir -p "${STAGE}/heating_web" "${STAGE}/deploy"
cp requirements.txt "${STAGE}/"
cp heating_web/*.py "${STAGE}/heating_web/"
cp deploy/setup_python.sh "deploy/${SERVICE_NAME}.service" "${STAGE}/deploy/"
chmod -R u=rwX,go=rX "${STAGE}"

VERSION=$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' heating_web/version.py)
COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo unknown)
if [ "${COMMIT}" != unknown ] && [ -n "$(git status --porcelain 2>/dev/null)" ]; then
    COMMIT="${COMMIT}-dirty"
fi
printf '{"version": "%s", "commit": "%s"}\n' "${VERSION}" "${COMMIT}" > "${STAGE}/build_info.json"

SSH_CMD="ssh ${REMOTE_USER}@${REMOTE_HOST}"
REMOTE="${REMOTE_USER}@${REMOTE_HOST}"

${SSH_CMD} sudo mkdir -p "${INSTALL_DIR}"
${SSH_CMD} sudo chown "${REMOTE_USER}" "${INSTALL_DIR}"

echo copying files
rsync -rltp --delete --exclude=/.venv "${STAGE}/" "${REMOTE}:${INSTALL_DIR}/"

echo creating venv
${SSH_CMD} sh "${INSTALL_DIR}/deploy/setup_python.sh"

echo "to install the unit run on the device:"
echo "sudo cp ${INSTALL_DIR}/deploy/${SERVICE_NAME}.service /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable ${SERVICE_NAME}"
echo "to start or restart it run: sudo systemctl restart ${SERVICE_NAME}"
