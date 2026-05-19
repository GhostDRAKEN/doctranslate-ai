# Feature - Upload PDF

## Objectif

Permettre a l'utilisateur d'importer un PDF numerique propre afin de lancer le pipeline de traduction documentaire.

## Perimetre MVP

- Upload d'un seul fichier PDF a la fois.
- Validation extension, MIME et taille.
- Validation du nombre de pages.
- Verification du texte selectionnable.
- Stockage temporaire local.
- Creation d'un `document_id`.
- Retour d'un statut initial.

## Hors perimetre

- Upload multi-fichiers.
- Traitement par lots.
- Stockage cloud.
- Authentification utilisateur.
- Antivirus avance.

## Exigences fonctionnelles

- L'utilisateur peut selectionner ou glisser-deposer un PDF.
- Le frontend affiche le nom et la taille du fichier.
- Le backend refuse les fichiers non PDF.
- Le backend refuse les fichiers trop volumineux.
- Le backend refuse les PDF de plus de 10 pages.
- Le backend refuse les PDF sans texte selectionnable.
- Le backend sauvegarde le fichier dans un dossier temporaire.
- Le backend retourne un identifiant document.

## Exigences non fonctionnelles

- Taille maximale MVP : 10 Mo.
- Nombre maximal de pages MVP : 10 pages.
- Temps de validation inferieur a 2 secondes pour un fichier raisonnable.
- Erreurs retournees au format JSON.
- Aucun contenu PDF ne doit etre logge.

## Validations fichier

- Extension `.pdf`.
- MIME `application/pdf`.
- Signature fichier commencant par `%PDF`.
- Taille superieure a 0.
- Taille inferieure ou egale a 10 Mo.
- Nombre de pages inferieur ou egal a 10.
- Texte selectionnable obligatoire, verifie par extraction texte minimale.

## Messages d'erreur

- `INVALID_FILE_TYPE` : "Le fichier doit etre un PDF."
- `FILE_TOO_LARGE` : "Le fichier depasse la taille maximale de 10 Mo."
- `PDF_TOO_MANY_PAGES` : "Le PDF depasse la limite de 10 pages."
- `PDF_NO_SELECTABLE_TEXT` : "Le PDF doit contenir du texte selectionnable."

## Endpoint backend

`POST /api/documents/upload`

Request :

- `multipart/form-data`
- champ `file`

Response 201 :

```json
{
  "document_id": "doc_123",
  "filename": "source.pdf",
  "status": "uploaded"
}
```

## Composants frontend

- `UploadDropzone`
- `FileSummary`
- `UploadError`
- `UploadActions`

## Logique technique

1. Le frontend valide rapidement extension et taille.
2. Le backend refait toutes les validations.
3. Le backend genere un identifiant non predictible.
4. Le fichier est stocke dans `storage/tmp/{document_id}/source.pdf`.
5. Les metadonnees minimales sont enregistrees.
6. Une purge opportuniste supprime les dossiers temporaires expires avant ou apres l'upload.

## Politique de purge MVP

- Les fichiers temporaires sont conserves dans `storage/tmp/{document_id}/`.
- Les fichiers de plus de 24 heures doivent etre supprimes.
- Le MVP peut declencher la purge au demarrage du backend et avant chaque upload.
- Une version future pourra utiliser un scheduler dedie.

## Criteres d'acceptation

- Un PDF numerique valide est accepte et recoit un `document_id`.
- Un fichier `.docx` est refuse.
- Un PDF de plus de 10 Mo est refuse.
- Un PDF de plus de 10 pages est refuse.
- Un PDF sans texte selectionnable est refuse.
- L'utilisateur voit un message clair en cas d'echec.
- Le fichier n'est pas accessible publiquement par URL directe.

## Cas limites

- Fichier renomme en `.pdf` mais contenu invalide.
- Fichier PDF protege par mot de passe.
- Upload interrompu.
- Nom de fichier contenant des caracteres speciaux.

## Tests a prevoir

- Test unitaire validation extension.
- Test unitaire validation MIME/signature.
- Test API upload valide.
- Test API fichier trop lourd.
- Test API fichier non PDF.
- Test API PDF de plus de 10 pages.
- Test API PDF sans texte selectionnable.
