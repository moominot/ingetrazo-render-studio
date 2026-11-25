# Render Studio per a IngeTrazo

Extensió de renders fotogràfics (carpeta `render_studio/`) que fa servir el Blender d'IngeTrazo. L'altre repositori de les extensions és `moominot/ingetrazo-skp-dc-import` (Render Studio Library, components dinàmics i fitxers .skp).

## Com treballar amb l'usuari

- Escriu en **català**; respon sempre en català.
- Sovint no és davant l'ordinador: **ensenya captures** del que fas i digues si són de dins o de fora del programa.
- Digues clarament què **no** has comprovat.
- **No treguis botons ni funcions sense consultar-ho.**
- Commit, push, versions i *pull requests* cap a altres repositoris: només quan ho demani (en una sessió al núvol, la feina va a la branca de la sessió).
- El repositori és **públic**: cap dada personal, nom de client, camí de l'ordinador ni model real de l'usuari.

## Abans de tocar res

1. Llegeix la **guia d'estil**: [docs/estil/GUIA.md](docs/estil/GUIA.md) (obligatòria per a qualsevol canvi d'interfície; no autoritza a redissenyar res que no s'hagi demanat).
2. Llegeix [docs/estat/PENDENT.md](docs/estat/PENDENT.md) i [docs/dev/NUVOL.md](docs/dev/NUVOL.md) (proves, captures i publicació).

## Proves

```bash
bash tools/run_offline_tests.sh <carpeta amb el codi d'IngeTrazo>
```

## On és cada cosa

- `render_studio/params.py`: registre únic dels ajustaments (d'aquí surten el mode expert, l'ull, el restabliment i el desat).
- `render_studio/panel.py`, `preview.py`, `widgets.py`, `icons.py`, `toolbar.py`.
- `render_studio/blender/studio_scene.py`: el que s'executa dins Blender.
- `tests/reference`: les feines de render de referència, perquè les imatges no canviïn sense voler.
- `docs/estat/pla-render-studio.md`: el pla de simplificació i les decisions preses.
