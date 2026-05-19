# Feature - Reconstruction DOCX

## Objectif

Generer un document DOCX editable en francais, proche de la structure du PDF source, a partir de la representation intermediaire traduite.

## Perimetre MVP

- Generation DOCX avec `python-docx`.
- Conservation approximative des titres et paragraphes.
- Reproduction simple des tableaux.
- Insertion des images extraites.
- Styles basiques : taille, gras, italique, alignement.
- Gestion simple des sauts de page.
- Export PDF optionnel et non bloquant.

## Hors perimetre

- Reconstruction pixel-perfect.
- Reproduction parfaite des colonnes.
- Styles complexes, calques, formulaires.
- Notes de bas de page avancees.
- Equations complexes.

## Exigences fonctionnelles

- Creer un DOCX par document traite.
- Parcourir les blocs selon `reading_order`.
- Convertir les titres en styles de titres DOCX.
- Convertir les paragraphes en paragraphes DOCX.
- Convertir les tableaux simples en tables DOCX.
- Inserer les images a une taille raisonnable.
- Ajouter des sauts de page entre pages source si utile.

## Exigences non fonctionnelles

- Le DOCX doit etre ouvrable dans Microsoft Word ou LibreOffice.
- Le document doit rester editable.
- Les erreurs de reconstruction doivent etre signalees dans le rapport.
- Le pipeline ne doit pas echouer pour une image non inserable si le reste est disponible.

## Logique technique

1. Charger la representation intermediaire traduite.
2. Creer un document `python-docx`.
3. Configurer marges et styles de base.
4. Pour chaque page, ajouter les blocs dans l'ordre.
5. Appliquer des styles approximatifs.
6. Ajouter tableaux et images.
7. Sauvegarder dans `storage/tmp/{document_id}/translated.docx`.

Le DOCX final du MVP est stocke dans :

```text
storage/tmp/{document_id}/translated.docx
```

L'export PDF reste optionnel pour le MVP. Son absence ne bloque pas la validation du prototype.

## Conservation des titres

- `title` principal : style `Heading 1`.
- sous-titre probable : style `Heading 2`.
- taille et gras adaptes lorsque disponibles.

## Conservation des paragraphes

- Ajouter un paragraphe par bloc logique.
- Preserver les retours de ligne seulement si necessaire.
- Eviter de conserver les coupures de ligne artificielles du PDF.

## Conservation des tableaux simples

- Creer une table DOCX avec nombre de lignes/colonnes detecte.
- Traduire chaque cellule.
- Appliquer une bordure simple.
- Signaler les tableaux incomplets.

## Conservation des images

- Inserer les images extraites.
- Respecter approximativement le ratio.
- Limiter la largeur a la largeur utile de page.
- Signaler les images contenant possiblement du texte.

## Gestion des debordements

Le francais pouvant etre plus long que l'anglais, le systeme doit :

- accepter une mise en page plus longue ;
- eviter le texte minuscule ;
- signaler les blocs dont la traduction est beaucoup plus longue ;
- ne pas promettre une pagination identique.

## Criteres d'acceptation

- Un DOCX est genere pour un document simple.
- Les titres et paragraphes sont lisibles.
- Les tableaux simples sont presents.
- Les images principales sont presentes.
- Les limites de mise en page sont indiquees dans le rapport.
- L'absence d'export PDF ne bloque pas le succes du traitement MVP.

## Cas d'erreur

- Image non lisible : ignorer l'image et ajouter une alerte.
- Bloc sans traduction : utiliser le texte source ou laisser vide selon configuration, puis alerter.
- Table mal structuree : inserer une representation texte et alerter.

## Tests a prevoir

- DOCX avec titres et paragraphes.
- DOCX avec tableau.
- DOCX avec image.
- Bloc traduit plus long que source.
- Document avec bloc echoue.
