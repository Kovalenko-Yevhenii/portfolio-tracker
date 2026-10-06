#!/bin/zsh
cd -- "${0:A:h}" || exit 1
if [[ ! -x .venv-terminal/bin/python ]]; then
  print 'The tracker environment is missing. See Terminal interface in README.md for setup.'
  read '?Press Return to close.'
  exit 1
fi
.venv-terminal/bin/python launch_terminal.py --open
