#!/bin/sh
# Installation of the demo farm on the server (once). Needs git and Docker (with compose).
#
#   curl -fsSL https://raw.githubusercontent.com/jesuisundesdeux/vigilo-demo/main/install.sh | sudo sh
#
# Then configure the nginx of the host (nginx/vigilo-demo.conf.example). Everything else
# comes from the repository: the controller applies instances.yml on its own.
set -eu

DEMO_DIR=${DEMO_DIR:-/opt/vigilo-demo}
REPO=${DEMO_REPO:-https://github.com/jesuisundesdeux/vigilo-demo.git}

command -v git > /dev/null || { echo "git est nécessaire"; exit 1; }
docker compose version > /dev/null || { echo "Docker avec compose est nécessaire"; exit 1; }

[ -d "$DEMO_DIR/.git" ] || git clone "$REPO" "$DEMO_DIR"
cd "$DEMO_DIR"

if [ ! -f .env ]; then
  cp .env.example .env
  # Install code of the setup assistant of every demo (no ambiguous characters)
  CODE=$(LC_ALL=C tr -dc 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789' < /dev/urandom | head -c 20)
  sed -i "s|^DEMO_DIR=.*|DEMO_DIR=$DEMO_DIR|; s|^VIGILO_SETUP_CODE=.*|VIGILO_SETUP_CODE=$CODE|" .env
  chmod 600 .env
fi

docker compose up -d --build

echo
echo "Ferme de démos démarrée dans $DEMO_DIR (point d'entrée : $(grep '^DEMO_BIND=' .env | cut -d= -f2))."
echo "Code d'installation des démos (à garder, demandé par /admin/ au premier lancement) :"
grep '^VIGILO_SETUP_CODE=' .env | cut -d= -f2
echo "Reste à configurer le nginx de l'hôte : nginx/vigilo-demo.conf.example"
