#!/usr/bin/env python3
"""
Demo farm controller: keeps the Docker containers in line with instances.yml.

Every SYNC_INTERVAL seconds:
  1. updates the checkout of this repository (git fetch + reset on DEMO_BRANCH);
  2. writes state/compose.instances.yml (db, backend, webapp per instance) and runs
     "docker compose up -d --remove-orphans" when it changed: added instances are created,
     removed ones are stopped (their volumes and state/instances/<id>/ are kept);
  3. writes state/instances/<id>/conf/citylist.json from the scopes of each instance
     (the closed "vigilo-conf" of the demo) and categorielist.json from conf/.
Every PULL_INTERVAL hours: docker compose pull, so that the instances follow their image tags.

Commands: loop (default), sync (one pass), check (validates instances.yml), render
(prints the compose file).
"""
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import time

import yaml

DEMO_DIR = os.environ.get('DEMO_DIR', os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEMO_DOMAIN = os.environ.get('DEMO_DOMAIN', 'vigilo-demo.velocite-montpellier.fr')
DEMO_BRANCH = os.environ.get('DEMO_BRANCH', 'main')
# Public repository over HTTPS: the controller has no SSH key, whatever the clone URL
DEMO_REPO_URL = os.environ.get('DEMO_REPO_URL') or 'https://github.com/jesuisundesdeux/vigilo-demo.git'
DEMO_GIT_PULL = os.environ.get('DEMO_GIT_PULL', 'true') != 'false'
SYNC_INTERVAL = int(os.environ.get('SYNC_INTERVAL', '60'))
PULL_INTERVAL = float(os.environ.get('PULL_INTERVAL', '6')) * 3600
SETUP_CODE = os.environ.get('VIGILO_SETUP_CODE', '')
TRUSTED_PROXIES = os.environ.get('DEMO_TRUSTED_PROXIES', '10.0.0.0/8,172.16.0.0/12,192.168.0.0/16')

PROJECT = 'vigilo-demo-instances'
PROXY_NETWORK = 'vigilo-demo-proxy'
BACKEND_IMAGE = os.environ.get('BACKEND_IMAGE', 'vigilobs/vigilo-backend')
WEBAPP_IMAGE = os.environ.get('WEBAPP_IMAGE', 'ghcr.io/jesuisundesdeux/vigilo-webapp')
MARIADB_IMAGE = os.environ.get('MARIADB_IMAGE', 'mariadb:lts')
# Web app image not published (no tag yet, private package): built here from the repository
WEBAPP_GIT = os.environ.get('WEBAPP_GIT') or 'https://github.com/jesuisundesdeux/vigilo-webapp.git'
WEBAPP_BUILD_CONTEXT = os.environ.get('WEBAPP_BUILD_CONTEXT', '')  # tests: local directory
DEFAULTS = {'backend': '0.0', 'webapp': 'latest'}

ID_RE = re.compile(r'^[a-z0-9](?:[a-z0-9-]{0,30}[a-z0-9])?$')
TAG_RE = re.compile(r'^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$')
RESERVED = {'www', 'traefik', 'admin', 'api', 'conf', 'webapp', 'status', 'mail'}
FIELDS = {'id', 'description', 'backend', 'webapp'}

STATE = os.path.join(DEMO_DIR, 'state')
COMPOSE_FILE = os.path.join(STATE, 'compose.instances.yml')


def log(message):
    print(time.strftime('%Y-%m-%d %H:%M:%S ') + message, flush=True)


def run(args, check=True, quiet=False):
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0 and not quiet:
        log('error: %s\n%s%s' % (' '.join(args), result.stdout, result.stderr))
    if check and result.returncode != 0:
        raise RuntimeError(' '.join(args[:3]) + ' failed')
    return result


def load_instances():
    """instances.yml: list of instances, or ValueError with every problem found."""
    with open(os.path.join(DEMO_DIR, 'instances.yml')) as f:
        data = yaml.safe_load(f) or {}
    items = data.get('instances') or []
    errors, seen, instances = [], set(), []
    if not isinstance(items, list):
        raise ValueError('"instances" doit être une liste')
    for n, item in enumerate(items, 1):
        if not isinstance(item, dict):
            errors.append('entrée %d : doit être un objet avec "id"' % n)
            continue
        # Host names ignore case; container names must be lowercase
        ident = str(item.get('id', '')).strip().lower()
        where = 'entrée %d (%s)' % (n, ident or 'sans id')
        if not ID_RE.match(ident):
            errors.append(where + ' : id en lettres, chiffres et tirets, 32 caractères au plus')
        elif ident in RESERVED:
            errors.append(where + ' : id réservé')
        elif ident in seen:
            errors.append(where + ' : id en double')
        seen.add(ident)
        for key in set(item) - FIELDS:
            errors.append(where + ' : champ inconnu "%s"' % key)
        instance = {'id': ident, 'description': str(item.get('description') or '')}
        for key, default in DEFAULTS.items():
            tag = str(item.get(key) or default)
            if not TAG_RE.match(tag):
                errors.append(where + ' : version %s invalide "%s"' % (key, tag))
            instance[key] = tag
        instances.append(instance)
    if errors:
        raise ValueError('\n'.join(errors))
    return instances


def instance_dir(ident):
    return os.path.join(STATE, 'instances', ident)


def secrets_for(ident):
    """Database passwords of an instance, created once and kept (also after a removal)."""
    path = os.path.join(instance_dir(ident), 'secrets.json')
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    os.makedirs(instance_dir(ident), exist_ok=True)
    values = {'MYSQL_PASSWORD': secrets.token_urlsafe(24), 'MYSQL_ROOT_PASSWORD': secrets.token_urlsafe(24)}
    with open(path, 'w') as f:
        json.dump(values, f)
    os.chmod(path, 0o600)
    return values


def compose_for(instances, with_secrets=True):
    """Compose file of the instances (dict)."""
    services, volumes, networks = {}, {}, {PROXY_NETWORK: {'external': True, 'name': PROXY_NETWORK}}
    for inst in instances:
        ident = inst['id']
        host = '%s.%s' % (ident, DEMO_DOMAIN)
        pw = secrets_for(ident) if with_secrets else {'MYSQL_PASSWORD': 'x', 'MYSQL_ROOT_PASSWORD': 'x'}
        net = 'net-' + ident
        networks[net] = {'name': 'vigilo-demo-' + ident}
        for vol in ('db', 'images', 'caches'):
            volumes['%s-%s' % (ident, vol)] = {'name': 'vigilo-demo_%s_%s' % (ident, vol)}
        labels = {'vigilo-demo.instance': ident}
        services[ident + '-db'] = {
            'image': MARIADB_IMAGE,
            'container_name': 'vigilo-demo-%s-db' % ident,
            'restart': 'unless-stopped',
            # Small instances: little memory
            'command': ['--innodb-buffer-pool-size=32M', '--performance-schema=OFF', '--max-connections=40'],
            'environment': {
                'MARIADB_ROOT_PASSWORD': pw['MYSQL_ROOT_PASSWORD'],
                'MARIADB_USER': 'vigilo',
                'MARIADB_PASSWORD': pw['MYSQL_PASSWORD'],
                'MARIADB_DATABASE': 'vigilo',
                'MARIADB_AUTO_UPGRADE': '1',
            },
            'volumes': ['%s-db:/var/lib/mysql' % ident],
            'networks': [net],
            'labels': labels,
        }
        services[ident + '-backend'] = {
            'image': '%s:%s' % (BACKEND_IMAGE, inst['backend']),
            'container_name': 'vigilo-demo-%s-backend' % ident,
            'restart': 'unless-stopped',
            'depends_on': [ident + '-db'],
            'environment': {
                'MYSQL_HOST': ident + '-db',
                'MYSQL_USER': 'vigilo',
                'MYSQL_PASSWORD': pw['MYSQL_PASSWORD'],
                'MYSQL_DATABASE': 'vigilo',
                'AUTOUPDATE': 'true',
                # Closed ecosystem: the configuration and the web app of this demo
                'VIGILO_CONF_URL': 'http://%s-webapp/conf' % ident,
                'VIGILO_WEBAPP_URL': 'https://%s/webapp/' % host,
                'VIGILO_SETUP_CODE': SETUP_CODE,
                'VIGILO_TRUSTED_PROXIES': TRUSTED_PROXIES,
            },
            'volumes': ['%s-images:/var/www/html/images' % ident, '%s-caches:/var/www/html/caches' % ident],
            'networks': [net, PROXY_NETWORK],
            'labels': dict(labels, **{
                'traefik.enable': 'true',
                'traefik.docker.network': PROXY_NETWORK,
                'traefik.http.routers.%s-backend.rule' % ident: 'Host(`%s`)' % host,
                'traefik.http.routers.%s-backend.priority' % ident: '1',
                'traefik.http.routers.%s-backend.entrypoints' % ident: 'web',
                'traefik.http.services.%s-backend.loadbalancer.server.port' % ident: '80',
            }),
        }
        services[ident + '-webapp'] = {
            'image': '%s:%s' % (WEBAPP_IMAGE, inst['webapp']),
            'container_name': 'vigilo-demo-%s-webapp' % ident,
            'restart': 'unless-stopped',
            'volumes': [
                os.path.join(DEMO_DIR, 'webapp', 'nginx.conf') + ':/etc/nginx/conf.d/default.conf:ro',
                os.path.join(instance_dir(ident), 'conf') + ':/srv/conf:ro',
            ],
            'networks': [PROXY_NETWORK],
            'labels': dict(labels, **{
                'traefik.enable': 'true',
                'traefik.docker.network': PROXY_NETWORK,
                'traefik.http.routers.%s-webapp.rule' % ident:
                    'Host(`%s`) && (Path(`/`) || Path(`/webapp`) || PathPrefix(`/webapp/`) || PathPrefix(`/conf/`))' % host,
                'traefik.http.routers.%s-webapp.priority' % ident: '10',
                'traefik.http.routers.%s-webapp.entrypoints' % ident: 'web',
                'traefik.http.services.%s-webapp.loadbalancer.server.port' % ident: '80',
            }),
        }
    return {'name': PROJECT, 'services': services, 'volumes': volumes, 'networks': networks}


def write_if_changed(path, content):
    old = open(path).read() if os.path.exists(path) else None
    if old == content:
        return False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        f.write(content)
    os.replace(tmp, path)
    return True


def git_update():
    """Checkout of the repository at the last commit of DEMO_BRANCH. True when it changed."""
    before = run(['git', '-C', DEMO_DIR, 'rev-parse', 'HEAD']).stdout.strip()
    run(['git', '-C', DEMO_DIR, 'fetch', '--quiet', DEMO_REPO_URL,
         '+refs/heads/%s:refs/remotes/origin/%s' % (DEMO_BRANCH, DEMO_BRANCH)])
    # The server never edits the checkout: state/ and .env are ignored by git
    run(['git', '-C', DEMO_DIR, 'reset', '--quiet', '--hard', 'origin/' + DEMO_BRANCH])
    after = run(['git', '-C', DEMO_DIR, 'rev-parse', 'HEAD']).stdout.strip()
    if before != after:
        log('dépôt mis à jour : %s -> %s' % (before[:8], after[:8]))
    return before != after


def compose(*args, check=True):
    return run(['docker', 'compose', '-p', PROJECT, '-f', COMPOSE_FILE] + list(args), check=check)


def webapp_ref(tag):
    """Git reference of the web app for an image tag: vX.Y.Z for a version, master otherwise."""
    if re.match(r'^\d+\.\d+\.\d+$', tag):
        return 'v' + tag
    if tag in ('latest', 'edge') or re.match(r'^\d+(\.\d+)?$', tag):
        return 'master'
    return tag


def ensure_webapp_images(instances, refresh):
    """Web app images: pulled, or built from the repository when the registry has none."""
    for tag in sorted(set(i['webapp'] for i in instances)):
        image = '%s:%s' % (WEBAPP_IMAGE, tag)
        present = run(['docker', 'image', 'inspect', image], check=False, quiet=True).returncode == 0
        if present and not refresh:
            continue
        if run(['docker', 'pull', '--quiet', image], check=False, quiet=True).returncode == 0:
            continue
        context = WEBAPP_BUILD_CONTEXT or '%s#%s' % (WEBAPP_GIT, webapp_ref(tag))
        log('%s introuvable sur le registre : construction depuis %s' % (image, context))
        if run(['docker', 'build', '--quiet', '-t', image, context], check=False).returncode == 0:
            log('%s construite' % image)


def up_each(instances):
    """Starts the demos one by one and removes the removed ones. True if all started."""
    failed = []
    for inst in instances:
        ident = inst['id']
        if compose('up', '-d', '--quiet-pull', ident + '-db', ident + '-backend', ident + '-webapp',
                   check=False).returncode != 0:
            failed.append(ident)
    wanted = set(i['id'] for i in instances)
    listed = run(['docker', 'ps', '-a', '--filter', 'label=com.docker.compose.project=' + PROJECT,
                  '--format', '{{.Label "vigilo-demo.instance"}} {{.Names}}'], check=False, quiet=True)
    for line in listed.stdout.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0] not in wanted:
            run(['docker', 'rm', '-f', parts[1]], check=False)
    ok = [i['id'] for i in instances if i['id'] not in failed]
    log('instances en service : %s ; en échec : %s' % (', '.join(ok) or 'aucune', ', '.join(failed)))
    return not failed


def scopes_of(ident):
    """(scope_name, display name) of an instance, None while its database is not ready."""
    pw = secrets_for(ident)
    result = run(['docker', 'exec', '-e', 'MYSQL_PWD=' + pw['MYSQL_PASSWORD'], 'vigilo-demo-%s-db' % ident,
                  'mariadb', '-uvigilo', 'vigilo', '-N', '-B', '-e',
                  'SELECT scope_name, scope_display_name FROM obs_scopes ORDER BY scope_id'],
                 check=False, quiet=True)
    if result.returncode != 0:
        return None
    return [tuple((line.split('\t') + [''])[:2]) for line in result.stdout.splitlines() if line.strip()]


def update_conf(instances):
    """citylist.json (scopes of the instance) and categorielist.json of each demo."""
    with open(os.path.join(DEMO_DIR, 'conf', 'categorielist.json')) as f:
        categories = f.read()
    for inst in instances:
        ident = inst['id']
        conf = os.path.join(instance_dir(ident), 'conf')
        os.makedirs(conf, exist_ok=True)
        write_if_changed(os.path.join(conf, 'categorielist.json'), categories)
        citylist_path = os.path.join(conf, 'citylist.json')
        scopes = scopes_of(ident)
        if scopes is None:
            if not os.path.exists(citylist_path):
                write_if_changed(citylist_path, '{}\n')
            continue
        citylist = {}
        for scope, display in scopes:
            name = display.strip() or scope
            if name in citylist:
                name = '%s (%s)' % (name, scope)
            citylist[name] = {'api_path': 'https://%s.%s' % (ident, DEMO_DOMAIN), 'scope': scope,
                              'prod': True, 'country': 'France'}
        if write_if_changed(citylist_path, json.dumps(citylist, ensure_ascii=False, indent=2) + '\n'):
            log('%s : territoires %s' % (ident, ', '.join(sorted(citylist)) or 'aucun'))


def sync(state):
    """One pass. state: dict kept between passes (last pull)."""
    if DEMO_GIT_PULL:
        try:
            if git_update() and state.get('script') != script_hash():
                log('nouvelle version du contrôleur : redémarrage')
                os.execv(sys.executable, [sys.executable] + sys.argv)
        except RuntimeError:
            log('dépôt non mis à jour, on continue avec la version actuelle')
    try:
        instances = load_instances()
    except (ValueError, OSError, yaml.YAMLError) as e:
        log('instances.yml invalide, rien n\'est changé :\n%s' % e)
        return
    os.makedirs(STATE, exist_ok=True)
    for inst in instances:
        os.makedirs(os.path.join(instance_dir(inst['id']), 'conf'), exist_ok=True)
    update_conf(instances)
    content = '# Generated by controller/vigilo-demo.py from instances.yml: do not edit\n' + \
        yaml.safe_dump(compose_for(instances), sort_keys=False, allow_unicode=True)
    changed = write_if_changed(COMPOSE_FILE, content)
    pull = time.time() - state.get('pulled', 0) > PULL_INTERVAL
    if pull:
        log('mise à jour des images')
        compose('pull', '--quiet', '--ignore-pull-failures', check=False)
        state['pulled'] = time.time()
    ensure_webapp_images(instances, pull)
    if changed or pull or not state.get('up'):
        ids = ', '.join(i['id'] for i in instances) or 'aucune'
        if compose('up', '-d', '--remove-orphans', '--quiet-pull', check=False).returncode == 0:
            log('instances en service : ' + ids)
            state['up'] = True
        else:
            # One broken demo (missing image...) must not stop the others
            state['up'] = up_each(instances)
        if pull:
            run(['docker', 'image', 'prune', '-f'], check=False, quiet=True)
        update_conf(instances)


def script_hash():
    with open(os.path.abspath(__file__), 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else 'loop'
    if command == 'check':
        try:
            instances = load_instances()
        except (ValueError, yaml.YAMLError) as e:
            print(e)
            sys.exit(1)
        print('%d instance(s) : %s' % (len(instances), ', '.join(i['id'] for i in instances)))
    elif command == 'render':
        print(yaml.safe_dump(compose_for(load_instances(), with_secrets=False), sort_keys=False, allow_unicode=True))
    elif command in ('sync', 'loop'):
        if not re.match(r'^[A-Za-z0-9]{12,64}$', re.sub(r'[\s-]', '', SETUP_CODE)):
            log('VIGILO_SETUP_CODE manquant ou trop court (12 lettres ou chiffres au moins) : arrêt')
            sys.exit(1)
        state = {'script': script_hash()}
        while True:
            try:
                sync(state)
            except Exception as e:  # keep the farm running
                log('erreur : %r' % e)
            if command == 'sync':
                break
            time.sleep(SYNC_INTERVAL)
    else:
        print(__doc__)
        sys.exit(2)


if __name__ == '__main__':
    main()
