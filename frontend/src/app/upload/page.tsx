import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";

const constraints = [
  "PDF numerique uniquement",
  "10 Mo maximum",
  "10 pages maximum",
  "Texte selectionnable obligatoire",
];

export default function UploadPage() {
  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <h1 className="text-2xl font-semibold text-ink">Preparation du PDF</h1>
        <p className="max-w-2xl text-sm leading-6 text-muted">
          L'import reel sera ajoute dans une etape suivante. Cette page prepare
          le parcours utilisateur et les contraintes MVP.
        </p>
      </div>

      <section className="grid gap-4 lg:grid-cols-[1.2fr_0.8fr]">
        <Card title="Import PDF">
          <div className="flex min-h-48 flex-col items-center justify-center rounded-md border border-dashed border-line bg-white px-6 py-8 text-center">
            <p className="text-sm font-medium text-ink">
              Zone d'import placeholder
            </p>
            <p className="mt-2 max-w-md text-sm leading-6 text-muted">
              Le drag and drop, la selection fichier et l'appel API seront
              ajoutes lors de l'etape upload.
            </p>
            <div className="mt-5">
              <Button disabled>Selection indisponible</Button>
            </div>
          </div>
        </Card>

        <Card title="Contraintes visibles">
          <ul className="space-y-3">
            {constraints.map((item) => (
              <li key={item} className="flex items-center gap-3 text-sm">
                <span className="h-2 w-2 rounded-full bg-brand" />
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </Card>
      </section>
    </div>
  );
}
