import Link from "next/link";

export function Navbar() {
  return (
    <header className="border-b border-slate-100 bg-white/80 backdrop-blur">
      <div className="mx-auto flex w-full max-w-6xl items-center justify-between px-4 py-4 sm:px-6 lg:px-8">
        <Link href="/" className="flex items-center gap-2 text-sm font-semibold text-slate-950">
          <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-blue-600 text-xs font-bold text-white">
            D
          </span>
          <span>DocTranslate AI</span>
        </Link>
        <nav className="flex items-center text-sm">
          <Link
            href="/upload"
            className="rounded-lg px-3 py-2 font-medium text-slate-600 transition hover:bg-slate-100 hover:text-slate-950"
          >
            Upload
          </Link>
        </nav>
      </div>
    </header>
  );
}
