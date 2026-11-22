# Pla de millora de la previsualització en directe

Estat: **esborrany per decidir**. Només és un pla: no s'ha canviat cap codi funcional.
Base: `render_studio` 0.26.0 (commit `0ce1039`). Fitxers mirats: `live.py`, `preview.py`, `fast_export.py`,
`proxies.py`, `panel.py` (`live_key`, `live_job`, `write_studio_job`) i `blender/studio_scene.py`
(`build`, `update`, `serve`, `measure_exposure`, `render_styled`).

## 1. Objectiu

Que la vista en directe respongui com un visor interactiu:

1. **Moviment fluid de la càmera.** Ara són 3–4 fotogrames per segon, i no per la mida de la imatge sinó pel cost fix d'EEVEE per
   imatge (~0,25 s, segons el README).
2. **Primera imatge ràpida en models grans.** Ara s'espera export + arrencada de Blender + importació + mesura d'exposició.
3. **Canvis (model, materials, sol) visibles sense reconstruir tota l'escena.**
4. **Sense empitjorar res del Render final.** Tot el que es proposa afecta només el mode `live`.

## 2. Què sabem i què no

### Mesurat (xifres del README, Blender 5.3, màquina de proves de l'autor)

| Pas | Temps |
|---|---|
| Primer inici de Blender | ~3 s |
| Parada de càmera → imatge ràpida | ~0,3 s |
| Canvi de look, material o model (escena en marxa) | ~0,7–1 s |
| Fotogrames mentre es mou la càmera | 3–4 per segon (~0,25 s fixos d'EEVEE) |
| Importació del model a Blender (588.000 cares) | 3,9 s (comentari de `studio_scene.py`) |
| Mesura d'exposició | ~2 s (0,2 s al camí de llums en lloc) |
| Reconstrucció d'escena sencera | "uns 9 s" (comentari de `studio_scene.py`) |
| Export del model (588.000 cares) | 26,7 s (era 33,5 s abans de `fast_export`) |

### No mesurat (ho cal saber abans de decidir)

- Quant triga el pas **Python → disc → Blender → PNG → disc → `QPixmap`** per fotograma, separat del temps d'EEVEE.
- Quant triga `panel.live_key()`, que es crida a **cada poll de 40 ms** (vegeu 3.2).
- Quant triga el depth buffer de NumPy de Croquis a 480×270 i 960×540 en models de 50k, 200k i 700k triangles.
  Es va intentar un micro-benchmark amb triangles sintètics per aquesta passada i no es va poder executar a la
  sessió; queda com a **pas 0** de la fase 1.
- Quant tarda `_pick_index(near="all")` d'IngeTrazo en un model gran (és el que alimentaria el clay).

## 3. On es perd el temps

### 3.1 Flux actual

```
obrir previsualització
 └─ live_job → write_studio_job → export glb          (secs; 27 s en 588k cares)   [fil de la UI + barra]
     └─ arrencar Blender -b                            (~3 s, ara en SEQÜÈNCIA després de l'export)
         └─ importar model + construir escena + look   (~4 s + materials)
             └─ measure_exposure (pre-render 25 %)     (~2 s)
                 └─ "INGETRAZO ready" → primera imatge
moviment: _poll cada 40 ms → _render("motion") 1/3 d'amplada, 1 mostra → PNG → QPixmap   (~3–4 fps)
repòs 250 ms: "quick" (1/2, 1 mostra) → "draft" (1, 8 mostres, amb outlines si no és gran)
canvi: reload/update → (model sense canvis: reutilitza glb) → build/update → exposició
```

### 3.2 Hipòtesis trobades llegint el codi (cal verificar amb mesures)

1. **`live_key()` a cada poll.** `LiveSession._poll` crida `_wanted_key()` → `panel.live_key()` cada 40 ms. Aquesta funció fa
   `json.dumps(settings_dict())`, `material_specs()`, `studio_lights.signature`, `section.signature` i `sun_site.site`,
   tot al fil de la UI. En un document amb molts materials pot ser mesurable i competeix amb l'arrossegament de la càmera.
   Remei probable: calcular-ho només quan canvia `scene.content_version` o un senyal del panell (*dirty flag*).
2. **Cadena PNG.** Cada fotograma s'escriu com a PNG des de Blender i es llegeix de disc a la UI. No hi ha cap ajust de compressió a
   `studio_scene.py`. Per als fotogrames de moviment es pot provar compressió 0, TGA/BMP o JPEG; només afecta `live`.
3. **Arrencada en sèrie.** Primer s'exporta el model i només després s'arrenca Blender (`LiveSession._load` crida
   `live_job` abans de `proc.start`). El protocol `serve` ja té `reload`; Blender podria arrencar i esperar mentre s'exporta,
   estalviant els ~3 s d'inici (més en un disc lent).
4. **Cost fix d'EEVEE per imatge** (~0,25 s). El README diu que és un cost fix d'EEVEE per imatge i que un moviment més suau
   demanaria un viewport interactiu, que un Blender en segon pla (`-b`) no té. Quin tros és `bpy.ops.render.render`, quin la
   preparació de l'escena i quin el context GL no està separat: P0 ho ha de mesurar. És el límit dur de 3–4 fps i la raó
   per provar un camí de moviment diferent (apartats 5 i 6).
5. **Reconstrucció completa per canvis de sol, cel o estil.** `_patch_names` només fa servir el camí ràpid per canvis de
   materials; sol, cel, llums de la pestanya Render, vidre/aigua/emissius i estils que canvien materials reconstrueixen l'escena
   (4–9 s en un model gran).
6. **Cada canvi de model reexporta tot el model** (`content_version` és global). No hi ha cap export per grup.

## 4. Propostes

Esforç en dies de feina concentrada, orientatiu. "Guany" és una hipòtesi fins que el pas 0 de cada fase la confirmi.

| ID | Proposta | Guany esperat | Esforç | Risc |
|---|---|---|---|---|
| P0 | Instrumentació (`RS_PROFILE=1`): temps per fase al log, sense canviar comportament | Base per decidir tota la resta | 0,5 d | Baix |
| P1 | `live_key` amb *dirty flag* en lloc de recalcular-lo a cada poll | Menys feina al fil de la UI durant el moviment | 0,5–1 d | Baix (cal no perdre canvis) |
| P2 | Fotogrames de moviment més barats de transportar (PNG sense compressió o format alternatiu) | Uns quants ms per fotograma | 0,5 d | Baix |
| P3 | Arrencar Blender en paral·lel a l'export (escena buida que espera `reload`) | ~3 s en la primera imatge | 1 d | Mitjà (estat inicial de `serve`, arrencada fallida) |
| P4 | **Clay NumPy en procés** per als fotogrames de moviment i la primera imatge (apartat 5) | De 3–4 fps a potencialment 10+ fps, i primera imatge sense esperar Blender | 5–8 d | Mitjà–alt |
| P5 | Alternativa a P4: motor *Workbench* de Blender als fotogrames de moviment (apartat 6) | Més fps sense codi de rasterització propi | 1–2 d de prova | Mitjà (aspecte, i no ajuda al primer arrencament) |
| P6 | Exposició automàtica més barata (apartat 7) | 1–2 s per reconstrucció | 1–2 d | Mitjà (no ha d'alterar el Render final) |
| P7 | Qualitat adaptativa i refinament progressiu (apartat 9) | Percepció de fluïdesa | 1–2 d | Baix |
| P8 | Passades auxiliars (profunditat, ID, AO) i selecció des de la vista (apartat 8) | Funcions noves | 2–4 d | Baix |
| P9 | Export per grup i importació incremental | El guany més gran en editar models grans | 10+ d | Alt |

## 5. Avaluació: clay NumPy instantani (P4)

### 5.1 Idea

Mentre la càmera es mou (i com a primera imatge abans que Blender estigui llest), el procés de l'extensió dibuixa una imatge
"clay" amb ombra directa, ombra projectada i color per cara, tot en NumPy. Quan la càmera reposa, Blender manté el paper de
sempre (quick → draft). El clay no substitueix el draft ni el Render: només cobreix el temps entre el moviment i la
imatge de Blender.

### 5.2 Peces de Croquis que es poden reutilitzar

(`github.com/vicc3d/croquis-ingetrazo`, GPL-3.0-or-later com Render Studio. Les icones i el disseny són de l'autor: demanar-ne
permís o reescriure la idea, no copiar a cegues.)

| Peça de Croquis | Fitxer | Serveix per a |
|---|---|---|
| `depth_buffer(tris, M, w, h, persp)` — rasteritzador per lots (triangles petits tots alhora, per mides 2–32 px) | `visibility.py` | z-buffer + índex de triangle per píxel |
| `clip_matrix(camera)` — `projection_matrix() * view_matrix()` d'IngeTrazo | `visibility.py` | Mateixa projecció que la vista 3D |
| `shadow_map` + `cast_shadow` + `pixel_points` (desprojecció) | `shadow.py` | Ombres amb un sol paral·lel, mapa 1024² |
| `settled` (4 punts per píxel) | `drawing.py`/`shadow.py` | Evitar moiré a les ombres |
| `from_pick_index(viewport, colour_of)` | `host.py` | Triangles + color per cara de l'índex de pick d'IngeTrazo, sense recórrer cares una a una; camí ràpid per a malles diferides |

### 5.3 Dades d'entrada que ja existeixen

- Triangles i colors per cara: `viewport._pick_index(near="all")` (API privada d'IngeTrazo, 0.5.8+).
- Sol: `core.render_blender.sun_toward(scene)` i `sun_site` de Render Studio.
- Materials de Render Studio (color, vidre, brillantor): es poden aplicar com a tint per triangle a partir de `material_specs()`.

### 5.4 Què cal construir

1. Un mòdul `clay.py` pur NumPy (testable sense Qt ni Blender), amb `render_clay(tris, colours, camera, sun, size) -> RGB`.
2. Un fil de treball (no el de la UI) que rep la càmera, genera la imatge i la mostra; descarta fotogrames vells.
3. Calibratge visual: lluminositat mitjana i exposició del clay alineades amb l'última imatge de Blender, per evitar un salt visible
   quan el draft substitueix el clay. El valor d'exposició ja s'escriu al log (`INGETRAZO exposure …`).
4. Indicador discret a la finestra ("moviment") o fosa de 100–150 ms entre el clay i la imatge de Blender.
5. Opció per desactivar-lo (`Settings ▸ Preview ▸ Fast motion preview`), activat per defecte només si el pas 0 el justifica.

### 5.5 Límits i riscos

- **No és GI.** Només ombra de sol i colors plans; no s'assembla a EEVEE ni a Cycles. Útil per orientar-se, no per jutjar l'acabat.
  Interiors i il·luminació artificial es veuran molt diferents: en aquests casos (look *Interior*, llums de la pestanya) cal desactivar-lo.
- **API privada d'IngeTrazo.** `_pick_index`, `_pick_flat` i `hlr_geometry` poden canviar. Croquis les tracta amb *fallback*
  (`from_scene`); caldria el mateix.
- **Cost d'extreure triangles.** Si `_pick_index` triga segons en un model gran, el clay es construeix un cop per versió del document
  i es cacheja; cal mesurar-ho al pas 0.
- **Memòria.** Els triangles en float64 de 700k cares són uns 50 MB; acceptable, però cal alliberar-los si el model canvia.
- **Rendiment NumPy.** La velocitat del rasteritzador de Croquis no està mesurada en aquesta sessió (només el seu README: 700.000 cares
  en ~30 s *per al croquis complet*, que inclou línies, traços i ombres, no només el depth buffer). El pas 0 ho resol.
- **Mida de buffer.** Croquis limita a 2000 px d'ample; per a moviment n'hi ha prou amb 480–640 px.
- **Transparències i vidre.** El depth buffer és opac; el vidre i l'aigua es dibuixarien com a sòlids o s'ometrien.
  Cal decidir-ho (probablement ometre-ho o aplicar un tint).
- **Proxies.** `proxies.py` deixa els reemplaçaments fora del fitxer del model; el clay hauria d'incloure els *stand-ins*
  tal com es veuen al visor 3D (és el que dóna `_pick_index`), no el model complet.

### 5.6 Criteri de decisió (go / no-go)

Després de P0 i del benchmark del rasteritzador: continuar amb P4 només si, en un model de ≥ 300k cares, el clay a 480×270
supera **8 fps sostinguts** al fil de treball sense bloquejar la UI, i la primera imatge (clay) arriba **abans de 3 s** després d'obrir.
Si no, descartar P4 i quedar-se amb P5 + P1–P3.

## 6. Alternativa: Workbench de Blender per al moviment (P5)

Canviar `scene.render.engine` a `BLENDER_WORKBENCH` només als fotogrames "motion" (i tornar a EEVEE per a "quick" i "draft").

- **Pros:** poc codi, utilitza l'escena i els colors que ja té Blender, no depèn d'API privada d'IngeTrazo.
- **Contres:** no resol l'espera de la primera imatge (Blender ha d'haver importat el model); el canvi d'engine té un cost
  propi que cal mesurar; els materials tenen `diffuse_color` només en alguns casos (`studio_scene.py:2918`, `:2948`), de manera
  que el color en Workbench potser no coincidiria amb el de l'EEVEE; si el cost fix ve de l'operador de render i no
  d'EEVEE, es manté (el README només diu que és fix per imatge).
- **Prova:** 1–2 dies amb un Blender real, mesurant ms per fotograma de cada engine a 320×180 i 640×360 en l'escena gran de proves.
  Si el temps de Workbench és molt més baix que 250 ms, és l'opció de menys risc per a P4; si no, no val la pena.

P4 i P5 no són excloents: P5 és la prova barata que decideix si P4 compensa.

## 7. Exposició automàtica sense pre-render (P6)

Ara cada `build()` fa `measure_exposure`: render petit (25 %, 8 mostres EEVEE, 16 Cycles) en EXR, mitjana logarítmica amb pes
central i percentil 97 (~2 s). Només es repeteix en canvis de llums al camí en lloc (~0,2 s).

Opcions, de menys a més ambiciosa:

1. **Memoritzar.** Clau = (versió del model, sol, cel/look, llums, esdeveniments que alterin la llum). Si només canvia un
   material que no emet ni deixa passar llum (ja ho decideix `_light_affecting`), reutilitzar l'exposició. Part d'això ja passa a
   `update`; falta fer-ho també al camí de `reload`.
2. **Mesura més barata a la vista en directe.** 25 % → 12 % i 8 → 4 mostres, i refinar en segon pla un cop mostrada la imatge.
   **No tocar** la mesura del Render final.
3. **Estimació NumPy** (llum solar directa sobre un clay) com a valor inicial, substituït per la mesura real quan arriba.
   Només té sentit si P4 es fa; cal validar que l'error d'exposició sigui < 0,3 EV en la col·lecció d'escenes de prova.

Risc comú: qualsevol canvi que mogués l'exposició del Render final queda fora d'abast (la mesura final és la que cal conservar).

## 8. Passades auxiliars i selecció des de la vista (P8)

Amb el buffer d'índex de triangle del clay (o amb una passada *Index* de Blender) hi ha tres usos pràctics:

- **Selecció al clic:** clicar a la previsualització selecciona el material o grup, i obre el selector de **Materials…**
  ("From the selection" ja existeix). És la funció d'usuari més visible d'aquesta fase.
- **AO i profunditat a l'espai de pantalla** per donar volum al clay (barat des del z-buffer).
- **Màscares** per a retoc selectiu (el retoc de la imatge final ara és global).

No requereix canvis a EEVEE ni al Render final.

## 9. Qualitat adaptativa i refinament progressiu (P7)

- **Mida de fotograma segons rendiment.** Ara la mida de moviment és una constant (`MOTION_SCALE = 1/3`, presets `fast/normal/high`).
  Un controlador senzill que ajusti l'escala per apropar-se a un temps objectiu (p. ex. 150–250 ms) fa que equips lents i ràpids
  funcionin bé sense tocar el preset.
- **Escala segons moviment.** Menys resolució mentre la càmera va ràpid, més quan va a poc a poc.
- **Descartar fotogrames vells.** `_busy` ja serialitza; amb el clay no hi ha cua i els fotogrames es descarten sols.
- **Refinament progressiu en repòs.** Després del draft (8 mostres), si la càmera continua quieta uns 2 s, un tercer pas amb més mostres
  (24–32) i *denoise* en Cycles; es cancel·la en moure's. En EEVEE el guany és limitat; en Cycles (Interior, models grans quan no es
  segueix res) és el cas útil.
- **Outlines.** Ara només al draft i només si el model no és gran, perquè Freestyle no es pot interrompre.
  Es podria afegir una versió barata amb el z-buffer del clay (vora per salt de profunditat/índex) que no depengui de Freestyle.

## 10. Ordre de treball

| Fase | Contingut | Sortida / criteri |
|---|---|---|
| 1 | P0 (instrumentació) + benchmark del rasteritzador de Croquis + prova de Workbench (P5) | Informe amb xifres reals; decisió go/no-go de P4 (5.6) |
| 2 | P1 (`live_key` amb *dirty flag*), P2 (transport de fotogrames), P3 (arrencada en paral·lel) | Menys latència sense canvis visibles; `tests/` existents en verd |
| 3 | P5 o P4 segons la fase 1; P7 (qualitat adaptativa) | Moviment mesurat contra els objectius de la secció 11 |
| 4 | P6 (exposició) | Exposició idèntica al Render final (comparar píxels en proves de Blender existents) |
| 5 | P8 (selecció des de la vista i passades) | Funcions noves, amb prova d'usuari |
| 6 (opcional) | P9 (export per grup / importació incremental) | Només si la fase 1 diu que l'export domina l'ús real |

Cada fase acaba amb tests offline nous i, si toca Blender, tests amb Blender real (com `test_*_blender.py`), i una entrada al README.

## 11. Com mesurar l'èxit

**Escenes de prova** (mateixes sempre): la de 588.000 cares del README; una de ~150.000 (just sobre `INSTANCED_FROM_FACES`); una petita
(<20.000); una amb proxies; un interior (look *Interior*, Cycles).

**Mètriques**

| Mètrica | Ara (README) | Objectiu |
|---|---|---|
| FPS sostinguts mentre es mou la càmera | 3–4 | ≥ 8 (≥ 12 al segon objectiu) |
| Latència càmera → píxel (percentil 95) | ~0,25–0,4 s | < 150 ms |
| Temps fins a la primera imatge en 588k cares | export 27 s + 3 s + ~4 s + ~2 s ≈ 36 s | < 10 s la primera imatge (clay); resta igual |
| Parada de càmera → imatge ràpida | ~0,3 s | ≤ 0,3 s (no empitjorar) |
| Canvi de material → imatge | 0,7–1 s | ≤ 0,7 s |
| Canvi de sol/cel → imatge | 4–9 s | ≤ 3 s |
| Ús de CPU al fil de la UI en moviment | no mesurat | quedar per sota del 30 % d'un nucli |
| Diferència clay vs. draft (luminància mitjana) | — | < 15 % després del calibratge |

**Com** — `RS_PROFILE=1` escriu al log `ingetrazo.plugins` una línia per fase (`export`, `blender_start`, `import`, `meter`, `frame`
amb `kind`, `ms_render`, `ms_png`, `ms_load`, `ms_poll`). Un script de banc (`tools/bench_preview.py`) mou la càmera en una
trajectòria fixa i resumeix mediana, p95 i fps. Tot s'executa abans i després de cada fase i es guarda a `docs/preview-bench.md`.

**No regressions** — Les proves existents (`tests/test_*_blender.py`, `test_preview_offline.py`) han de seguir verdes, i el Render
final ha de ser bit a bit igual (mateixa exposició, mostres i engine) en les escenes de prova.

## 12. Riscos

| Risc | Probabilitat | Mitigació |
|---|---|---|
| El clay no es veu prou com el draft i desorienta | Mitjana | Calibratge d'exposició, fosa, opció per desactivar-lo, desactivat en *Interior* |
| `_pick_index` / `hlr_geometry` canvien a IngeTrazo | Mitjana | Detecció de versió, *fallback* a recórrer l'escena, desactivar el clay si falla |
| El rasteritzador NumPy és massa lent en models grans | Mitjana | Pas 0 abans de fer res; mida de buffer menor; LOD per mida de triangle en pantalla |
| Canviar l'ordre d'arrencada (P3) deixa un Blender penjat | Baixa | Temps màxim, reinici automàtic ja existent a `_ended` |
| *Dirty flag* de `live_key` (P1) perd canvis | Mitjana | Prova que compara `live_key` complet cada N s fins que s'ha provat prou; clau de versió prudent |
| P6 canvia l'exposició del Render final | Baixa | La mesura final no es toca; comparació de píxels a les proves |
| Llicència i atribució si es copia codi o icones de Croquis | Baixa | Mateixa GPL-3.0-or-later; mantenir crèdits; reescriure en lloc de copiar quan sigui possible |
| Esforç de P9 desproporcionat | Alta | Només amb dades de la fase 1 |

## 13. Decisions que cal que prengui l'usuari

1. **Aprovar la fase 1** (instrumentació, benchmark i prova de Workbench) abans de decidir res més?
2. **Clay NumPy (P4) o Workbench (P5)** per al moviment? Recomanació: provar P5 primer perquè és barat, i fer P4 només si cal
   la primera imatge ràpida en models grans.
3. **La previsualització pot mostrar durant el moviment una imatge visualment diferent** (clay en lloc d'EEVEE)? Si no, P4 queda descartat
   i només queden P5 i les millores de transport.
4. **Objectiu real d'ús:** models grans (≥ 300k cares) o d'una mida mitjana? Canvia la prioritat entre P3/P4 (arrencada) i P7 (fluïdesa).
5. **Selecció al clic (P8):** vols aquesta funció? És la que té més valor visible per a l'usuari final.
6. **Croquis:** reescriure les tècniques amb codi propi, o demanar permís a l'autor per reutilitzar-ne codi?
7. **P9 (export per grup):** només si les mesures mostren que l'export domina; no fer-ho ara.
