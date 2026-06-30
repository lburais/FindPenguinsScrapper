# Programme Python type Relive

Ce dossier contient `relive_like.py`, un programme Python qui transforme une trace GPS `.gpx` en video `.mp4` avec :

- une carte OpenStreetMap ;
- le trajet qui se dessine progressivement ;
- un marqueur de position ;
- les statistiques principales : distance, temps, vitesse, denivele ;
- des photos optionnelles si tu fournis un dossier d'images.

## Installation

Dans un terminal :

```bash
pip install pillow imageio imageio-ffmpeg requests
```

## Utilisation simple

```bash
python relive_like.py ma_sortie.gpx --output ma_sortie.mp4
```

## Avec photos

```bash
python relive_like.py ma_sortie.gpx --photos ./photos --output ma_sortie.mp4
```

## Options utiles

```bash
python relive_like.py ma_sortie.gpx \
  --title "Sortie velo du dimanche" \
  --duration 60 \
  --width 1920 \
  --height 1080 \
  --output sortie.mp4
```

Le programme telecharge des tuiles OpenStreetMap au premier lancement et les garde dans `.tile-cache` pour les executions suivantes.

## Limites par rapport a Relive

Ce n'est pas une copie complete de Relive : il n'y a pas de rendu 3D satellite ni de montage automatique avance. En revanche, c'est une base modifiable et locale pour produire une video de sortie GPS sans passer par une application mobile.
