# vigilo-demo

Instances de démonstration de [Vigilo](https://vigilo.city) : chaque démo est un écosystème Vigilo complet et fermé
(base de données, [backend](https://github.com/jesuisundesdeux/vigilo-backend),
[application web](https://github.com/jesuisundesdeux/vigilo-webapp) et sa propre liste des instances et des catégories, à
la place de [vigilo-conf](https://github.com/jesuisundesdeux/vigilo-conf)), dans ses propres conteneurs.

| Adresse | Contenu |
|---|---|
| `https://<id>.vigilo-demo.velocite-montpellier.fr/webapp/` | Application web, qui ne parle qu'au backend de cette démo |
| `https://<id>.vigilo-demo.velocite-montpellier.fr/admin/` | Administration de la démo |
| `https://<id>.vigilo-demo.velocite-montpellier.fr/` | Redirige vers `/webapp/` |

## Ajouter, retirer ou mettre à jour une démo

Tout se fait dans [`instances.yml`](instances.yml), par une pull request sur `main` (la CI vérifie le fichier) :

```yaml
instances:
  - id: demo                  # sous-domaine : minuscules, chiffres, tirets
    description: Démo générale
  - id: asso-x
    description: Présentation à l'association X
    backend: "0.0.31"         # facultatif : version de vigilobs/vigilo-backend (défaut 0.0)
    webapp: edge              # facultatif : version de ghcr.io/jesuisundesdeux/vigilo-webapp (défaut latest)
```

Une minute environ après la fusion, le serveur applique la liste :

- **ajout** : la démo est créée vide, comme une installation à la main avec Docker ;
- **retrait** : ses conteneurs sont arrêtés et supprimés, **ses données sont gardées** ; remettre la même `id` la
  redémarre avec ses données ;
- **versions** : les images sont mises à jour toutes les 6 heures (dernière version publiée pour `0.0`, `latest`…).

Aucune connexion au serveur n'est nécessaire.

## Première connexion à une démo

1. Ouvrir `https://<id>.vigilo-demo.velocite-montpellier.fr/admin/` : l'assistant d'installation demande le **code
   d'installation** de la ferme (affiché par `install.sh`, gardé par la personne qui a installé le serveur), puis le
   compte administrateur (mot de passe choisi à ce moment) et le nom de l'instance. L'URL est détectée.
2. Dans l'admin, suivre le guide **Première configuration** : territoire (scope), villes. Le territoire apparaît dans
   l'application web de la démo une minute environ après sa création (étape « Référencement » automatique).
3. Ouvrir `https://<id>.vigilo-demo.velocite-montpellier.fr/webapp/`.

## Installation du serveur (une seule fois)

Prérequis : Docker avec compose, git, un nginx qui reçoit `*.vigilo-demo.velocite-montpellier.fr` (DNS en place) avec
un certificat TLS joker.

```sh
curl -fsSL https://raw.githubusercontent.com/jesuisundesdeux/vigilo-demo/main/install.sh | sudo sh
```

Le script clone le dépôt dans `/opt/vigilo-demo`, crée `.env` (dont le code d'installation des démos, à noter), puis
démarre Traefik (point d'entrée sur `127.0.0.1:8480`) et le contrôleur. Il reste à configurer le nginx de l'hôte avec
[`nginx/vigilo-demo.conf.example`](nginx/vigilo-demo.conf.example).

Fonctionnement, exploitation et dépannage : [doc/GUIDE.md](doc/GUIDE.md).
