# Render Studio: pla de simplificació

> Pla de treball. L'apartat «Estat» és un historial: on diu «sense commit», ja hi és (versió 0.29.0). El que queda pendent és a [PENDENT.md](PENDENT.md).

## Estat

- **Fase 1:** feta (branca `feat/param-registry`).
- **Fase 2:** feta a la mateixa branca. Diferències respecte del pla:
  - «Correccions» i «Efectes» continuen com a dos grups dins d'Estil; la vinyeta i l'oclusió s'amagaran amb el mode expert (fase 5).
  - «Mantén vidre i aigua» es veu fins que hi hagi mode expert.
  - «Paper» és una opció nova de Fons.
  - Les ombres només s'han mogut a Entorn; el seu comportament no ha canviat.

- **Fase 3:** feta (sense commit). La barra té els sis botons i l'«Actualitza»; la finestra de previsualització i el peu del tauler ja no els repeteixen. «Obre al Blender» és sota la fletxa de Render. Totes les pestanyes caben en 240 px.

- **Fase 4:** feta (sense commit). Cinc botons de llum i galeria de predefinits amb set de sèrie (inclòs «Dibuix de línies»); fitxers `.rspreset` amb miniatura i imatges; els predefinits antics es converteixen sols. «Interior» ja no és una casella. S'ha corregit un error: amb el terra desactivat, la trama d'ombres embrutava tot el fons.

- **Fase 5:** feta (sense commit). Interruptor «Mode expert», pestanya Expert amb 62 paràmetres, cercador, ull, marca i restabliment, i disposicions desables. «Estrelles» i «Lluna» passen a la vista senzilla perquè només surten de nit. Queden fora d'Expert l'amplada (és a Sortida) i les opcions de lloc del sol, Secció i Sortida.

- **Fase 6, en curs (sense commit):**
  - Els ajustaments nous es generen sols a partir del registre i es desen al bloc «fine», només si no tenen el valor per defecte.
  - **Bloc A, fet:** textura de paper o tela (paper fi, paper rugós, tela o una imatge), amb força i mida.
  - **Bloc B, fet:** vora suau de l'ombra, altura del sol a l'hora daurada, mida, brillantor i forma dels núvols, contrast, balanç de blancs, tint, resplendor, exposició automàtica i blanc màxim dels materials.
  - **Pendent, bloc C:** superfície d'un sol color (rugositat, reflex, terra amb el mateix material, escala i gir de la textura) i lux.
  - **Pendent, bloc D:** contorn, gruix de la trama, intensitat de l'ombra sobre color pla, aquarel·la, distància de la boirina i sol del panorama.
  - **Afegit a petició:** Fons «Transparent» (model, línies i ombra a terra sense res al darrere).
  - **A petició:** tornen al tauler els botons Materials, Llums i Obre la previsualització (trets a la fase 3), amb les icones de la barra.
  - **A petició:** Fora el desplegable «Avançat» de Qualitat; el motor, el motor de la previsualització i la seva qualitat són a Expert. La finestra de Llums conserva el seu «Avançat».
  - Corregit: «Tria un fitxer…» demanava dues vegades la panoràmica i la imatge fixa.
  - S'ha corregit un error: «Ombra al terra» quedava desactivada en obrir un dibuix sense terra generat.

## Redisseny en targetes (a petició, 25-11)

- **Fet a tot el tauler:** grups en targetes amb capçalera de color i icona, plegables; botons plans amb icona; grups d'Expert plegables.
- **Fet a Entorn:** tots els controls tenen ull, també els del sol. Vista bàsica: data, hora, localització, sol, núvols (estrelles i lluna de nit); dibuix d'ombra i ombra a terra; tipus de fons i el seu fitxer o color; terra i tipus; perfil i altura de l'horitzó; boira.
- **Pendent:** repassar amb el mateix criteri Principal (predefinits, llum, càmera, qualitat), Estil, Secció i Sortida.

## Per fer més endavant

- Posar una **icona davant el nom de cada grup** de cada pestanya del tauler (Superfície, Contorn, Acabat, Correccions, Sol i cel, Ombres, Fons, Terra, Horitzó, Boira, Predefinits, Llum, Càmera…).

## 1. Idea central

Ara cada estil porta les seves opcions i moltes es trepitgen. La proposta és separar **quatre coses independents** i fer que els «estils» complexos siguin predefinits que les combinen.

| Cosa | On | Què decideix |
|---|---|---|
| **Superfície** | Estil | Com es pinta el model |
| **Contorn** | Estil | Les línies, amb qualsevol superfície |
| **Ombres** | Entorn | Com es dibuixen les ombres |
| **Acabat** | Estil | El tractament de la imatge sencera |

| Superfície | Substitueix |
|---|---|
| Materials reals | Estil «Cap» |
| Un sol material o color (blanc per defecte) | «Blanc» i «Maqueta» |
| Cap (paper) | Esboç sense «Render sota les línies» |
| Anàlisi de llum (lux) | Estil «Llum» |

| Acabat | Substitueix |
|---|---|
| Cap | |
| Aquarel·la | Estil «Aquarel·la» |

**«Esboç» deixa de ser un estil.** Passa a ser un predefinit: superfície «Cap» o «Un color», contorn a mà alçada, ombres amb trama i color de paper.

## 2. Barra d'eines

`Previsualització` · `Sincronitza canvis` · `Sincronitza càmera` | `Materials` · `Llums` · `Biblioteca`

- Les dues sincronitzacions són botons premuts quan estan actives.
- Si «Sincronitza canvis» està desactivat, al costat apareix `Actualitza`.
- A la finestra de previsualització es treuen aquests tres botons, per no tenir-los repetits. Hi queden «Nova escena» i «Render».
- `Biblioteca`: si l'extensió no hi és, surt un missatge que demana instal·lar-la des del Gestor d'extensions, amb un botó per obrir-lo.

## 3. Pestanyes (vista senzilla)

| Pestanya | Grups i controls visibles per defecte |
|---|---|
| **Principal** | Predefinits (miniatures) · Ambient (5 botons) · Càmera (projecció, angle, profunditat de camp) · Qualitat (3 botons i amplada) |
| **Estil** | Superfície (i color o material) · Contorn (activat, color, gruix, mà alçada) · Acabat |
| **Entorn** | Sol (data, hora) · Cel (núvols) · Ombres (dibuix, color, intensitat) · Fons · Terra · Horitzó · Boira |
| **Secció** | Com ara |
| **Sortida** | Com ara |
| **Expert** | Només amb el mode expert activat (apartat 6) |

La pestanya **Imatge** desapareix. Exposició, calidesa i saturació passen a **Estil ▸ Imatge**. Vinyeta i oclusió queden ocultes, disponibles des d'Expert.

## 4. Predefinits i ambients

La regla perquè no es confonguin:

- **Ambient** canvia només **la llum**: sol, cel, exposició i balanç de blancs. No toca l'estil.
- **Predefinit** canvia **tot l'aspecte**: superfície, contorn, ombres, acabat, entorn, imatge i ambient.

### Ambients

| Botó | Aspecte actual |
|---|---|
| Exterior assolellat | `clear` |
| Ennuvolat | `overcast` |
| Hora daurada | `golden_hour` |
| Nit | `night` |
| Interior | `interior` |

- «Parcialment ennuvolat» desapareix: és el mateix que assolellat amb més núvols.
- «Maqueta blanca» passa a ser un predefinit.
- Ara, si el sol és sota l'horitzó, la nit s'activa sola. Proposo mantenir-ho i que s'il·lumini el botó «Nit».

### Predefinits
- **De sèrie:** Realista, Maqueta blanca, Esboç, Aquarel·la, Plànol sobre blanc i Anàlisi de llum.
- **Miniatura:** es fa en desar. Si la previsualització és oberta, s'agafa la imatge que mostra. Si no, es fa un render petit (320 × 180).
- **Fitxer:** un `.rspreset` per predefinit (ZIP amb els ajustaments, la miniatura i les imatges de fons o panorames que faci servir). Es desen a la carpeta de l'extensió.
- **Accions** (botó dret): aplicar, actualitzar, canviar el nom, duplicar, importar, exportar i esborrar.
- **No inclouen:** càmera, qualitat, secció ni sortida, que pertanyen al dibuix o a cada render.
- Els predefinits que ja tens es converteixen automàticament, sense miniatura fins que els tornis a desar.

## 5. Paràmetres que ara no es poden tocar

**Vista** indica on es veuria: «senzilla» (visible per defecte) o «expert» (ocult fins que l'activis).

### Ambients (fixats dins cada aspecte)

| Paràmetre | Valor actual | Destí | Vista |
|---|---|---|---|
| Suavitat de la vora de l'ombra (mida del sol) | segons l'aspecte (1° a l'hora daurada) | Entorn ▸ Ombres | senzilla |
| Altura del sol a l'hora daurada | 7°, imposada | Entorn ▸ Sol | expert |
| Mida i brillantor dels núvols | 1,0 | Entorn ▸ Cel | expert |
| Forma dels núvols (llavor) | fixa | Entorn ▸ Cel | expert |
| Contrast del to (AgX) | segons l'aspecte | Estil ▸ Imatge | expert |
| Balanç de blancs en kelvin | 5600–8500; ara només «Calidesa» | Estil ▸ Imatge | expert |
| Tint verd o magenta | sense control | Estil ▸ Imatge | expert |
| Resplendor (bloom) | 0; 0,2 de nit | Estil ▸ Imatge | expert |
| Exposició automàtica: objectiu, blanc i límit | 0,07–0,36 · 1,6–6 · fins a 8 | Estil ▸ Imatge | expert |
| Límit de blancor dels materials | 80 % | Estil ▸ Superfície | expert |

### Superfície

| Paràmetre | Valor actual | Destí | Vista |
|---|---|---|---|
| Color del «Blanc» | gris 0,82 | Superfície (és el color únic) | senzilla |
| Rugositat i reflex del color únic | 0,75–0,80 · 0,3 | Estil ▸ Superfície | expert |
| Mantenir vidre i aigua | sempre | Estil ▸ Superfície | expert |
| Terra amb el mateix material | sempre gris blanc | Estil ▸ Superfície | expert |
| Escala i gir de la textura general | els del material del dibuix | Estil ▸ Superfície | senzilla, si el material té textura |
| Lux: reflectància de referència | 0,82 | Estil ▸ Superfície (lux) | expert |
| Lux: llum del sol | 100 000 lx | Estil ▸ Superfície (lux) | expert |
| Lux: paleta, llegenda i color del cel | fixos | Estil ▸ Superfície (lux) | expert |

### Contorn

| Paràmetre | Valor actual | Destí | Vista |
|---|---|---|---|
| Mà alçada i prolongació | només a l'esboç i a la finestra de retoc | Estil ▸ Contorn | senzilla |
| Opacitat de la tinta | només a la finestra de retoc | Estil ▸ Contorn | expert |
| Pes de les siluetes | automàtic segons la mà alçada | Estil ▸ Contorn | expert |
| Traç doble i traç trencat | automàtics (més del 5 % i del 20 %) | Estil ▸ Contorn | expert |
| Quantitat de detall | fixa | Estil ▸ Contorn | expert |
| Contorn del tall | pestanya Secció | es queda a Secció | — |

### Ombres

| Paràmetre | Valor actual | Destí | Vista |
|---|---|---|---|
| Intensitat de l'ombra al terra sobre color pla, «Del render» | 35 % | Entorn ▸ Ombres (la mateixa «Intensitat») | senzilla |
| Gruix de la trama | el del contorn | independent, perquè el contorn ja es pot desactivar | expert |
| Ombra al terra | grup Terra | Entorn ▸ Ombres | senzilla |

### Acabat i textura de la imatge

| Paràmetre | Valor actual | Destí | Vista |
|---|---|---|---|
| **Textura general del paper o tela** (imatge, escala, intensitat) | **no existeix**; només el gra de l'aquarel·la | Estil ▸ Acabat, per a qualsevol combinació | senzilla |
| Color del paper | blanc trencat fix a l'esboç | Entorn ▸ Fons ▸ Color pla | senzilla |
| Aquarel·la: mida del gra | fixa | Estil ▸ Acabat | expert |
| Aquarel·la: claror del pigment | fixa | Estil ▸ Acabat | expert |
| Aquarel·la: força de les vores i expansió | en part, amb «Vores» i «Humitat» | Estil ▸ Acabat | expert |

La «textura general del paper» és una funció nova. La resta són valors que el codi ja té fixats.

### Entorn

| Paràmetre | Destí | Vista |
|---|---|---|
| Distància on comença i acaba la boirina de l'horitzó | Entorn ▸ Boira | expert |
| El sol del panorama (si fa ombres i amb quin llindar) | Entorn ▸ Fons | expert |

L'inventari surt dels aspectes, dels estils i dels contorns. Els materials i les llums tenen finestra pròpia i no els he repassat paràmetre per paràmetre.

## 6. Mode expert i disposició

- S'activa amb un interruptor al peu del tauler, i apareix la pestanya **Expert**.
- Hi surt **tot** el que es pot modificar, en blocs per pestanya i grup, amb un **cercador**.
- Cada fila té el control i un **ull**:
  - ull obert: el control es veu a la seva pestanya;
  - ull tancat: només surt a Expert.
- Un punt marca els valors diferents del valor per defecte, **encara que estiguin ocults**. Cada fila es pot restablir. Això evita ajustaments invisibles que canvien el resultat.
- **Disposicions:** desar, carregar, esborrar i restablir. Són fitxers `.json` a la carpeta de l'extensió.
- La disposició **Per defecte** és de només lectura i correspon a la columna «senzilla».
- La disposició només decideix **què es veu**. No canvia cap valor del render ni es desa amb el dibuix.

## 7. Com fer-ho sense fer créixer el monstre

`panel.py` supera les 2.700 línies, i cada opció nova es toca en molts llocs: control, senyal, desar, aplicar, enviar a Blender i traduir.

**La peça clau és un registre únic de paràmetres.** Cada paràmetre es descriu **una sola vegada**: clau, nom, pestanya, grup, tipus, límits, valor per defecte, visibilitat i condició per mostrar-se. D'aquí surten:

- les pestanyes i la pestanya Expert;
- l'ull i les disposicions;
- el desat al dibuix, els predefinits i els ambients;
- el botó de restablir.

Sense aquest registre, l'ull i la pestanya Expert obligarien a duplicar tot el tauler.

## 8. Fases

Cada fase es pot instal·lar i provar per separat.

| Fase | Contingut | Què es nota |
|---|---|---|
| **1. Registre** | Registre de paràmetres i conversió dels dibuixos i predefinits antics | Res a la vista; mateixos renders |
| **2. Reorganització** | Pestanyes noves; Superfície, Contorn i Acabat; Ombres a Entorn; fora la pestanya Imatge | El canvi gros d'ús |
| **3. Barra d'eines** | Botons i avís de la Biblioteca; neteja de la previsualització | Accés directe |
| **4. Predefinits i ambients** | Miniatures, fitxers, importar, exportar i 5 botons | Pàgina principal definitiva |
| **5. Expert** | Pestanya, ull i disposicions | Cada usuari es fa el seu tauler |
| **6. Paràmetres nous** | Els de l'apartat 5 i la textura del paper | Més control sense més soroll |

**Verificació a cada fase:**
- Abans de la fase 1 es fan renders de referència (realista, blanc, esboç, aquarel·la, lux i nit), per comparar-los després.
- Es comprova que un dibuix desat amb la versió actual es veu igual.

**Punt de partida:** la branca `feat/preview-shadows-two-point`, després de provar-la.

## Notes de les proves

- La perspectiva de dos punts funciona (provada amb el model real).
- **Per revisar a la fase 2:** el color de l'ombra i la trama no es comporten com s'esperava. De moment es deixen com són. Abans de redissenyar-los, cal concretar el resultat que es vol, idealment amb una imatge d'exemple.

- **Error ja existent, per corregir a la fase 2:** en un dibuix nou, els lliscadors d'«Esboç» i «Aquarel·la» comencen a 0 i no als valors previstos (traç irregular 50 %, prolongació 40 %, humitat 50 %, paper 50 % i vores 40 %).

## 9. Decisions preses

1. **Esboç i aquarel·la:** l'esboç és un predefinit i l'aquarel·la és un acabat.
2. **Lux:** va dins «Superfície».
3. **Barra d'eines:** les sincronitzacions es treuen de la finestra de previsualització.
4. **Predefinits:** no desen la càmera; per a això hi ha les escenes.
