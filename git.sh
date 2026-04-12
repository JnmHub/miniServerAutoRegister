#!/bin/bash

export http_proxy="http://127.0.0.1:7897"
export https_proxy="http://127.0.0.1:7897"

git add .
git commit -m "auto backup $(date '+%Y-%m-%d %H:%M:%S')" || exit 0
git push origin main