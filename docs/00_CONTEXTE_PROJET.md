# DocTranslate AI - Contexte projet

## Presentation du probleme

La traduction de documents PDF professionnels ne consiste pas seulement a traduire du texte. Un PDF contient une mise en page visuelle, des titres, paragraphes, tableaux, images, styles, espacements et ordres de lecture qui ne sont pas toujours representes comme une structure logique claire.

DocTranslate AI vise a produire un document traduit en francais tout en conservant autant que possible la structure visuelle et editoriale du PDF source.

## Objectif du projet

L'objectif du MVP est de creer une application web capable de :

- importer un PDF numerique propre en anglais ;
- extraire son contenu textuel natif ;
- identifier des blocs simples : titres, paragraphes, tableaux et images ;
- construire une representation intermediaire structuree ;
- traduire les blocs anglais vers francais avec contexte documentaire ;
- appliquer un glossaire metier simple ;
- reconstruire un document final editable, prioritairement en DOCX ;
- produire un rapport de validation listant les zones a verifier.

Le prototype doit etre demonstrable, techniquement realiste et evolutif.

## Pourquoi la traduction fidele d'un PDF est difficile

Le format PDF est concu pour l'affichage et l'impression, pas pour l'edition semantique. Les difficultes principales sont :

- l'ordre de lecture peut differer de l'ordre visuel ;
- les paragraphes peuvent etre fragmentes en lignes ou en morceaux de texte ;
- les titres ne sont pas toujours marques comme titres ;
- les tableaux peuvent etre seulement des lignes et du texte positionne ;
- les images peuvent contenir du texte non extractible ;
- la traduction modifie souvent la longueur du texte ;
- le francais est souvent plus long que l'anglais ;
- les styles originaux doivent etre approximes lors de la reconstruction ;
- un PDF peut contenir plusieurs colonnes, en-tetes, pieds de page ou notes.

## Traduction de texte vs reconstruction documentaire

Un simple traducteur de texte prend une chaine de caracteres et retourne une autre chaine. DocTranslate AI doit fonctionner comme un pipeline documentaire :

1. comprendre la structure minimale du document ;
2. traduire chaque unite logique avec son contexte ;
3. controler la coherence terminologique ;
4. reconstruire un document exploitable ;
5. signaler les incertitudes au lieu de promettre une fidelite parfaite.

La valeur du systeme vient de cette combinaison extraction + IA + reconstruction + validation.

## Limites du MVP

Le MVP se limite volontairement a :

- des PDF numeriques propres ;
- des documents majoritairement en anglais ;
- des tableaux simples ;
- une reconstruction DOCX approximative mais lisible ;
- un stockage temporaire local ;
- une traduction par fournisseur IA configurable ;
- un rapport de validation basique.

Sont exclus du MVP :

- OCR avance de documents scannes ;
- conservation pixel-perfect ;
- documents manuscrits ;
- formulaires complexes ;
- equations scientifiques complexes ;
- comparaison visuelle automatique avancee ;
- workflows collaboratifs multi-utilisateurs.

## Vision long terme

A terme, DocTranslate AI pourrait evoluer vers une plateforme SaaS de traduction documentaire avec :

- OCR pour documents scannes ;
- detection avancee de layout ;
- memoire de traduction ;
- glossaires par client ou secteur ;
- comparaison visuelle source/resultat ;
- traitement par lots ;
- authentification et gestion des roles ;
- stockage cloud chiffre ;
- API publique ;
- suivi humain des corrections ;
- apprentissage a partir des validations utilisateur.

