# Limites et risques

## Limites techniques

- Le PDF ne fournit pas toujours une structure logique.
- Les blocs peuvent etre extraits dans un ordre incorrect.
- Les tableaux peuvent etre difficiles a detecter.
- Les styles PDF ne se traduisent pas parfaitement en DOCX.
- Le francais peut provoquer des debordements.
- Les images contenant du texte ne sont pas traduites dans le MVP.

## Risques de mauvaise traduction

- Mauvais choix terminologique.
- Perte de contexte entre blocs.
- Ambiguite de phrases courtes.
- Traduction incorrecte de termes juridiques, medicaux ou techniques.
- Hallucination ou reformulation excessive du LLM.

Reduction :

- utiliser un glossaire ;
- fournir un resume documentaire ;
- traduire par blocs avec contexte ;
- controler les termes obligatoires ;
- produire un rapport de validation.

## Risques de confidentialite

- Documents sensibles envoyes a un fournisseur IA externe.
- Fichiers temporaires conserves trop longtemps.
- Logs contenant du contenu confidentiel.
- Telechargements accessibles sans controle.

Reduction :

- ne pas logger le contenu complet ;
- supprimer les fichiers temporaires ;
- stocker les secrets dans `.env` ;
- documenter le fournisseur IA utilise ;
- ajouter authentification en version future.

## Limites du PDF

Le PDF peut contenir :

- texte fragmente ;
- polices incorporees complexes ;
- encodages non standard ;
- calques ;
- annotations ;
- formulaires ;
- images de texte.

Le MVP accepte ces limites et signale les incertitudes.

## Limites OCR

L'OCR n'est pas inclus dans le MVP. Les documents scannes peuvent donc produire peu ou pas de texte. Le systeme doit detecter ce cas et indiquer que le document est hors perimetre MVP.

## Limites du MVP

- Pas de fidelite pixel-perfect.
- Pas d'authentification.
- Pas de stockage cloud.
- Pas de traitement par lots.
- Pas de garantie de qualite linguistique parfaite.
- Pas de validation humaine integree.

## Strategies de reduction des risques

- Demarrer avec PDF numeriques propres.
- Ajouter des fixtures de test representatives.
- Garder une architecture modulaire.
- Utiliser des services IA abstraits.
- Generer un rapport de validation explicite.
- Communiquer clairement les limites a l'utilisateur.
- Prevoir une purge automatique des fichiers.

