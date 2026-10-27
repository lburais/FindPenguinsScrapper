# FindPenguinsScrapper 🐧✈️

Un outil puissant en Python permettant d'extraire, sauvegarder et archiver localement l'intégralité des données de profils **FindPenguins** (publics ou privés). 

Ce script orchestre l'authentification, le scraping des données dynamiques (textes, météo, coordonnées, nuits) et télécharge les médias (photos, vidéos et pièces jointes). Il génère des archives **GPX** et **XML**, un **livre de voyage HTML** et des sources **reStructuredText compatibles Pelican**.

---

## ✨ Fonctionnalités

- **Extraction Complète :** Récupération de la biographie de l'utilisateur, de la liste des voyages, des étapes (*footprints*), récits, dates, altitudes et relevés météo.
- **Authentification :** Session HTTP pour la connexion, puis Chromium piloté par Playwright avec les cookies de cette session pour lire les pages dynamiques.
- **Hébergement Multi-Profils :** Possibilité de scraper plusieurs comptes d'un coup avec fusion automatique des indexes.
- **Export de Données Géographiques :** 
  - Restitution d'un fichier **GPX 1.1** standardisé par voyage avec intégration des waypoints et métadonnées enrichies.
  - Enrichissement optionnel des altitudes des traces via des API topographiques externes (SRTM90m).
- **Livre de voyage HTML :**
  - Génération d'une page d'index par profil, d'un index global lorsque plusieurs profils sont exportés, d'un index par voyage et d'une page par étape.
  - Cartes interactives Leaflet avec fonds OpenStreetMap. Les bibliothèques et tuiles cartographiques nécessitent une connexion réseau.
  - Photos téléchargées localement dans les pages d'étapes.
- **Export Pelican (reStructuredText) :**
  - Génération d'un fichier `trip.rst` par voyage et d'un `footprint.rst` par étape. Il n'y a pas de page RST de profil.
  - Chaque voyage peut inclure une carte de route PNG. Le fond est transparent par défaut; les fonds `satellite` et `street` sont sélectionnables. Les bulles numérotées des étapes sont optionnelles.
  - Métadonnées Pelican en champ reStructuredText, avec une image de la carte du pays enregistrée dans le dossier de chaque *footprint* géolocalisé.
  - Les métadonnées des voyages alimentent l'index généré par le site Pelican; les sources contiennent les photos, vidéos, cartes et références des étapes.

---

## 📂 Architecture du Projet

Le projet est structuré de manière hautement modulaire :

```text
├── findpenguins_scrapper.py # Point d'entrée CLI et orchestrateur principal
├── fp_config.py             # Configuration centrale (endpoints, headers, namespaces)
├── fp_utils.py              # Utilitaires (navigation Playwright, gestion des cookies, téléchargements)
├── fp_parsers.py            # Extraction des données et parsing DOM (BeautifulSoup)
├── fp_writers.py            # Sérialisation des sorties (génération GPX, XML et templates HTML)
├── fp_elevation.py          # Enrichissement topographique des points de trace GPX
└── profiles.json            # (Optionnel) Fichier de gestion sécurisée des identifiants
```

La documentation technique complémentaire se trouve dans [`docs/`](docs/).

---

## 🚀 Prérequis et Installation

### 1. Cloner le dépôt
```bash
git clone https://github.com/lburais/FindPenguinsParser.git
cd FindPenguinsParser
```

```bash
rm -rf venv
python3 -m venv venv
source venv/bin/activate

````

### 2. Installer les dépendances Python
Le script s'appuie sur plusieurs bibliothèques majeures (`requests`, `beautifulsoup4`, `playwright`, `scipy`, `numpy`, `geopandas`, `matplotlib`, `shapely`) :
```bash
python -m pip install -r requirements.txt
# Ou manuellement :
pip install requests beautifulsoup4 playwright numpy scipy geopandas matplotlib shapely
```

### 3. Initialiser Playwright
Le projet utilise un navigateur Chromium automatisé pour charger le contenu dynamique et interagir avec les menus de FindPenguins :
```bash
python -m playwright install chromium
```

---

## ⚙️ Utilisation

Le script s'exécute en ligne de commande (CLI) et propose plusieurs arguments de configuration :

### Méthode Directe (En passant les identifiants)
```bash
python findpenguins_scrapper.py --profile <ID_PROFIL> <EMAIL_CONNEXION> <MOT_DE_PASSE>
```

### Méthode Sécurisée (Via le fichier `profiles.json`)
Vous pouvez créer un fichier `profiles.json` à la racine pour stocker de manière hermétique vos profils :
```json
{
  "MonVoyageur": {
    "id": "pseudo_findpenguins",
    "username": "votre_email@exemple.com",
    "password": "votre_mot_de_passe"
  }
}
```
Lancez ensuite simplement l'extraction par le nom du profil :
```bash
python findpenguins_scrapper.py --profile-name MonVoyageur
```

`--profile` peut être répété pour fournir plusieurs triplets ID/identifiant/mot de passe. `--profile-name` peut être répété pour choisir plusieurs entrées du fichier d'identifiants. Sans l'un ou l'autre, l'outil propose une sélection interactive de tous les profils de ce fichier. `--credentials PATH` permet de choisir ce fichier; par défaut, `profiles.json` est recherché à côté du script.

Options de carte des voyages :

```bash
python findpenguins_scrapper.py --profile-name MonVoyageur --trip-map-background satellite --trip-map-footprint-bubbles
```

### Options Disponibles
- `--profile ID USERNAME PASSWORD` : Profil à scraper; répétable.
- `--profile-name NAME` : Nom d'un profil enregistré dans les identifiants; répétable.
- `--credentials PATH` : Fichier JSON d'identifiants (par défaut `profiles.json` près du script).
- `-o`, `--output` : Dossier de destination des fichiers XML, GPX et médias (par défaut `output`).
- `-t`, `--trip` : Isoler et parser uniquement un voyage spécifique via son slug d'URL.
- `--no-elevation` : Désactiver l'enrichissement des altitudes des points de trace GPX (activé par défaut).
- `--save-html` : Conserver les captures HTML brutes téléchargées à des fins de débogage.
- `--trip-map-background` : Fond de carte PNG (`transparent`, `satellite` ou `street`; transparent par défaut).
- `--trip-map-footprint-bubbles` : Afficher les bulles numérotées des étapes sur la carte.
- `--html PATH` : Générer le livre de voyage HTML sous ce dossier.
- `--rst PATH` : Générer les pages reStructuredText compatibles avec Pelican sous `PATH`.

Les options `--html PATH` et `--rst PATH` peuvent être utilisées séparément ou ensemble. Les cartes de route des sources RST sont générées lors du scraping et copiées avec `--rst`; les fonds satellite et rue nécessitent un accès au service cartographique Esri.
Sans l'une de ces options, seuls les exports GPX et XML sont générés.

---

## 💾 Structure de l'Archive Générée (`output/`)

Une fois le scraping terminé, le dossier d'archive regroupe les données et médias téléchargés :

```text
output/                         # Sources (option --output) 
└── pseudo_findpenguins/
    ├── pseudo_findpenguins.xml # Index XML complet du profil
    ├── voyage-islande.gpx      # Fichier GPX du parcours avec waypoints enrichis
    └── voyage-islande/         # Médias du voyage
        ├── map_trip.png        # Carte de route si une trace GPX valide existe
        ├── cover_*.jpg         # Image de couverture si elle existe
        ├── *.jpg               # Photos et images des compagnons
        └── *.mp4               # Vidéos téléchargées localement
```

Cette arborescence décrit l'archive GPX/XML et ses médias. Elle n'inclut pas les pages HTML
optionnelles, sauf si `--html` pointe explicitement vers `--output`.

Les pages HTML générées par `--html PATH` sont écrites séparément sous `PATH` :

```text
PATH/
└── pseudo_findpenguins/
    ├── index.html              # Index du profil
    └── voyage-islande/
        ├── index.html          # Index du voyage et carte
        ├── etape_1.html        # Une page par étape
        └── etape_2.html
```

Les sources Pelican générées par `--rst PATH` sont également séparées :

```text
PATH/
└── pseudo_findpenguins/
    └── voyage-islande/
        ├── trip.rst
        ├── map_trip.png
        └── footprint_1/
            ├── footprint.rst
            ├── map_country.png
            ├── photo_12345.jpg
            └── video_67890.mp4
```

Les médias de l'archive sont stockés sous `--output`; les exportateurs HTML et Pelican les copient ou les référencent dans leurs structures de sortie respectives.

Les cartes de route mesurent 1200×800 pixels et tracent la route en blanc (trait de 4 px). Un voyage sans trace GPX valide n'a pas de carte de route. Les images de fond `satellite` et `street` proviennent du service d'export cartographique Esri.

---

## 🔒 Sécurité & Bonnes Pratiques

- **Respect des quotas :** Le module d'élévation intègre une gestion adaptative du *Rate Limiting* (attente exponentielle en cas de code HTTP 429) pour ne pas saturer les serveurs tiers.
- **Fichier `.gitignore` :** Si vous publiez ce projet sur un dépôt public (GitHub), veillez à ajouter votre fichier `profiles.json` à votre `.gitignore` pour protéger vos identifiants FindPenguins.
