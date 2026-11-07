import React from "react";

/** A short "how it works" section for a public page: what the tool does, where
 *  its data comes from and what it costs. No hooks, so it renders on the server. */
export function PageGuide({ title, intro, points }: { title: string; intro: string; points: { term: string; text: string }[] }) {
  return (
    <section aria-labelledby="page-guide" className="mx-auto w-full max-w-3xl space-y-3 text-sm leading-relaxed text-muted-foreground">
      <h2 id="page-guide" className="text-base font-semibold tracking-tight text-foreground">{title}</h2>
      <p>{intro}</p>
      <dl className="space-y-2">
        {points.map((p) => (
          <div key={p.term}>
            <dt className="inline font-medium text-foreground">{p.term}: </dt>
            <dd className="inline">{p.text}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
