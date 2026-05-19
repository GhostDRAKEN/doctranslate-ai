# Feature - Rapport de validation

## Objectif

Produire un rapport clair indiquant les problemes detectes et les zones qui necessitent une verification humaine.

## Perimetre MVP

- Rapport JSON et affichage frontend.
- Score de confiance global.
- Liste d'alertes par `page_number` et bloc.
- Detection de blocs non traduits.
- Detection de traductions potentiellement trop longues.
- Detection de tableaux suspects.
- Detection d'images pouvant contenir du texte.
- Alertes terminologiques.

## Hors perimetre

- Validation linguistique humaine integree.
- Comparaison visuelle pixel par pixel.
- Annotation interactive dans le DOCX.
- Evaluation automatique exhaustive de qualite.

## Exigences fonctionnelles

- Generer un rapport pour chaque traitement.
- Classer les alertes par severite.
- Associer les alertes a un `page_number` et un bloc si possible.
- Fournir une suggestion courte.
- Exposer le rapport via API.
- Afficher le rapport dans le frontend.

## Exigences non fonctionnelles

- Le rapport doit etre comprehensible par un utilisateur non expert.
- Les alertes ne doivent pas bloquer le telechargement sauf erreur critique.
- Le score doit etre indicatif, pas presente comme une garantie.

## Types d'alertes

- `untranslated_block`
- `translation_failed`
- `text_overflow_risk`
- `table_suspicious`
- `image_possible_text`
- `terminology_missing`
- `pdf_page_without_text`
- `reconstruction_warning`

## Score de confiance

Le score peut etre calcule selon :

- proportion de blocs traduits ;
- nombre d'alertes critiques ;
- nombre d'alertes moyennes ;
- presence de pages sans texte selectionnable ;
- problemes terminologiques.

Exemple simple :

```text
score = 1.0
score -= 0.05 par bloc non traduit
score -= 0.10 par bloc failed
score -= 0.05 par tableau suspect
score -= 0.03 par image avec texte possible
score -= 0.05 par terme obligatoire absent
score final = min(max(score, 0), 1)
```

Le score doit etre borne entre 0 et 1.

## Format du rapport

```json
{
  "document_id": "doc_123",
  "confidence_score": 0.82,
  "issues": [
    {
      "severity": "medium",
      "type": "text_overflow_risk",
      "page_number": 3,
      "block_id": "block_041",
      "message": "La traduction est nettement plus longue que le texte source.",
      "suggestion": "Verifier la mise en page dans le DOCX."
    }
  ]
}
```

## Logique technique

1. Parcourir les blocs traduits.
2. Detecter les statuts `failed`, `skipped`, `needs_review`.
3. Comparer longueur source/traduction.
4. Lire les warnings de tableaux et images.
5. Ajouter les alertes terminologiques du `GlossaryService`.
6. Calculer le score.
7. Sauvegarder le rapport JSON.

## Criteres d'acceptation

- Un rapport est genere meme si le document est traite avec alertes.
- Les blocs non traduits sont visibles.
- Les tableaux suspects sont signales.
- Les images avec texte possible sont signalees.
- Le frontend peut afficher le rapport.

## Cas d'erreur

- Rapport impossible a generer : retourner une erreur backend et garder les artefacts disponibles si possible.
- Bloc sans `page_number` : rapporter l'alerte sans localisation precise.

## Tests a prevoir

- Rapport sans alerte.
- Rapport avec bloc non traduit.
- Rapport avec glossaire non respecte.
- Rapport avec image contenant possiblement du texte.
- Calcul de score borne entre 0 et 1.
