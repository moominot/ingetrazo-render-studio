# Estat i feina pendent (totes les extensions)

Actualitzat el 25-11-2026. Aquest és el document **mestre**; si tanqueu o obriu alguna cosa, poseu-ho aquí al dia.

## Les extensions

| Extensió | Carpeta | Repositori | Versió publicada |
|---|---|---|---|
| Render Studio | `render_studio/` | `moominot/ingetrazo-render-studio` | 0.29.0 |
| Render Studio Library | `asset_manager/` | `moominot/ingetrazo-skp-dc-import` | 0.8.0 |
| Components dinàmics | `dc_tools/` | el mateix | 0.3.9 |
| Fitxers .skp | `skp_dc_import/` | el mateix | 0.8.1 |

Als dos repositoris, `main` és la branca bona.

## Peticions obertes (comproveu-ne l'estat abans de fer res)

- Catàleg `ingelibre/ingetrazo-extensions`: **#487** (Render Studio 0.29.0, amb captura nova), **#488** (Library 0.8.0), **#483** (dc_tools 0.3.9). Passen les proves; falta que un mantenidor les aprovi.
- IngeTrazo `ingelibre/ingetrazo`: **#1612** (Cut Opening: triar el pla enrasat amb la paret) i **#1590** (treure la marca a la secció que talla mostra el model sencer). Quan #1612 s'accepti, cal revisar `dc_tools`.
- `vicc3d/dispersa-ingetrazo` **#1** (extensió d'un altre autor): selecció ràpida en models grans.
- Ja acceptades: `ingelibre/ingetrazo` #1497 (traducció al català) i `iamahsanmehmood/openskp` #530.

## Feina que no és a `main` (branques de còpia)

Són còpies de feina de l'ordinador local, **sense revisar ni provar**. No les fusioneu senceres: trieu-ne el que calgui.

| Repositori | Branca | Què és |
|---|---|---|
| ingetrazo-render-studio | `wip/local-main-uncommitted-2026-11-25` | canvis vells sense commit sobre el `main` antic (0.28) |
| ingetrazo-render-studio | `wip/stash-grass-igmat-2026-11-25` | «igmat + densitat d'herba + readme», apartat amb `git stash` |
| ingetrazo-render-studio | `wip/bento-panel-2026-11-25` | experiment de tauler d'estil «bento» (sobre 0.26) |
| ingetrazo-render-studio | `preview-improvement-plan` | pla de millora de la vista prèvia (`docs/preview-plan.md`) |
| ingetrazo-skp-dc-import | `wip/local-dc-tools-0.3.6-uncommitted-2026-11-25` | canvis vells sense commit |
| ingetrazo-skp-dc-import | `wip/library-redesign-folder-2026-11-25` | carpeta de treball del redisseny de la Library |
| moominot/ingetrazo (*fork*) | `wip/wheel-guard-2026-11-25` | correcció del nucli perquè la roda no canviï valors (incidència #1483). Abans d'obrir cap PR, cal el vistiplau de l'usuari. Proves a mitges: les específiques passaven; no consta el resultat de la bateria sencera |
| moominot/openskp (*fork*) | `feat/instanced-definition-attribute-dictionaries` | atributs de definició a l'escena instanciada. L'usuari vol fer-ne una proposta més endavant (importar .skp sense aplanar) |

## Render Studio: pendent

Pla complet: [pla-render-studio.md](pla-render-studio.md).

- Aplicar el criteri de l'**ull i la vista bàsica** a Principal i Estil (a Entorn i Secció ja hi és).
- **Icones** davant el nom de cada grup: les targetes ja en tenen; comproveu que no en falti cap.
- Revisar les finestres de **Llums i Materials** (encara tenen desplegables «Avançat»; l'usuari no ho va voler tocar quan es van treure del tauler).
- **Fase 6**, blocs que falten: superfície d'un color i lux; gruix de la trama d'ombra, intensitat sobre color pla, aquarel·la, distància de la boirina i sol del panorama.
- El botó d'ajuda «?» de la capçalera es veu massa fluix.
- Potser reanomenar «Què renderitzar» a «Què es captura».
- El color i la trama de les **ombres** no es comporten com s'esperava: cal una imatge d'exemple abans de redissenyar-ho.
- El text llarg de l'ajuda només és en anglès, català i castellà.
- Algunes captures del `README` són antigues.
- Sense provar dins el programa: a la vista prèvia, desplaçar amb Maj i amb el botó central; a la 0.29.0 instal·lada des del `.zip`, les traduccions noves.

## Render Studio Library: pendent

- La captura del catàleg (`screenshots/asset_manager.webp`) encara mostra les cinc pestanyes antigues.
- `tests_su/test_asset_manager_library.py` falla «and the simple picture beside it» (també passava abans de la 0.8.0).
- Idea apuntada, no començada: que el *stand-in* sigui un concepte del nucli (vegeu `docs/estat/NOTES-TECNIQUES.md` del repositori de la Library).

## Components dinàmics i .skp: pendent

- `dc_tools` encara no té la protecció de la roda del ratolí.
- Els textos nous del pla de tall de `dc_tools` només són en català i castellà; traduïu-los quan #1612 s'accepti.
- De l'altre programa d'origen: importar el sol (pla acordat, no fet) i la resta de dades dels objectes de biblioteca (vegeu les notes tècniques).
- Proposta a openSKP (branca del *fork*, més amunt).

## Altres

- L'extensió temporal que instal·lava la traducció catalana ja no cal si la versió d'IngeTrazo instal·lada porta el català (#1497 acceptada).
- Congelacions amb models molt grans: vegeu les notes tècniques i `tools/gc_tune/` (repositori de la Library).
- Esborrany d'incidència no publicat sobre la triangulació de cares al nucli: només és a l'ordinador local.
