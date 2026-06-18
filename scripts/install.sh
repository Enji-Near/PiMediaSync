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

# install python requirements
PYSIMPLEDMX_VERSION="v0.2.0"
pip3 install git+https://github.com/limbicmedia/pySimpleDMX.git@${PYSIMPLEDMX_VERSION} # `pip3 install pysimpledmx` does not install working version
pip3 install -r ${WORKDIR}/requirements.txt

# SystemD Setup
APPLICATION_FLAGS="${APPLICATION_FLAGS:--c${WORKDIR}/example_config.py}"
echo "APPLICATION_FLAGS=${APPLICATION_FLAGS}" > /etc/pimediasync.conf # setup pimediasync config file
systemctl enable ${WORKDIR}/scripts/pimediasync.service

# Adjust Display settings
# On the Pi 5 / Raspberry Pi OS (Bookworm) the boot config lives in
# /boot/firmware/config.txt and the legacy hdmi_* options are ignored by the
# KMS display stack. To force a 1080p HDMI signal even when no monitor is
# detected (useful for kiosk/headless installs) set a kernel video= mode on
# the HDMI connector via cmdline.txt instead.
BOOT_DIR="/boot/firmware"
if [ ! -d "${BOOT_DIR}" ]; then
    BOOT_DIR="/boot"   # fall back for older images
fi
if ! grep -q "video=HDMI-A-1" "${BOOT_DIR}/cmdline.txt"; then
    # append to the single-line cmdline.txt
    sed -i 's/$/ video=HDMI-A-1:1920x1080@60D/' "${BOOT_DIR}/cmdline.txt"
fi

# Setup tmpfs filesystem for log (protect the SDCard)
if [ -z "$DEBUG" ]; then 
    # set log directory to be TMPFS;
    echo "tmpfs    /var/log    tmpfs    defaults,noatime,nosuid,mode=0755,size=100m    0    0" >> /etc/fstab
fi
set +e
