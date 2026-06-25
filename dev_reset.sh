#!/bin/bash

rm -rf instance/ migrations/versions/
uv run flask db init
uv run flask db migrate -m "initial"
uv run flask db upgrade
uv run flask seed --dev
