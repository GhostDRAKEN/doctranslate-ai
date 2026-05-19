# Feature - Glossaire et terminologie

## Objectif

Ameliorer la coherence terminologique en permettant l'utilisation d'un glossaire metier pendant et apres la traduction.

## Perimetre MVP

- Glossaire utilisateur simple.
- Glossaire genere automatiquement exclu du coeur MVP.
- Application du glossaire dans le prompt de traduction.
- Controle terminologique basique apres traduction.
- Alertes dans le rapport.

## Hors perimetre

- Gestion collaborative du glossaire.
- Workflow de validation terminologique complet.
- Memoire de traduction.
- Detection morphologique avancee.
- Glossaire genere automatiquement par LLM.

## Exigences fonctionnelles

- Permettre de fournir une liste source/cible.
- Associer les termes a un domaine.
- Inclure les termes pertinents dans la traduction.
- Verifier apres traduction que les termes obligatoires sont presents.
- Signaler les incoherences.

## Exigences non fonctionnelles

- Le controle doit etre rapide.
- Les faux positifs doivent etre signales comme alertes, pas erreurs bloquantes.
- Les termes sensibles a la casse doivent etre supportes.
- Le format doit etre serialisable en JSON.

## Glossaire utilisateur

Exemple :

```json
[
  {
    "source": "agreement",
    "target": "contrat",
    "domain": "legal",
    "required": true
  },
  {
    "source": "liability",
    "target": "responsabilite",
    "domain": "legal",
    "required": true
  }
]
```

## Glossaire genere automatiquement

Le glossaire genere automatiquement par LLM est une fonctionnalite de version avancee. Il ne doit pas bloquer le MVP, qui s'appuie d'abord sur un glossaire utilisateur simple.

Format :

```json
{
  "terms": [
    {
      "source": "data processing",
      "suggested_target": "traitement des donnees",
      "confidence": 0.86
    }
  ]
}
```

## Application pendant la traduction

Le prompt doit inclure :

- source term ;
- traduction attendue ;
- caractere obligatoire ou recommande ;
- contexte domaine.

Regle : si un terme du glossaire apparait dans le bloc source, la traduction cible doit apparaitre dans le bloc traduit sauf impossibilite linguistique justifiee.

## Controle apres traduction

Logique MVP :

1. Pour chaque bloc source, rechercher les termes source.
2. Si un terme obligatoire est present, verifier la presence du terme cible dans la traduction.
3. Si absent, creer une alerte `terminology_missing`.
4. Detecter les traductions concurrentes connues si disponibles.

## Detection des incoherences

Exemples :

- `agreement` traduit parfois par `accord`, parfois par `contrat`.
- terme obligatoire absent ;
- acronyme traduit alors qu'il devait rester identique.

## Criteres d'acceptation

- Un glossaire peut etre attache a un traitement.
- Les termes sont transmis au service de traduction.
- Les absences de termes obligatoires sont detectees.
- Les alertes apparaissent dans le rapport.
- Le pipeline continue meme si le glossaire est vide.

## Cas d'erreur

- Glossaire mal forme : retourner une erreur de validation compatible avec le format standard de `docs/11_SPEC_API_BACKEND.md`.
- Terme source vide : refuser l'entree avec une erreur de validation explicite.
- Terme cible vide pour un terme obligatoire : refuser l'entree avec une erreur de validation explicite.

Pour harmoniser avec l'API MVP actuelle, les erreurs de glossaire doivent utiliser le meme format de reponse que les autres erreurs backend. Si le glossaire est expose dans le MVP, ajouter le code metier `INVALID_GLOSSARY` a la specification API avec statut HTTP `400`.

```json
{
  "error": {
    "code": "INVALID_GLOSSARY",
    "message": "Le glossaire fourni est invalide.",
    "details": null
  }
}
```

## Tests a prevoir

- Terme obligatoire present et respecte.
- Terme obligatoire present mais traduction absente.
- Glossaire vide.
- Terme sensible a la casse.
