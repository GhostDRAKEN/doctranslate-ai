# Modele de donnees

## 1. Objectif

Ce document definit uniquement les structures de donnees principales du MVP DocTranslate AI.

Le modele sert de contrat entre :

- l'extraction PDF ;
- la traduction ;
- la reconstruction DOCX ;
- le rapport de validation ;
- l'affichage frontend.

## 2. Principes du modele MVP

- Le modele doit rester simple et lisible.
- Il ne doit pas contenir de collection globale `blocks`.
- Chaque `Page` contient directement ses `blocks`.
- Les tableaux sont des blocs de type `table`.
- Les images sont des blocs de type `image`.
- Les styles sont approximatifs.
- Les coordonnees PDF sont conservees pour aider la reconstruction et le rapport.
- Les alertes sont stockees soit au niveau global, soit au niveau des blocs.

## 3. Limites MVP representees dans les donnees

Les limites suivantes doivent etre representees dans `mvp_limits` :

- PDF numerique uniquement ;
- texte selectionnable obligatoire ;
- maximum 10 pages ;
- maximum 10 Mo ;
- tableaux simples uniquement ;
- documents a une colonne en priorite ;
- pas de scans complexes ;
- pas de formulaires complexes ;
- pas de remplacement de texte dans les images.

## 4. DocumentIntermediate

`DocumentIntermediate` est la representation centrale du document pendant le traitement.

Champs :

- `document_id` : identifiant unique du document.
- `source_language` : langue source, `en` pour le MVP.
- `target_language` : langue cible, `fr` pour le MVP.
- `domain` : domaine detecte ou defini, par exemple `legal`, `technical`, `general`.
- `metadata` : informations generales sur le fichier.
- `mvp_limits` : limites appliquees au traitement.
- `glossary` : liste des termes de glossaire.
- `pages` : liste complete des pages, chacune contenant ses blocs.
- `warnings` : alertes globales.

Exemple :

```json
{
  "document_id": "doc_123",
  "source_language": "en",
  "target_language": "fr",
  "domain": "legal",
  "metadata": {
    "filename": "contract.pdf",
    "page_count": 4,
    "file_size_mb": 2.4,
    "created_at": "2026-05-19T10:00:00Z"
  },
  "mvp_limits": {
    "max_pages": 10,
    "max_file_size_mb": 10,
    "digital_pdf_only": true,
    "requires_selectable_text": true
  },
  "glossary": [],
  "pages": [
    {
      "page_number": 1,
      "width": 595,
      "height": 842,
      "blocks": []
    }
  ],
  "warnings": []
}
```

## 5. Page

Une page contient directement les blocs detectes sur cette page.

Champs :

- `page_number` : numero de page, commence a 1.
- `width` : largeur de la page dans l'unite PDF.
- `height` : hauteur de la page dans l'unite PDF.
- `blocks` : liste ordonnee des blocs de la page.

Exemple :

```json
{
  "page_number": 1,
  "width": 595,
  "height": 842,
  "blocks": [
    {
      "id": "block_001",
      "page_number": 1,
      "type": "title",
      "source_text": "Service Agreement",
      "translated_text": "Contrat de service",
      "bbox": [50, 80, 520, 120],
      "style": {
        "font": "Arial",
        "size": 18,
        "bold": true,
        "italic": false,
        "color": "#000000",
        "alignment": "center"
      },
      "reading_order": 1,
      "status": "translated",
      "warnings": []
    }
  ]
}
```

## 6. Block

`Block` represente une unite documentaire : titre, paragraphe, tableau, image, en-tete, pied de page ou bloc inconnu.

Champs communs :

- `id` : identifiant unique du bloc.
- `page_number` : page d'origine du bloc.
- `type` : type du bloc.
- `source_text` : texte source extrait.
- `translated_text` : texte traduit.
- `bbox` : coordonnees `[x0, y0, x1, y1]`.
- `style` : style approximatif.
- `reading_order` : ordre de lecture dans la page.
- `status` : statut de traitement.
- `warnings` : alertes associees au bloc.
- `metrics` : metriques optionnelles utiles pour la validation visuelle future.

Exemple :

```json
{
  "id": "block_002",
  "page_number": 1,
  "type": "paragraph",
  "source_text": "This agreement defines the responsibilities of each party.",
  "translated_text": "Ce contrat definit les responsabilites de chaque partie.",
  "bbox": [50, 140, 520, 190],
  "style": {
    "font": "Arial",
    "size": 11,
    "bold": false,
    "italic": false,
    "color": "#000000",
    "alignment": "left"
  },
  "reading_order": 2,
  "status": "translated",
  "warnings": []
}
```

## 7. TableBlock

Un tableau est un `Block` avec `type` egal a `table`.

Champs specifiques :

- `rows` : liste des lignes.
- `cells` : liste des cellules dans chaque ligne.
- `row` : index de ligne.
- `column` : index de colonne.
- `source_text` : texte source de la cellule.
- `translated_text` : texte traduit de la cellule.

Exemple :

```json
{
  "id": "block_003",
  "page_number": 2,
  "type": "table",
  "source_text": "",
  "translated_text": "",
  "bbox": [40, 200, 540, 360],
  "style": {
    "font": "Arial",
    "size": 10,
    "bold": false,
    "italic": false,
    "color": "#000000",
    "alignment": "left"
  },
  "reading_order": 4,
  "status": "translated",
  "warnings": ["possible_alignment_issue"],
  "rows": [
    {
      "cells": [
        {
          "row": 0,
          "column": 0,
          "source_text": "Term",
          "translated_text": "Terme"
        },
        {
          "row": 0,
          "column": 1,
          "source_text": "Definition",
          "translated_text": "Definition"
        }
      ]
    }
  ]
}
```

## 8. ImageBlock

Une image est un `Block` avec `type` egal a `image`.

Le MVP ne traduit pas le texte contenu dans les images. Si une image semble contenir du texte, le bloc doit etre signale dans le rapport.

Note securite : les chemins internes comme `image_path` sont utiles pour le backend, mais ne doivent pas etre exposes directement au frontend en production. Une API de telechargement controlee ou une URL temporaire signee devra etre utilisee dans une version plus avancee.

Champs specifiques :

- `image_path` : chemin interne vers l'image extraite.
- `has_possible_text` : indique si l'image peut contenir du texte.
- `status` : generalement `skipped` ou `needs_review` si du texte est suspecte.

Exemple :

```json
{
  "id": "block_004",
  "page_number": 1,
  "type": "image",
  "source_text": "",
  "translated_text": "",
  "bbox": [80, 300, 400, 520],
  "style": {
    "font": null,
    "size": null,
    "bold": false,
    "italic": false,
    "color": null,
    "alignment": "center"
  },
  "reading_order": 5,
  "status": "needs_review",
  "warnings": ["image_possible_text"],
  "image_path": "storage/tmp/doc_123/images/image_001.png",
  "has_possible_text": true
}
```

## 9. Metriques de bloc optionnelles

Pour preparer une future validation visuelle, un bloc peut contenir des metriques simples. Elles restent optionnelles dans le MVP et ne doivent pas compliquer le pipeline initial.

Champs :

- `source_char_count` : nombre de caracteres du texte source.
- `translated_char_count` : nombre de caracteres du texte traduit.
- `overflow_risk` : indique si la traduction risque de depasser l'espace disponible.

Exemple :

```json
{
  "source_char_count": 58,
  "translated_char_count": 76,
  "overflow_risk": true
}
```

## 10. GlossaryTerm

`GlossaryTerm` represente une contrainte terminologique.

```json
{
  "id": "term_001",
  "source": "agreement",
  "target": "contrat",
  "domain": "legal",
  "case_sensitive": false,
  "required": true,
  "source_type": "user"
}
```

## 11. TranslationJob

`TranslationJob` represente l'etat d'un traitement.

Pour le MVP, cet etat peut etre conserve en memoire ou dans `storage/tmp/{document_id}/status.json`.

```json
{
  "id": "job_001",
  "document_id": "doc_123",
  "status": "processing",
  "current_step": "translation",
  "progress": 65,
  "translation_provider": "mock",
  "created_at": "2026-05-19T10:00:00Z",
  "updated_at": "2026-05-19T10:03:00Z",
  "error": null
}
```

## 12. ValidationReport

`ValidationReport` liste les problemes detectes et les zones a verifier.

```json
{
  "document_id": "doc_123",
  "confidence_score": 0.82,
  "summary": {
    "total_blocks": 48,
    "translated_blocks": 46,
    "needs_review": 5
  },
  "issues": [
    {
      "id": "issue_001",
      "severity": "medium",
      "type": "terminology_missing",
      "page_number": 2,
      "block_id": "block_019",
      "message": "Le terme attendu 'contrat' est absent de la traduction.",
      "suggestion": "Verifier la traduction du terme 'agreement'."
    }
  ]
}
```

## 13. Enumerations utiles

Types de blocs :

- `title`
- `paragraph`
- `table`
- `image`
- `header`
- `footer`
- `unknown`

Statuts de blocs :

- `pending`
- `translated`
- `skipped`
- `failed`
- `needs_review`

Statuts de job :

- `uploaded`
- `queued`
- `processing`
- `completed`
- `failed`
- `expired`

Etapes de job :

- `upload`
- `analysis`
- `extraction`
- `domain_detection`
- `translation`
- `terminology_check`
- `reconstruction`
- `validation_report`
- `done`

Severites du rapport :

- `low`
- `medium`
- `high`
- `critical`

## 14. Exemples JSON valides

Exemple complet minimal :

```json
{
  "document_id": "doc_123",
  "source_language": "en",
  "target_language": "fr",
  "domain": "general",
  "metadata": {
    "filename": "sample.pdf",
    "page_count": 1,
    "file_size_mb": 1.2,
    "created_at": "2026-05-19T10:00:00Z"
  },
  "mvp_limits": {
    "max_pages": 10,
    "max_file_size_mb": 10,
    "digital_pdf_only": true,
    "requires_selectable_text": true
  },
  "glossary": [
    {
      "id": "term_001",
      "source": "agreement",
      "target": "contrat",
      "domain": "legal",
      "case_sensitive": false,
      "required": true,
      "source_type": "user"
    }
  ],
  "pages": [
    {
      "page_number": 1,
      "width": 595,
      "height": 842,
      "blocks": [
        {
          "id": "block_001",
          "page_number": 1,
          "type": "paragraph",
          "source_text": "Original English text",
          "translated_text": "Texte francais traduit",
          "bbox": [50, 120, 500, 180],
          "style": {
            "font": "Arial",
            "size": 11,
            "bold": false,
            "italic": false,
            "color": "#000000",
            "alignment": "left"
          },
          "reading_order": 1,
          "status": "translated",
          "warnings": []
        }
      ]
    }
  ],
  "warnings": []
}
```
