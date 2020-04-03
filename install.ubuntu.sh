#!/bin/bash -x

# Install script for VTServer for Linux Ubuntu systemd
# Run as root

if [[ $EUID -ne 0 ]]; then
    echo "This script must be run as root"
    exit 1
fi

# Creating the vt_server user
useradd -r -s /bin/false vt_server

DEST=/usr/local/lib/vt_server

mkdir -p $DEST
install -C -g vt_server -o vt_server -v -t $DEST/ src/*.py README.md
chmod 755 $DEST/vt_server.py

# Configuration file
mkdir -p /usr/local/etc/vt_server/
install -C -g vt_server -o vt_server -v -t /usr/local/etc/vt_server/ src/vt_server.conf.json

# Creating the cache folder
# (Should do that using the configuration file...)
CACHE=/var/cache/vt_server
mkdir -p $CACHE
chown vt_server:www-data $CACHE
chmod 773 $CACHE

# Installing the systemd service
ln -s $DEST/vt_server_systemd.py /usr/local/sbin/vt_server
chown vt_server /usr/local/sbin/vt_server
chmod 755 /usr/local/sbin/vt_server

install -C -m 644 -v src/vt_server.service /etc/systemd/system/

touch /var/log/vt_server.log
chown vt_server:adm /var/log/vt_server.log
chmod 777 /var/log/vt_server.log

systemctl stop vt_server
systemctl daemon-reload
systemctl enable vt_server
systemctl start vt_server

# Uncomment if your server will be opened to the world
#sudo ufw allow 1996
