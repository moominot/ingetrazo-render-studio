# Pla: pestanya Entorn, pestanya Secció i caixa de secció

Escrit el 2026-11-23, després de revisar el codi (`panel.py`, `sun_panel.py`, `section_panel.py`, `section.py`, `blender/studio_scene.py`) i el
`core/section.py` d'IngeTrazo 0.6.3. Res d'això està fet encara tret del que diu l'apartat 0.

## 0. Ja resolt i un error trobat

- **Selector de color (resolt, `3695451`).** El botó de color tenia una regla `QPushButton { background-color: … }` sense nom. Una regla així arriba
  a tots els botons que pengen d'ell, i el diàleg de color ho era (s'obria amb el botó com a pare). Per això *D'acord*, *Cancel·la* i els botons de
  colors personalitzats agafaven el color triat. Ara la regla és només per al botó (`#colourSwatch`) i el diàleg penja de la finestra. Només
  passava a `ColourButton` (secció, estil, contorns, horitzó, terra…); els altres selectors (llums, materials) no pengen d'un botó pintat.
- **Error nou (resolt amb S1): els contorns ignoraven la secció.** Comprovat: amb un pla de secció actiu, les línies encara es dibuixen per a la part tallada (arestes
  amb x > 0 en un pla que treu x > 0). Freestyle no ho feia perquè dibuixava el que Blender ja havia tallat. S'ha de retallar la geometria de les
  línies amb els plans de tall *abans* del buffer de profunditat (apartat 3, pas S1). Fins que no es faci, una render amb secció i contorns
  surt amb línies de més.
- **La caixa de secció es renderitza sense tallar.** `section.job_block` només llegeix `scene.active_section()` (un pla). Una caixa activa no entra
  al job: la render surt sencera, sense avís.

## 1. Pestanya Entorn: què hi ha ara

| Grup | Controls | Plegats o amagats |
|---|---|---|
| Fons | Mostra (cel del look / panorama 360° / imatge) · Imatge · Fit · Brillantor de la imatge · «Il·lumina l'escena» | Segons el mode; **Rotació, Brillantor, Alçada del punt de vista** dins «Avançat» |
| Cel | Interior · Data · Hora · Sol · Núvols · (Lluna, Estrelles només de nit) | **Lloc i data** plegat: latitud/longitud, nord, fus horari, «Ombres a la vista 3D», i **un altre cop** Data i Hora |
| Terra | Tipus · «Terra generat» · «Ombra a terra» | **Tot el que importa** dins «Avançat»: color, rugositat, **calitja de l'horitzó**, alçada, radi del terra, radi d'herba, material, mida de rajola |
| Horitzó | Skyline · Alçada | **Distància, Forma, Color** dins «Avançat» |
| Boira | Boira · Comença a (i la nota si el dibuix té boira) | — |

### Problemes

1. **Repetit.** Data i hora hi són dues vegades (Cel i «Lloc i data»). Calitja d'horitzó (Terra) i Boira són el mateix efecte en dos llocs.
   «Color» surt a Terra i a Horitzó, «Alçada» tres cops amb tres significats (punt de vista, desplaçament del terra, alçada del skyline en graus),
   i la brillantor té tres noms (Sol, Brillantor de la imatge, Brillantor del fons).
2. **Amagat i necessari.** Rotació i brillantor d'un panorama són el que es toca primer i són dins «Avançat». El color i el material del terra,
   igual. «Lloc» (on és el model) és el que fa que el sol sigui el correcte, i és plegat.
3. **Ordre.** Fons va primer i el Cel després, però el cel és una de les tres coses que pot ser el fons: si trias panorama, núvols i estrelles
   no fan res i continuen visibles.
4. **«Interior»** és un mode de render (mesura per a l'interior, passa a Cycles) i és enmig dels controls del cel.
5. **Noms.** El grup «Cel» i l'opció «Cel del look» es confonen.

### Proposta (ordre de dalt a baix, com ho pensa qui ho fa servir)

1. **Llum** (abans «Cel»): *Interior* · Data · Hora · **Lloc** (ciutat o lat/lon) · **Nord** · Fus horari — tots a la vista, una sola vegada — ·
   *Força del sol* · Núvols · (Lluna i Estrelles només de nit). «Ombres a la vista 3D» és una opció d'IngeTrazo: es queda en una línia petita.
2. **Fons** (el que es veu darrere): selector de tres botons grans amb icona (Cel / Panorama / Imatge). Sota, **només els controls del que has
   triat, tots a la vista**: panorama → imatge, rotació, brillantor, «il·lumina l'escena», alçada del punt de vista; imatge → fitxer, ajust,
   brillantor; cel → res (la llum ja és a dalt). Si no és cel, Núvols/Estrelles queden grisos amb una línia que diu per què.
3. **Terra**: casella «Terra generat» (i «ombra a terra» just sota). Quan està activat, **a la vista**: material o color, rugositat,
   mida de rajola, radi del terra, radi d'herba, nivell. Quan no, grisos.
4. **Horitzó**: tipus · alçada (°) · distància · forma · color, a la vista quan el tipus no és «Cap».
5. **Boira i calitja**: Boira · Comença a · **Calitja del terra** (moguda des de Terra) · color (com el cel / propi). Si el dibuix té boira,
   la nota actual i els lliscadors grisos.

Regles: un control, un lloc; res es plega per ser «avançat» (només es gris o s'amaga per no tenir sentit); mateixa paraula = mateixa cosa
(«Nivell» per al desplaçament del terra, «Alçada (°)» al skyline, «Alçada de la càmera» al panorama); un color sempre amb el mateix botó i el mateix
«×» per tornar al del look; cada grup es pot plegar sencer (com els plafons d'IngeTrazo) i recorda l'estat.

**Esforç:** mitjà. És reorganitzar `panel.py`/`sun_panel.py` sense canviar què s'envia a Blender; les proves de visibilitat són la part llarga.
**Risc:** els tests que compten grups i files (`test_preview_offline`, `test_backdrop_panel_offline`).

## 2. Pestanya Secció: què hi ha ara

*Tanca el tall amb una cara* · Tapa (material / color pla / trama) · Material · Color · Trama · Línies · Espaiat · «Sense ombres a la tapa» ·
Llum (oberta / bloquejada) · una nota: el tall és el pla actiu d'IngeTrazo.

**Falta:** la vora de la tapa, la caixa de secció, i fer servir el farcit de tall que el dibuix ja té.

## 3. Pla per a la Secció

### S0 (previ) Una frase de context
La nota de baix passa a dir què talla ara: «Pla *Planta baixa*» / «Caixa *Detall* (6 cares)» / «Pla + caixa» / «No hi ha cap tall actiu».

### S1 Retallar les línies pels plans de tall (corregeix l'error) — FET
- Llegir els plans amb `core.section.cut_planes(scene)` (el pla actiu i les sis cares de la caixa activa; buit si «Talls de secció» està apagat).
- A `outlines.py`: retallar triangles i arestes (dures i toves) pels semiespais abans de `depth_buffer`, amb el mateix tipus de retall que ja fa
  Croquis al pla proper. Per a cada triangle: 0 plans → es queda; tot fora → fora; si el travessa → es parteix.
- Que també ho faci el camí ràpid (`hlr_geometry`): la geometria retallada es calcula igual i només una vegada per render.
- **Prova:** una caixa amb un pla al mig: cap línia al costat tret (avui n'hi ha).

### S2 Vora de la tapa (color i gruix)
- La tapa no és al model: és a Blender. Les arestes de la vora són el que IngeTrazo ja calcula per al seu tall: `core.section.cut_chords` (cordes del
  pla amb els triangles) i, per a la caixa, `plane_pair_line` (on es troben dos talls dins el material).
- A `outlines.py`: afegir aquestes cordes com a arestes de classe **«tall»**, i la tapa (`fill_triangles`) com a **oclusor** al buffer de profunditat
  (sense la tapa, el que hi ha darrere de la secció taparia o mostraria línies de dins).
- **Controls a la pestanya Secció** (sota «Tapa»): *Vora de la tapa* (casella), **color** (per defecte, el dels contorns) i **gruix** en píxels
  (per defecte, 1,6 × el dels contorns: la vora d'una secció és la línia forta d'un plànol).
- **Vectorial a la finestra de render:** el `LineSet` guarda la classe de cada línia; el quadre *Contorns* de la barra lateral guanya una fila
  «Vora de la tapa» (color, gruix) que es redibuixa a l'instant com la resta, i en desar s'aplana.
- **Prova:** una caixa tallada: la vora té el color i el gruix demanats; sense tapa o amb la casella apagada, no n'hi ha.

### S3 Caixa de secció (nova a IngeTrazo 0.6.3)
- **Job:** `section.job_block` torna una **llista de plans** (el pla actiu primer i les sis cares de la caixa) amb els mateixos paràmetres de tapa.
- **Blender:** `clip_section` ja talla amb un pla (triangulació + material de tapa per objecte). Es crida un cop per pla: cada passada talla també
  les tapes de l'anterior, així les sis tapes queden retallades per les altres cinc. Cal comprovar tres coses: (a) els materials de tapa no es
  dupliquen per passada, (b) «Llum bloquejada» (còpia fantasma) fa una sola còpia per objecte i no sis, (c) la tapa «sense ombres» (objecte solt) no
  es talla en pedaços.
- **Farcit del tall d'IngeTrazo:** la caixa i els plans tenen un farcit propi (`fill`, i l'estil del dibuix). A «Tapa» s'hi afegeix l'opció
  **«Com el dibuix»** (per defecte quan el dibuix en defineix un): color pla o trama d'IngeTrazo. Mateixa idea que la boira: el que veus a la
  vista 3D és el que es renderitza.
- **Cal que primer ho mirem amb un model:** les proves d'aquí s'han fet amb IngeTrazo 0.6.2.1 (sense caixa); `SectionBox` és de 0.6.3. Una prova
  amb Blender: caixa a l'interior d'un edifici, comparada amb la vista 3D.

### Ordre i esforç
1. S1 (arregla un error) — petit.
2. Entorn (apartat 1) — mitjà.
3. S2 vora de la tapa — mitjà (depèn de S1).
4. S3 caixa de secció — mitjà-gran, el més arriscat (Blender per passades).

### Decisions que cal que prenguis
1. **Entorn:** vols la proposta de 5 grups tal com està, o prefereixes mantenir «Cel» i «Fons» separats amb altres noms?
2. **Calitja del terra:** la unim a Boira (proposta) o es queda al Terra?
3. **Vora de la tapa:** gruix per defecte 1,6 × el dels contorns, o un valor fix?
4. **Caixa de secció:** «Com el dibuix» per defecte quan el dibuix té farcit, o sempre el material triat?
