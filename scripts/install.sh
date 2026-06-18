#!/usr/bin/env bash

## PiMediaSync Installer
# This script installs the PiMediaSync application
# and enables the systemd service so that it runs at boot
#
# This script is designed to be run by other scripts
# to setup config and media files for specific installations
# 
# On its own, this script will enable a simple 
# default config (example_config.py)

set -e
if [ "$(whoami)" != "root" ]; then
    echo "must be run as root."
    exit 1
fi

HOMEDIR="${HOMEDIR:-/opt}"
WORKDIR="${HOMEDIR}/pimediasync"

# Setup hostname of device
PIHOSTNAME="${PIHOSTNAME:-pimediasync}"
echo "Setting HOSTNAME to $PIHOSTNAME"
echo "$PIHOSTNAME" > /etc/hostname

# Install apt requirements
# NOTE: omxplayer was deprecated in 2020 and does not run on the Pi 5; VLC
# (libvlc, used via python-vlc) is the replacement media player.
# liblgpio1 provides the Pi 5 GPIO backend used by gpiozero.
apt-get update
apt-get install --no-install-recommends -y \
    git \
    vim \
    vlc \
    python3 \
    python3-pip \
    python3-lgpio \
    python3-setuptools
apt-get clean

# download PiMediaSync git repo
PIMEDIASYNC_VERSION="${PIMEDIASYNC_VERSION:-master}"
if [ -d "${WORKDIR}/.git" ]
then
    cd ${WORKDIR}
    git fetch
    git checkout ${PIMEDIASYNC_VERSION}
    git pull
else
    git clone --branch ${PIMEDIASYNC_VERSION} --single-branch https://github.com/limbicmedia/pimediasync ${WORKDIR}
fi

# enable app
chmod +x ${WORKDIR}/app.py

# install python requirements (includes pySimpleDMX from git, see requirements.txt)
pip3 install -r ${WORKDIR}/requirements.txt

# SystemD Setup
APPLICATION_FLAGS="${APPLICATION_FLAGS:--c${WORKDIR}/example_config.py}"
echo "APPLICATION_FLAGS=${APPLICATION_FLAGS}" > /etc/pimediasync.conf # setup pimediasync config file

# The service runs inside the desktop user's X11 session so VLC can display
# fullscreen on the monitor. Point the unit at the actual desktop user
# (the user who ran sudo, or "pi" by default) and make sure that user can
# access the DMX serial device (dialout), GPIO (gpio), and video (video).
RUNUSER="${RUNUSER:-${SUDO_USER:-pi}}"
sed -i "s/^User=.*/User=${RUNUSER}/" ${WORKDIR}/scripts/pimediasync.service
sed -i "s#^Environment=XAUTHORITY=.*#Environment=XAUTHORITY=/home/${RUNUSER}/.Xauthority#" ${WORKDIR}/scripts/pimediasync.service
usermod -aG dialout,gpio,video "${RUNUSER}" || true

systemctl enable ${WORKDIR}/scripts/pimediasync.service

# Display: the Raspberry Pi OS Desktop autodetects the connected monitor and
# VLC plays fullscreen on it, so no manual HDMI/KMS configuration is required.

# Setup tmpfs filesystem for log (protect the SDCard)
if [ -z "$DEBUG" ]; then 
    # set log directory to be TMPFS;
    echo "tmpfs    /var/log    tmpfs    defaults,noatime,nosuid,mode=0755,size=100m    0    0" >> /etc/fstab
fi
set +e
