#!/bin/sh

set -e # Exit on failure

exec python3 -m app.main "$@"
