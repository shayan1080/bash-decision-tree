#!/bin/bash

source network.sh
source packages.sh

if check_network; then
    install_packages
else
    echo "No internet connection"
fi