# Feature - Analyse et extraction

## Objectif

Extraire le contenu structure d'un PDF numerique afin de construire une representation intermediaire exploitable par la traduction et la reconstruction.

## Perimetre MVP

- Extraction du texte natif avec PyMuPDF.
- Recuperation des coordonnees des blocs.
- Detection simple des titres et paragraphes.
- Extraction basique des images.
- Detection de tableaux simples avec pdfplumber ou Camelot si necessaire.
- Creation de la representation intermediaire.
- Limite stricte MVP : 10 pages maximum.

## Hors perimetre

- OCR de pages scannees.
- Layout multi-colonnes complexe.
- Equations, annotations avancees, formulaires interactifs.
- Reconstruction exacte de tous les styles.

## Exigences fonctionnelles

- Lire le nombre de pages.
- Extraire les blocs de texte avec page et bbox.
- Associer un ordre de lecture.
- Classer les blocs en `title`, `paragraph`, `table`, `image`, `unknown`.
- Identifier les images et leur position.
- Produire un JSON intermediaire sauvegarde.

## Exigences non fonctionnelles

- Echec controle si le PDF est illisible.
- Traitement raisonnable pour un PDF de 10 pages maximum.
- Heuristiques documentees.
- Resultat intermediaire stable et serialisable.

## Logique technique

1. Ouvrir le PDF avec PyMuPDF.
2. Pour chaque page, extraire les blocs via `get_text("dict")`.
3. Normaliser le texte : espaces, lignes, caracteres invisibles.
4. Calculer l'ordre de lecture par page puis position verticale/horizontale.
5. Identifier les titres avec taille de police, gras, longueur et position.
6. Identifier les paragraphes par blocs textuels continus.
7. Extraire les images avec bbox et reference locale.
8. Detecter les tableaux simples avec lignes/cellules quand possible.
9. Construire `DocumentIntermediate`.

Les tableaux detectes doivent etre representes dans `DocumentIntermediate` comme des blocs de type `table`, contenant directement leurs `rows` et `cells`. Il ne doit pas y avoir de collection globale separee pour les tableaux dans le MVP.

## Detection basique

Titres probables :

- police plus grande que la moyenne ;
- texte court ;
- gras ou majuscules ;
- position en haut de section.

Paragraphes probables :

- texte multi-mots ;
- taille de police standard ;
- bbox large ;
- ponctuation normale.

Tableaux probables :

- alignements repetes en colonnes ;
- lignes horizontales/verticales detectees ;
- densite de cellules ;
- extraction reussie via pdfplumber ou Camelot.

Definition d'un tableau simple MVP :

- tableau sur une seule page ;
- lignes et colonnes detectables ;
- pas de cellules fusionnees ;
- pas de tableau imbrique.

Images :

- objet image dans la page ;
- bbox non nulle ;
- export dans un dossier temporaire.

## Criteres d'acceptation

- Le systeme extrait le texte d'un PDF numerique simple.
- Chaque bloc possede un id, une page, un type, une bbox et un ordre de lecture.
- Les images principales sont detectees.
- Les tableaux simples sont extraits comme blocs `table` ou marques comme suspects.
- Un fichier JSON intermediaire est produit.

## Cas d'erreur

- PDF protege : marquer le job en echec.
- Page sans texte : ajouter une alerte `possible_scanned_page`.
- Extraction partielle : continuer si possible et signaler dans le rapport.
- Tableau non extractible : creer un bloc `unknown` ou `table` avec warning.

## Tests a prevoir

- PDF une page avec paragraphes.
- PDF avec titre et sous-titre.
- PDF avec image.
- PDF avec tableau simple.
- PDF protege ou invalide.
