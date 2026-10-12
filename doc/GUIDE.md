# Guide de la ferme de démos

## Architecture

```
Internet → nginx de l'hôte (TLS *.vigilo-demo.velocite-montpellier.fr)
         → 127.0.0.1:8480 : Traefik (projet compose « vigilo-demo »)
              ├─ <id>…/ , /webapp, /webapp/…, /conf/…  → vigilo-demo-<id>-webapp (nginx)
              └─ tout le reste (API, /admin/)            → vigilo-demo-<id>-backend ─→ vigilo-demo-<id>-db (MariaDB)
controller (projet « vigilo-demo ») : applique instances.yml (projet « vigilo-demo-instances »)
```

| Élément | Rôle |
|---|---|
| `docker-compose.yml` | Socle : `traefik` (point d'entrée, lit les labels des conteneurs des démos) et `controller` |
| `controller/vigilo-demo.py` | Contrôleur (Python, lu depuis le dépôt : il suit les mises à jour du dépôt et se relance quand il change) |
| `controller/Dockerfile` | Image du contrôleur : client Docker + compose, git, Python, PyYAML |
| `instances.yml` | Liste des démos |
| `conf/categorielist.json` | Catégories nationales des démos (copie de vigilo-conf, modifiable ici) |
| `webapp/nginx.conf` | nginx du conteneur webapp de chaque démo : redirections, `/webapp/` (application et `config.json`), `/conf/` |
| `nginx/vigilo-demo.conf.example` | Configuration du nginx de l'hôte |
| `install.sh`, `.env.example` | Installation du serveur |
| `state/` (non versionné) | Fichier compose généré, mots de passe des bases, `citylist.json` de chaque démo |

### Une démo

| Conteneur | Image | Détail |
|---|---|---|
| `vigilo-demo-<id>-db` | `mariadb:lts` | Base `vigilo`, mots de passe aléatoires (`state/instances/<id>/secrets.json`), volume `vigilo-demo_<id>_db`, réglages mémoire réduits |
| `vigilo-demo-<id>-backend` | `vigilobs/vigilo-backend:<backend>` | Volumes `vigilo-demo_<id>_images` et `_caches` ; `VIGILO_CONF_URL=http://<id>-webapp/conf`, `VIGILO_WEBAPP_URL=https://<id>.<domaine>/webapp/`, `VIGILO_SETUP_CODE` (code de la ferme), `VIGILO_TRUSTED_PROXIES` (IP réelle des visiteurs) |
| `vigilo-demo-<id>-webapp` | `ghcr.io/jesuisundesdeux/vigilo-webapp:<webapp>` | Sert l'application sous `/webapp/` avec `config.json` = `{"conf_url": "/conf"}`, et `/conf/` (`state/instances/<id>/conf/`) |

Réseaux : la base n'est que sur le réseau de sa démo (`vigilo-demo-<id>`) ; backend et webapp sont aussi sur
`vigilo-demo-proxy` (Traefik).

**Écosystème fermé** : l'application web lit `/conf/citylist.json` et `/conf/categorielist.json` de sa démo, jamais
vigilo-conf. Le contrôleur écrit `citylist.json` d'après les scopes de la base de la démo (une entrée par scope, nom =
nom affiché du scope, `api_path` = `https://<id>.<domaine>`) : un scope créé dans l'admin apparaît dans l'application
en une minute environ. Le backend lit les mêmes fichiers (catégories nationales, nom de l'instance pour les liens des
webhooks, étape « Référencement » du guide de l'admin).

## Contrôleur

Toutes les `SYNC_INTERVAL` secondes (60) :

1. `git fetch` de `DEMO_REPO_URL` (HTTPS, quelle que soit l'adresse du clone : le conteneur n'a pas de clé SSH) +
   `git reset --hard origin/<DEMO_BRANCH>` (le serveur ne modifie jamais le dépôt ; `state/` et `.env` sont ignorés
   par git) ; si le script a changé, il se relance ;
2. lecture et vérification d'`instances.yml` ; s'il est invalide, rien n'est changé ;
3. images de la webapp : si une image `ghcr.io/jesuisundesdeux/vigilo-webapp:<webapp>` n'est ni présente ni
   téléchargeable (pas encore de tag, package privé), elle est **construite sur le serveur** depuis le dépôt
   vigilo-webapp (`docker build <WEBAPP_GIT>#<ref>` : `vX.Y.Z` pour une version, `master` pour `latest`, `edge`, `1`,
   `1.19`, sinon la branche du même nom ; nécessite `git` sur l'hôte Docker). Elle est reconstruite à chaque mise à
   jour des images tant que le registre n'en a pas ;
4. écriture de `state/compose.instances.yml` et, s'il a changé (ou au démarrage, ou après la mise à jour des images
   toutes les `PULL_INTERVAL` heures), `docker compose -p vigilo-demo-instances up -d --remove-orphans` : les démos
   retirées sont supprimées, leurs volumes et `state/instances/<id>/` restent. Si cette commande échoue (image
   introuvable pour une démo…), les démos sont démarrées une par une : une démo en échec n'empêche pas les autres ;
5. mise à jour de `citylist.json` et `categorielist.json` de chaque démo.

Commandes : `python3 controller/vigilo-demo.py check` (vérifie `instances.yml`), `render` (affiche le compose généré),
`sync` (un passage), `loop` (par défaut).

Variables (`.env`) : `DEMO_DIR`, `DEMO_DOMAIN`, `DEMO_BIND`, `VIGILO_SETUP_CODE` (obligatoire, 12 à 64 lettres ou
chiffres), `DEMO_BRANCH`, `DEMO_REPO_URL`, `SYNC_INTERVAL`, `PULL_INTERVAL` ; pour les tests : `DEMO_GIT_PULL=false`,
`BACKEND_IMAGE`, `WEBAPP_IMAGE`, `WEBAPP_GIT`, `WEBAPP_BUILD_CONTEXT` (dossier local à construire), `MARIADB_IMAGE`.

Une modification de `docker-compose.yml` ou de `controller/Dockerfile` (socle) n'est pas appliquée automatiquement :
`docker compose up -d --build` sur le serveur.

## Exploitation

Sur le serveur, dans `/opt/vigilo-demo` :

```sh
docker compose logs -f controller                           # ce que fait le contrôleur
docker compose -p vigilo-demo-instances ps                   # conteneurs des démos
docker logs vigilo-demo-<id>-backend                         # une démo
docker volume rm vigilo-demo_<id>_db vigilo-demo_<id>_images vigilo-demo_<id>_caches \
  && rm -rf state/instances/<id>                             # effacer définitivement une démo retirée
grep VIGILO_SETUP_CODE .env                                  # code d'installation des démos
```

Repartir de zéro pour une démo : la retirer d'`instances.yml`, effacer ses volumes et `state/instances/<id>` comme
ci-dessus, puis la remettre.

## Tester en local

```sh
cp .env.example .env    # DEMO_DIR=$PWD, VIGILO_SETUP_CODE=...
docker compose up -d traefik
DEMO_DIR=$PWD DEMO_GIT_PULL=false VIGILO_SETUP_CODE=... python3 controller/vigilo-demo.py sync
curl -H 'Host: demo.vigilo-demo.velocite-montpellier.fr' -H 'X-Forwarded-Proto: https' http://127.0.0.1:8480/webapp/
```

Versions nécessaires : backend ≥ 0.0.31 (`VIGILO_CONF_URL`, `VIGILO_WEBAPP_URL`, `VIGILO_SETUP_CODE`,
`VIGILO_TRUSTED_PROXIES`), webapp ≥ 1.19.0 (`config.json`, image Docker).
