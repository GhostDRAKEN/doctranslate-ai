# Feature - Traduction avec contexte

## Objectif

Traduire le contenu anglais vers francais par blocs intelligents, en conservant le sens, le ton et la coherence terminologique du document.

## Perimetre MVP

- Traduction anglais vers francais.
- `MockTranslationProvider` prioritaire pour valider le pipeline complet.
- Abstraction `TranslationService` permettant d'ajouter un LLM plus tard.
- Contexte documentaire simple : domaine detecte et glossaire utilisateur.
- Traduction par lots de blocs.
- Format de reponse structure.
- Gestion simple des erreurs.

## Hors perimetre

- Traduction multi-langues.
- Memoire de traduction persistante.
- Post-edition humaine integree.
- Fine-tuning de modele.
- Integration LLM reelle avant validation du pipeline complet.
- Resume documentaire LLM obligatoire.

## Exigences fonctionnelles

- Detecter ou definir le domaine du document.
- Utiliser une detection de domaine simple pour le MVP.
- Traduire les blocs dans l'ordre de lecture.
- Fournir au modele le glossaire applicable.
- Conserver les balises ou identifiants de blocs.
- Retourner une traduction par `block_id`.
- Marquer les blocs echoues.

## Exigences non fonctionnelles

- Le fournisseur IA doit etre interchangeable.
- Les timeouts doivent etre configures.
- Les couts doivent etre limites par taille de lot.
- Le contenu envoye doit etre minimal mais suffisant.
- Les erreurs IA doivent etre tracables sans exposer les textes complets dans les logs.

## TranslationService

Interface attendue :

- `detect_domain(document)`
- `translate_blocks(blocks, context, glossary)`
- `validate_response(response)`

Pour le MVP, `TranslationService` doit proposer deux implementations :

- `MockTranslationProvider` : implementation prioritaire, deterministe, sans appel externe ;
- `LLMTranslationProvider` : implementation optionnelle, activee seulement apres validation du pipeline complet.

La variable `MOCK_TRANSLATION_ENABLED=true/false` permet de selectionner l'implementation.

## Detection de domaine MVP

La detection de domaine peut etre mockee ou basee sur quelques mots-cles.

| Domaine | Mots-cles indicatifs |
| --- | --- |
| `legal` | agreement, liability, clause, party, jurisdiction |
| `technical` | system, API, configuration, server, protocol |
| `academic` | abstract, methodology, results, references |
| `business` | revenue, market, customer, strategy, invoice |
| `general` | fallback si aucun domaine specifique n'est detecte |

## Comportement du MockTranslationProvider

Le mock doit produire une sortie deterministe pour tester tout le pipeline sans LLM reel :

- paragraphes : `"[FR MOCK] " + source_text` ;
- titres : `"[FR MOCK] " + source_text` ;
- cellules de tableau : traduction mockee cellule par cellule ;
- images : non traduites, avec statut `needs_review` si `has_possible_text` vaut `true`.

Le mock ne vise pas une qualite linguistique reelle. Il sert a valider extraction, ordre de lecture, glossaire, reconstruction DOCX et rapport.

## Prompt systeme de traduction

Ce prompt concerne l'implementation `LLMTranslationProvider`, optionnelle apres validation du pipeline mocke.

Role attendu :

```text
Tu es un traducteur professionnel specialise dans la traduction documentaire anglais vers francais.
Tu dois traduire fidelement le sens, respecter le domaine, appliquer le glossaire fourni et conserver les identifiants de blocs.
Ne traduis pas les noms propres sauf usage etabli.
Retourne uniquement un JSON valide conforme au schema demande.
```

## Format attendu de la reponse IA

```json
{
  "translations": [
    {
      "block_id": "block_001",
      "translated_text": "Texte traduit",
      "confidence": 0.91,
      "notes": []
    }
  ]
}
```

## Gestion des erreurs IA

Cette section concerne principalement `LLMTranslationProvider`.

- Timeout : retry avec backoff.
- Reponse non JSON : retry avec prompt de correction.
- Bloc manquant : marquer `failed`.
- Quota atteint : stopper proprement le job avec code `TRANSLATION_FAILED`.
- Erreur fournisseur : retourner `TRANSLATION_FAILED`.

## Retry

Strategie MVP :

- maximum 2 retries par lot ;
- backoff court ;
- journalisation du type d'erreur ;
- pas de boucle infinie.

## Cout et limitation LLM

- Limiter la taille des lots en nombre de blocs ou tokens estimes.
- Le resume documentaire LLM est une option tardive ou une fonctionnalite de version avancee.
- Eviter d'envoyer les images.
- Permettre une configuration du modele via `.env`.

## Criteres d'acceptation

- Les blocs texte recoivent une traduction francaise.
- Les identifiants de blocs sont conserves.
- Le glossaire est inclus dans la demande.
- Une reponse IA invalide ne casse pas tout le pipeline.
- Les blocs non traduits apparaissent dans le rapport.

## Tests a prevoir

- Test avec fournisseur IA mocke.
- Test reponse JSON valide.
- Test reponse JSON invalide.
- Test bloc manquant.
- Test application de glossaire.
