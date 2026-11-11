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
├── findpenguins.py          # CLI et orchestrateur FindPenguins
├── aventures2rst.py         # Conversion des archives FindPenguins en articles Pelican
├── reminder.py              # Export Apple Reminders via rem
├── reminders2rst.py         # Conversion des rappels en articles Pelican
├── output_safety.py         # Garde-fous pour --force et les composants de chemin
├── docs/                    # Documentation technique (dont api-reference.md)
├── fp_archive.py            # Manifestes JSON portables
├── fp_config.py             # Configuration centrale (endpoints, headers, namespaces)
├── fp_utils.py              # Utilitaires (navigation Playwright, gestion des cookies, téléchargements)
├── fp_parsers.py            # Extraction des données et parsing DOM (BeautifulSoup)
├── fp_writers.py            # Sérialisation des sorties (génération GPX, XML et articles Pelican RST)
├── fp_elevation.py          # Enrichissement topographique des points de trace GPX
└── profiles.json            # Profils, identifiants et réglages
```

La documentation technique complémentaire se trouve dans [`docs/`](docs/), notamment la
[référence de toutes les fonctions](docs/api-reference.md).

---

## 🚀 Prérequis et Installation

### 1. Cloner le dépôt
```bash
git clone https://github.com/lburais/scrapers.git
cd scrapers
```

```bash
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

Pour les rappels, installer [rem](https://github.com/BRO3886/rem) et autoriser
l'accès à Reminders dans les réglages macOS. Les commandes de conversion n'ont
pas besoin d'accéder aux comptes sources.

---

## ⚙️ Utilisation

```bash
python findpenguins.py profiles.json [--output DIR] [-t SLUG] [--force] [--skip]
python aventures2rst.py --output DIR [--content DIR] [-t SLUG]
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
python reminder.py --list "Ma liste" --output reminders-output [--all] [--force]
python reminders2rst.py --output reminders-output [--content ../website/content/articles/reminders]
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
