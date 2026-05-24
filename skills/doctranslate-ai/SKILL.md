---
name: doctranslate-ai
description: Guide agentique pour utiliser, tester, diagnostiquer et améliorer DocTranslate AI, un moteur de traduction PDF anglais-français avec extraction structurée, traduction IA et reconstruction PDF par overlay.
---

# DocTranslate AI Skill

## Objectif

Ce skill aide un assistant de développement comme Codex ou Claude Code à utiliser, tester, diagnostiquer et améliorer le moteur **DocTranslate AI**.

DocTranslate AI est une application web qui importe un PDF numérique propre, extrait une représentation intermédiaire structurée, traduit les blocs textuels en français, puis génère un PDF traduit par overlay en conservant autant que possible les pages, images, fonds et éléments graphiques du document source.

Le but n’est pas seulement de traduire du texte, mais de reconstruire un document exploitable.

## Philosophie du MVP

DocTranslate AI ne cherche pas seulement à remplacer les mots anglais par du français.

Le système cherche à reconstruire un document en préservant :

- la structure ;
- les images ;
- le contexte ;
- la lisibilité ;
- les blocs logiques ;
- la cohérence documentaire.

La qualité de reconstruction est aussi importante que la qualité linguistique.

## Quand utiliser ce skill

Utiliser ce skill pour :

- traduire un PDF via le pipeline DocTranslate AI ;
- diagnostiquer un problème de traduction PDF ;
- vérifier la qualité de `intermediate.json` avant génération PDF ;
- tester le pipeline backend ;
- analyser un job échoué ;
- comprendre pourquoi un PDF traduit ne change pas visuellement ;
- détecter des blocs dupliqués ou suspects ;
- analyser les risques de mauvais overlay PDF ;
- préparer une démonstration technique du MVP ;
- proposer une amélioration sans casser les contraintes MVP.

## Capacités du skill

Ce skill permet à un agent IA de :

- analyser un pipeline documentaire PDF ;
- vérifier la qualité d’une extraction structurée ;
- diagnostiquer des problèmes de segmentation logique ;
- détecter des blocs dupliqués ;
- vérifier la cohérence de `intermediate.json` ;
- évaluer les risques de mauvais overlay PDF ;
- vérifier si un document est prêt pour `generate-pdf` ;
- proposer des améliorations de reconstruction documentaire ;
- assister un développeur pendant les phases de test et de démonstration.

## Workflow principal

Le parcours produit attendu est :

```text
upload -> process -> inspect intermediate -> generate-pdf -> download