# Specification UI/UX

## Objectif UX

L'interface doit donner l'impression d'un outil SaaS B2B serieux, simple et fiable. L'utilisateur doit comprendre ou il en est dans le traitement et ce qui demande une verification humaine.

## Parcours utilisateur

1. L'utilisateur arrive sur la page d'accueil.
2. Il importe un PDF numerique en anglais.
3. Le systeme valide le fichier.
4. Le traitement demarre.
5. Une page de progression affiche les etapes.
6. Le resultat permet de telecharger le DOCX.
7. Le rapport presente les alertes et zones a verifier.

## Ecrans MVP

### Page d'accueil

Contenu :

- nom du produit ;
- proposition de valeur concise ;
- bouton principal vers l'upload ;
- rappel des limites MVP : PDF numeriques propres, anglais vers francais.

### Page upload

Contenu :

- zone drag and drop ;
- bouton de selection fichier ;
- contraintes visibles : PDF numerique uniquement, 10 Mo maximum, 10 pages maximum, texte selectionnable obligatoire ;
- affichage du fichier choisi ;
- bouton "Lancer le traitement".

### Page traitement/progression

Contenu :

- statut global ;
- liste d'etapes : upload, analyse, extraction, traduction, reconstruction, rapport ;
- indicateur de progression ;
- message si le traitement prend plus longtemps que prevu.

### Page resultat

Contenu :

- statut final ;
- bouton telechargement DOCX prioritaire ;
- bouton PDF seulement si l'export optionnel est disponible ;
- resume du rapport ;
- lien vers le rapport complet.

Le DOCX est le livrable principal du MVP. L'export PDF est optionnel et son absence ne doit pas etre presentee comme une erreur bloquante.

### Page rapport

Contenu :

- score de confiance global ;
- liste des alertes ;
- filtres simples par type : traduction, mise en page, tableau, image, terminologie ;
- reference page/bloc pour chaque alerte.

### Page historique simple optionnelle

Contenu :

- liste locale des derniers traitements ;
- statut ;
- date ;
- liens de telechargement tant que les fichiers existent.

## Etats de chargement

- `idle` : aucun fichier selectionne.
- `validating` : verification du fichier.
- `uploading` : upload en cours.
- `processing` : pipeline en cours.
- `completed` : resultat disponible.
- `failed` : erreur bloquante.

## Messages d'erreur

Les messages doivent etre courts et actionnables :

- "Le fichier doit etre un PDF."
- "Le fichier depasse la taille maximale de 10 Mo."
- "Le PDF depasse la limite de 10 pages."
- "Le PDF doit contenir du texte selectionnable."
- "Le PDF semble protege ou illisible."
- "La traduction a echoue. Reessayez ou verifiez la configuration IA."
- "Le document a ete traite avec des alertes. Consultez le rapport."

## Experience d'import PDF

Exigences :

- accepter drag and drop et selection classique ;
- afficher nom, taille et type du fichier ;
- bloquer l'envoi si le fichier est invalide ;
- ne pas lancer automatiquement le traitement sans confirmation ;
- afficher une erreur sans perdre l'etat de la page.

## Design system minimal

- Palette sobre : fond clair, texte contraste, accent bleu ou vert professionnel.
- Typographie lisible.
- Boutons primaires et secondaires coherents.
- Cartes utilisees uniquement pour des blocs d'information.
- Tableaux simples pour le rapport.
- Design responsive desktop prioritaire, mobile acceptable.

## Criteres d'acceptation

- L'utilisateur peut importer un PDF valide en moins de trois actions.
- Le statut du traitement est toujours visible.
- Les erreurs sont comprehensibles.
- Le DOCX final est accessible depuis la page resultat.
- Le rapport indique clairement les points a verifier.
