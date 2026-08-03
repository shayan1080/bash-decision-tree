#!/bin/bash

install_packages() {

    if apt update; then
        echo "Packages installed"
    else
        echo "Installation failed"
    fi

}