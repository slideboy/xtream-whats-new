# Xtream What's New

[English](README.md)

Xtream What's New est une application Docker légère qui surveille un catalogue VOD et Séries compatible Xtream et affiche ce qui a changé depuis les scans précédents.

## Points forts

- 🎬 Détecte les nouveaux films, séries et épisodes, ainsi que les suppressions du catalogue et autres changements.
- 🌍 Filtre la surveillance par pays et par catégories fournisseur.
- 🌓 Thèmes clair et sombre avec mémorisation du choix dans le navigateur.
- 📧 Récapitulatifs email configurables pour les films, séries, épisodes, catégories et suppressions.
- ⚠️ Alertes email immédiates en cas d'échec de scan ou de sauvegarde.
- 🔄 Fréquence des scans automatiques configurable directement depuis l'interface web.
- 💾 Sauvegardes SQLite planifiées intégrées avec rétention configurable.
- 🔎 Historique consultable et recherchable sur Aujourd'hui, 7 jours ou 30 jours.
- 🧹 Nettoie à l'affichage les préfixes fournisseur tels que `|FR|` sans modifier les données originales stockées.
- 🐳 Conçu pour un auto-hébergement simple avec Docker Compose et les images GHCR.

![Tableau de bord Xtream What's New](docs/images/dashboard.png)


Elle ne lit ni ne retransmet les flux : elle surveille uniquement les métadonnées du catalogue exposées par l'API du fournisseur.

## Fonctionnalités

- Découverte automatique des catégories VOD et Séries du fournisseur.
- Détection des pays/zones à partir des noms de catégories et des drapeaux.
- Sélection du suivi par pays et par catégorie.
- Détection des nouveaux films, nouvelles séries et nouveaux épisodes.
- Détection des ajouts, suppressions et renommages de catégories, ainsi que des suppressions de contenus confirmées.
- Création sûre d'une référence lors de l'activation d'une catégorie.
- Historique Aujourd'hui, 7 jours et 30 jours avec rétention des événements pendant 45 jours.
- Périodicité de scan configurable et scan manuel.
- Sauvegardes SQLite intégrées avec planification, rotation et sauvegarde manuelle.
- Notifications email SMTP immédiates ou regroupées en récapitulatifs périodiques.
- Interface et emails en français ou en anglais.
- Identifiants fournisseur et SMTP conservés hors de SQLite.

## Installation rapide — Dockhand / Portainer / stack Compose

C'est la méthode d'installation recommandée.

L'image Docker publiée contient déjà l'application :

```text
ghcr.io/slideboy/xtream-whats-new:latest
```

Il n'est **pas nécessaire** de télécharger `watcher.py`, de créer manuellement un dossier pour l'application ou de créer `config.json`.

Dans Dockhand ou Portainer, créez une nouvelle Stack et collez le Compose suivant :

```yaml
services:
  xtream-whats-new:
    image: ghcr.io/slideboy/xtream-whats-new:latest
    container_name: xtream-whats-new
    restart: unless-stopped

    ports:
      - "${XTREAM_WHATS_NEW_PORT:-36401}:36401"

    environment:
      XTREAM_PROVIDER_URL: "${XTREAM_PROVIDER_URL}"
      XTREAM_USERNAME: "${XTREAM_USERNAME}"
      XTREAM_PASSWORD: "${XTREAM_PASSWORD}"
      SMTP_USERNAME: "${SMTP_USERNAME:-}"
      SMTP_PASSWORD: "${SMTP_PASSWORD:-}"
      TZ: "${TZ:-Europe/Paris}"

    volumes:
      - xtream-whats-new-data:/data

    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:36401/', timeout=5)"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 30s

volumes:
  xtream-whats-new-data:
    name: xtream-whats-new-data
```

### Variables d'environnement

Avant de déployer la Stack, renseignez dans Dockhand ou Portainer les variables d'environnement suivantes :

```env
XTREAM_PROVIDER_URL=https://votre-fournisseur.example
XTREAM_USERNAME=votre_identifiant
XTREAM_PASSWORD=votre_mot_de_passe
```

Variables facultatives :

```env
XTREAM_WHATS_NEW_PORT=36401
TZ=Europe/Paris
SMTP_USERNAME=
SMTP_PASSWORD=
```

`XTREAM_PROVIDER_URL`, `XTREAM_USERNAME` et `XTREAM_PASSWORD` sont obligatoires.

`XTREAM_WHATS_NEW_PORT` est facultatif. S'il n'est pas renseigné, l'application est accessible sur le port `36401`.

`TZ` est facultatif et utilise `Europe/Paris` par défaut.

`SMTP_USERNAME` et `SMTP_PASSWORD` sont uniquement nécessaires si vous souhaitez utiliser les notifications email avec authentification SMTP.

Avec les variables d'environnement de Dockhand ou Portainer, **aucun fichier `.env` local n'est nécessaire**.

Déployez ensuite la Stack puis ouvrez :

```text
http://IP-DE-VOTRE-SERVEUR:36401
```

Si vous avez modifié `XTREAM_WHATS_NEW_PORT`, utilisez le port choisi.

Par exemple, avec :

```env
XTREAM_WHATS_NEW_PORT=36402
```

ouvrez :

```text
http://IP-DE-VOTRE-SERVEUR:36402
```

Au premier démarrage, le conteneur crée automatiquement `/data/config.json` ainsi que la base SQLite dans le volume Docker persistant `xtream-whats-new-data`.

## Docker Compose en ligne de commande

Si vous préférez utiliser la ligne de commande, clonez ou téléchargez le dépôt.

Créez votre fichier d'environnement local :

```bash
cp .env.example .env
```

Modifiez `.env` et renseignez les identifiants de votre fournisseur.

Démarrez ensuite l'application :

```bash
docker compose up -d
```

Consultez les logs :

```bash
docker compose logs --tail=100
```

Docker Compose lit automatiquement le fichier `.env` local.

Ne publiez et ne commitez jamais votre fichier `.env`.

Ouvrez ensuite :

```text
http://IP-DE-VOTRE-SERVEUR:36401
```

ou utilisez le port défini avec `XTREAM_WHATS_NEW_PORT`.

## Premier démarrage

Le premier scan découvre les catégories proposées par votre fournisseur.

Aucun pays ou aucune zone n'est activé par défaut sur une nouvelle installation.

Ouvrez **Paramètres**, activez le pays ou la zone souhaitée, sélectionnez les catégories Films et Séries à surveiller puis enregistrez.

Le contenu déjà présent dans le catalogue est d'abord absorbé comme référence. Seuls les ajouts ultérieurs apparaissent ensuite comme de véritables nouveautés, ce qui évite de générer des milliers de faux événements lors de l'activation initiale.

## Notifications email

Le nom d'utilisateur et le mot de passe SMTP sont fournis uniquement via les variables d'environnement :

```env
SMTP_USERNAME=votre-utilisateur-smtp
SMTP_PASSWORD=votre-mot-de-passe-application
```

Le serveur SMTP, le port, STARTTLS/SSL, l'expéditeur, les destinataires, la fréquence des récapitulatifs et les types de notifications se règlent depuis l'interface web.

Après modification des variables d'environnement de la Stack, recréez ou redéployez le conteneur afin que les nouvelles valeurs soient prises en compte.

## Données persistantes

Les données persistantes de l'application sont stockées dans `/data` à l'intérieur du conteneur et sauvegardées dans le volume Docker nommé :

```text
xtream-whats-new-data
```

Il contient notamment :

- `config.json` — paramètres non sensibles de l'application, créé automatiquement au premier démarrage.
- `nouveautes.sqlite3` — base SQLite active.
- `backups/` — sauvegardes SQLite gérées par l'application.

Supprimer ou recréer le conteneur ne supprime **pas** ce volume.

En revanche, supprimer le volume Docker **efface la base de données, les paramètres, l'historique et les sauvegardes de l'application**.

Le nom interne historique `nouveautes.sqlite3` est volontairement conservé pour assurer la compatibilité.

Si vous préférez conserver les données persistantes dans un dossier visible de l'hôte, par exemple `/srv/xtream-whats-new`, vous pouvez remplacer le volume Docker nommé par un bind mount dans votre propre configuration Compose.

## Mise à jour

Avec Dockhand ou Portainer, récupérez la dernière image puis redéployez la Stack.

En ligne de commande :

```bash
docker compose pull
docker compose up -d
```

Le volume Docker persistant est conservé lors des mises à jour normales du conteneur.

## Construction locale

Si vous souhaitez construire l'image depuis les sources au lieu d'utiliser l'image publiée sur GHCR :

```bash
docker build -t xtream-whats-new:local .
```

L'image officielle est construite automatiquement depuis ce dépôt par GitHub Actions pour :

```text
linux/amd64
linux/arm64
```

## Sécurité

L'interface web ne possède actuellement aucune authentification intégrée.

Ne l'exposez **pas directement sur Internet**. Pour un accès distant, utilisez un VPN ou un reverse proxy avec authentification.

Ne publiez jamais `.env`, les bases SQLite ou les fichiers de sauvegarde.

Consultez [SECURITY.md](SECURITY.md).

## Support et contributions

Les issues et pull requests sont les bienvenues.

Ce projet communautaire est proposé selon les disponibilités. Aucun délai de support, calendrier de maintenance ou développement futur n'est garanti.

## Avertissement

Xtream What's New est un projet indépendant, sans affiliation avec Xtream Codes ou les fournisseurs IPTV.

Utilisez-le uniquement avec des services et des sources de données auxquels vous êtes autorisé à accéder.

## Licence

Licence MIT. Consultez [LICENSE](LICENSE).
