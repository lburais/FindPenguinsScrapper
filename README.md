# scrapers

Des outils Python pour archiver des profils **FindPenguins** et des listes Apple Reminders, puis générer séparément des articles reStructuredText pour Pelican.

Le scraper FindPenguins orchestre l'authentification et télécharge les données et médias. Il génère des archives **GPX**, **XML** et JSON ; `aventures2rst.py` les convertit en sources Pelican. `reminder.py` exporte une liste Apple Reminders avec la commande **rem** ; `reminders2rst.py` génère un article par rappel.

---

## ✨ Fonctionnalités

- **Extraction Complète :** Récupération de la biographie de l'utilisateur, de la liste des voyages, des étapes (*footprints*), récits, dates, altitudes et relevés météo.
- **Authentification :** Session HTTP pour la connexion, puis Chromium piloté par Playwright avec les cookies de cette session pour lire les pages dynamiques.
- **Hébergement Multi-Profils :** Possibilité de scraper plusieurs comptes d'un coup avec fusion automatique des indexes.
- **Export de Données Géographiques :** 
  - Restitution d'un fichier **GPX 1.1** standardisé par voyage avec intégration des waypoints et métadonnées enrichies.
  - Enrichissement optionnel des altitudes des traces via des API topographiques externes (SRTM90m).
- **Export Pelican (reStructuredText) :**
  - Génération d'un fichier `trip.rst` par voyage et d'un `footprint.rst` par étape. Il n'y a pas de page RST de profil.
  - Chaque voyage peut inclure une carte de route PNG. Le fond est transparent par défaut; les fonds `satellite` et `street` sont sélectionnables. Les bulles numérotées des étapes sont optionnelles.
  - Métadonnées Pelican en champ reStructuredText, avec une image de la carte du pays enregistrée dans le dossier de chaque *footprint* géolocalisé.
  - Les métadonnées des voyages alimentent l'index généré par le site Pelican; les sources contiennent les photos, vidéos, cartes et références des étapes.

---

## 📂 Architecture du Projet

Le projet est structuré de manière hautement modulaire :

```text
├── scrapers.py              # Point d'entrée CLI et sélection du programme
├── findpenguins.py          # Orchestrateur FindPenguins
├── aventures2rst.py         # Conversion des archives FindPenguins en articles Pelican
├── reminder.py              # Export Apple Reminders via rem
├── reminders2rst.py         # Conversion des rappels en articles Pelican
├── output_safety.py         # Garde-fous pour --force et les composants de chemin
├── build_scrapers.sh        # Construction de l'exécutable PyApp
├── docs/                    # Documentation technique (dont api-reference.md)
├── findpenguins_archive.py  # Écriture des manifestes JSON portables
├── findpenguins_config.py   # Endpoints et en-têtes HTTP FindPenguins
├── findpenguins_utils.py    # Navigation Playwright, cookies et téléchargements
├── findpenguins_parsers.py  # Extraction des données et parsing DOM
├── findpenguins_writers.py  # Génération GPX, XML et cartes de route
├── findpenguins_elevation.py # Enrichissement topographique des traces GPX
├── aventures_archive.py    # Lecture des manifestes pour la conversion
├── aventures_writers.py    # Génération des articles Pelican et cartes de pays
├── common_config.py        # Espaces de noms XML partagés
├── common_utils.py         # Utilitaires XML, texte et images partagés
└── profiles.json            # Profils, identifiants et réglages
```

La documentation technique complémentaire se trouve dans [`docs/`](docs/), notamment la
[référence de toutes les fonctions](docs/api-reference.md).

---

## 🚀 Prérequis et Installation

Python 3.10 ou plus récent est nécessaire. Pour installer depuis le dépôt :

```bash
git clone https://github.com/lburais/scrapers.git
cd scrapers
python3 -m venv venv
source venv/bin/activate
python -m pip install -e .
```

Les dépendances sont déclarées dans `pyproject.toml` ; `pip install -r requirements.txt`
installe également le projet en mode éditable. L'installation fournit la seule commande
`scrapers`, avec les sous-commandes `findpenguins`, `aventures2rst`, `reminder`
et `reminders2rst`. On peut aussi utiliser `python -m scrapers` ou, depuis le
dépôt, `python scrapers.py`. Sans sous-commande, l'aide est affichée.

Après publication sur PyPI sous un nom disponible, l'installation pourra aussi
se faire avec `python -m pip install <nom-de-distribution>`.

### Initialiser Playwright
Le projet utilise un navigateur Chromium automatisé pour charger le contenu dynamique et interagir avec les menus de FindPenguins :
```bash
python -m playwright install chromium
```

Pour les rappels, installer [rem](https://github.com/BRO3886/rem) et autoriser
l'accès à Reminders dans les réglages macOS. Les commandes de conversion n'ont
pas besoin d'accéder aux comptes sources.

### Construire et distribuer

Construire le wheel et l'archive source, puis vérifier leur contenu avant publication :

```bash
python -m pip install build twine
python -m build
python -m twine check dist/*
```

Le nom de distribution est `scrapers`, déjà utilisé par un autre projet sur PyPI :
choisir un nom disponible et modifier `project.name` avant publication. Aucun identifiant, fichier
de profils ni archive de données n'est inclus dans les distributions.

Pour tester le wheel construit depuis le dépôt :

```bash
SCRAPERS_TEST_WHEEL="$(pwd)/dist/scrapers-0.1.0-py3-none-any.whl" \
SCRAPERS_TEST_SDIST="$(pwd)/dist/scrapers-0.1.0.tar.gz" \
python -m unittest discover -s tests -v
```

Adapter les noms des fichiers à la version construite. Les tests installent le wheel
et ses dépendances dans un environnement temporaire et lancent les commandes hors
du dépôt ; cette installation nécessite un accès aux paquets.

### Exécutable PyApp

[PyApp](https://ofek.dev/pyapp/latest/) produit un exécutable unique. Avec
Rust/Cargo installé, construire le wheel comme ci-dessus, puis télécharger et
décompresser les sources PyApp selon son [guide](https://ofek.dev/pyapp/latest/how-to/).
Depuis le dossier des sources PyApp, exécuter le script du dépôt en remplaçant le
chemin du script et, si nécessaire, celui du wheel :

```bash
/chemin/vers/scrapers/build_scrapers.sh /chemin/absolu/scrapers-0.1.0-py3-none-any.whl
./executables/scrapers --help
```

Cet exemple et le script concernent macOS/Linux ; Windows produit `pyapp.exe`.
Le wheel est intégré à l'exécutable, mais PyApp télécharge Python et installe les
dépendances au premier lancement : une connexion réseau est donc nécessaire.
Pour préparer Chromium dans l'environnement PyApp avant une collecte :

```bash
./executables/scrapers self python -m playwright install chromium
```

`rem` et l'autorisation macOS restent nécessaires pour les rappels. Les chemins
par défaut des archives et articles sont relatifs au dossier courant, pas à
l'emplacement de l'exécutable.

---

## ⚙️ Utilisation

```bash
scrapers findpenguins profiles.json [--output DIR] [-t SLUG] [--force] [--skip]
scrapers aventures2rst --output DIR [--content DIR] [-t SLUG]
```

- `profiles.json` : fichier de profils (obligatoire).
- `--output` : archive JSON, XML, GPX et médias (défaut `output` pour les deux programmes).
- `--content` : destination des articles Pelican du convertisseur (défaut `../website/content/articles/findpenguins`).
- `-t`, `--trip` : ne scraper que le voyage portant ce slug (défaut : tous).
- `--force` : vider `--output` avant de scraper (avec `--trip`, seul ce voyage est supprimé). Les articles Pelican ne sont pas supprimés.
- Les pages HTML et les données des menus d'étape sont toujours conservées pour permettre leur réutilisation avec `--skip`.
- `--skip` : utiliser les pages HTML précédemment enregistrées sans les recharger ; désactive `--force` s'il est aussi fourni.

Exécutez une première collecte, puis relancez avec `--skip` pour réutiliser
les pages du profil, du voyage, des étapes et des statistiques. Une page manquante
arrête l'exécution avec une erreur, sans téléchargement de remplacement. Les
données des menus d'étape sont également sauvegardées ; pour les anciennes
captures sans ces données, un avertissement est affiché et les champs
correspondants restent vides. Les anciens noms de fichiers HTML restent utilisables.
Cette option ne rend pas le traitement entièrement hors ligne : les médias
manquants, les cartes et les données d'altitude peuvent encore nécessiter le
réseau. Le GPX existant est réutilisé au lieu de retélécharger le parcours.

Les nouveaux manifestes `profile.json` et `trip.json` conservent les champs nécessaires
à la conversion, avec des chemins de médias relatifs à l'archive. Les anciennes archives
XML/GPX ne contiennent pas toutes ces données : rescraper (ou utiliser `--skip` avec
des captures existantes) pour créer les manifestes. Le convertisseur ne nettoie pas
les anciens articles ; retirer séparément les articles périmés si nécessaire.

### Apple Reminders

```bash
scrapers reminder --list "Ma liste" --output reminders-output [--all] [--force]
scrapers reminders2rst --output reminders-output [--content ../website/content/articles/reminders]
```

**État actuel :** `reminder.py` prépare le dossier de sortie (avec `--force`, il est
supprimé après validation de sécurité) puis **affiche** la commande
`rem export --list "…" --format json --incomplete > <dossier>/reminders.json` à exécuter
dans un terminal ; l'appel direct à `rem` est désactivé (commenté) dans `export_reminders`,
et `--all` n'a donc pas encore d'effet. `reminders2rst.py` lit ensuite `reminders.json`.
Une fois l'appel direct réactivé, sans `--all` seuls les rappels incomplets seront exportés.
Chaque rappel donne un
article à nom stable avec `Category: reminder` ; les notes sont rendues en texte
littéral. La conversion ne supprime pas les articles devenus périmés.
L'export utilise `rem export` ; macOS peut demander l'autorisation d'accès aux
rappels via la fenêtre de confidentialité système.

### Fichier de profils
```json
{
  "settings": {
    "map_background": "satellite"
  },
  "MonVoyageur": {
    "id": "pseudo_findpenguins",
    "username": "votre_email@exemple.com",
    "password": "votre_mot_de_passe"
  }
}
```
Toutes les entrées autres que `settings` sont des profils, tous scrapés à chaque exécution. L'entrée `settings` est facultative :

| Réglage | Défaut | Rôle |
|---|---|---|
| `small_size` | `128` | Côté maximal (px) des photos de profil / compagnons (remplacent l'original). |
| `large_size` | `1600` | Côté maximal (px) des cartes, de la couverture et des photos `_thumb`. |
| `map_background` | `transparent` | Fond de `map_trip.webp` : `transparent`, `satellite` ou `street` (Esri). |
| `footprint_bubbles` | `false` | Bulles numérotées des étapes sur `map_trip.webp`. |

---

## 💾 Structure générée

Archive (`--output`) :

```text
output/
├── flags/                    # Drapeaux WebP partagés entre tous les profils et voyages
└── pseudo_findpenguins/
    ├── pseudo_findpenguins.xml # Index XML complet du profil
    ├── profile.json           # Données de profil et tailles d'image
    ├── voyage-islande.gpx      # Parcours avec waypoints enrichis
    └── voyage-islande/         # Médias du voyage (images en WebP sans perte)
        ├── trip.json           # Voyage et étapes pour aventures2rst
        ├── map_trip.webp
        ├── satellite_trip.webp  # Carte satellite avec étapes numérotées
        ├── cover_trip.webp
        ├── *.webp              # Photos et images des compagnons
        └── *.mp4
```

Articles Pelican (`--content`) :

```text
content/
├── flags/                    # Copie partagée pour le site Pelican
└── pseudo_findpenguins/
    └── voyage-islande/
        ├── trip.rst            # Article du voyage (Category: findpenguins, Date/EndDate)
        ├── cover_trip.webp      # Couverture (taille `large_size`)
        ├── map_trip.webp
        ├── satellite_trip.webp
        └── footprint_1/
            ├── footprint.rst   # Article de l'étape (Category: titre du voyage)
            ├── map_country.webp
            └── *.webp, *.mp4
```

Le voyage porte les métadonnées `Date` (première étape), `EndDate` (dernière étape plus ses nuits), `Transport` (ex. `bus 682 km; flight 581 km`) et `Category: findpenguins`; ses tags sont `findpenguins`, `trip` et les pays. Les étapes ont le tag `footprint`. Toutes les images (photos, couvertures, avatars, cartes) sont converties en WebP sans perte; les vidéos sont conservées telles quelles.

Les drapeaux proviennent des URL d'images FindPenguins, y compris les subdivisions.
Chaque URL est téléchargée une seule fois dans `output/flags/`, puis copiée dans
`--content/flags/`. Les champs `CountryFlags` et `Flag` référencent `flags/...`;
le site publie ces images à la racine `flags/`. En cas d'échec, un avertissement
est affiché et le nom du pays reste visible sans image. Rescraper les anciens
voyages pour remplacer leurs emojis par ces fichiers.

Les articles conservent l'image originale et ajoutent des variantes redimensionnées (jamais agrandies), référencées par les métadonnées :

| Image | Variantes créées | Utilisée dans le RST |
|---|---|---|
| Photo de profil / compagnon | aucune (taille `small_size` à la place de l'original) | `Companions` (photo du profil, partagée par tous les voyages) |
| Couverture du voyage | aucune (`cover_trip.webp` en taille `large_size`) | `TripImage` |
| Cartes du voyage et du pays | aucune (`map_trip.webp`, `satellite_trip.webp`, `map_country.webp` en taille `large_size`) | `TripMap`, `TripSatelliteMap`, `map_country.webp` (thème) |
| Photo d'étape | `_thumb` (taille `large_size`) | `Photo` (original, « Ouvrir la photo »); le thème déduit `_thumb` du nom (vignettes et carrousel) |

Les cartes de route mesurent 1200×800 pixels. `satellite_trip.webp` utilise toujours
un fond satellite Esri et des bulles numérotées pour les étapes ; elle nécessite
un accès réseau. En cas d'échec, la carte principale reste disponible. Un voyage
sans trace GPX valide n'a pas de carte de route.

---

## 🔒 Sécurité & Bonnes Pratiques

- **Respect des quotas :** Le module d'élévation intègre une gestion adaptative du *Rate Limiting* (attente exponentielle en cas de code HTTP 429) pour ne pas saturer les serveurs tiers.
- **Fichier `.gitignore` :** Si vous publiez ce projet sur un dépôt public (GitHub), veillez à ajouter votre fichier `profiles.json` à votre `.gitignore` pour protéger vos identifiants FindPenguins.
