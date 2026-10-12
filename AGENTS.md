# AGENTS.md — vigilo-demo

Informations pour les agents IA (et les humains) qui travaillent sur ce dépôt.

## Le projet

Ferme d'instances de démonstration de [Vigilo](https://vigilo.city) : chaque entrée d'`instances.yml` devient une
démo complète et fermée (MariaDB, [vigilo-backend](https://github.com/jesuisundesdeux/vigilo-backend),
[vigilo-webapp](https://github.com/jesuisundesdeux/vigilo-webapp), sa propre liste d'instances et de catégories) sur
`https://<id>.vigilo-demo.velocite-montpellier.fr` (`/webapp/`, `/admin/`). Un contrôleur sur le serveur suit ce dépôt
(`main`) et applique la liste toutes les minutes : **une modification fusionnée sur `main` est en production**.

Fonctionnement détaillé : `doc/GUIDE.md`. Usage : `README.md`.

## Organisation

| Chemin | Contenu |
|---|---|
| `instances.yml` | Liste des démos (`id`, `description`, versions `backend` / `webapp`) |
| `controller/vigilo-demo.py` | Contrôleur : git (HTTPS), images de la webapp (construites si absentes du registre), compose généré (`state/compose.instances.yml`, démarrage démo par démo en cas d'échec), `citylist.json` de chaque démo |
| `controller/Dockerfile` | Image du contrôleur (docker CLI + compose, git, Python, PyYAML) |
| `docker-compose.yml` | Socle : Traefik (point d'entrée `127.0.0.1:8480`) et contrôleur |
| `webapp/nginx.conf` | nginx des conteneurs webapp des démos (`/webapp/`, `config.json`, `/conf/`) |
| `conf/categorielist.json` | Catégories nationales des démos |
| `nginx/vigilo-demo.conf.example` | nginx de l'hôte (TLS) |
| `install.sh`, `.env.example` | Installation du serveur |

## Règles à respecter

- **Données des démos** : ne jamais supprimer de volume ni de `state/instances/<id>/` automatiquement ; une démo
  retirée garde ses données. Les mots de passe des bases (`secrets.json`) ne doivent jamais changer pour une démo
  existante (MariaDB ne les lit qu'à la création).
- **Rien d'extérieur** : une démo ne dépend ni de vigilo-conf ni d'app.vigilo.city (variables `VIGILO_CONF_URL`,
  `VIGILO_WEBAPP_URL` du backend, `config.json` de la webapp).
- **Sécurité** : aucun secret dans le dépôt (public) ; le code d'installation est dans `.env` sur le serveur. Le
  contrôleur a accès au socket Docker : il ne doit exécuter que des commandes construites à partir de valeurs
  vérifiées (`id` et versions validés par `load_instances()`).
- **Compatibilité** : le contrôleur tourne dans l'image `docker:29-cli` (Python d'Alpine) ; pas de dépendance hors
  PyYAML.
- **Documentation** : toute modification met à jour `README.md` / `doc/GUIDE.md` et ce fichier si l'organisation change.
- **Langue** : documentation, messages et commits en **français** ; commentaires du code en anglais, courts.

## Vérifier

```sh
python3 controller/vigilo-demo.py check                 # instances.yml
python3 controller/vigilo-demo.py render > /tmp/c.yml && docker compose -f /tmp/c.yml config -q
```

Test complet en local : `doc/GUIDE.md` (« Tester en local »). La CI (`.github/workflows/ci.yml`) vérifie
`instances.yml`, le compose généré, le socle et construit l'image du contrôleur.

## Dépôts liés

- [vigilo-backend](https://github.com/jesuisundesdeux/vigilo-backend) : image `vigilobs/vigilo-backend` (≥ 0.0.31).
- [vigilo-webapp](https://github.com/jesuisundesdeux/vigilo-webapp) : image `ghcr.io/jesuisundesdeux/vigilo-webapp`
  (≥ 1.19.0).
- [vigilo-conf](https://github.com/jesuisundesdeux/vigilo-conf) : origine de `conf/categorielist.json`.
