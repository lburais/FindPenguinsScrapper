# FindPenguinsScrapper 🐧✈️

Un outil puissant en Python permettant d'extraire, sauvegarder et archiver localement l'intégralité des données de profils **FindPenguins** (publics ou privés). 

Ce script orchestre l'authentification, le scraping des données dynamiques (textes, météo, coordonnées, overnights) et télécharge localement l'ensemble des médias (photos et vidéos). Il génère à la fois des structures d'archivage standards (**GPX**, **XML**), un rendu visuel sous forme de **Livre de Voyage numérique (HTML)** interactif et autonome, et des sources **Markdown compatibles Pelican**.

---

## ✨ Fonctionnalités

- **Extraction Complète :** Récupération de la biographie de l'utilisateur, de la liste des voyages, des étapes (*footprints*), récits, dates, altitudes et relevés météo.
- **Double Support (Public & Privé) :** Connexion sécurisée par simulation de navigateur permettant d'accéder aux comptes privés ou brouillons.
- **Hébergement Multi-Profils :** Possibilité de scraper plusieurs comptes d'un coup avec fusion automatique des indexes.
- **Export de Données Géographiques :** 
  - Restitution d'un fichier **GPX 1.1** standardisé par voyage avec intégration des waypoints et métadonnées enrichies.
  - Enrichissement optionnel des altitudes des traces via des API topographiques externes (SRTM90m).
- **Livre Photo Numérique Automone (HTML) :**
  - Génération de pages HTML locales adoptant le style épuré et élégant des *Travel Books* imprimés de FindPenguins.
  - Intégration de cartes géographiques interactives **Leaflet** (basées sur OpenStreetMap) lisibles entièrement hors-ligne.
  - Lecteurs vidéo HTML5 natifs intégrés directement dans le fil des récits.
- **Export Pelican (Markdown) :**
  - Génération d'une page de profil, d'une page par voyage et d'un article par *footprint*.
  - Métadonnées `Title`, `Slug`, `Date`, `Category`, `Tags` et `Summary` reconnues par Pelican.
  - Liens internes Pelican (`{filename}`) entre les profils, voyages et étapes.

---

## 📂 Architecture du Projet

Le projet est structuré de manière hautement modulaire :

```text
├── findpenguins_scrapper.py # Point d'entrée CLI et orchestrateur principal
├── fp_config.py             # Configuration centrale (endpoints, headers, namespaces)
├── fp_utils.py              # Utilitaires (navigation Playwright, gestion des cookies, téléchargements)
├── fp_parsers.py            # Extraction des données et parsing DOM (BeautifulSoup)
├── fp_writers.py            # Sérialisation des sorties (génération GPX, XML et templates HTML)
├── elevation.py             # Module d'enrichissement et de lissage des altitudes topographiques
└── profiles.json            # (Optionnel) Fichier de gestion sécurisée des identifiants
```

---

## 🚀 Prérequis et Installation

### 1. Cloner le dépôt
```bash
git clone https://github.com
cd FindPenguinsScrapper
```

### 2. Installer les dépendances Python
Le script s'appuie sur plusieurs bibliothèques majeures (`requests`, `beautifulsoup4`, `playwright`, `scipy`, `numpy`) :
```bash
pip install -r requirements.txt
# Ou manuellement :
pip install requests beautifulsoup4 playwright numpy scipy
```

### 3. Initialiser Playwright
Le projet utilise un navigateur Chromium automatisé pour charger le contenu dynamique et interagir avec les menus de FindPenguins :
```bash
playwright install chromium
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

### Options Disponibles
- `-o`, `--output` : Spécifier le dossier de destination (Par défaut : `output`).
- `-t`, `--trip` : Isoler et parser uniquement un voyage spécifique via son slug d'URL.
- `--elevation` : Activer la correction et l'enrichissement des données d'altitude sur les tracés GPX.
- `--save-html` : Conserver les captures HTML brutes téléchargées à des fins de débogage.
- `--html` : Générer les pages HTML du livre de voyage.
- `--md PATH` : Générer les pages Markdown compatibles avec Pelican sous `PATH`.

Les options `--html` et `--md PATH` peuvent être utilisées séparément ou ensemble.
Sans l'une de ces options, seuls les exports GPX et XML sont générés.

---

## 💾 Structure de l'Archive Générée (`output/`)

Une fois le scraping terminé, le dossier de sortie est structuré de manière étanche et autonome :

```text
output/
├── pseudo_findpenguins/
│   ├── pseudo_findpenguins.xml # Index XML complet du profil
│   ├── index.html              # Page d'accueil du profil (Style étagère de livres)
│   ├── voyage-islande.gpx      # Fichier GPX du parcours avec waypoints enrichis
│   └── voyage-islande/         # Livre numérique dédié au voyage
│       ├── index.html          # Sommaire chronologique et carte globale du voyage
│       ├── etape_1.html        # Récit, carte Leaflet et photos de l'étape 1
│       ├── etape_2.html
│       ├── img_12345_pic.jpg   # Photos téléchargées localement
│       └── vid_67890_mov.mp4   # Vidéos téléchargées localement
└── content/
    └── pages/                  # Sources Markdown Pelican (option --md)
        └── pseudo_findpenguins/
            ├── user.md
            └── voyage-islande/
                ├── trip.md
                └── footprint_1/
                    ├── footprint.md
                    ├── img_12345_pic.jpg
                    └── vid_67890_mov.mp4
```

---

## 🔒 Sécurité & Bonnes Pratiques

- **Respect des quotas :** Le module d'élévation intègre une gestion adaptative du *Rate Limiting* (attente exponentielle en cas de code HTTP 429) pour ne pas saturer les serveurs tiers.
- **Fichier `.gitignore` :** Si vous publiez ce projet sur un dépôt public (GitHub), veillez à ajouter votre fichier `profiles.json` à votre `.gitignore` pour protéger vos identifiants FindPenguins.
